from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from unittest.mock import patch

from processing.extraction.archive import freeze_run, import_run, verify_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_extraction_prompt_metadata import metadata

REPO = Path(__file__).resolve().parents[2]


class FreezeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / 'archive'
        self.input = self.work / 'input.json'
        self.input.write_bytes((REPO / 'contracts/examples/ai-input.json').read_bytes())
        self.metadata = self.work / 'metadata.json'
        self.metadata.write_text(json.dumps(metadata()), encoding='utf-8')
        self.prompt = self.work / 'prompt.txt'; self.prompt.write_bytes(b'actual synthetic prompt')
        self.output = self.work / 'output.json'
        self.output.write_bytes((REPO / 'contracts/examples/ai-extraction.json').read_bytes())
        self.id = metadata()['run_id']
        self.receipt = import_run(self.input, self.metadata, [(self.prompt, self.output)], self.root)

    def test_snapshot_copies_original_bytes_seals_and_reuses_without_nesting(self):
        result = freeze_run(self.id, self.root)
        self.assertEqual(result['protocol_version'], 'extraction-registration-v1')
        self.assertEqual(result['receipt'], self.receipt)
        snapshot = self.root / result['snapshot_ref']
        for name in list(self.receipt['artifacts']) + ['identity.json', 'receipt.json']:
            self.assertEqual((snapshot / name).read_bytes(), (self.root / self.id / name).read_bytes())
            self.assertEqual((snapshot / name).stat().st_mode & 0o777, 0o400)
        self.assertEqual(snapshot.stat().st_mode & 0o777, 0o500)
        self.assertEqual((self.root / self.id / 'attempt-1.output').stat().st_mode & 0o777, 0o600)
        self.assertEqual(freeze_run(self.id, self.root), result)
        sealed = freeze_run(self.id, snapshot.parent)
        self.assertEqual(sealed['snapshot_ref'], self.id)
        self.assertEqual(sealed['receipt'], self.receipt)
        self.assertEqual(len(list(self.root.rglob('attempt-1.output'))), 2)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_concurrent_snapshotters_publish_one_complete_image(self):
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: freeze_run(self.id, self.root), range(4)))
        self.assertTrue(all(value == results[0] for value in results))
        snapshot = self.root / results[0]['snapshot_ref']
        self.assertEqual(verify_run(self.id, snapshot.parent), self.receipt)
        self.assertEqual(list(self.root.rglob('.freeze-*')), [])

    def test_changed_source_during_copy_is_rejected_and_stage_removed(self):
        from processing.extraction import archive
        original = archive._copy
        def changed(source, target, expected):
            if Path(source).name == 'attempt-1.output':
                Path(source).write_bytes(b'PRIVATE_VALUE changed during snapshot copy')
            return original(source, target, expected)
        with patch.object(archive, '_copy', side_effect=changed), self.assertRaises(ExtractionError):
            freeze_run(self.id, self.root)
        digest = hashlib.sha256((self.root / self.id / 'receipt.json').read_bytes()).hexdigest()
        self.assertFalse((self.root / 'registered' / digest / self.id).exists())
        self.assertEqual(list(self.root.rglob('.freeze-*')), [])

    def test_failed_oversize_bytes_cli_and_existing_corrupt_snapshot_are_preserved(self):
        self.root = self.work / 'failed'
        content = b'\xff' + b'x' * (8 * 1024 * 1024)
        self.output.write_bytes(content)
        failed = import_run(self.input, self.metadata, [(self.prompt, self.output)], self.root)
        process = subprocess.run([sys.executable, '-m', 'processing.extraction', 'freeze', self.id, '--root', str(self.root)],
                                 cwd=REPO, capture_output=True, timeout=10)
        self.assertEqual(process.returncode, 4, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result['receipt'], failed)
        snapshot = self.root / result['snapshot_ref']
        self.assertEqual((snapshot / 'attempt-1.output').read_bytes(), content)
        snapshot.chmod(0o700); (snapshot / 'attempt-1.output').chmod(0o600)
        (snapshot / 'attempt-1.output').write_bytes(b'changed snapshot')
        with self.assertRaises(ExtractionError):
            freeze_run(self.id, self.root)
        self.assertEqual((snapshot / 'attempt-1.output').read_bytes(), b'changed snapshot')
        self.assertEqual((self.root / self.id / 'attempt-1.output').read_bytes(), content)

    def test_publish_io_failure_cleans_sealed_stage_and_keeps_source(self):
        with patch('processing.extraction.archive.os.rename', side_effect=OSError('PRIVATE_VALUE')), self.assertRaises(OSError):
            freeze_run(self.id, self.root)
        self.assertEqual(verify_run(self.id, self.root), self.receipt)
        self.assertEqual(list(self.root.rglob('.freeze-*')), [])

    def test_repository_unicode_and_case_aliases_still_enforce_private_root(self):
        from processing.extraction import archive
        repository = self.work / '가상-Repository'
        public = repository / 'data/public'; public.mkdir(parents=True)
        private = repository / 'data/private'; private.mkdir()
        with patch.object(archive, 'REPO', repository):
            for alias in {public, Path(unicodedata.normalize('NFD', str(public))), Path(str(public).upper())}:
                if alias.exists() and alias.samefile(public):
                    with self.subTest(alias=alias), self.assertRaises(ExtractionError):
                        archive._root(alias, create=False)
            alias = Path(unicodedata.normalize('NFD', str(private)))
            if alias.exists() and alias.samefile(private):
                self.assertTrue(archive._root(alias, create=False).samefile(private))
            private.rmdir(); private.symlink_to(public, target_is_directory=True)
            with self.assertRaises(ExtractionError):
                archive._root(public, create=False)
        fresh = self.work / 'fresh-repository'; (fresh / 'data').mkdir(parents=True)
        with patch.object(archive, 'REPO', fresh):
            target = fresh / 'data/private/runs'
            self.assertEqual(archive._root(target, create=False), target)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
