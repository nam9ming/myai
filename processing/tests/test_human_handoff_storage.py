import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import handoff_storage as storage
from processing.extraction.archive import _fingerprint, _json, freeze_run
from processing.extraction.validation import ExtractionError, MAX_BYTES
from processing.tests.test_dataset import REPO, uid
from processing.tests.test_human_handoff import HumanHandoffFixture


class HumanHandoffStorageTest(HumanHandoffFixture):
    def setUp(self):
        super().setUp()
        self.handoff_root = self.work / 'handoffs'

    def write_request(self, value=None, name='handoff.json'):
        path = self.work / name; path.write_bytes(_json(self.request if value is None else value)); return path

    def freeze(self, root=None):
        class ProjectClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 5, tzinfo=tz)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 5, 30, tzinfo=tz)
        with patch('processing.evaluation.human_handoff.datetime', ProjectClock), patch('processing.extraction.archive.datetime', FreezeClock):
            return storage.freeze_handoff(self.write_request(), self.handoff_root if root is None else root, self.human_root)

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): (_fingerprint(p), p.stat().st_mode & 0o777) for p in root.rglob('*') if p.is_file()}

    def test_full_review_and_parent_copy_reuse_and_offline_replay(self):
        ref = self.request['review_ref']; source = self.snapshot(self.human_root / ref)
        receipt = self.freeze(); handoff_ref = receipt['handoff_ref']; image = self.handoff_root / handoff_ref
        before = self.snapshot(image)
        for name, value in source.items(): self.assertEqual(before[f'review/{ref}/{name}'], value)
        self.assertTrue(all(mode == 0o400 for _, mode in before.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o500 for p in [image, *image.rglob('*')] if p.is_dir()))
        self.assertEqual((image / 'selection.json').read_bytes(), self.write_request().read_bytes())
        for root in (self.human_root, self.run_root): root.rename(root.with_name(root.name + '-gone'))
        self.input.unlink()
        self.assertEqual(storage.verify_handoff(handoff_ref, self.handoff_root), receipt)
        self.assertEqual(self.freeze(), receipt); self.assertEqual(self.snapshot(image), before)
        self.assertEqual(receipt['summary']['status'], 'projection_only')
        self.assertFalse(receipt['summary']['backend_import_supported'])

    def test_same_id_changed_context_conflicts_without_replacing_original(self):
        receipt = self.freeze(); before = self.snapshot(self.handoff_root)
        self.request['dictionary_version'] = 'different-private-dictionary'
        with self.assertRaises(ExtractionError) as caught: self.freeze()
        self.assertEqual(caught.exception.code, 'HANDOFF_CONFLICT')
        self.assertEqual(storage.verify_handoff(receipt['handoff_ref'], self.handoff_root), receipt)
        self.assertEqual(self.snapshot(self.handoff_root), before)

    def test_noncanonical_identity_whitespace_and_key_order_are_integrity_errors(self):
        receipt = self.freeze(); ref = receipt['handoff_ref']; original = self.handoff_root / ref
        for case in ('whitespace', 'key-order'):
            root = self.work / ('identity-' + case); image = root / ref; shutil.copytree(original, image)
            target = image / 'identity.json'; raw = target.read_bytes()
            if case == 'whitespace': changed = raw + b' '
            else:
                value = json.loads(raw)
                changed = (json.dumps(dict(reversed(list(value.items()))), ensure_ascii=False, separators=(',', ':')) + '\n').encode()
            self.assertNotEqual(changed, raw)
            target.chmod(0o600); target.write_bytes(changed); target.chmod(0o400)
            with self.subTest(case=case):
                with self.assertRaises(ExtractionError) as caught: storage.verify_handoff(ref, root)
                self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'HANDOFF_INTEGRITY'))

    def test_native_same_and_conflicting_requests_install_exclusively(self):
        one = self.write_request(name='one.json'); changed = copy.deepcopy(self.request); changed['area_id'] = uid(990)
        two = self.write_request(changed, 'two.json')
        for paths, label, successes in (([one] * 4, 'same', 4), ([one, two], 'different', 1)):
            root = self.work / label
            def run(path):
                try: return storage.freeze_handoff(path, root, self.human_root)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(run, paths))
            self.assertEqual(sum(isinstance(value, dict) for value in results), successes)
            if successes == 1: self.assertIn('HANDOFF_CONFLICT', results)
            else: self.assertTrue(all(value == results[0] for value in results))
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_nested_tamper_missing_extra_symlink_and_permissions_fail_safely(self):
        receipt = self.freeze(); ref = receipt['handoff_ref']; original = self.handoff_root / ref
        for case in ('extra', 'directory', 'missing', 'file-mode', 'dir-mode', 'symlink', 'projection', 'source', 'identity'):
            root = self.work / ('corrupt-' + case); image = root / ref; shutil.copytree(original, image); image.chmod(0o700)
            target = image / 'projection.json'
            if case == 'extra': (image / 'extra').write_text('PRIVATE_VALUE'); (image / 'extra').chmod(0o400)
            elif case == 'directory': (image / 'extra').mkdir(mode=0o500)
            elif case == 'missing': target.unlink()
            elif case == 'file-mode': target.chmod(0o600)
            elif case == 'dir-mode': (image / 'review').chmod(0o700)
            elif case == 'symlink': target.unlink(); target.symlink_to(original / 'projection.json')
            else:
                if case == 'source': target = image / 'review' / self.request['review_ref'] / 'output.json'
                elif case == 'identity': target = image / 'identity.json'
                target.chmod(0o600)
                if case == 'identity':
                    value = json.loads(target.read_bytes()); value['recorded_at'] = 1.5; target.write_bytes(_json(value))
                else: target.write_bytes(target.read_bytes() + b' ')
                target.chmod(0o400)
            image.chmod(0o500)
            with self.subTest(case=case):
                with self.assertRaises(ExtractionError) as caught: storage.verify_handoff(ref, root)
                self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'HANDOFF_INTEGRITY'))

    def test_copy_mutation_and_install_failure_leave_no_partial_image(self):
        with patch.object(storage, '_rename_exclusive', side_effect=OSError(errno.EIO, 'PRIVATE_IO')):
            with self.assertRaises(OSError): self.freeze()
        self.assertEqual(list(self.handoff_root.iterdir()), [])
        copy_file = storage._copy
        def mutate(source, destination, expected):
            if destination.name == 'output.json':
                source.chmod(0o600); source.write_bytes(source.read_bytes() + b' '); source.chmod(0o400)
            return copy_file(source, destination, expected)
        with patch.object(storage, '_copy', side_effect=mutate):
            with self.assertRaises(ExtractionError): self.freeze()
        self.assertEqual(list(self.handoff_root.iterdir()), [])

    def test_partial_destination_created_by_competitor_is_preserved(self):
        def collide(source, destination):
            destination.mkdir(mode=0o500); raise FileExistsError(errno.EEXIST, 'synthetic')
        with patch.object(storage, '_rename_exclusive', side_effect=collide):
            with self.assertRaises(ExtractionError): self.freeze()
        image = self.handoff_root / hashlib.sha256(self.request['handoff_id'].encode()).hexdigest()
        self.assertEqual(list(image.iterdir()), []); self.assertEqual(list(self.handoff_root.iterdir()), [image])

    def test_full_oversized_failed_parent_response_is_copied_without_truncation(self):
        from processing.extraction.api import run_api
        from processing.tests.test_extraction_api import KEY
        class SourceClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 3, tzinfo=timezone.utc)
        raw = b'x' * (MAX_BYTES + 1)
        with patch.dict(os.environ, OPENAI_API_KEY=KEY), patch('processing.extraction.api._exchange', return_value=(401, raw, 'API_RESPONSE_LIMIT', False)), \
             patch('processing.extraction.api._now', return_value='2020-01-01T03:00:00Z'), patch('processing.extraction.archive.datetime', SourceClock):
            run_api(self.input, 'fixture-nfc-v1', self.run_root, uid(554), model='gpt-6.1-sol')
        frozen = freeze_run(uid(554), self.run_root); folder = self.run_root / frozen['snapshot_ref']
        parent = dict(run_id=uid(554), snapshot_ref=frozen['snapshot_ref'],
            receipt_sha256=hashlib.sha256((folder / 'receipt.json').read_bytes()).hexdigest())
        self.use_review(self.make_human(uid(989), source=parent, failed=True))
        receipt = self.freeze(); image = self.handoff_root / receipt['handoff_ref']
        name = next(name for name in receipt['artifacts'] if name.endswith('attempt-1.response'))
        self.assertEqual(receipt['artifacts'][name]['size'], MAX_BYTES + 1)
        self.assertEqual((image / name).read_bytes(), raw)
        self.assertEqual(receipt['summary']['source_status'], 'failed')
        self.assertEqual(storage.verify_handoff(receipt['handoff_ref'], self.handoff_root), receipt)

    def test_empty_projection_keeps_context_and_does_not_create_fake_events(self):
        output = copy.deepcopy(self.good_output); output.update(items=[], warnings=['NO_EVENT_FOUND'])
        self.use_review(self.make_human(uid(991), output=output))
        receipt = self.freeze(); image = self.handoff_root / receipt['handoff_ref']
        value = json.loads((image / 'projection.json').read_bytes())
        self.assertEqual(value['events'], []); self.assertGreater(len(value['evidence']), 0)
        self.assertEqual(value['context']['dictionary_version'], self.request['dictionary_version'])
        self.assertEqual(storage.verify_handoff(receipt['handoff_ref'], self.handoff_root), receipt)

    def test_actual_cli_success_input_archive_io_errors_and_no_private_stdout(self):
        path = self.write_request(); root = self.work / 'cli-handoffs'
        def run(*args):
            return subprocess.run([sys.executable, '-m', 'processing.evaluation', *map(str, args)], cwd=REPO,
                capture_output=True, timeout=45)
        checked = run('check-handoff', '--input', path, '--review-root', self.human_root)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['status'], 'projection_only')
        frozen = run('freeze-handoff', '--input', path, '--root', root, '--review-root', self.human_root)
        self.assertEqual(frozen.returncode, 0, frozen.stderr); receipt = json.loads(frozen.stdout)
        verified = run('verify-handoff', receipt['handoff_ref'], '--root', root)
        self.assertEqual(verified.returncode, 0, verified.stderr); self.assertEqual(json.loads(verified.stdout), receipt)
        for result in (checked, frozen, verified):
            self.assertEqual(result.stderr, b''); self.assertEqual(result.stdout.count(b'\n'), 1)
            for private in (b'PRIVATE_', str(self.work).encode(), b'cleaned_text', b'reviewed_by', b'raw_asset_path'):
                self.assertNotIn(private, result.stdout)
        bad = self.work / 'bad.json'; bad.write_bytes(b'{"schema_version":"PRIVATE_VALUE"}')
        cases = [(run('check-handoff', '--input', bad, '--review-root', self.human_root), 2),
            (run('check-handoff'), 2), (run('verify-handoff', '0' * 64, '--root', root), 3),
            (run('check-handoff', '--input', self.work / 'missing.json', '--review-root', self.human_root), 5)]
        for result, expected in cases:
            self.assertEqual(result.returncode, expected, result.stderr); self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE_', result.stderr); self.assertNotIn(str(self.work).encode(), result.stderr)
