from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.extraction.archive import verify_run
from processing.extraction import rule_runs
from processing.extraction.validation import ExtractionError
from processing.tests.test_rules import encoded, fixture, profile

RUN = '70000000-0000-4000-8000-000000000001'


class RuleRunsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / 'runs'
        self.input = self.base / 'input.json'; self.profile = self.base / 'profile.json'
        self.input.write_bytes(encoded(fixture()[0])); self.profile.write_bytes(encoded(profile()))
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for path in self.base.rglob('*'):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        self.temporary.cleanup()

    def run_rule(self, run_id=RUN):
        return rule_runs.run_rules(self.input, self.profile, 'synthetic-nfc-v1', self.root, run_id)

    def rewrite(self, name, content):
        path = self.root / RUN / name
        path.chmod(0o600); path.write_bytes(content); path.chmod(0o400)

    def assert_integrity(self):
        with self.assertRaises(ExtractionError) as caught:
            rule_runs.verify_rules_run(RUN, self.root)
        self.assertEqual(caught.exception.kind, 'archive')

    def cli(self, *arguments):
        return subprocess.run([sys.executable, '-m', 'processing.extraction', *arguments],
            cwd=Path(__file__).resolve().parents[2], capture_output=True)

    def test_complete_image_reuses_exact_bytes_and_verifies_without_sources(self):
        receipt = self.run_rule()
        self.assertEqual(receipt['format_version'], 'rules-run-v1')
        self.assertEqual((receipt['execution_mode'], receipt['status'], receipt['attempts']), ('rules', 'validated', 1))
        self.assertTrue(receipt['review_required'])
        image = self.root / RUN
        expected = {'input.json', 'profile.json', 'output.json', 'metadata.json', 'identity.json', 'receipt.json'}
        self.assertEqual({p.name for p in image.iterdir()}, expected)
        before = {p.name: p.read_bytes() for p in image.iterdir()}
        self.assertEqual(self.run_rule(), receipt)
        self.input.unlink(); self.profile.unlink()
        self.assertEqual(rule_runs.verify_rules_run(RUN, self.root), receipt)
        self.assertEqual({p.name: p.read_bytes() for p in image.iterdir()}, before)
        self.assertEqual(image.stat().st_mode & 0o777, 0o500)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o400 for p in image.iterdir()))
        self.assertNotIn('공사', json.dumps(receipt, ensure_ascii=False))
        self.assertNotIn(str(self.base), json.dumps(receipt))

    def test_failed_output_is_preserved_and_recomputed(self):
        document = fixture()[0]
        document['blocks'][0]['text'] = '공사.\n' + '\n'.join(f'예외: 합성 조건{i}' for i in range(257))
        self.input.write_bytes(encoded(document))
        receipt = self.run_rule()
        self.assertEqual((receipt['status'], receipt['validation_error']), ('failed', 'RULE_OUTPUT_LIMIT'))
        self.assertEqual(json.loads((self.root / RUN / 'output.json').read_bytes()), {'rule_error': 'RULE_OUTPUT_LIMIT'})
        self.assertEqual(rule_runs.verify_rules_run(RUN, self.root), receipt)

    def test_same_id_different_input_profile_or_preprocessing_is_conflict(self):
        self.run_rule()
        for target in ('input', 'profile', 'preprocessing'):
            with self.subTest(target=target):
                original_input, original_profile = self.input.read_bytes(), self.profile.read_bytes()
                if target == 'input': self.input.write_bytes(original_input + b' ')
                if target == 'profile': self.profile.write_bytes(original_profile + b' ')
                with self.assertRaises(ExtractionError) as caught:
                    rule_runs.run_rules(self.input, self.profile, 'other' if target == 'preprocessing' else 'synthetic-nfc-v1', self.root, RUN)
                self.assertEqual(caught.exception.code, 'RULE_RUN_CONFLICT')
                self.input.write_bytes(original_input); self.profile.write_bytes(original_profile)

    def test_modified_payload_identity_metadata_or_receipt_is_rejected(self):
        self.run_rule()
        for name in ('input.json', 'profile.json', 'output.json', 'metadata.json', 'identity.json', 'receipt.json'):
            with self.subTest(name=name):
                original = (self.root / RUN / name).read_bytes()
                self.rewrite(name, original + b' ')
                self.assert_integrity()
                self.rewrite(name, original)

    def test_permissions_extra_files_and_symlinks_are_rejected(self):
        self.run_rule(); image = self.root / RUN
        (image / 'output.json').chmod(0o600); self.assert_integrity(); (image / 'output.json').chmod(0o400)
        image.chmod(0o700); self.assert_integrity(); image.chmod(0o500)
        image.chmod(0o700); (image / 'extra').write_bytes(b''); image.chmod(0o500)
        self.assert_integrity()
        image.chmod(0o700); (image / 'extra').unlink()
        original = (image / 'output.json').read_bytes(); (image / 'output.json').unlink()
        target = self.base / 'output-copy'; target.write_bytes(original); target.chmod(0o400)
        (image / 'output.json').symlink_to(target); image.chmod(0o500)
        self.assert_integrity()

    def test_malformed_numeric_archive_metadata_is_integrity_error(self):
        self.run_rule()
        for name, key in (('metadata.json', 'started_at'), ('identity.json', 'recorded_at')):
            with self.subTest(name=name):
                original = (self.root / RUN / name).read_bytes()
                value = json.loads(original); value[key] = 1.5
                self.rewrite(name, encoded(value))
                self.assert_integrity()
                self.rewrite(name, original)

    def test_concurrent_conflicting_profile_has_one_winner_and_no_overwrite(self):
        other = self.base / 'other-profile.json'; other.write_bytes(self.profile.read_bytes() + b' ')
        def run(path):
            try:
                return rule_runs.run_rules(self.input, path, 'v1', self.root, RUN)
            except ExtractionError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as workers:
            receipts = list(workers.map(run, (self.profile, other)))
        self.assertEqual(sum(isinstance(result, dict) for result in receipts), 1)
        self.assertIn('RULE_RUN_CONFLICT', receipts)
        self.assertIn(rule_runs.verify_rules_run(RUN, self.root), receipts)

    def test_invalid_input_profile_version_and_ids_do_not_create_archive(self):
        for target in ('input', 'profile', 'run_id', 'preprocessing'):
            with self.subTest(target=target):
                input_bytes, profile_bytes = self.input.read_bytes(), self.profile.read_bytes()
                if target == 'input': self.input.write_bytes(b'INVALID_PRIVATE_INPUT')
                if target == 'profile': self.profile.write_bytes(b'{}')
                with self.assertRaises(ExtractionError):
                    rule_runs.run_rules(self.input, self.profile, '' if target == 'preprocessing' else 'v1', self.root,
                                        '../bad' if target == 'run_id' else RUN)
                self.assertFalse(self.root.exists())
                self.input.write_bytes(input_bytes); self.profile.write_bytes(profile_bytes)

    def test_concurrent_identical_install_and_failed_install_preserve_winner(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            receipts = list(workers.map(lambda _: self.run_rule(), range(4)))
        self.assertTrue(all(receipt == receipts[0] for receipt in receipts))
        self.assertEqual([p.name for p in self.root.iterdir()], [RUN])
        other = '70000000-0000-4000-8000-000000000002'
        with patch.object(rule_runs, '_rename_exclusive', side_effect=OSError('injected')):
            with self.assertRaises(OSError): self.run_rule(other)
        self.assertEqual([p.name for p in self.root.iterdir()], [RUN])
        self.assertEqual(rule_runs.verify_rules_run(RUN, self.root), receipts[0])

    def test_existing_partial_destination_is_not_overwritten(self):
        (self.root / RUN).mkdir(parents=True)
        marker = self.root / RUN / 'marker'; marker.write_bytes(b'KEEP')
        with self.assertRaises(ExtractionError): self.run_rule()
        self.assertEqual(marker.read_bytes(), b'KEEP')
        self.assertEqual({p.name for p in (self.root / RUN).iterdir()}, {'marker'})

    def test_ai_archive_and_draft_do_not_accept_rules_provenance(self):
        self.run_rule()
        with self.assertRaises(ExtractionError): verify_run(RUN, self.root)
        command = self.cli('verify', RUN, '--root', str(self.root))
        self.assertEqual(command.returncode, 3)
        self.assertEqual(command.stdout, b'')

    def test_actual_cli_run_verify_reuse_and_safe_errors(self):
        args = ['rules-run', '--input', str(self.input), '--profile', str(self.profile),
                '--preprocessing-version', 'synthetic-nfc-v1', '--run-id', RUN, '--root', str(self.root)]
        command = self.cli(*args)
        self.assertEqual((command.returncode, command.stderr), (0, b''))
        self.assertEqual(json.loads(command.stdout)['execution_mode'], 'rules')
        self.assertNotIn('공사'.encode(), command.stdout)
        self.assertNotIn(str(self.base).encode(), command.stdout)
        self.assertEqual(self.cli(*args).stdout, command.stdout)
        verify = self.cli('rules-verify', RUN, '--root', str(self.root))
        self.assertEqual((verify.returncode, verify.stdout, verify.stderr), (0, command.stdout, b''))
        missing = self.cli('rules-run')
        self.assertEqual((missing.returncode, missing.stdout, missing.stderr), (2, b'', b'ARGUMENT_INVALID\n'))
        self.input.write_bytes(b'PRIVATE_BAD_INPUT')
        bad = self.cli(*args)
        self.assertEqual((bad.returncode, bad.stdout), (2, b''))
        self.assertNotIn(b'PRIVATE', bad.stderr)

    def test_actual_cli_failure_exit_and_corrupt_archive_exit(self):
        document = fixture()[0]; document['blocks'][0]['text'] = '공사.\n' + '\n'.join(f'제외: 조건{i}' for i in range(257))
        self.input.write_bytes(encoded(document))
        failed = self.cli('rules-run', '--input', str(self.input), '--profile', str(self.profile),
            '--preprocessing-version', 'v1', '--run-id', RUN, '--root', str(self.root))
        self.assertEqual(failed.returncode, 4)
        self.assertEqual(json.loads(failed.stdout)['status'], 'failed')
        (self.root / RUN / 'output.json').chmod(0o600)
        corrupt = self.cli('rules-verify', RUN, '--root', str(self.root))
        self.assertEqual((corrupt.returncode, corrupt.stdout), (3, b''))
        self.assertNotIn(str(self.base).encode(), corrupt.stderr)
