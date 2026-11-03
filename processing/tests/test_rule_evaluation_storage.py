from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import copy
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import __main__ as cli, evaluation_storage as storage, records
from processing.extraction.archive import _fingerprint
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_rule_evaluation import RuleEvaluationFixture, encoded


class RuleEvaluationStorageTest(RuleEvaluationFixture):
    def write_control(self, value=None, name='selection.json'):
        path = self.work/name; path.write_bytes(encoded(self.control if value is None else value)); return path

    def freeze(self, value=None, hour=5, root=None, run_root=None):
        class EvalClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, tzinfo=timezone.utc)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, 30, tzinfo=timezone.utc)
        with patch('processing.evaluation.records.datetime', EvalClock), patch('processing.extraction.archive.datetime', FreezeClock):
            return storage.freeze_evaluation(self.write_control(value), root or self.initial_root, self.gold_root,
                self.rule_root if run_root is None else run_root, self.initial_root)

    def snapshot(self, folder):
        return {p.relative_to(folder).as_posix(): (_fingerprint(p), p.stat().st_mode & 0o777)
                for p in folder.rglob('*') if p.is_file()}

    def command(self, *arguments):
        return subprocess.run([sys.executable, '-m', 'processing.evaluation', *arguments],
            cwd=Path(__file__).resolve().parents[2], capture_output=True)

    def test_six_source_files_copy_reuse_and_verify_without_original_paths(self):
        receipt = self.freeze(); ref = receipt['evaluation_ref']; folder = self.initial_root/ref
        before = self.snapshot(folder)
        source_names = {p.split('/')[-1] for p in before if p.startswith('runs/')}
        self.assertEqual(source_names, {'input.json', 'profile.json', 'output.json', 'metadata.json', 'identity.json', 'receipt.json'})
        self.assertEqual((folder/'selection.json').read_bytes(), self.write_control().read_bytes())
        self.assertTrue(all(mode == 0o400 for _, mode in before.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o500 for p in [folder, *folder.rglob('*')] if p.is_dir()))
        self.gold_root.rename(self.work/'gold-gone'); self.rule_root.rename(self.work/'rules-gone')
        self.input.unlink(); self.profile_path.unlink()
        self.assertEqual(storage.verify_evaluation(ref, self.initial_root), receipt)
        self.assertEqual(self.freeze(), receipt)
        self.assertEqual(self.snapshot(folder), before)
        self.assertNotIn('PRIVATE_', json.dumps(receipt)); self.assertNotIn(str(self.work), json.dumps(receipt))

    def test_default_freeze_root_delegates_to_method_and_embedded_roots_stay_explicit(self):
        original = records.evaluate_record
        def check_default(content, gold_root, run_root, *args, **kwargs):
            # 기본 경로 실수로 실제 private 원본을 읽기 전에 모듈 경계에서 차단한다.
            if gold_root == self.gold_root: self.assertIsNone(run_root)
            return original(content, gold_root, run_root, *args, **kwargs)
        with patch.object(records, 'RULE_ROOT', self.rule_root), patch.object(storage, 'evaluate_record', side_effect=check_default):
            receipt = storage.freeze_evaluation(self.write_control(), root=self.initial_root,
                gold_root=self.gold_root, initial_root=self.initial_root)
        self.assertEqual(receipt['summary']['method'], 'rules')

    def test_cli_default_routes_by_method_without_reading_actual_private_roots(self):
        original = records.evaluate_record
        def check_default(content, gold_root, run_root, initial_root):
            self.assertIsNone(run_root)
            return original(content, gold_root, run_root, initial_root)
        arguments = ['evaluation', 'check-evaluation', '--input', str(self.write_control()),
                     '--gold-root', str(self.gold_root), '--initial-root', str(self.initial_root)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(records, 'RULE_ROOT', self.rule_root), patch.object(cli, 'evaluate_record', side_effect=check_default), \
             patch.object(sys, 'argv', arguments), redirect_stdout(stdout), redirect_stderr(stderr):
            result = cli.main()
        self.assertEqual((result, stderr.getvalue()), (0, ''))
        self.assertEqual(json.loads(stdout.getvalue())['method'], 'rules')

    def test_retest_profile_change_copies_initial_and_records_policy(self):
        initial = self.freeze(); initial_folder = self.initial_root/initial['evaluation_ref']; before = self.snapshot(initial_folder)
        self.profile['profile_version'] = 'synthetic-places-v2'; self.profile_path.write_bytes(encoded(self.profile))
        changed = copy.deepcopy(self.control); changed.update(extraction_eval_id=uid(602), phase='retest', initial_ref=initial['evaluation_ref'], policy=self.rule_policy())
        changed['policy']['profile_locked_at'] = '2020-01-01T05:45:00Z'
        changed['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        changed['documents'][0].update(self.make_rules(uid(710), started='2020-01-01T06:00:00Z'))
        receipt = self.freeze(changed, hour=8)
        self.assertTrue(receipt['summary']['policy_changed']); self.assertFalse(receipt['summary']['gold_changed'])
        self.assertFalse(receipt['summary']['generalization_claim']); self.assertIsNone(receipt['summary']['m02']['accuracy_percent'])
        self.assertEqual(self.snapshot(initial_folder), before)
        chained = copy.deepcopy(changed); chained.update(extraction_eval_id=uid(615), initial_ref=receipt['evaluation_ref'])
        with self.assertRaises(ExtractionError) as caught: self.freeze(chained, hour=9)
        self.assertEqual(caught.exception.code, 'EVALUATION_INITIAL_REQUIRED')
        self.rule_root.rename(self.work/'rules-gone'); self.gold_root.rename(self.work/'gold-gone')
        self.initial_root.rename(self.work/'evaluations-moved')
        root = self.work/'evaluations-moved'
        self.assertEqual(storage.verify_evaluation(receipt['evaluation_ref'], root), receipt)

    def test_gold_correction_reuses_exact_rule_source_and_preserves_initial(self):
        self.value['gold_version'] = 'synthetic-wrong-rule-gold'
        self.value['documents'][0]['output']['items'][0]['occurrences'][0]['date_end']['value'] = '2026-11-08'
        self.gold_receipt = self.make_gold()
        self.control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        review = dict(local_item_id='rule-item-1', field='date_end', unsupported=False, reason='합성 금표 오류: 원문 종료일은7일')
        for key in ('first_annotation', 'final_annotation'):
            self.control['documents'][0][key]['generation_reviews'] = [copy.deepcopy(review)]
        initial = self.freeze(); original = self.initial_root/initial['evaluation_ref']; before = self.snapshot(original)
        self.value['gold_version'] = 'synthetic-corrected-rule-gold'
        self.value['documents'][0]['output'] = copy.deepcopy(self.good_output)
        self.value['authorship'].update(authored_at='2020-01-01T05:45:00Z', reviewed_at='2020-01-01T05:55:00Z')
        evidence = self.good_output['items'][0]['occurrences'][0]['date_end']['evidence_ids']
        self.value['adjudications'] = [dict(document_version_id=self.source['document_version_id'], slot_id='item1',
            field='date_end', disagreement='합성 종료일 오류', resolution='원문7일로 수정', reason='합성 판독 대조',
            evidence_ids=evidence, adjudicated_by='synthetic-corrector', adjudicated_at='2020-01-01T05:50:00Z')]
        class CorrectedGoldClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 6, tzinfo=timezone.utc)
        self.gold_receipt = self.make_gold(CorrectedGoldClock)
        changed = copy.deepcopy(self.control)
        changed.update(extraction_eval_id=uid(613), phase='retest', initial_ref=initial['evaluation_ref'],
            gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        changed['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        receipt = self.freeze(changed, hour=8)
        self.assertTrue(receipt['summary']['gold_changed']); self.assertFalse(receipt['summary']['policy_changed'])
        self.assertEqual(receipt['summary']['initial_comparison']['final_auto_delta_percent'], 12.5)
        self.assertEqual(self.snapshot(original), before)

    def test_retest_rejects_cross_method_initial(self):
        initial = self.freeze()
        ai = copy.deepcopy(self.ai_control); ai.update(extraction_eval_id=uid(605), phase='retest', initial_ref=initial['evaluation_ref'])
        ai['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        with self.assertRaises(ExtractionError) as caught: self.freeze(ai, hour=8, run_root=self.run_root)
        self.assertEqual(caught.exception.code, 'EVALUATION_COHORT_MISMATCH')
        ai = copy.deepcopy(self.ai_control); ai['extraction_eval_id'] = uid(606)
        ai_initial = self.freeze(ai, run_root=self.run_root)
        rule = copy.deepcopy(self.control); rule.update(extraction_eval_id=uid(607), phase='retest', initial_ref=ai_initial['evaluation_ref'])
        rule['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        with self.assertRaises(ExtractionError) as caught: self.freeze(rule, hour=8)
        self.assertEqual(caught.exception.code, 'EVALUATION_COHORT_MISMATCH')

    def test_retest_unclear_or_holdout_profile_basis_keeps_observations_and_exposure(self):
        initial = self.freeze()
        selected = self.make_rules(uid(714), started='2020-01-01T06:00:00Z')
        for index, basis in enumerate(('unknown', 'holdout_feedback')):
            changed = copy.deepcopy(self.control)
            changed.update(extraction_eval_id=uid(620+index), phase='retest', initial_ref=initial['evaluation_ref'])
            changed['policy'].update(profile_locked_at='2020-01-01T05:45:00Z', profile_basis=basis)
            changed['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed',
                                    semantic_feedback_used=basis=='holdout_feedback')
            changed['documents'][0].update(selected)
            summary = self.freeze(changed, hour=8)['summary']
            self.assertIn('RULE_PROFILE_BASIS_UNCLEARED', summary['m02']['warnings'])
            self.assertEqual(summary['semantic_feedback_used'], basis=='holdout_feedback')
            self.assertFalse(summary['generalization_claim']); self.assertIsNone(summary['m02']['accuracy_percent'])
            self.assertEqual(summary['views']['final_auto']['accuracy_percent'], initial['summary']['views']['final_auto']['accuracy_percent'])

    def test_retest_rejects_early_new_run_and_same_uuid_different_receipt(self):
        initial = self.freeze(); changed = copy.deepcopy(self.control)
        changed.update(extraction_eval_id=uid(608), phase='retest', initial_ref=initial['evaluation_ref'])
        changed['review'].update(reviewed_at='2020-01-01T07:00:00Z', exposure_status='exposed')
        changed['documents'][0].update(self.make_rules(uid(711), started='2020-01-01T04:00:00Z'))
        with self.assertRaises(ExtractionError) as caught: self.freeze(changed, hour=8)
        self.assertEqual(caught.exception.code, 'EVALUATION_RETEST_RUN_TIME_INVALID')
        other = self.work/'other-rules'
        changed['documents'][0].update(self.make_rules(self.selected_rules['run_id'], root=other, preprocessing='different-nfc'))
        with self.assertRaises(ExtractionError) as caught: self.freeze(changed, hour=8, run_root=other)
        self.assertEqual(caught.exception.code, 'EVALUATION_RETEST_RUN_MISMATCH')

    def test_frozen_source_corruption_permissions_extra_and_symlink_are_rejected(self):
        receipt = self.freeze(); ref = receipt['evaluation_ref']; original = self.initial_root/ref
        for case in ('profile.json', 'output.json', 'metadata.json', 'receipt.json', 'mode', 'extra', 'symlink'):
            root = self.work/('corrupt-'+case); folder = root/ref; shutil.copytree(original, folder)
            source = folder/'runs'/self.selected_rules['run_id']
            if case in ('mode', 'symlink'): target = source/'profile.json'
            elif case == 'extra': target = source/'extra'
            else: target = source/case
            if case == 'mode': target.chmod(0o600)
            elif case == 'extra': source.chmod(0o700); target.write_bytes(b''); target.chmod(0o400); source.chmod(0o500)
            elif case == 'symlink':
                source.chmod(0o700); target.unlink(); target.symlink_to(original/'runs'/self.selected_rules['run_id']/'profile.json'); source.chmod(0o500)
            else: target.chmod(0o600); target.write_bytes(target.read_bytes()+b' '); target.chmod(0o400)
            with self.subTest(case=case), self.assertRaises(ExtractionError) as caught: storage.verify_evaluation(ref, root)
            self.assertEqual(caught.exception.kind, 'archive')

    def test_concurrent_same_and_conflicting_selections_keep_one_image(self):
        original = self.write_control(name='one.json')
        changed = copy.deepcopy(self.control); changed['review']['exposure_note'] = 'PRIVATE_CHANGED'
        other = self.write_control(changed, 'two.json')
        for paths, name, count in (([original]*4, 'same', 4), ([original, other], 'conflict', 1)):
            root = self.work/name
            def run(path):
                try: return storage.freeze_evaluation(path, root, self.gold_root, self.rule_root, self.initial_root)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=4) as workers: receipts = list(workers.map(run, paths))
            self.assertEqual(sum(isinstance(r, dict) for r in receipts), count)
            if count == 1: self.assertIn('EVALUATION_CONFLICT', receipts)
            self.assertEqual(len(list(root.iterdir())), 1)

    def test_actual_cli_freeze_verify_and_safe_input_archive_io_failures(self):
        args = ['--input', str(self.write_control()), '--gold-root', str(self.gold_root),
                '--run-root', str(self.rule_root), '--initial-root', str(self.initial_root)]
        check = self.command('check-evaluation', *args)
        self.assertEqual((check.returncode, check.stderr), (0, b''))
        frozen = self.command('freeze-evaluation', *args, '--root', str(self.initial_root))
        self.assertEqual((frozen.returncode, frozen.stderr), (0, b''))
        receipt = json.loads(frozen.stdout)
        verified = self.command('verify-evaluation', receipt['evaluation_ref'], '--root', str(self.initial_root))
        self.assertEqual((verified.returncode, verified.stdout, verified.stderr), (0, frozen.stdout, b''))
        self.assertNotIn(b'PRIVATE_', frozen.stdout); self.assertNotIn(str(self.work).encode(), frozen.stdout)
        bad = copy.deepcopy(self.control); bad['documents'][0]['receipt_sha256'] = '0'*64
        self.write_control(bad)
        rejected = self.command('check-evaluation', *args)
        self.assertEqual((rejected.returncode, rejected.stdout), (2, b''))
        missing = self.command('check-evaluation', '--input', str(self.work/'missing'), '--gold-root', str(self.gold_root))
        self.assertEqual((missing.returncode, missing.stdout, missing.stderr), (5, b'', b'DATASET_IO_FAILED\n'))
        target = self.initial_root/receipt['evaluation_ref']/'runs'/self.selected_rules['run_id']/'profile.json'; target.chmod(0o600)
        corrupt = self.command('verify-evaluation', receipt['evaluation_ref'], '--root', str(self.initial_root))
        self.assertEqual((corrupt.returncode, corrupt.stdout, corrupt.stderr), (3, b'', b'EVALUATION_INTEGRITY\n'))

    def test_failed_rule_source_still_freezes_as_successful_evaluation(self):
        self.replace_source_with_overflow()
        result = self.command('freeze-evaluation', '--input', str(self.write_control()), '--root', str(self.initial_root),
                              '--gold-root', str(self.gold_root), '--run-root', str(self.rule_root))
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        receipt = json.loads(result.stdout); view = receipt['summary']['views']['final_auto']
        self.assertEqual((view['correct_fields'], view['known_fields'], view['document_failures']), (0, 8, 1))
        self.assertIsNone(view['generation_rate_percent'])

    def test_empty_rule_result_keeps_missing_events_in_denominator(self):
        self.profile['type_keywords'] = dict(construction=[], event=[], traffic=[])
        self.profile_path.write_bytes(encoded(self.profile)); self.control['policy'] = self.rule_policy()
        self.control['documents'][0].update(self.make_rules(uid(712)))
        receipt = self.freeze(); view = receipt['summary']['views']['final_auto']
        self.assertEqual((view['correct_fields'], view['known_fields'], view['missing_events'], view['document_failures']), (0, 8, 1, 0))
        self.assertIsNone(view['generation_rate_percent'])
