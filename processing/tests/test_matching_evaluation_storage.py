import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import errno
import hashlib
import io
import json
import shutil
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import matching_storage as storage
from processing.evaluation import __main__ as cli
from processing.extraction.archive import _fingerprint, _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import REPO, uid
from processing.tests.test_matching_evaluation import MatchingEvaluationFixture, MATCHING_AT


class MatchingStorageTest(MatchingEvaluationFixture):
    def freeze(self, selection=None, *, at=MATCHING_AT, root=None):
        instant = datetime.fromisoformat(at.replace('Z', '+00:00'))
        class EvalClock(datetime):
            @classmethod
            def now(cls, tz=None): return instant
        class SealClock(datetime):
            @classmethod
            def now(cls, tz=None): return instant + timedelta(hours=1)
        with patch('processing.evaluation.matching.datetime', EvalClock), patch('processing.extraction.archive.datetime', SealClock):
            return storage.freeze_matching(self.write_matching(selection), self.matching_root if root is None else root,
                                           self.comparison_root, self.matching_root)

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): (_fingerprint(p), p.stat().st_mode & 0o777)
                for p in root.rglob('*') if p.is_file()}

    def test_all_originals_are_sealed_and_survive_source_path_removal(self):
        before = self.snapshot(self.comparison_root)
        receipt = self.freeze(); ref = receipt['matching_ref']; image = self.matching_root / ref
        saved = self.snapshot(image)
        for name, metadata in before.items(): self.assertEqual(saved['comparisons/' + name], metadata)
        self.assertTrue(any(name.endswith('attempt-1.response') for name in saved))
        self.assertTrue(all(mode == 0o400 for _, mode in saved.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o500 for p in [image, *image.rglob('*')] if p.is_dir()))
        self.assertEqual((image / 'selection.json').read_bytes(), self.write_matching().read_bytes())
        for root in (self.comparison_root, self.evaluation_root, self.gold_root, self.run_root, self.rule_root, self.human_root):
            root.rename(root.with_name(root.name + '-gone'))
        self.input.unlink()
        self.assertEqual(storage.verify_matching(ref, self.matching_root), receipt)
        self.assertEqual(self.freeze(), receipt)
        self.assertEqual(self.snapshot(image), saved)
        self.assertNotIn('PRIVATE_', json.dumps(receipt))
        self.assertNotIn(str(self.work), json.dumps(receipt))

    def test_same_identity_with_other_bytes_preserves_first_image(self):
        receipt = self.freeze(); before = self.snapshot(self.matching_root)
        path = self.write_matching(); path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaises(ExtractionError) as caught:
            storage.freeze_matching(path, self.matching_root, self.comparison_root, self.matching_root)
        self.assertEqual(caught.exception.code, 'MATCHING_CONFLICT')
        self.assertEqual(storage.verify_matching(receipt['matching_ref'], self.matching_root), receipt)
        self.assertEqual(before, self.snapshot(self.matching_root))

    def test_competing_same_or_different_bytes_install_exclusively(self):
        first = self.write_matching(); one = self.work / 'one.json'; one.write_bytes(first.read_bytes())
        two = self.work / 'two.json'; two.write_bytes(one.read_bytes() + b' ')
        for paths, label, winners in (([one] * 3, 'same', 3), ([one, two], 'different', 1)):
            root = self.work / label
            def run(path):
                try: return storage.freeze_matching(path, root, self.comparison_root, self.matching_root)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(run, paths))
            self.assertEqual(sum(type(r) is dict for r in results), winners)
            if winners == 1: self.assertIn('MATCHING_CONFLICT', results)
            else: self.assertTrue(all(r == results[0] for r in results))
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_retest_copies_entire_initial_and_verifies_without_both_sources(self):
        initial = self.freeze(); old = self.matching_root / initial['matching_ref']; before = self.snapshot(old)
        selection = copy.deepcopy(self.matching_selection)
        selection.update(matching_eval_id=uid(1400), phase='retest',
            initial=dict(matching_ref=initial['matching_ref'], receipt_sha256=hashlib.sha256((old / 'receipt.json').read_bytes()).hexdigest()))
        receipt = self.freeze(selection, at='2026-11-03T05:00:00Z', root=self.work / 'retest')
        image = self.work / 'retest' / receipt['matching_ref']
        for name, metadata in before.items(): self.assertEqual(self.snapshot(image)['initial/' + initial['matching_ref'] + '/' + name], metadata)
        self.assertEqual(receipt['summary']['phase'], 'retest')
        self.assertFalse(receipt['summary']['generalization_claim'])
        self.comparison_root.rename(self.work / 'comparison-gone')
        self.matching_root.rename(self.work / 'initial-gone')
        self.assertEqual(storage.verify_matching(receipt['matching_ref'], self.work / 'retest'), receipt)
        with self.assertRaises(ExtractionError): storage._verify_directory(image, receipt['matching_ref'], initial_only=True)

    def test_nested_corruption_extras_modes_and_links_are_not_reused(self):
        receipt = self.freeze(); ref = receipt['matching_ref']; original = self.matching_root / ref
        for case in ('extra', 'directory', 'missing', 'file-mode', 'dir-mode', 'symlink', 'result', 'source', 'identity'):
            root = self.work / ('bad-' + case); folder = root / ref; shutil.copytree(original, folder); folder.chmod(0o700)
            target = folder / 'result.json'
            if case == 'extra': (folder / 'extra').write_text('PRIVATE_VALUE'); (folder / 'extra').chmod(0o400)
            elif case == 'directory': (folder / 'extra').mkdir(mode=0o500)
            elif case == 'missing': target.unlink()
            elif case == 'file-mode': target.chmod(0o600)
            elif case == 'dir-mode': (folder / 'comparisons').chmod(0o700)
            elif case == 'symlink': target.unlink(); target.symlink_to(original / 'result.json')
            else:
                if case == 'source': target = folder / 'comparisons' / self.comparison_reference['comparison_ref'] / 'result.json'
                elif case == 'identity': target = folder / 'identity.json'
                target.chmod(0o600)
                if case == 'identity':
                    data = json.loads(target.read_bytes()); data['recorded_at'] = 1.5; target.write_bytes(_json(data))
                else: target.write_bytes(target.read_bytes() + b' ')
                target.chmod(0o400)
            folder.chmod(0o500)
            with self.subTest(case=case):
                with self.assertRaises(ExtractionError) as caught: storage.verify_matching(ref, root)
                self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'MATCHING_INTEGRITY'))

    def test_rehashed_false_result_is_recomputed_instead_of_trusted(self):
        receipt = self.freeze(); ref = receipt['matching_ref']; folder = self.matching_root / ref
        folder.chmod(0o700); result = folder / 'result.json'; result.chmod(0o600)
        data = json.loads(result.read_bytes()); data['summary']['generalization_claim'] = True; result.write_bytes(_json(data)); result.chmod(0o400)
        identity_file = folder / 'identity.json'; identity_file.chmod(0o600); identity = json.loads(identity_file.read_bytes())
        identity['artifacts']['result.json'] = _fingerprint(result); identity_file.write_bytes(_json(identity)); identity_file.chmod(0o400)
        receipt_file = folder / 'receipt.json'; receipt_file.chmod(0o600); forged = dict(receipt, artifacts=identity['artifacts'], summary=data['summary'])
        receipt_file.write_bytes(_json(forged)); receipt_file.chmod(0o400); folder.chmod(0o500)
        with self.assertRaises(ExtractionError) as caught: storage.verify_matching(ref, self.matching_root)
        self.assertEqual(caught.exception.code, 'MATCHING_INTEGRITY')

    def test_copy_change_and_install_io_failures_preserve_sources_and_no_partial_destination(self):
        before = self.snapshot(self.comparison_root)
        with patch.object(storage, '_rename_exclusive', side_effect=OSError(errno.EIO, 'PRIVATE_IO')):
            with self.assertRaises(OSError): self.freeze()
        self.assertEqual(list(self.matching_root.iterdir()), [])
        self.assertEqual(self.snapshot(self.comparison_root), before)
        copy_file = storage._copy
        def change(source, destination, expected):
            if destination.name == 'result.json':
                source.chmod(0o600); source.write_bytes(source.read_bytes() + b' '); source.chmod(0o400)
            return copy_file(source, destination, expected)
        with patch.object(storage, '_copy', side_effect=change):
            with self.assertRaises(ExtractionError): self.freeze()
        self.assertEqual(list(self.matching_root.iterdir()), [])

    def test_partial_destination_is_not_replaced(self):
        def compete(source, destination):
            destination.mkdir(mode=0o500); raise FileExistsError(errno.EEXIST, 'synthetic')
        with patch.object(storage, '_rename_exclusive', side_effect=compete):
            with self.assertRaises(ExtractionError): self.freeze()
        destination = self.matching_root / hashlib.sha256(self.matching_selection['matching_eval_id'].encode()).hexdigest()
        self.assertEqual(list(self.matching_root.iterdir()), [destination]); self.assertEqual(list(destination.iterdir()), [])

    def test_result_limit_and_oversized_input_do_not_install(self):
        with patch('processing.evaluation.matching.MAX_BYTES', 1):
            with self.assertRaises(ExtractionError): self.freeze()
        self.assertEqual(list(self.matching_root.iterdir()), [])
        path = self.work / 'large.json'; path.write_bytes(b' ' * (8 * 1024 * 1024 + 1))
        with self.assertRaises(ExtractionError): storage.freeze_matching(path, self.matching_root, self.comparison_root, self.matching_root)
        self.assertEqual(list(self.matching_root.iterdir()), [])

    def test_actual_cli_is_single_safe_json_and_classifies_failures(self):
        path = self.write_matching(); root = self.work / 'cli-matching'
        def run(*args):
            return subprocess.run([sys.executable, '-m', 'processing.evaluation', *map(str, args)], cwd=REPO,
                capture_output=True, timeout=45)
        checked = run('check-matching', '--input', path, '--comparison-root', self.comparison_root)
        self.assertEqual(checked.returncode, 0, checked.stderr); self.assertEqual(checked.stderr, b'')
        self.assertFalse(json.loads(checked.stdout)['generalization_claim'])
        frozen = run('freeze-matching', '--input', path, '--root', root, '--comparison-root', self.comparison_root)
        self.assertEqual(frozen.returncode, 0, frozen.stderr); receipt = json.loads(frozen.stdout)
        verified = run('verify-matching', receipt['matching_ref'], '--root', root)
        self.assertEqual(verified.returncode, 0, verified.stderr); self.assertEqual(json.loads(verified.stdout), receipt)
        for result in (checked, frozen, verified):
            self.assertEqual(result.stdout.count(b'\n'), 1)
            self.assertNotIn(b'PRIVATE_', result.stdout); self.assertNotIn(str(self.work).encode(), result.stdout)
            self.assertNotIn(b'event_id', result.stdout); self.assertNotIn(b'gold_values', result.stdout)
        bad = self.work / 'bad.json'; bad.write_bytes(b'{"schema_version":"PRIVATE_VALUE"}')
        blocked = self.work / 'file-root'; blocked.write_text('keep')
        cases = [(run('check-matching', '--input', bad, '--comparison-root', self.comparison_root), 2),
                 (run('check-matching'), 2), (run('verify-matching', '0' * 64, '--root', root), 3),
                 (run('freeze-matching', '--input', path, '--root', blocked, '--comparison-root', self.comparison_root), 3),
                 (run('check-matching', '--input', self.work / 'missing', '--comparison-root', self.comparison_root), 5)]
        for result, code in cases:
            self.assertEqual(result.returncode, code, result.stderr); self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE_', result.stderr); self.assertNotIn(str(self.work).encode(), result.stderr)
        self.assertEqual(blocked.read_text(), 'keep')

    def test_unexpected_cli_failures_have_fixed_stderr_and_exit_one(self):
        path = self.write_matching()
        cases = [('check-matching', 'evaluate_matching', ['--input', str(path)]),
                 ('freeze-matching', 'freeze_matching', ['--input', str(path)]),
                 ('verify-matching', 'verify_matching', ['0' * 64])]
        for command, target, args in cases:
            with self.subTest(command=command), patch.object(sys, 'argv', ['evaluation', command, *args]), \
                    patch.object(cli, target, side_effect=RuntimeError('PRIVATE_VALUE')), \
                    patch.object(sys, 'stdout', io.StringIO()) as stdout, patch.object(sys, 'stderr', io.StringIO()) as stderr:
                self.assertEqual(cli.main(), 1)
                self.assertEqual(stdout.getvalue(), '')
                self.assertEqual(stderr.getvalue(), 'DATASET_INTERNAL_FAILED\n')
