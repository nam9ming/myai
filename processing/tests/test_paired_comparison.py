import copy
from datetime import datetime
import hashlib
import json
from unittest.mock import patch

from processing.evaluation import comparison, evaluation_storage
from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_human_evaluation import HumanEvaluationFixture
from processing.tests.test_rule_evaluation import RuleEvaluationFixture
from processing.tests.test_rules import encoded, profile
from processing.tests.test_scoring import fv

AT = '2020-01-01T06:00:00Z'


class PairedComparisonFixture(HumanEvaluationFixture):
    rule_policy = RuleEvaluationFixture.rule_policy
    make_rules = RuleEvaluationFixture.make_rules

    def setUp(self):
        super().setUp()
        self.rule_root = self.work / 'rule-runs'
        self.profile_path = self.work / 'PRIVATE_PROFILE.json'
        self.profile = profile(); self.profile_path.write_bytes(encoded(self.profile))
        rule = copy.deepcopy(self.ai_control)
        rule.update(method='rules', policy=self.rule_policy())
        rule['documents'][0].update(self.make_rules(uid(701)))
        self.controls = dict(rules=rule, ai_auto=copy.deepcopy(self.ai_control), human_reviewed=copy.deepcopy(self.control))
        self.evaluation_root = self.work / 'paired-evaluations'
        self.sequence = 0
        for index, value in enumerate(self.controls.values()): value['extraction_eval_id'] = uid(800 + index)
        self.freeze_methods()
        self.selection = dict(schema_version='extraction-comparison-v1', comparison_id=uid(850), evaluations=self.references)

    def freeze_methods(self, *, hour=5, methods=None):
        class EvalClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, tzinfo=tz)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, hour, 30, tzinfo=tz)
        if not hasattr(self, 'references'): self.references = {}
        roots = dict(rules=self.rule_root, ai_auto=self.run_root, human_reviewed=self.human_root)
        for method in self.controls if methods is None else methods:
            path = self.work / (method + '-selection.json'); path.write_bytes(_json(self.controls[method]))
            with patch('processing.evaluation.records.datetime', EvalClock), patch('processing.extraction.archive.datetime', FreezeClock):
                receipt = evaluation_storage.freeze_evaluation(path, self.evaluation_root, self.gold_root, roots[method], self.evaluation_root)
            ref = receipt['evaluation_ref']
            self.references[method] = dict(evaluation_ref=ref,
                receipt_sha256=hashlib.sha256((self.evaluation_root / ref / 'receipt.json').read_bytes()).hexdigest())

    def new_evaluations(self):
        self.sequence += 1
        for index, value in enumerate(self.controls.values()): value['extraction_eval_id'] = uid(1000 + self.sequence * 10 + index)

    def replace_ai(self, *, bad_type=False, failed=False, retry=False):
        good = copy.deepcopy(self.good_output)
        try:
            if bad_type: self.good_output['items'][0]['types']['value'] = ['traffic']
            selected = self.make_run(uid(510), failed=failed, retry=retry)
            human = self.make_human(uid(960), source=selected, output=good, failed=failed)
            self.controls['ai_auto']['documents'][0].update(selected)
            empty = dict(schema_version='score-links-v1', item_links=[], generation_reviews=[])
            self.controls['ai_auto']['documents'][0]['first_annotation'] = empty if failed or retry else self.annotations(self.good_output)
            self.controls['ai_auto']['documents'][0]['final_annotation'] = empty if failed else self.annotations(self.good_output)
            self.controls['human_reviewed']['documents'][0].update(human)
        finally: self.good_output = good
        self.new_evaluations(); self.freeze_methods()

    def compare(self, selection=None, *, at=AT, root=None):
        return comparison.compare_evaluations(_json(self.selection if selection is None else selection),
            self.evaluation_root if root is None else root, compared_at=at)

    def invalid(self, value, code=None, *, at=AT):
        with self.assertRaises(ExtractionError) as caught: self.compare(value, at=at)
        if code: self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_', str(caught.exception))


