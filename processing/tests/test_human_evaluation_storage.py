import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import errno
import hashlib
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import evaluation_storage as storage, records
from processing.evaluation.storage import freeze_dataset
from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_evaluation_records import DatasetClock
from processing.tests.test_human_evaluation import HumanEvaluationFixture


class HumanEvaluationStorageTest(HumanEvaluationFixture):
    def write_control(self, value=None, name='selection.json'):
        path = self.work / name; path.write_bytes(_json(self.control if value is None else value)); return path

    def freeze(self, value=None, hour=5, root=None, run_root=None):
        class EvalClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, tzinfo=timezone.utc)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, 30, tzinfo=timezone.utc)
        path = self.write_control(value)
        with patch('processing.evaluation.records.datetime', EvalClock), patch('processing.extraction.archive.datetime', FreezeClock):
            return storage.freeze_evaluation(path, self.initial_root if root is None else root, self.gold_root,
                self.human_root if run_root is None else run_root, self.initial_root)

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix(): (p.read_bytes(), p.stat().st_mode & 0o777)
                for p in folder.rglob('*') if p.is_file()}

    def retest(self, initial, identity=970):
        value = copy.deepcopy(self.control)
        value.update(extraction_eval_id=uid(identity), phase='retest', initial_ref=initial['evaluation_ref'])
        value['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        return value

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'processing.evaluation', *map(str, args)],
                              cwd=Path(__file__).resolve().parents[2], capture_output=True)

    def test_full_human_parent_tree_replays_without_original_paths(self):
        receipt = self.freeze(); directory = self.initial_root / receipt['evaluation_ref']; before = self.snapshot(directory)
        reference = self.control['documents'][0]['review_ref']
        self.assertIn(f'runs/{reference}/source/{self.selected["snapshot_ref"]}/attempt-1.exchange', before)
        for path in self.human_root.joinpath(reference).rglob('*'):
            if path.is_file():
                self.assertEqual(before[f'runs/{reference}/{path.relative_to(self.human_root / reference).as_posix()}'][0], path.read_bytes())
        for folder in (self.human_root, self.gold_root, self.run_root, self.dataset_root):
            folder.rename(folder.with_name(folder.name + '-gone'))
        self.input.unlink(); self.gold_control.unlink()
        self.assertEqual(storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root), receipt)
        self.assertEqual(self.freeze(), receipt)
        self.assertEqual(self.snapshot(directory), before)
        self.assertTrue(all(mode == 0o400 for _, mode in before.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o500 for p in [directory, *directory.rglob('*')] if p.is_dir()))

    def test_new_review_after_initial_can_reuse_exact_parent(self):
        initial = self.freeze(); value = self.retest(initial)
        value['documents'][0].update(self.make_human(uid(960), started='2020-01-01T06:00:00Z',
            finished='2020-01-01T06:10:00Z', frozen='2020-01-01T06:20:00Z'))
        receipt = self.freeze(value, hour=8)
        self.assertEqual(receipt['summary']['initial_comparison']['human_reviewed_delta_percent'], 0)
        result = json.loads((self.initial_root / receipt['evaluation_ref'] / 'result.json').read_bytes())
        self.assertEqual(result['documents'][0]['source_run_id'], self.selected['run_id'])
        self.assertEqual(result['review_ids'], [uid(960)])
        for folder in (self.human_root, self.run_root, self.gold_root): folder.rename(folder.with_name(folder.name + '-gone'))
        original = self.initial_root / initial['evaluation_ref']; original.chmod(0o700)
        moved = original.rename(self.work / 'initial-gone'); moved.chmod(0o500)
        self.assertEqual(storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root), receipt)

    def test_new_review_must_start_after_initial_and_retest_is_not_initial(self):
        initial = self.freeze(); value = self.retest(initial)
        value['documents'][0].update(self.make_human(uid(961)))
        with self.assertRaises(ExtractionError) as caught: self.freeze(value, hour=8)
        self.assertEqual(caught.exception.code, 'EVALUATION_RETEST_REVIEW_TIME_INVALID')
        value['documents'][0].update(self.control['documents'][0]); retest = self.freeze(value, hour=8)
        value.update(extraction_eval_id=uid(971), initial_ref=retest['evaluation_ref'])
        with self.assertRaises(ExtractionError) as caught: self.freeze(value, hour=9)
        self.assertEqual(caught.exception.code, 'EVALUATION_INITIAL_REQUIRED')

    def test_same_review_identity_cannot_select_another_receipt(self):
        initial = self.freeze(); value = self.retest(initial); other = self.work / 'other-human-root'
        value['documents'][0].update(self.make_human(uid(950), root=other, started='2020-01-01T06:00:00Z',
            finished='2020-01-01T06:10:00Z', frozen='2020-01-01T06:20:00Z'))
        with self.assertRaises(ExtractionError) as caught: self.freeze(value, hour=8, run_root=other)
        self.assertEqual(caught.exception.code, 'EVALUATION_RETEST_REVIEW_MISMATCH')

    def test_same_parent_identity_cannot_change_original_receipt(self):
        initial = self.freeze(); value = self.retest(initial); original_root = self.run_root
        try:
            self.run_root = self.work / 'other-ai-root'
            source = self.make_run(self.selected['run_id'], started='2020-01-01T06:00:00Z', prompt_version='prompt-v1')
            selected = self.make_human(uid(962), source=source, started='2020-01-01T06:30:00Z',
                finished='2020-01-01T06:40:00Z', frozen='2020-01-01T06:50:00Z')
        finally: self.run_root = original_root
        value['documents'][0].update(selected)
        with self.assertRaises(ExtractionError) as caught: self.freeze(value, hour=8)
        self.assertEqual(caught.exception.code, 'EVALUATION_RETEST_PARENT_MISMATCH')

    def test_initial_rejects_parent_uuid_reused_for_different_document_versions(self):
        second = copy.deepcopy(self.source); second['document_version_id'] = uid(102)
        path = self.work / 'second-version.json'; path.write_bytes(_json(second))
        self.manifest['dataset_version'] = 'fictional-parent-collision'
        self.manifest['documents'][0]['versions'].append(dict(document_version_id=uid(102),
            input_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        manifest_path = self.work / 'two-version-manifest.json'; manifest_path.write_bytes(_json(self.manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock):
            dataset = freeze_dataset(manifest_path, self.dataset_root)
        answer = copy.deepcopy(self.value['documents'][0]); answer.update(document_version_id=uid(102), input_path=str(path))
        answer['output']['document_version_id'] = uid(102)
        self.value.update(gold_version='fictional-parent-collision-gold', dataset_ref=dataset['dataset_ref'],
                          manifest_sha256=dataset['manifest_sha256'])
        self.value['documents'].append(answer); self.gold_receipt = self.make_gold()
        value = copy.deepcopy(self.control); value.update(gold_ref=self.gold_receipt['gold_ref'],
            gold_receipt_sha256=self.gold_receipt_hash())
        original_input, original_output, original_root = self.input, self.good_output, self.run_root
        try:
            self.input, self.good_output, self.run_root = path, answer['output'], self.work / 'colliding-parent'
            parent = self.make_run(self.selected['run_id'])
            selected = self.make_human(uid(965), source=parent)
        finally: self.input, self.good_output, self.run_root = original_input, original_output, original_root
        value['documents'].append(dict(document_version_id=uid(102), **selected, annotation=self.annotations(answer['output'])))
        with self.assertRaises(ExtractionError) as caught: self.evaluate(value)
        self.assertEqual(caught.exception.code, 'EVALUATION_PARENT_IDENTITY_CONFLICT')
        with self.assertRaises(ExtractionError) as caught: self.freeze(value)
        self.assertEqual(caught.exception.code, 'EVALUATION_PARENT_IDENTITY_CONFLICT')
        self.assertEqual(list(self.initial_root.iterdir()), [])

    def test_gold_feedback_and_unknown_retests_keep_observed_scores_with_exposure(self):
        initial = self.freeze()
        for index, basis in enumerate(('gold_feedback', 'unknown')):
            value = self.retest(initial, 972 + index)
            value['documents'][0].update(self.make_human(uid(963 + index), basis=basis,
                started='2020-01-01T06:00:00Z', finished='2020-01-01T06:10:00Z', frozen='2020-01-01T06:20:00Z'))
            value['review']['semantic_feedback_used'] = basis == 'gold_feedback'
            receipt = self.freeze(value, hour=8); summary = receipt['summary']
            self.assertEqual(summary['views']['human_reviewed']['correct_fields'], 8)
            self.assertIn('HUMAN_REVIEW_BASIS_UNCLEARED', summary['m02']['warnings'])
            self.assertIsNone(summary['m02']['accuracy_percent']); self.assertFalse(summary['generalization_claim'])

    def test_gold_correction_reuses_review_and_preserves_initial_image(self):
        self.value['gold_version'] = 'fictional-human-wrong-gold'
        self.value['documents'][0]['output']['items'][0]['occurrences'][0]['time_end']['value'] = '15:00'
        self.gold_receipt = self.make_gold(); self.control.update(gold_ref=self.gold_receipt['gold_ref'],
            gold_receipt_sha256=self.gold_receipt_hash())
        self.control['documents'][0]['annotation']['generation_reviews'] = [dict(local_item_id='item1',
            field='time_end', unsupported=False, reason='합성 금표 오류')]
        initial = self.freeze(); original = self.initial_root / initial['evaluation_ref']; before = self.snapshot(original)
        self.value['gold_version'] = 'fictional-human-corrected-gold'
        self.value['documents'][0]['output'] = copy.deepcopy(self.good_output)
        self.value['authorship'].update(authored_at='2020-01-01T05:45:00Z', reviewed_at='2020-01-01T05:55:00Z')
        class GoldClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 6, tzinfo=timezone.utc)
        self.gold_receipt = self.make_gold(GoldClock)
        value = self.retest(initial); value.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        receipt = self.freeze(value, hour=8)
        self.assertTrue(receipt['summary']['gold_changed'])
        self.assertEqual(receipt['summary']['initial_comparison']['human_reviewed_delta_percent'], 12.5)
        self.assertEqual(receipt['summary']['human_review_time']['total_duration_ns'], 600_000_000_000)
        self.assertEqual(self.snapshot(original), before)

    def test_both_cross_method_initial_references_are_rejected(self):
        initial = self.freeze(self.ai_control, run_root=self.run_root)
        with self.assertRaises(ExtractionError) as caught: self.freeze(self.retest(initial), hour=8)
        self.assertEqual(caught.exception.code, 'EVALUATION_COHORT_MISMATCH')
        self.initial_root = self.work / 'human-initials'
        human = self.freeze(); value = copy.deepcopy(self.ai_control)
        value.update(extraction_eval_id=uid(974), phase='retest', initial_ref=human['evaluation_ref'])
        value['review']['reviewed_at'] = '2020-01-01T07:00:00Z'
        with self.assertRaises(ExtractionError) as caught: self.freeze(value, hour=8, run_root=self.run_root)
        self.assertEqual(caught.exception.code, 'EVALUATION_COHORT_MISMATCH')

    def test_tampered_nested_source_result_extra_and_modes_fail_closed(self):
        receipt = self.freeze(); folder = self.initial_root / receipt['evaluation_ref']
        reference = self.control['documents'][0]['review_ref']
        paths = [folder / 'result.json', folder / 'runs' / reference / 'source' / self.selected['snapshot_ref'] / 'attempt-1.response']
        for path in paths:
            before = path.read_bytes(); path.chmod(0o600); path.write_bytes(before + b' '); path.chmod(0o400)
            with self.subTest(path=path.name), self.assertRaises(ExtractionError): storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root)
            path.chmod(0o600); path.write_bytes(before); path.chmod(0o400)
        folder.chmod(0o700); extra = folder / 'extra'; extra.mkdir(mode=0o500); folder.chmod(0o500)
        with self.assertRaises(ExtractionError): storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root)
        folder.chmod(0o700); extra.rmdir(); folder.chmod(0o500)
        paths[0].chmod(0o600)
        with self.assertRaises(ExtractionError): storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root)
        paths[0].chmod(0o400)
        target = paths[1]; raw = target.read_bytes(); copied = self.work / 'response-copy'
        copied.write_bytes(raw); copied.chmod(0o400)
        target.parent.chmod(0o700); target.unlink(); target.symlink_to(copied); target.parent.chmod(0o500)
        with self.assertRaises(ExtractionError): storage.verify_evaluation(receipt['evaluation_ref'], self.initial_root)

    def test_native_races_and_failed_install_do_not_overwrite(self):
        one = self.write_control(name='one.json'); value = copy.deepcopy(self.control)
        value['review']['exposure_note'] = '합성 다른 입력'; other = self.write_control(value, 'two.json')
        for paths, name, count in [([one] * 4, 'same', 4), ([one, other], 'conflict', 1)]:
            root = self.work / name
            def run(path):
                try: return storage.freeze_evaluation(path, root, self.gold_root, self.human_root, self.initial_root)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=4) as pool: results = list(pool.map(run, paths))
            self.assertEqual(sum(isinstance(r, dict) for r in results), count)
            if count == 1: self.assertIn('EVALUATION_CONFLICT', results)
            self.assertEqual(len(list(root.iterdir())), 1)
        failed = self.work / 'failed-install'
        with patch.object(storage, '_rename_exclusive', side_effect=OSError(errno.EIO, 'PRIVATE_IO')):
            with self.assertRaises(OSError): self.freeze(root=failed)
        self.assertEqual(list(failed.iterdir()), [])

    def test_default_storage_and_cli_route_to_human_root(self):
        from processing.evaluation import __main__ as cli
        path = self.write_control()
        with patch.multiple(records, REVIEW_ROOT=self.human_root, RUN_ROOT=self.work / 'wrong-ai', RULE_ROOT=self.work / 'wrong-rules'):
            receipt = storage.freeze_evaluation(path, self.initial_root, self.gold_root, initial_root=self.initial_root)
            out, err = StringIO(), StringIO()
            with patch.object(sys, 'argv', ['evaluation', 'check-evaluation', '--input', str(path), '--gold-root', str(self.gold_root)]), redirect_stdout(out), redirect_stderr(err):
                code = cli.main()
        self.assertEqual((code, err.getvalue()), (0, ''))
        self.assertEqual(json.loads(out.getvalue())['views']['human_reviewed']['correct_fields'], 8)
        self.assertEqual(receipt['summary']['method'], 'human_reviewed')

    def test_real_cli_check_freeze_verify_and_safe_error_codes(self):
        path = self.write_control(); args = ['--input', path, '--gold-root', self.gold_root, '--run-root', self.human_root]
        checked = self.cli('check-evaluation', *args)
        self.assertEqual((checked.returncode, checked.stderr), (0, b''))
        self.assertEqual(json.loads(checked.stdout)['views']['human_reviewed']['correct_fields'], 8)
        frozen = self.cli('freeze-evaluation', *args, '--root', self.initial_root)
        self.assertEqual((frozen.returncode, frozen.stderr), (0, b''))
        ref = json.loads(frozen.stdout)['evaluation_ref']
        verified = self.cli('verify-evaluation', ref, '--root', self.initial_root)
        self.assertEqual((verified.returncode, verified.stdout, verified.stderr), (0, frozen.stdout, b''))
        for output in (checked, frozen, verified):
            self.assertNotIn(b'PRIVATE_', output.stdout + output.stderr); self.assertNotIn(str(self.work).encode(), output.stdout + output.stderr)
        self.assertEqual(self.cli('check-evaluation').returncode, 2)
        missing = self.cli('check-evaluation', '--input', self.work / 'PRIVATE_MISSING')
        self.assertEqual((missing.returncode, missing.stdout, missing.stderr), (5, b'', b'DATASET_IO_FAILED\n'))
        (self.initial_root / ref / 'result.json').chmod(0o600)
        corrupt = self.cli('verify-evaluation', ref, '--root', self.initial_root)
        self.assertEqual((corrupt.returncode, corrupt.stdout, corrupt.stderr), (3, b'', b'EVALUATION_INTEGRITY\n'))

    def test_complete_declared_real_cohort_never_enables_ai_target_for_human_scores(self):
        # real 선언 분기만 시험한다. 문서·응답·검토자40건 모두 가상이며 실제 성능 실적이 아니다.
        manifest = copy.deepcopy(self.manifest); manifest.update(dataset_version='fictional-human-real-gate', data_kind='real', documents=[], events=[], split_assignments=[])
        manifest['grouping_review'].update(reviewed_by='fictional-reviewer', reviewed_at='2020-01-01T00:00:00Z')
        answers, inputs = [], []
        for i in range(40):
            source = copy.deepcopy(self.source); source.update(data_kind='real', document_version_id=uid(1000 + i))
            path = self.work / f'fictional-{i}.json'; path.write_bytes(_json(source)); inputs.append(path)
            doc = copy.deepcopy(self.manifest['documents'][0]); doc.update(document_id=uid(2000 + i),
                official_url=f'https://example.test/fictional-human/{i}', exposure_status='development' if i < 20 else 'unexposed',
                versions=[dict(document_version_id=uid(1000 + i), input_sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
            manifest['documents'].append(doc)
            manifest['events'].append(dict(event_id=uid(3000 + i), document_ids=[uid(2000 + i)], split_group_id=uid(4000 + i), suspected_duplicate_ids=[]))
            assignment = copy.deepcopy(self.manifest['split_assignments'][0]); assignment.update(document_id=uid(2000 + i), split_group_id=uid(4000 + i), split='dev' if i < 20 else 'holdout')
            manifest['split_assignments'].append(assignment)
            answer = copy.deepcopy(self.value['documents'][0]); answer.update(document_version_id=uid(1000 + i), input_path=str(path))
            answer['output']['document_version_id'] = uid(1000 + i); answer['anchors'][0]['event_id'] = uid(3000 + i); answers.append(answer)
        path = self.work / 'fictional-manifest.json'; path.write_bytes(_json(manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock): dataset = freeze_dataset(path, self.dataset_root)
        self.value.update(gold_version='fictional-human-real-gold', dataset_ref=dataset['dataset_ref'], manifest_sha256=dataset['manifest_sha256'], documents=answers)
        self.gold_receipt = self.make_gold(); value = copy.deepcopy(self.control)
        value.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash(), documents=[])
        value['review']['exposure_status'] = 'none_declared'
        for i, (path, answer) in enumerate(zip(inputs, answers)):
            self.input = path; self.good_output = answer['output']
            source = self.make_run(uid(5000 + i)); selected = self.make_human(uid(6000 + i), source=source)
            value['documents'].append(dict(document_version_id=answer['document_version_id'], **selected, annotation=self.annotations(self.good_output)))
        summary = self.evaluate(value)['result']['summary']
        self.assertEqual(summary['views']['human_reviewed']['known_fields'], 320)
        self.assertEqual(summary['splits']['holdout']['human_reviewed']['known_fields'], 160)
        self.assertEqual(summary['human_review_time']['splits']['holdout'], dict(review_count=20, total_duration_ns=12_000_000_000_000))
        self.assertEqual(summary['m02']['warnings'], ['M02_REQUIRES_AI_AUTO'])
        self.assertFalse(summary['m02']['eligible_as_declared']); self.assertIsNone(summary['m02']['accuracy_percent'])
