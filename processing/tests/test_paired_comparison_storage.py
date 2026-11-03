import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import errno
import hashlib
import json
import shutil
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import comparison, comparison_storage as storage
from processing.extraction.archive import _fingerprint, _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import REPO, uid
from processing.tests.test_paired_comparison import PairedComparisonFixture


class PairedComparisonStorageTest(PairedComparisonFixture):
    def setUp(self):
        super().setUp()
        self.comparison_root = self.work / 'comparisons'

    def write_selection(self, value=None, name='comparison.json'):
        path = self.work / name; path.write_bytes(_json(self.selection if value is None else value)); return path

    def freeze(self, *, hour=6, root=None):
        class CompareClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, tzinfo=tz)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, 30, tzinfo=tz)
        with patch('processing.evaluation.comparison.datetime', CompareClock), patch('processing.extraction.archive.datetime', FreezeClock):
            return storage.freeze_comparison(self.write_selection(), self.comparison_root if root is None else root, self.evaluation_root)

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix(): (_fingerprint(p), p.stat().st_mode & 0o777)
                for p in folder.rglob('*') if p.is_file()}

    def test_full_images_are_frozen_reused_and_verified_without_original_paths(self):
        source = self.snapshot(self.evaluation_root)
        receipt = self.freeze(); ref = receipt['comparison_ref']; image = self.comparison_root / ref
        before = self.snapshot(image)
        self.assertTrue(all(mode == 0o400 for _, mode in before.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o500 for p in [image, *image.rglob('*')] if p.is_dir()))
        self.assertTrue(any(name.endswith('attempt-1.response') for name in before))
        for name, metadata in source.items(): self.assertEqual(before['evaluations/' + name], metadata)
        self.assertEqual((image / 'selection.json').read_bytes(), self.write_selection().read_bytes())
        for root in (self.evaluation_root, self.gold_root, self.run_root, self.human_root, self.rule_root):
            root.rename(root.with_name(root.name + '-gone'))
        self.input.unlink()
        self.assertEqual(storage.verify_comparison(ref, self.comparison_root), receipt)
        self.assertEqual(self.freeze(), receipt)
        self.assertEqual(self.snapshot(image), before)
        self.assertNotIn('PRIVATE_', json.dumps(receipt)); self.assertNotIn(str(self.work), json.dumps(receipt))

    def test_same_id_different_selection_bytes_conflict_preserves_original(self):
        receipt = self.freeze(); before = self.snapshot(self.comparison_root)
        path = self.write_selection(); path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaises(ExtractionError) as caught: storage.freeze_comparison(path, self.comparison_root, self.evaluation_root)
        self.assertEqual(caught.exception.code, 'COMPARISON_CONFLICT')
        self.assertEqual(storage.verify_comparison(receipt['comparison_ref'], self.comparison_root), receipt)
        self.assertEqual(self.snapshot(self.comparison_root), before)

    def test_native_same_and_conflicting_installations_are_exclusive(self):
        one = self.write_selection(name='one.json'); two = self.work / 'two.json'; two.write_bytes(one.read_bytes() + b' ')
        for paths, label, successes in (([one] * 4, 'same', 4), ([one, two], 'different', 1)):
            root = self.work / label
            def run(path):
                try: return storage.freeze_comparison(path, root, self.evaluation_root)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(run, paths))
            self.assertEqual(sum(isinstance(x, dict) for x in results), successes)
            if successes == 1: self.assertIn('COMPARISON_CONFLICT', results)
            else: self.assertTrue(all(x == results[0] for x in results))
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_retests_keep_all_initial_images_and_reused_declared_time(self):
        old = copy.deepcopy(self.references); self.new_evaluations()
        for method, value in self.controls.items():
            value.update(phase='retest', initial_ref=old[method]['evaluation_ref'])
            value['review']['reviewed_at'] = '2020-01-01T06:00:00Z'
        self.freeze_methods(hour=7)
        receipt = self.freeze(hour=8); image = self.comparison_root / receipt['comparison_ref']
        self.assertTrue(any('/initial/' in name for name in receipt['artifacts']))
        self.assertEqual(receipt['summary']['human_review_time']['total_duration_ns'], 600_000_000_000)
        self.assertEqual(receipt['summary']['phase'], 'retest'); self.assertFalse(receipt['summary']['generalization_claim'])
        for method in old:
            initial = image / 'evaluations' / self.references[method]['evaluation_ref'] / 'initial' / old[method]['evaluation_ref']
            self.assertEqual((initial / 'receipt.json').read_bytes(), (self.evaluation_root / old[method]['evaluation_ref'] / 'receipt.json').read_bytes())
        self.evaluation_root.rename(self.work / 'evaluations-gone')
        self.assertEqual(storage.verify_comparison(receipt['comparison_ref'], self.comparison_root), receipt)

    def test_nested_tamper_extra_missing_symlink_modes_and_invalid_identity_are_archive_errors(self):
        receipt = self.freeze(); ref = receipt['comparison_ref']; original = self.comparison_root / ref
        for case in ('extra', 'directory', 'missing', 'file-mode', 'dir-mode', 'symlink', 'result', 'source', 'identity'):
            root = self.work / ('corrupt-' + case); folder = root / ref; shutil.copytree(original, folder); folder.chmod(0o700)
            target = folder / 'result.json'
            if case == 'extra': (folder / 'extra').write_text('PRIVATE_VALUE'); (folder / 'extra').chmod(0o400)
            elif case == 'directory': (folder / 'extra').mkdir(mode=0o500)
            elif case == 'missing': target.unlink()
            elif case == 'file-mode': target.chmod(0o600)
            elif case == 'dir-mode': (folder / 'evaluations').chmod(0o700)
            elif case == 'symlink': target.unlink(); target.symlink_to(original / 'result.json')
            else:
                if case == 'source': target = folder / 'evaluations' / self.references['ai_auto']['evaluation_ref'] / 'result.json'
                elif case == 'identity': target = folder / 'identity.json'
                target.chmod(0o600)
                if case == 'identity':
                    value = json.loads(target.read_bytes()); value['recorded_at'] = 1.5; target.write_bytes(_json(value))
                else: target.write_bytes(target.read_bytes() + b' ')
                target.chmod(0o400)
            folder.chmod(0o500)
            with self.subTest(case=case):
                with self.assertRaises(ExtractionError) as caught: storage.verify_comparison(ref, root)
                self.assertEqual(caught.exception.kind, 'archive')
                self.assertEqual(caught.exception.code, 'COMPARISON_INTEGRITY')

    def test_copy_change_and_install_io_failure_remove_only_temporary_image(self):
        copy_file = storage._copy
        def change(source, destination, expected):
            if destination.name == 'result.json':
                source.chmod(0o600); source.write_bytes(source.read_bytes() + b' '); source.chmod(0o400)
            return copy_file(source, destination, expected)
        with patch.object(storage, '_rename_exclusive', side_effect=OSError(errno.EIO, 'PRIVATE_IO')):
            with self.assertRaises(OSError): self.freeze()
        self.assertEqual(list(self.comparison_root.iterdir()), [])
        with patch.object(storage, '_copy', side_effect=change):
            with self.assertRaises(ExtractionError): self.freeze()
        self.assertEqual(list(self.comparison_root.iterdir()), [])

    def test_partial_destination_created_by_competitor_is_not_replaced(self):
        def collision(source, destination):
            destination.mkdir(mode=0o500); raise FileExistsError(errno.EEXIST, 'synthetic')
        with patch.object(storage, '_rename_exclusive', side_effect=collision):
            with self.assertRaises(ExtractionError): self.freeze()
        destination = self.comparison_root / hashlib.sha256(self.selection['comparison_id'].encode()).hexdigest()
        self.assertEqual(list(destination.iterdir()), [])
        self.assertEqual(list(self.comparison_root.iterdir()), [destination])

    def test_same_parent_uuid_with_different_original_receipt_is_rejected(self):
        original = self.run_root; self.run_root = self.work / 'different-parent-image'
        try:
            selected = self.make_run(self.selected['run_id'], retry=True)
            human = self.make_human(uid(963), source=selected)
        finally: self.run_root = original
        self.controls['human_reviewed']['documents'][0].update(human)
        self.controls['human_reviewed']['extraction_eval_id'] = uid(823)
        self.freeze_methods(methods=['human_reviewed'])
        with self.assertRaises(ExtractionError) as caught: self.freeze()
        self.assertEqual(caught.exception.code, 'COMPARISON_PARENT_MISMATCH')
        self.assertEqual(list(self.comparison_root.iterdir()), [])

    def test_result_budget_rejects_before_installing_any_image(self):
        with patch.object(comparison, 'MAX_BYTES', 1):
            with self.assertRaises(ExtractionError) as caught: self.freeze()
        self.assertEqual(caught.exception.code, 'COMPARISON_RESULT_TOO_LARGE')
        self.assertEqual(list(self.comparison_root.iterdir()), [])

    def test_actual_cli_success_and_safe_input_archive_io_failures(self):
        path = self.write_selection(); root = self.work / 'cli-comparisons'
        def run(*arguments):
            return subprocess.run([sys.executable, '-m', 'processing.evaluation', *map(str, arguments)], cwd=REPO,
                capture_output=True, timeout=45)
        checked = run('check-comparison', '--input', path, '--evaluation-root', self.evaluation_root)
        self.assertEqual(checked.returncode, 0, checked.stderr); self.assertEqual(checked.stderr, b'')
        self.assertEqual(json.loads(checked.stdout)['pairs']['rules_to_ai']['improved'], 5)
        frozen = run('freeze-comparison', '--input', path, '--evaluation-root', self.evaluation_root, '--root', root)
        self.assertEqual(frozen.returncode, 0, frozen.stderr); receipt = json.loads(frozen.stdout)
        verified = run('verify-comparison', receipt['comparison_ref'], '--root', root)
        self.assertEqual(verified.returncode, 0, verified.stderr); self.assertEqual(json.loads(verified.stdout), receipt)
        self.assertEqual(verified.stdout.count(b'\n'), 1)
        for result in (checked, frozen, verified):
            self.assertNotIn(b'PRIVATE_', result.stdout); self.assertNotIn(str(self.work).encode(), result.stdout)
            self.assertNotIn(b'gold_values', result.stdout)
        bad = self.work / 'bad.json'; bad.write_bytes(b'{"schema_version":"PRIVATE_VALUE"}')
        blocked = self.work / 'file-root'; blocked.write_text('keep')
        cases = [(run('check-comparison', '--input', bad, '--evaluation-root', self.evaluation_root), 2),
            (run('check-comparison'), 2), (run('verify-comparison', '0' * 64, '--root', root), 3),
            (run('freeze-comparison', '--input', path, '--root', blocked, '--evaluation-root', self.evaluation_root), 3),
            (run('check-comparison', '--input', self.work / 'missing-input.json', '--evaluation-root', self.evaluation_root), 5)]
        for result, expected in cases:
            self.assertEqual(result.returncode, expected, result.stderr); self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE_', result.stderr); self.assertNotIn(str(self.work).encode(), result.stderr)
        self.assertEqual(blocked.read_text(), 'keep')