class PairedComparisonTest(PairedComparisonFixture):
    def test_real_archives_pair_five_improvements_without_losing_method_views(self):
        result = self.compare()['result']; summary = result['summary']
        pair = summary['pairs']['rules_to_ai']
        self.assertEqual((pair['known_fields'], pair['improved'], pair['worsened'], pair['unchanged_correct'], pair['unchanged_incorrect']), (8, 5, 0, 3, 0))
        self.assertEqual(pair['delta_percent'], 62.5)
        self.assertEqual(summary['pairs']['ai_to_human']['unchanged_correct'], 8)
        self.assertEqual(pair['fields']['time_start']['improved'], 1)
        self.assertEqual(summary['splits']['dev']['rules_to_ai']['improved'], 5)
        self.assertEqual(summary['splits']['holdout']['rules_to_ai']['known_fields'], 0)
        self.assertIsNone(summary['splits']['holdout']['rules_to_ai']['delta_percent'])
        self.assertEqual(set(summary['methods']['ai_auto']['views']), {'first_raw', 'final_auto'})
        self.assertEqual(summary['methods']['rules']['views']['final_auto']['correct_fields'], 3)
        self.assertEqual(set(summary['methods']['human_reviewed']['views']), {'human_reviewed'})
        self.assertEqual(len(result['field_results']), 8)

    def test_improvements_and_worsening_are_kept_separately_instead_of_only_net_score(self):
        self.replace_ai(bad_type=True)
        result = self.compare()['result']; pair = result['summary']['pairs']['rules_to_ai']
        self.assertEqual((pair['improved'], pair['worsened'], pair['unchanged_correct'], pair['delta_percent']), (5, 1, 2, 50.0))
        row = next(x for x in result['field_results'] if x['field'] == 'types')
        self.assertEqual(row['transitions'], dict(rules_to_ai='worsened', ai_to_human='improved', rules_to_human='unchanged_correct'))
        ai = result['summary']['methods']['ai_auto']['views']['final_auto']
        self.assertGreater(ai['generation_review_pending'], 0)
        self.assertIsNone(ai['generation_rate_percent'])

    def test_failed_ai_denominator_and_human_recovery_preserve_original_failure(self):
        self.replace_ai(failed=True)
        summary = self.compare()['result']['summary']
        ai = summary['methods']['ai_auto']['views']['final_auto']
        self.assertEqual((ai['known_fields'], ai['correct_fields'], ai['document_failures'], ai['missing_events']), (8, 0, 1, 1))
        self.assertEqual(summary['pairs']['ai_to_human']['improved'], 8)
        self.assertEqual(summary['pairs']['rules_to_ai']['worsened'], 3)
        self.assertIsNone(ai['generation_rate_percent'])

    def test_primary_comparison_uses_final_auto_but_keeps_first_failure(self):
        self.replace_ai(retry=True)
        summary = self.compare()['result']['summary']
        self.assertEqual(summary['pairs']['rules_to_ai']['improved'], 5)
        self.assertEqual(summary['methods']['ai_auto']['views']['first_raw']['correct_fields'], 0)
        self.assertEqual(summary['methods']['ai_auto']['views']['first_raw']['document_failures'], 1)
        self.assertEqual(summary['methods']['ai_auto']['views']['final_auto']['correct_fields'], 8)

    def test_unknown_gold_stays_unscored_and_zero_denominator_is_na(self):
        item = self.value['documents'][0]['output']['items'][0]
        for key in ('types', 'applicability', 'exceptions', 'route_names', 'stop_names', 'directions'):
            item[key] = fv(knowledge='ambiguous' if key == 'types' else 'not_stated')
        for key in ('date_start', 'date_end', 'time_start', 'time_end', 'end_day_offset', 'all_day'): item['occurrences'][0][key] = fv()
        for key in ('name', 'address', 'kind'): item['locations'][0][key] = fv()
        self.value['gold_version'] = 'synthetic-unknown-gold'; self.gold_receipt = self.make_gold()
        for control in self.controls.values(): control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        self.new_evaluations(); self.freeze_methods()
        result = self.compare()['result']; pair = result['summary']['pairs']['rules_to_ai']
        self.assertEqual((pair['known_fields'], pair['not_scored'], pair['improved'], pair['worsened']), (0, 8, 0, 0))
        self.assertIsNone(pair['delta_percent'])
        self.assertTrue(all(x['transitions']['ai_to_human'] == 'not_scored' for x in result['field_results']))
        self.assertGreater(result['summary']['methods']['ai_auto']['views']['final_auto']['generation_errors'], 0)

    def test_exact_receipts_and_all_three_method_names_are_required(self):
        for case in ('missing', 'extra', 'method', 'receipt', 'ref', 'id', 'schema', 'extra-top'):
            value = copy.deepcopy(self.selection)
            if case == 'missing': del value['evaluations']['rules']
            elif case == 'extra': value['evaluations']['manual'] = value['evaluations']['rules']
            elif case == 'method': value['evaluations']['rules'] = value['evaluations']['ai_auto']
            elif case == 'receipt': value['evaluations']['rules']['receipt_sha256'] = '0' * 64
            elif case == 'ref': value['evaluations']['rules']['evaluation_ref'] = '../outside'
            elif case == 'id': value['comparison_id'] = 'not-a-uuid'
            elif case == 'schema': value['schema_version'] = 'future'
            else: value['PRIVATE_EXTRA'] = True
            with self.subTest(case=case): self.invalid(value)

    def test_same_facts_under_different_gold_receipt_cannot_be_paired(self):
        self.value['gold_version'] = 'synthetic-same-facts-new-gold'; self.gold_receipt = self.make_gold()
        control = self.controls['human_reviewed']
        control.update(extraction_eval_id=uid(820), gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        self.freeze_methods(methods=['human_reviewed'])
        self.invalid(self.selection, 'COMPARISON_COHORT_MISMATCH')

    def test_human_review_of_another_valid_ai_parent_is_rejected(self):
        selected = self.make_run(uid(511))
        self.controls['human_reviewed']['documents'][0].update(self.make_human(uid(961), source=selected))
        self.controls['human_reviewed']['extraction_eval_id'] = uid(821)
        self.freeze_methods(methods=['human_reviewed'])
        self.invalid(self.selection, 'COMPARISON_PARENT_MISMATCH')

    def test_initial_and_retest_are_not_mixed_but_all_retests_keep_disclosures(self):
        old = copy.deepcopy(self.references)
        self.new_evaluations()
        for method, value in self.controls.items():
            value.update(phase='retest', initial_ref=old[method]['evaluation_ref'])
            value['review']['reviewed_at'] = '2020-01-01T06:00:00Z'
        self.controls['ai_auto']['review'].update(exposure_status='exposed', semantic_feedback_used=True)
        self.freeze_methods(hour=7, methods=['ai_auto'])
        self.invalid(self.selection, 'COMPARISON_COHORT_MISMATCH', at='2020-01-01T08:00:00Z')
        self.freeze_methods(hour=7, methods=['rules', 'human_reviewed'])
        result = self.compare(at='2020-01-01T08:00:00Z')['result']
        self.assertEqual(result['phase'], 'retest'); self.assertFalse(result['summary']['generalization_claim'])
        self.assertTrue(result['summary']['methods']['ai_auto']['semantic_feedback_used'])
        self.assertFalse(result['summary']['methods']['rules']['semantic_feedback_used'])
        self.assertEqual(result['summary']['human_review_time']['total_duration_ns'], 600_000_000_000)
        self.assertEqual(result['summary']['methods']['ai_auto']['initial_ref'], old['ai_auto']['evaluation_ref'])

    def test_source_must_be_frozen_before_comparison_and_tampering_is_archive_error(self):
        with self.assertRaises(ExtractionError) as caught: self.compare(at='2020-01-01T05:29:59.999999999Z')
        self.assertEqual(caught.exception.code, 'COMPARISON_TIME_INVALID')
        ref = self.references['ai_auto']['evaluation_ref']; path = self.evaluation_root / ref / 'result.json'
        path.chmod(0o600); path.write_bytes(path.read_bytes() + b' '); path.chmod(0o400)
        with self.assertRaises(ExtractionError) as caught: self.compare()
        self.assertEqual(caught.exception.kind, 'archive')

    def test_declared_time_privacy_determinism_and_read_only_source_images(self):
        before = {str(p.relative_to(self.evaluation_root)): p.read_bytes() for p in self.evaluation_root.rglob('*') if p.is_file()}
        first = self.compare(); value = copy.deepcopy(self.selection)
        value['evaluations'] = dict(reversed(list(value['evaluations'].items())))
        self.assertEqual(first, self.compare(value))
        summary = first['result']['summary']
        self.assertEqual(summary['human_review_time']['status'], 'declared_only')
        self.assertEqual(summary['human_review_time']['splits']['holdout']['total_duration_ns'], 0)
        self.assertFalse(summary['generalization_claim'])
        self.assertIsNone(summary['methods']['human_reviewed']['m02']['accuracy_percent'])
        self.assertNotIn('PRIVATE_', json.dumps(summary)); self.assertNotIn(str(self.work), json.dumps(summary))
        self.assertNotIn('gold_values', json.dumps(summary)); self.assertNotIn('reviewed_by', json.dumps(summary))
        self.assertEqual({str(p.relative_to(self.evaluation_root)): p.read_bytes() for p in self.evaluation_root.rglob('*') if p.is_file()}, before)
        self.assertTrue(any('source/' in name for name in first['sources']))

    def test_two_versions_pair_by_gold_identity_despite_reversed_document_selection(self):
        from processing.evaluation.storage import freeze_dataset
        from processing.tests.test_evaluation_records import DatasetClock
        self.source['document_version_id'] = uid(102)
        self.input = self.work / 'PRIVATE_SECOND_INPUT.json'; self.input.write_bytes(_json(self.source))
        self.manifest['dataset_version'] = 'synthetic-paired-two-versions'
        self.manifest['documents'][0]['versions'].append(dict(document_version_id=uid(102),
            input_sha256=hashlib.sha256(self.input.read_bytes()).hexdigest()))
        path = self.work / 'two-version-manifest.json'; path.write_bytes(_json(self.manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock): dataset = freeze_dataset(path, self.dataset_root)
        answer = copy.deepcopy(self.value['documents'][0])
        answer.update(document_version_id=uid(102), input_path=str(self.input))
        answer['output']['document_version_id'] = uid(102)
        self.value.update(gold_version='synthetic-paired-two-gold', dataset_ref=dataset['dataset_ref'],
            manifest_sha256=dataset['manifest_sha256'])
        self.value['documents'].append(answer); self.gold_receipt = self.make_gold()
        self.good_output = copy.deepcopy(answer['output'])
        ai = self.make_run(uid(512)); human = self.make_human(uid(962), source=ai)
        selected = dict(rules=self.make_rules(uid(702)), ai_auto=ai, human_reviewed=human)
        for method, control in self.controls.items():
            control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
            doc = dict(document_version_id=uid(102), **selected[method])
            if method == 'human_reviewed': doc['annotation'] = self.annotations(self.good_output)
            elif method == 'ai_auto':
                doc.update(first_annotation=self.annotations(self.good_output), final_annotation=self.annotations(self.good_output))
            control['documents'].append(doc)
        self.new_evaluations(); self.freeze_methods()
        first = self.compare()['result']
        self.controls['ai_auto']['documents'].reverse()
        self.controls['ai_auto']['extraction_eval_id'] = uid(822)
        self.freeze_methods(methods=['ai_auto'])
        second = self.compare()['result']
        self.assertEqual(first['field_results'], second['field_results'])
        self.assertEqual(first['summary'], second['summary'])
        pair = second['summary']['pairs']['rules_to_ai']
        self.assertEqual((pair['known_fields'], pair['improved'], pair['unchanged_correct']), (16, 10, 6))
        self.assertEqual(second['summary']['cohort_counts']['documents'], 1)
        self.assertEqual(second['summary']['human_review_time']['total_duration_ns'], 1_200_000_000_000)

    def test_method_specific_exposure_retest_and_basis_warnings_are_preserved(self):
        old = copy.deepcopy(self.references); self.new_evaluations()
        for method, value in self.controls.items():
            value.update(phase='retest', initial_ref=old[method]['evaluation_ref'])
            value['review']['reviewed_at'] = '2020-01-01T07:00:00Z'
        self.controls['ai_auto']['review'].update(exposure_status='exposed', semantic_feedback_used=True)
        self.controls['rules']['policy']['profile_basis'] = 'unknown'
        self.controls['human_reviewed']['documents'][0].update(self.make_human(uid(964), basis='unknown',
            started='2020-01-01T06:00:00Z', finished='2020-01-01T06:10:00Z', frozen='2020-01-01T06:20:00Z'))
        self.freeze_methods(hour=8)
        summary = self.compare(at='2020-01-01T09:00:00Z')['result']['summary']
        warnings = {method: summary['methods'][method]['m02']['warnings'] for method in self.controls}
        self.assertIn('EXPOSURE_NOT_CLEARED', warnings['ai_auto'])
        self.assertIn('RETEST_NOT_INITIAL_GENERALIZATION', warnings['ai_auto'])
        self.assertIn('RULE_PROFILE_BASIS_UNCLEARED', warnings['rules'])
        self.assertIn('HUMAN_REVIEW_BASIS_UNCLEARED', warnings['human_reviewed'])
        for method, selected in self.references.items():
            original = json.loads((self.evaluation_root / selected['evaluation_ref'] / 'receipt.json').read_bytes())['summary']
            self.assertEqual(warnings[method], original['m02']['warnings'])
            self.assertEqual(summary['holdout_warnings'], original['holdout_warnings'])
