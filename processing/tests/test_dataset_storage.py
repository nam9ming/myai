from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.evaluation.storage import freeze_dataset, verify_dataset
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import FIXTURE, REPO, manifest


class DatasetStorageTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name).resolve()
        self.root = self.work / 'datasets'
        self.input = self.work / 'manifest.json'
        self.input.write_bytes(FIXTURE.read_bytes())
        self.addCleanup(self.cleanup)

    def cleanup(self):
        for current, _, _ in os.walk(self.work): Path(current).chmod(0o700)
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'processing.evaluation', *args], cwd=REPO, capture_output=True)

    def test_freeze_preserves_bytes_seals_and_survives_source_removal(self):
        receipt = freeze_dataset(self.input, self.root)
        ref = receipt['dataset_ref']; folder = self.root / ref
        self.assertEqual(ref, hashlib.sha256(b'synthetic-dataset-v1').hexdigest())
        self.assertEqual(receipt['status'], 'frozen')
        self.assertEqual((folder / 'manifest.json').read_bytes(), self.input.read_bytes())
        self.assertEqual(set(p.name for p in folder.iterdir()), {'manifest.json', 'identity.json', 'receipt.json'})
        self.assertEqual(folder.stat().st_mode & 0o777, 0o500)
        for p in folder.iterdir(): self.assertEqual(p.stat().st_mode & 0o777, 0o400)
        self.assertEqual(receipt, freeze_dataset(self.input, self.root))
        self.input.unlink()
        self.assertEqual(receipt, verify_dataset(ref, self.root))
        self.assertNotIn(str(self.work), json.dumps(receipt))
        self.assertNotIn('example.org', json.dumps(receipt))

    def test_same_version_different_bytes_conflict_without_overwrite(self):
        receipt = freeze_dataset(self.input, self.root); folder = self.root / receipt['dataset_ref']
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        self.input.write_bytes(self.input.read_bytes() + b'\n')
        with self.assertRaises(ExtractionError) as caught: freeze_dataset(self.input, self.root)
        self.assertEqual(caught.exception.code, 'DATASET_CONFLICT')
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_new_version_creates_distinct_archive_and_does_not_use_label_as_path(self):
        first = freeze_dataset(self.input, self.root)
        value = manifest(); value['dataset_version'] = '../../PRIVATE_SECRET/한글'
        self.input.write_text(json.dumps(value))
        second = freeze_dataset(self.input, self.root)
        self.assertNotEqual(first['dataset_ref'], second['dataset_ref'])
        self.assertEqual(second, verify_dataset(second['dataset_ref'], self.root))
        self.assertNotIn('PRIVATE_SECRET', json.dumps(second))
        self.assertEqual(len(list(self.root.iterdir())), 2)

    def test_concurrent_same_manifest_has_one_complete_identical_archive(self):
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: freeze_dataset(self.input, self.root), range(8)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual([p.name for p in self.root.iterdir()], [results[0]['dataset_ref']])

    def test_concurrent_conflicting_manifest_has_only_one_winner(self):
        other = self.work / 'other.json'; other.write_bytes(self.input.read_bytes() + b'\n')
        def execute(path):
            try: return freeze_dataset(path, self.root)
            except ExtractionError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as executor: results = list(executor.map(execute, [self.input, other]))
        self.assertEqual(sum(type(r) is dict for r in results), 1)
        self.assertIn('DATASET_CONFLICT', results)
        winner = next(r for r in results if type(r) is dict)
        self.assertEqual(winner, verify_dataset(winner['dataset_ref'], self.root))

    def test_tampering_writable_missing_and_unexpected_artifacts_rejected(self):
        receipt = freeze_dataset(self.input, self.root); ref = receipt['dataset_ref']; folder = self.root / ref
        p = folder / 'manifest.json'; original = p.read_bytes()
        p.chmod(0o600)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        p.write_bytes(original + b' '); p.chmod(0o400)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        p.chmod(0o600); p.write_bytes(original); p.chmod(0o400)
        self.assertEqual(receipt, verify_dataset(ref, self.root))
        folder.chmod(0o700)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        extra = folder / 'unexpected'; extra.write_text('PRIVATE_SECRET'); folder.chmod(0o500)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        folder.chmod(0o700); extra.unlink(); p.unlink(); folder.chmod(0o500)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)

    def test_receipt_forgery_and_symlink_never_read_external_target(self):
        receipt = freeze_dataset(self.input, self.root); ref = receipt['dataset_ref']; folder = self.root / ref
        target = folder / 'receipt.json'; original = target.read_bytes(); target.chmod(0o600)
        value = json.loads(original); value['summary']['counts']['documents'] = 999
        target.write_text(json.dumps(value)); target.chmod(0o400)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        folder.chmod(0o700); target.unlink(); target.symlink_to(self.input); folder.chmod(0o500)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)
        self.assertEqual(self.input.read_bytes(), FIXTURE.read_bytes())

    def test_input_root_and_dataset_directory_symlinks_rejected(self):
        link = self.work / 'input-link'; link.symlink_to(self.input)
        with self.assertRaises((ExtractionError, OSError)): freeze_dataset(link, self.root)
        self.root.mkdir(exist_ok=True); root_link = self.work / 'root-link'; root_link.symlink_to(self.root)
        with self.assertRaises(ExtractionError): freeze_dataset(self.input, root_link)
        ref = hashlib.sha256(b'synthetic-dataset-v1').hexdigest()
        (self.root / ref).symlink_to(self.work)
        with self.assertRaises(ExtractionError): verify_dataset(ref, self.root)

    def test_incomplete_existing_archive_is_not_replaced(self):
        ref = hashlib.sha256(b'synthetic-dataset-v1').hexdigest(); folder = self.root / ref
        folder.mkdir(parents=True); (folder / 'manifest.json').write_bytes(self.input.read_bytes())
        with self.assertRaises(ExtractionError): freeze_dataset(self.input, self.root)
        self.assertEqual(set(p.name for p in folder.iterdir()), {'manifest.json'})

    def test_failed_atomic_install_cleans_only_its_staging(self):
        self.root.mkdir(); sentinel = self.root / 'operator-note'; sentinel.write_text('KEEP')
        with patch('processing.evaluation.storage._rename_exclusive', side_effect=PermissionError(errno.EACCES, 'PRIVATE_SECRET')):
            with self.assertRaises(OSError): freeze_dataset(self.input, self.root)
        self.assertEqual([p.name for p in self.root.iterdir()], ['operator-note'])
        self.assertEqual(sentinel.read_text(), 'KEEP')
        self.assertEqual(self.input.read_bytes(), FIXTURE.read_bytes())

    def test_corrupt_staging_is_rejected_before_installing_dataset(self):
        from processing.evaluation.storage import _write
        def corrupt(path, content):
            _write(path, content)
            if path.name == 'manifest.json': path.write_bytes(content + b'\n')
        with patch('processing.evaluation.storage._write', side_effect=corrupt):
            with self.assertRaises(ExtractionError): freeze_dataset(self.input, self.root)
        self.assertEqual(list(self.root.iterdir()), [])
        self.assertEqual(self.input.read_bytes(), FIXTURE.read_bytes())

    def test_expanded_read_permissions_fail_verification(self):
        receipt = freeze_dataset(self.input, self.root); folder = self.root / receipt['dataset_ref']
        for path, expanded, original in ((folder/'manifest.json',0o444,0o400),
                                         (folder/'identity.json',0o440,0o400),
                                         (folder/'receipt.json',0o404,0o400),
                                         (folder,0o555,0o500)):
            path.chmod(expanded)
            with self.subTest(path=path.name), self.assertRaises(ExtractionError):
                verify_dataset(receipt['dataset_ref'], self.root)
            path.chmod(original)
        self.assertEqual(receipt, verify_dataset(receipt['dataset_ref'], self.root))

    def test_empty_destination_created_after_staging_is_never_replaced(self):
        from processing.evaluation.storage import _verify_directory
        inserted = []
        def race(directory, ref):
            result = _verify_directory(directory, ref)
            if directory.name.startswith('.dataset-'):
                target = self.root / ref; target.mkdir(mode=0o700)
                inserted.append((target, target.stat().st_ino))
            return result
        with patch('processing.evaluation.storage._verify_directory', side_effect=race):
            with self.assertRaises(ExtractionError): freeze_dataset(self.input, self.root)
        target, inode = inserted[0]
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(list(target.iterdir()), [])
        self.assertEqual(list(self.root.iterdir()), [target])

    def test_unsupported_atomic_rename_never_falls_back_to_overwriting(self):
        for unavailable in ('symbol', 'platform'):
            guard = (patch('processing.evaluation.storage.ctypes.CDLL', return_value=object())
                     if unavailable == 'symbol' else patch('processing.evaluation.storage.sys.platform', 'unsupported'))
            with self.subTest(unavailable=unavailable), guard, self.assertRaises(OSError) as caught:
                freeze_dataset(self.input, self.root)
            self.assertEqual(caught.exception.errno, errno.ENOTSUP)
            self.assertEqual(list(self.root.iterdir()), [])
            self.assertEqual(self.input.read_bytes(), FIXTURE.read_bytes())

    def test_invalid_input_and_future_assignments_do_not_create_root(self):
        self.input.write_bytes(b'{}')
        with self.assertRaises(ExtractionError): freeze_dataset(self.input, self.root)
        self.assertFalse(self.root.exists())
        value = manifest(); value['split_assignments'][0]['assigned_at'] = '2099-01-01T00:00:00Z'
        self.input.write_text(json.dumps(value))
        with self.assertRaises(ExtractionError): freeze_dataset(self.input, self.root)
        self.assertFalse(self.root.exists())

    def test_cli_check_freeze_verify_returns_safe_summary(self):
        checked = self.cli('check', '--input', str(self.input))
        self.assertEqual((checked.returncode, checked.stderr), (0, b''))
        self.assertEqual(json.loads(checked.stdout)['counts']['documents'], 4)
        frozen = self.cli('freeze', '--input', str(self.input), '--root', str(self.root))
        self.assertEqual((frozen.returncode, frozen.stderr), (0, b''))
        receipt = json.loads(frozen.stdout)
        verified = self.cli('verify', receipt['dataset_ref'], '--root', str(self.root))
        self.assertEqual((verified.returncode, verified.stderr), (0, b''))
        self.assertEqual(receipt, json.loads(verified.stdout))
        self.assertNotIn(b'example.org', frozen.stdout)
        self.assertNotIn(str(self.work).encode(), frozen.stdout)

    def test_cli_errors_never_echo_unknown_values_paths_or_bodies(self):
        self.input.write_text('{"PRIVATE_SECRET":true}')
        for args, code in ((('check', '--input', str(self.input)), 2),
                           (('check', '--PRIVATE_SECRET'), 2),
                           (('verify', '../PRIVATE_SECRET', '--root', str(self.root)), 2),
                           (('verify', 'a'*64, '--root', str(self.root)), 3),
                           (('check', '--input', str(self.work/'PRIVATE_SECRET')), 5)):
            result = self.cli(*args)
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE_SECRET', result.stderr)
            self.assertNotIn(str(self.work).encode(), result.stderr)


if __name__ == '__main__': unittest.main()
