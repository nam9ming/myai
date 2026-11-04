import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.extraction.archive import freeze_run, import_run
from processing.extraction.validation import MAX_BYTES
from processing.tests.test_extraction_api import KEY, response
from processing.tests.test_extraction_prompt_metadata import metadata

REPO = Path(__file__).resolve().parents[2]


class SealedVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.work = Path(self.temporary.name).resolve()
        self.root = self.work / 'archive'
        self.source = self.work / 'input.json'
        self.source.write_bytes((REPO / 'contracts/examples/ai-input.json').read_bytes())
        self.meta = self.work / 'metadata.json'
        self.prompt = self.work / 'prompt.txt'; self.prompt.write_bytes(b'synthetic manual prompt')
        self.output = self.work / 'output.bin'
        self.output.write_bytes((REPO / 'contracts/examples/ai-extraction.json').read_bytes())
        self.run_id = metadata()['run_id']

    def cleanup(self):
        for current, _, _ in os.walk(self.work):
            Path(current).chmod(0o700)
        self.temporary.cleanup()

    def manual(self, content=None, attempts=1):
        if content is not None: self.output.write_bytes(content)
        value = metadata(); value['attempts'] = attempts
        self.meta.write_text(json.dumps(value), encoding='utf-8')
        bad = self.work / 'first-output'; bad.write_bytes(b'PRIVATE_VALUE not json')
        pairs = [(self.prompt, bad)] * (attempts - 1) + [(self.prompt, self.output)]
        return import_run(self.source, self.meta, pairs, self.root)

    def frozen(self):
        packet = freeze_run(self.run_id, self.root)
        return self.root / packet['snapshot_ref']

    def tree(self):
        result = {}
        for path in [self.work, *sorted(self.work.rglob('*'))]:
            info = path.lstat()
            content = os.readlink(path) if path.is_symlink() else (
                hashlib.sha256(path.read_bytes()).hexdigest() if stat.S_ISREG(info.st_mode) else None)
            result[str(path.relative_to(self.work))] = (info.st_mode, info.st_size, content)
        return result

    def verify(self, root):
        before = self.tree()
        process = subprocess.run([sys.executable, '-B', '-m', 'processing.extraction', 'verify-sealed', self.run_id,
                                  '--root', str(root)], cwd=REPO, capture_output=True, timeout=15)
        self.assertEqual(self.tree(), before)
        return process

    def test_sealed_registered_parent_returns_existing_registration_packet_without_writes(self):
        receipt = self.manual()
        directory = self.frozen()
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), dict(protocol_version='extraction-registration-v1',
                         snapshot_ref=self.run_id, receipt=receipt))
        self.assertEqual(process.stderr, b'')

    def test_mutable_completed_archive_is_rejected_without_freezing_or_repairs(self):
        self.manual()
        process = self.verify(self.root)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stdout, b'')
        self.assertEqual(process.stderr, b'ARCHIVE_REQUIRES_SEALED\n')
        self.assertFalse((self.root / 'registered').exists())

    def test_non_utf8_and_oversize_failed_outputs_remain_full_original_bytes(self):
        for number, content in enumerate((b'\xffPRIVATE_VALUE', b'\xff' + b'x' * MAX_BYTES)):
            with self.subTest(size=len(content)):
                self.root = self.work / f'failed-{number}'
                receipt = self.manual(content)
                directory = self.frozen()
                process = self.verify(directory.parent)
                self.assertEqual(process.returncode, 4, process.stderr)
                self.assertEqual(json.loads(process.stdout)['receipt'], receipt)
                self.assertNotIn(b'PRIVATE_VALUE', process.stdout + process.stderr)
                self.assertEqual((directory / 'attempt-1.output').read_bytes(), content)

    def test_every_attempt_and_final_status_are_preserved(self):
        receipt = self.manual(attempts=3)
        directory = self.frozen()
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)['receipt'], receipt)
        self.assertEqual([a['status'] for a in receipt['attempts']], ['failed', 'failed', 'validated'])

    def test_incomplete_api_keeps_all_response_bytes_and_empty_derived_outputs(self):
        from processing.extraction.api import run_api
        raw = response('{"schema_version":', status='incomplete', incomplete_details=dict(reason='max_output_tokens'))
        with patch.dict(os.environ, OPENAI_API_KEY=KEY), patch('processing.extraction.api._exchange',
                return_value=(200, raw, None, True)), patch('processing.extraction.api.time.sleep'):
            receipt = run_api(self.source, 'fixture-nfc-v1', self.root, self.run_id, model='gpt-6.1-sol')
        directory = self.frozen()
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 4, process.stderr)
        self.assertEqual(json.loads(process.stdout)['receipt'], receipt)
        for number in range(1, 4):
            self.assertEqual((directory / f'attempt-{number}.response').read_bytes(), raw)
            self.assertEqual((directory / f'attempt-{number}.output').read_bytes(), b'')

    def test_missing_and_tampered_artifacts_fail_without_changing_what_remains(self):
        self.manual(); directory = self.frozen()
        output = directory / 'attempt-1.output'
        directory.chmod(0o700); output.chmod(0o600)
        output.write_bytes(b'PRIVATE_VALUE tampered'); output.chmod(0o400); directory.chmod(0o500)
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stdout, b'')
        self.assertNotIn(b'PRIVATE_VALUE', process.stderr)
        directory.chmod(0o700); output.unlink(); directory.chmod(0o500)
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stdout, b'')

    def test_writable_sealed_file_is_rejected_without_chmod_repair(self):
        self.manual(); directory = self.frozen()
        (directory / 'attempt-1.output').chmod(0o600)
        process = self.verify(directory.parent)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stderr, b'ARCHIVE_REQUIRES_SEALED\n')

    def test_absent_root_is_not_created(self):
        process = self.verify(self.root)
        self.assertEqual(process.returncode, 3, process.stderr)
        self.assertEqual(process.stdout, b'')
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
