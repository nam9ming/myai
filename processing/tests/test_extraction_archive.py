from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.extraction.archive import import_run, prepare, verify_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_extraction_prompt_metadata import metadata

ROOT = Path(__file__).resolve().parents[2]


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name).resolve()
        self.root = self.work / 'archive'
        self.source = self.work / 'input.json'
        self.source.write_bytes((ROOT / 'contracts/examples/ai-input.json').read_bytes())
        self.meta = self.work / 'metadata.json'
        self.meta.write_text(json.dumps(metadata()), encoding='utf-8')
        self.prompt = self.work / 'actual-prompt.txt'
        self.prompt.write_bytes(b'PRIVATE_PROMPT actual manual tool input\n')
        self.output = self.work / 'output.bin'
        self.output.write_bytes((ROOT / 'contracts/examples/ai-extraction.json').read_bytes())
        self.run_id = metadata()['run_id']

    def run_import(self, pairs=None):
        return import_run(self.source, self.meta, pairs or [(self.prompt, self.output)], self.root)

    def test_original_bytes_hashes_privacy_and_idempotence(self):
        result = self.run_import()
        self.assertEqual(result['status'], 'validated')
        self.assertTrue(result['review_required'])
        directory = self.root / self.run_id
        for name, original in [('input.json', self.source), ('metadata.json', self.meta),
                               ('attempt-1.prompt', self.prompt), ('attempt-1.output', self.output)]:
            self.assertEqual((directory / name).read_bytes(), original.read_bytes())
            self.assertEqual(result['artifacts'][name]['sha256'], hashlib.sha256(original.read_bytes()).hexdigest())
            self.assertEqual((directory / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(result, self.run_import())
        self.assertEqual(result, verify_run(self.run_id, self.root))
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(result))
        self.assertNotIn(str(self.work), json.dumps(result))

    def test_failed_invalid_utf8_and_oversize_raw_are_retained(self):
        for content in [b'\xffPRIVATE_VALUE', b'x' * (8 * 1024 * 1024 + 1)]:
            with self.subTest(size=len(content)):
                self.root = self.work / str(len(content))
                self.output.write_bytes(content)
                result = self.run_import()
                self.assertEqual(result['status'], 'failed')
                self.assertEqual(result['attempts'][0]['failure_kind'], 'schema')
                self.assertEqual((self.root / self.run_id / 'attempt-1.output').read_bytes(), content)
                self.assertEqual(verify_run(self.run_id, self.root), result)
                self.assertNotIn('PRIVATE_VALUE', json.dumps(result))

    def test_all_attempts_retained_and_last_attempt_controls_status(self):
        bad = self.work / 'bad-output'; bad.write_bytes(b'not json')
        body = metadata(); body['attempts'] = 2; self.meta.write_text(json.dumps(body))
        result = self.run_import([(self.prompt, bad), (self.prompt, self.output)])
        self.assertEqual([a['status'] for a in result['attempts']], ['failed', 'validated'])
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(verify_run(self.run_id, self.root), result)
        self.root = self.work / 'reversed'
        result = self.run_import([(self.prompt, self.output), (self.prompt, bad)])
        self.assertEqual(result['status'], 'failed')

    def test_review_failures_are_not_schema_retry(self):
        body = json.loads(self.output.read_bytes()); body['evidence'][0]['quote'] = 'PRIVATE_VALUE'
        self.output.write_text(json.dumps(body))
        result = self.run_import()
        self.assertEqual(result['attempts'][0]['failure_kind'], 'review')
        self.assertFalse(result['attempts'][0]['retryable'])

    def test_conflict_tamper_incomplete_and_symlinks_fail_closed(self):
        original = self.run_import()
        self.output.write_bytes(b'changed')
        with self.assertRaises(ExtractionError):
            self.run_import()
        directory = self.root / self.run_id
        self.assertEqual(verify_run(self.run_id, self.root), original)
        saved = (directory / 'attempt-1.output').read_bytes()
        (directory / 'attempt-1.output').write_bytes(b'tampered')
        with self.assertRaises(ExtractionError):
            verify_run(self.run_id, self.root)
        (directory / 'attempt-1.output').write_bytes(saved)
        (directory / 'receipt.json').unlink()
        with self.assertRaises(ExtractionError):
            verify_run(self.run_id, self.root)
        (directory / 'input.json').unlink()
        (directory / 'input.json').symlink_to(self.source)
        with self.assertRaises((ExtractionError, OSError)):
            verify_run(self.run_id, self.root)

    def test_concurrent_same_run_and_resume_after_file_failure(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: self.run_import(), range(4)))
        self.assertTrue(all(value == results[0] for value in results))
        self.root = self.work / 'resume'
        link = os.link
        def fail(source, destination, **kwargs):
            if Path(destination).name == 'attempt-1.output':
                raise OSError('PRIVATE_VALUE')
            return link(source, destination, **kwargs)
        with patch('processing.extraction.archive.os.link', side_effect=fail), self.assertRaises(OSError):
            self.run_import()
        with self.assertRaises(ExtractionError):
            verify_run(self.run_id, self.root)
        self.assertEqual(self.run_import(), verify_run(self.run_id, self.root))
        self.assertEqual(list(self.root.rglob('*.tmp')), [])

    def test_source_change_during_copy_never_commits_a_receipt(self):
        from processing.extraction import archive
        original = archive._copy
        def changed(source, destination, expected):
            if Path(source) == self.output:
                self.output.write_bytes(b'PRIVATE_VALUE changed after fingerprint')
            return original(source, destination, expected)
        with patch.object(archive, '_copy', side_effect=changed), self.assertRaises(ExtractionError):
            self.run_import()
        self.assertFalse((self.root / self.run_id / 'receipt.json').exists())

    def test_missing_artifact_is_integrity_failure_and_no_repair_on_verify(self):
        absent = self.work / 'absent'
        with self.assertRaises(ExtractionError):
            verify_run(self.run_id, absent)
        self.assertFalse(absent.exists())
        self.run_import()
        path = self.root / self.run_id / 'attempt-1.prompt'
        path.unlink()
        with self.assertRaises(ExtractionError) as caught:
            verify_run(self.run_id, self.root)
        self.assertEqual(caught.exception.kind, 'archive')
        self.assertFalse(path.exists())

    def test_prepare_is_private_deterministic_and_rejects_public_root(self):
        result = prepare(self.source, self.root)
        self.assertEqual(result['status'], 'prepared')
        self.assertEqual(result, prepare(self.source, self.root))
        self.assertTrue((self.root / 'prepared' / result['input_sha256'] / 'prompt.json').is_file())
        with self.assertRaises(ExtractionError):
            prepare(self.source, ROOT / 'data/public/extraction-runs')
        with self.assertRaises(ExtractionError):
            verify_run('../../PRIVATE_VALUE', self.root)
        symlink = self.work / 'root-link'; symlink.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ExtractionError):
            prepare(self.source, symlink)

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'processing.extraction', *map(str, args)],
                              cwd=ROOT, capture_output=True, timeout=10)

    def test_actual_cli_success_failure_and_no_private_error_output(self):
        result = self.cli('import', '--input', self.source, '--metadata', self.meta,
                          '--attempt', self.prompt, self.output, '--root', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'validated')
        self.assertEqual(result.stderr, b'')
        result = self.cli('verify', self.run_id, '--root', self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['run_id'], self.run_id)
        self.output.write_bytes(b'PRIVATE_VALUE')
        result = self.cli('import', '--input', self.source, '--metadata', self.meta,
                          '--attempt', self.prompt, self.output, '--root', self.work / 'failed')
        self.assertEqual(result.returncode, 4)
        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
        result = self.cli('prepare', '--input', self.work / 'PRIVATE_VALUE', '--root', self.root)
        self.assertEqual(result.returncode, 5)
        self.assertEqual(result.stdout, b'')
        self.assertNotIn(b'PRIVATE_VALUE', result.stderr)
        result = self.cli('verify', '../../PRIVATE_VALUE', '--root', self.root)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b'PRIVATE_VALUE', result.stderr)
        result = self.cli('PRIVATE_VALUE')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(b'PRIVATE_VALUE', result.stderr)


if __name__ == '__main__':
    unittest.main()
