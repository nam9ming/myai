import copy
from datetime import datetime, timedelta
import hashlib
import json
from unittest.mock import patch
import unittest

from processing.evaluation import comparison_storage, matching
from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import REPO, uid
from processing.tests.test_paired_comparison import PairedComparisonFixture
from processing.tests.test_scoring import fv
from processing.tests.test_evaluation_records import DatasetClock
from processing.evaluation.storage import freeze_dataset

MATCHING_AT = '2026-11-03T03:00:00Z'
VIEWS = ('gold_engine', 'rules_first_raw', 'rules_final_auto', 'ai_first_raw', 'ai_final_auto', 'human_reviewed')


class MatchingEvaluationFixture(PairedComparisonFixture):
    def setUp(self):
        super().setUp()
        self.comparison_root = self.work / 'comparisons'
        self.matching_root = self.work / 'matching'
        self.freeze_selected_comparison()
        sample = json.loads((REPO / 'processing/examples/match-input.json').read_bytes())
        case = {key: copy.deepcopy(sample[key]) for key in ('context', 'point', 'query', 'source_versions')}
        case['case_id'] = uid(1200)
        case['query']['snapshot_id'] = None
        source = case['source_versions'][0]
        source.update(document_id=self.manifest['documents'][0]['document_id'],
                      document_version_id=self.source['document_version_id'],
                      official_url=self.manifest['documents'][0]['official_url'],
                      title=self.source['title'], published_date=self.source['published_date'])
        event = self.value['documents'][0]['anchors'][0]['event_id']
        case['area_memberships'] = [dict(entry_id=uid(1202), status='verified')]
        # 독립 수동 기대: 정확한 일정·거리이지만 원문에 lifecycle 확정이 없다.
        case['expected'] = [dict(event_id=event, classification='needs_check',
                                 reason_codes=['RELATION_UNCERTAIN'], note='합성 원문에 진행 상태 확정 없음')]
        self.matching_selection = dict(schema_version='matching-evaluation-v1', matching_eval_id=uid(1201),
            phase='initial', case_version='synthetic-matching-cases-v1', comparison=self.comparison_reference,
            expectations_review=dict(author='PRIVATE_TARGET_AUTHOR', reviewer='PRIVATE_TARGET_REVIEWER',
                authored_at='2026-11-03T02:00:00Z', reviewed_at='2026-11-03T02:30:00Z', basis='source_only',
                cross_reviewed=True, no_unresolved_disagreements=True),
            context_review=dict(reviewer='PRIVATE_CONTEXT_REVIEWER', reviewed_at='2026-11-03T02:30:00Z',
                                note='합성 조건·구역·장소 사전 검토 선언'),
            dictionary=dict(dictionary_version='synthetic-dictionary-v1', entries=[dict(entry_id=uid(1202),
                name='가상 시장 앞 연결도로 일부 구간', name_aliases=[], address=None, address_aliases=[], kind='segment',
                geometry=dict(type='LineString', coordinates=[[127.27, 37.01], [127.271, 37.01]]), coverage='complete',
                source='합성 검토 위치', checked_by='PRIVATE_DICTIONARY_REVIEWER', checked_at='2026-11-03T01:00:00Z')]),
            cases=[case], initial=None)

    def freeze_selected_comparison(self):
        class CompareClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 6, tzinfo=tz)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 6, 30, tzinfo=tz)
        path = self.work / 'comparison-selection.json'; path.write_bytes(_json(self.selection))
        with patch('processing.evaluation.comparison.datetime', CompareClock), patch('processing.extraction.archive.datetime', FreezeClock):
            receipt = comparison_storage.freeze_comparison(path, self.comparison_root, self.evaluation_root)
        ref = receipt['comparison_ref']
        self.comparison_reference = dict(comparison_ref=ref,
            receipt_sha256=hashlib.sha256((self.comparison_root / ref / 'receipt.json').read_bytes()).hexdigest())
        if hasattr(self, 'matching_selection'): self.matching_selection['comparison'] = self.comparison_reference

    def replace_matching_ai(self, output, annotation):
        original = copy.deepcopy(self.good_output)
        try:
            self.good_output = copy.deepcopy(output)
            selected = self.make_run(uid(1510 + self.sequence))
            reviewed = self.make_human(uid(1610 + self.sequence), source=selected, output=original)
        finally: self.good_output = original
        self.controls['ai_auto']['documents'][0].update(selected, first_annotation=copy.deepcopy(annotation), final_annotation=copy.deepcopy(annotation))
        self.controls['human_reviewed']['documents'][0].update(reviewed, annotation=self.annotations(original))
        self.new_evaluations(); self.freeze_methods(); self.refresh_comparison()

    def add_matching_version(self, *, failed=False, lifecycle=None, new_event=False):
        original_input, original_source, original_output = self.input, self.source, self.good_output
        version = uid(1901)
        source = copy.deepcopy(self.source); source['document_version_id'] = version
        path = self.work / 'PRIVATE_SECOND_INPUT.json'; path.write_bytes(_json(source))
        document_id = uid(1902) if new_event else self.manifest['documents'][0]['document_id']
        event_id = uid(1903) if new_event else self.value['documents'][0]['anchors'][0]['event_id']
        manifest_version = dict(document_version_id=version, input_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.manifest['dataset_version'] = 'synthetic-two-version-matching'
        if new_event:
            doc = copy.deepcopy(self.manifest['documents'][0])
            doc.update(document_id=document_id, official_url='https://example.test/second-synthetic', versions=[manifest_version])
            self.manifest['documents'].append(doc)
            self.manifest['events'].append(dict(event_id=event_id, document_ids=[document_id], split_group_id=uid(1904), suspected_duplicate_ids=[]))
            assigned = copy.deepcopy(self.manifest['split_assignments'][0])
            assigned.update(document_id=document_id, split_group_id=uid(1904), split='holdout')
            self.manifest['split_assignments'].append(assigned)
        else: self.manifest['documents'][0]['versions'].append(manifest_version)
        manifest_path = self.work / 'two-version-manifest.json'; manifest_path.write_bytes(_json(self.manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock):
            dataset = freeze_dataset(manifest_path, self.dataset_root)
        answer = copy.deepcopy(self.value['documents'][0]); answer.update(document_version_id=version, input_path=str(path))
        answer['output']['document_version_id'] = version; answer['anchors'][0]['event_id'] = event_id
        self.value.update(gold_version='synthetic-two-version-gold', dataset_ref=dataset['dataset_ref'], manifest_sha256=dataset['manifest_sha256'])
        self.value['documents'].append(answer); self.gold_receipt = self.make_gold()
        try:
            self.input, self.source = path, source
            self.good_output = copy.deepcopy(answer['output'])
            if lifecycle: self.good_output['items'][0]['lifecycle'] = fv(lifecycle)
            ai = self.make_run(uid(1905), failed=failed)
            human = self.make_human(uid(1906), source=ai, failed=failed)
            rules = self.make_rules(uid(1907))
            annotation = dict(schema_version='score-links-v1', item_links=[], generation_reviews=[]) if failed else self.annotations(self.good_output)
            self.controls['ai_auto']['documents'].append(dict(document_version_id=version, **ai, first_annotation=annotation, final_annotation=copy.deepcopy(annotation)))
            self.controls['human_reviewed']['documents'].append(dict(document_version_id=version, **human, annotation=self.annotations(self.good_output)))
            self.controls['rules']['documents'].append(dict(document_version_id=version, **rules))
        finally: self.input, self.source, self.good_output = original_input, original_source, original_output
        for value in self.controls.values(): value.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        self.new_evaluations(); self.freeze_methods(); self.refresh_comparison()
        case = self.matching_selection['cases'][0]
        source_version = copy.deepcopy(case['source_versions'][0]); source_version['document_version_id'] = version
        if new_event:
            source_version.update(document_id=document_id, official_url='https://example.test/second-synthetic')
            case['expected'].append(dict(event_id=event_id, classification='needs_check', reason_codes=['RELATION_UNCERTAIN'], note='두 번째 합성 사건 상태 미상'))
        case['source_versions'].append(source_version)

    def freeze_matching_initial(self):
        from processing.evaluation.matching_storage import freeze_matching
        instant = datetime.fromisoformat(MATCHING_AT)
        class EvalClock(datetime):
            @classmethod
            def now(cls, tz=None): return instant
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return instant + timedelta(hours=1)
        with patch('processing.evaluation.matching.datetime', EvalClock), patch('processing.extraction.archive.datetime', FreezeClock):
            receipt = freeze_matching(self.write_matching(), self.matching_root, self.comparison_root, self.matching_root)
        ref = receipt['matching_ref']
        return dict(matching_ref=ref, receipt_sha256=hashlib.sha256((self.matching_root / ref / 'receipt.json').read_bytes()).hexdigest())

    def refresh_comparison(self):
        self.selection['comparison_id'] = uid(1300 + self.sequence)
        self.freeze_selected_comparison()

    def write_matching(self, selection=None):
        path = self.work / 'matching-selection.json'
        path.write_bytes(_json(self.matching_selection if selection is None else selection))
        return path

    def matching(self, selection=None, *, at=MATCHING_AT, root=None):
        return matching.evaluate_matching(_json(self.matching_selection if selection is None else selection),
            self.comparison_root if root is None else root, self.matching_root, evaluated_at=at)


class MatchingEvaluationTest(MatchingEvaluationFixture):
    def test_real_frozen_sources_keep_six_views_and_manual_target(self):
        packet = self.matching(); result = packet['result']; case = result['cases'][0]
        self.assertEqual(set(result), set('schema_version matching_eval_id matching_ref matcher_version selection_sha256 evaluated_at phase case_version comparison gold_ref gold_sha256 manifest_sha256 initial_comparison cases summary'.split()))
        self.assertEqual(set(case['observations']), set(VIEWS))
        self.assertTrue(all(len(rows) == 1 for rows in case['observations'].values()))
        gold = case['event_results']['gold_engine'][0]
        self.assertEqual((gold['state'], gold['classification'], gold['reason_codes']), ('classified', 'needs_check', ['RELATION_UNCERTAIN']))
        s = result['summary']['views']['gold_engine']
        self.assertEqual((s['events'], s['anchors'], s['complete_classification']['correct'], s['classification_and_reasons']['correct']), (1, 1, 1, 1))
        self.assertIsNone(s['retrieval_presence']['precision_percent'])
        self.assertIsNone(s['retrieval_presence']['recall_percent'])
        self.assertTrue(any(name.endswith('attempt-1.response') for name in packet['sources']))
        self.assertTrue(all(name.startswith('comparisons/') for name in packet['sources']))
        self.assertNotIn('PRIVATE_', json.dumps(result['summary']))
        self.assertNotIn(str(self.work), json.dumps(result['summary']))
        self.assertFalse(result['summary']['generalization_claim'])

    def test_failed_first_raw_and_empty_output_keep_anchor_denominator(self):
        self.replace_ai(retry=True); self.refresh_comparison()
        result = self.matching()['result']; case = result['cases'][0]
        self.assertEqual(case['observations']['ai_first_raw'][0]['state'], 'failed')
        self.assertEqual(result['summary']['views']['ai_first_raw']['anchors'], 1)
        self.assertEqual(result['summary']['views']['ai_first_raw']['complete_classification']['correct'], 0)
        self.assertEqual(case['event_results']['ai_final_auto'][0]['classification'], 'needs_check')

    def test_independent_expected_class_is_not_overwritten_by_gold_engine(self):
        value = copy.deepcopy(self.matching_selection)
        value['cases'][0]['expected'][0].update(classification='candidate', reason_codes=[])
        result = self.matching(value)['result']; s = result['summary']['views']['gold_engine']
        self.assertEqual(s['complete_classification']['correct'], 0)
        self.assertEqual(s['retrieval_presence']['fn'], 1)
        self.assertEqual(s['investigation_required'], 1)

    def test_strict_header_expectations_and_review_clocks(self):
        mutations = [lambda v: v.update(extra=True), lambda v: v.update(phase='future'),
            lambda v: v['cases'][0]['expected'].clear(),
            lambda v: v['cases'][0]['expected'][0].update(reason_codes=['WRONG']),
            lambda v: v['expectations_review'].update(reviewer=' private_target_author '),
            lambda v: v['expectations_review'].update(reviewed_at='2026-11-03T04:00:00Z'),
            lambda v: v['comparison'].update(receipt_sha256='0' * 64)]
        for mutate in mutations:
            value = copy.deepcopy(self.matching_selection); mutate(value)
            with self.subTest(value=value), self.assertRaises(ExtractionError): self.matching(value)

    def test_document_unavailable_retains_failed_source_flag(self):
        self.replace_ai(failed=True); self.refresh_comparison()
        value = copy.deepcopy(self.matching_selection); case = value['cases'][0]
        case['context'].update(mode='replay', case_id=case['case_id'], reference_instant='2026-11-02T00:00:00Z',
            knowledge_cutoff='2026-11-02T00:00:00Z', history_fidelity='verified_snapshot', anchor_date='2026-11-02')
        case['query'].update(mode='replay', case_id=case['case_id'])
        case['source_versions'][0].update(checks=[], last_verified_at=None, latest_check_attempt_at=None, check_result='unchecked')
        row = self.matching(value)['result']['cases'][0]['observations']['ai_final_auto'][0]
        self.assertEqual((row['state'], row['document_failed']), ('unavailable', True))


    def test_unavailable_valid_output_preserves_projection_and_source_hashes(self):
        value = copy.deepcopy(self.matching_selection); case = value['cases'][0]
        case['context'].update(mode='replay', case_id=case['case_id'], reference_instant='2026-11-02T00:00:00Z',
            knowledge_cutoff='2026-11-02T00:00:00Z', history_fidelity='verified_snapshot', anchor_date='2026-11-02')
        case['query'].update(mode='replay', case_id=case['case_id'])
        case['source_versions'][0].update(checks=[], last_verified_at=None, latest_check_attempt_at=None, check_result='unchecked')
        row = self.matching(value)['result']['cases'][0]['observations']['ai_final_auto'][0]
        self.assertEqual(row['state'], 'unavailable')
        self.assertEqual(row['projection_body_sha256'], 'b158c3bd92385f4c191977904e2d48bc15606915e780fad621ed1fd2e25337fc')
        self.assertEqual(row['source_text_sha256'], case['source_versions'][0]['text_sha256'])
        self.assertFalse(row['document_failed'])

    def test_empty_gold_keeps_document_statuses_and_outputs_without_invented_events(self):
        self.value['gold_version'] = 'synthetic-empty-matching-gold'
        self.value['documents'][0]['output'].update(items=[], warnings=['NO_EVENT_FOUND'])
        self.value['documents'][0]['anchors'] = []
        self.gold_receipt = self.make_gold()
        for control in self.controls.values():
            control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
            document = control['documents'][0]
            for key in ('annotation',) if control['method'] == 'human_reviewed' else ('first_annotation', 'final_annotation'):
                for link in document[key]['item_links']: link.update(kind='additional', slot_id=None, occurrence_links=[])
        self.new_evaluations(); self.freeze_methods(); self.refresh_comparison()
        self.matching_selection['cases'][0]['expected'] = []
        case = self.matching()['result']['cases'][0]; gold = case['summary']['views']['gold_engine']
        self.assertEqual((gold['events'], gold['anchors'], gold['document_versions'], gold['empty_documents']), (0, 0, 1, 1))
        self.assertEqual(case['observations']['gold_engine'], [])
        self.assertEqual(case['event_results']['ai_final_auto'], [])
        self.assertEqual(case['observations']['ai_final_auto'][0]['kind'], 'additional')
        self.assertIsNone(gold['complete_classification']['accuracy_percent'])

    def test_cancelled_target_classified_excluded_counts_cancellation_omission(self):
        value = copy.deepcopy(self.matching_selection)
        value['cases'][0]['expected'][0].update(classification='cancelled', reason_codes=['CANCELLED'])
        value['cases'][0]['query']['types'] = ['traffic']
        case = self.matching(value)['result']['cases'][0]
        self.assertEqual(case['event_results']['ai_final_auto'][0]['classification'], 'excluded')
        metric = case['summary']['views']['ai_final_auto']
        self.assertEqual(metric['cancelled'], dict(expected=1, missing=1, candidate_exposure=0))
        self.assertEqual(metric['states']['missing'], 0)

    def test_needs_check_target_classified_candidate_counts_both_omission_and_overconfirmation(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['lifecycle'] = fv('active')
        self.replace_matching_ai(output, self.annotations(output))
        case = self.matching()['result']['cases'][0]
        metric = case['summary']['views']['ai_final_auto']
        self.assertEqual(case['event_results']['ai_final_auto'][0]['classification'], 'candidate')
        self.assertEqual(metric['needs_check'], dict(expected=1, correct=0, candidate_overconfirmation=1, missing=1))
        self.assertEqual(metric['states']['missing'], 0)

    def test_actual_duplicate_conflict_keeps_retrieval_presence_and_all_observations(self):
        output = copy.deepcopy(self.good_output)
        output['items'][0]['lifecycle'] = fv('active')
        duplicate = copy.deepcopy(output['items'][0]); duplicate['local_item_id'] = 'duplicate1'
        duplicate['lifecycle'] = fv('cancelled')
        duplicate['locations'][0]['local_location_id'] = 'ldup'
        duplicate['occurrences'][0].update(local_occurrence_id='odup', location_refs=['ldup'])
        output['items'].append(duplicate)
        annotation = self.annotations(self.good_output)
        annotation['item_links'].append(dict(slot_id='item1', local_item_id='duplicate1', kind='duplicate', occurrence_links=[]))
        self.replace_matching_ai(output, annotation)
        value = copy.deepcopy(self.matching_selection)
        value['cases'][0]['expected'][0].update(classification='candidate', reason_codes=[])
        case = self.matching(value)['result']['cases'][0]; summary = case['summary']['views']['ai_final_auto']
        self.assertEqual([r['kind'] for r in case['observations']['ai_final_auto']], ['match', 'duplicate'])
        self.assertEqual(case['event_results']['ai_final_auto'][0]['state'], 'conflict')
        self.assertEqual((summary['retrieval_presence']['tp'], summary['anchors'], summary['events'], summary['duplicate_outputs']), (1, 1, 1, 1))
        self.assertEqual(summary['complete_classification']['correct'], 0)

    def test_actual_duplicate_only_keeps_missing_primary_and_orphans_are_individual_fp(self):
        output = copy.deepcopy(self.good_output); item = output['items'][0]
        item.update(local_item_id='duplicate1', lifecycle=fv('active'))
        orphan = copy.deepcopy(item); orphan['local_item_id'] = 'orphan1'
        orphan['locations'][0]['local_location_id'] = 'lorphan1'
        orphan['occurrences'][0].update(local_occurrence_id='oorphan1', location_refs=['lorphan1'])
        output['items'].append(orphan)
        orphan2 = copy.deepcopy(item); orphan2['local_item_id'] = 'orphan2'
        orphan2['locations'][0]['local_location_id'] = 'lorphan2'
        orphan2['occurrences'][0].update(local_occurrence_id='oorphan2', location_refs=['lorphan2'])
        output['items'].append(orphan2)
        annotation = dict(schema_version='score-links-v1', generation_reviews=[], item_links=[
            dict(slot_id='item1', local_item_id='duplicate1', kind='duplicate', occurrence_links=[]),
            dict(slot_id=None, local_item_id='orphan1', kind='additional', occurrence_links=[]),
            dict(slot_id=None, local_item_id='orphan2', kind='additional', occurrence_links=[])])
        self.replace_matching_ai(output, annotation)
        value = copy.deepcopy(self.matching_selection)
        value['cases'][0]['expected'][0].update(classification='candidate', reason_codes=[])
        case = self.matching(value)['result']['cases'][0]
        self.assertEqual([r['kind'] for r in case['observations']['ai_final_auto']], ['missing', 'duplicate', 'additional', 'additional'])
        self.assertEqual(case['event_results']['ai_final_auto'][0]['state'], 'missing')
        self.assertEqual((case['summary']['views']['ai_final_auto']['retrieval_presence']['tp'],
                          case['summary']['views']['ai_final_auto']['retrieval_presence']['fp'],
                          case['summary']['views']['ai_final_auto']['additional_outputs']), (1, 2, 2))
        self.assertTrue(all(r['classification'] == 'candidate' for r in case['observations']['ai_final_auto'] if r['kind'] == 'additional'))

    def test_same_raw_classification_does_not_depend_on_match_duplicate_or_additional_annotation(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['lifecycle'] = fv('active')
        self.replace_matching_ai(output, self.annotations(output))
        states = []
        for kind in ('match', 'duplicate', 'additional'):
            if kind != 'match':
                annotation = dict(schema_version='score-links-v1', generation_reviews=[], item_links=[dict(
                    slot_id=None if kind == 'additional' else 'item1', local_item_id='item1', kind=kind, occurrence_links=[])])
                self.controls['ai_auto']['documents'][0].update(first_annotation=annotation, final_annotation=copy.deepcopy(annotation))
                self.new_evaluations(); self.freeze_methods(); self.refresh_comparison()
            rows = self.matching()['result']['cases'][0]['observations']['ai_final_auto']
            states.append(next((r['state'], r['classification'], r['reason_codes']) for r in rows if r['local_item_id'] == 'item1'))
        self.assertEqual(states, [('classified', 'candidate', [])] * 3)

    def test_actual_empty_output_is_missing_without_document_failure(self):
        output = copy.deepcopy(self.good_output); output.update(items=[], warnings=['NO_EVENT_FOUND'])
        annotation = dict(schema_version='score-links-v1', item_links=[], generation_reviews=[])
        self.replace_matching_ai(output, annotation)
        case = self.matching()['result']['cases'][0]
        row = case['observations']['ai_final_auto'][0]
        self.assertEqual((row['kind'], row['state'], row['document_failed'], row['empty_output']), ('missing', 'missing', False, True))
        s = case['summary']['views']['ai_final_auto']
        self.assertEqual((s['anchors'], s['events'], s['document_failures'], s['empty_documents']), (1, 1, 0, 1))

    def test_each_method_uses_own_types_and_keeps_not_computable_target(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['types'] = fv(knowledge='ambiguous')
        self.replace_matching_ai(output, self.annotations(output))
        value = copy.deepcopy(self.matching_selection); value['cases'][0]['query']['types'] = ['construction']
        case = self.matching(value)['result']['cases'][0]
        self.assertEqual((case['observations']['ai_final_auto'][0]['state'], case['observations']['ai_final_auto'][0]['disposition']), ('not_computable', 'type_unknown'))
        self.assertEqual(case['observations']['gold_engine'][0]['classification'], 'needs_check')
        self.assertEqual(case['summary']['views']['ai_final_auto']['anchors'], 1)

    def test_replay_preserves_current_source_state_and_reconstructed_warning(self):
        value = copy.deepcopy(self.matching_selection); case = value['cases'][0]
        case['context'].update(mode='replay', case_id=case['case_id'], reference_instant='2026-11-02T03:00:00Z',
            knowledge_cutoff='2026-11-02T03:00:00Z', history_fidelity='reconstructed', anchor_date='2026-11-02')
        case['query'].update(mode='replay', case_id=case['case_id'])
        case['source_versions'][0].update(current_check_result='unreachable', current_latest_check_attempt_at='2026-11-03T01:00:00Z')
        result = self.matching(value)['result']['cases'][0]
        self.assertIn('RECONSTRUCTED_HISTORY', result['summary']['context_warnings'])
        self.assertEqual(result['summary']['documents']['gold_engine'][0]['current_check_result'], 'unreachable')
        self.assertEqual(result['summary']['context']['history_fidelity'], 'reconstructed')

    def test_case_cross_product_budget_rejects_during_row_generation(self):
        value = copy.deepcopy(self.matching_selection)
        for i in range(3):
            case = copy.deepcopy(value['cases'][0]); case['case_id'] = uid(1800 + i); value['cases'].append(case)
        with patch.object(matching, 'MAX_BYTES', 1800), patch.object(matching.projection, 'classify_output', wraps=matching.projection.classify_output) as classified:
            with self.assertRaises(ExtractionError) as caught: self.matching(value)
        self.assertEqual(caught.exception.code, 'MATCHING_RESULT_TOO_LARGE')
        self.assertLess(classified.call_count, 6)

    def test_actual_candidate_and_failed_version_stays_partial_with_fixed_two_anchors(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['lifecycle'] = fv('active')
        self.replace_matching_ai(output, self.annotations(output)); self.add_matching_version(failed=True)
        value = copy.deepcopy(self.matching_selection); value['cases'][0]['expected'][0].update(classification='candidate', reason_codes=[])
        case = self.matching(value)['result']['cases'][0]; s = case['summary']['views']['ai_final_auto']
        self.assertEqual((s['anchors'], s['events'], s['retrieval_presence']['tp'], s['complete_classification']['correct']), (2, 1, 1, 0))
        self.assertEqual(case['event_results']['ai_final_auto'][0]['state'], 'partial')
        self.assertEqual([r['state'] for r in case['observations']['ai_final_auto']], ['classified', 'failed'])

    def test_actual_old_cancelled_new_candidate_keeps_conflict_without_latest_selection(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['lifecycle'] = fv('cancelled')
        self.replace_matching_ai(output, self.annotations(output)); self.add_matching_version(lifecycle='active')
        case = self.matching()['result']['cases'][0]
        self.assertEqual(case['event_results']['ai_final_auto'][0]['state'], 'conflict')
        self.assertEqual(case['summary']['views']['ai_final_auto']['anchors'], 2)
        self.assertEqual(case['summary']['views']['ai_final_auto']['retrieval_presence']['fp'], 1)

    def test_dev_and_holdout_are_aggregated_from_same_full_cohort(self):
        self.add_matching_version(new_event=True)
        summary = self.matching()['result']['summary']
        self.assertEqual((summary['views']['gold_engine']['events'], summary['views']['gold_engine']['anchors']), (2, 2))
        self.assertEqual((summary['splits']['dev']['gold_engine']['events'], summary['splits']['holdout']['gold_engine']['events']), (1, 1))
        self.assertEqual(summary['splits']['holdout']['gold_engine']['complete_classification']['correct'], 1)
        self.assertFalse(summary['generalization_claim'])

    def test_source_artifact_changes_after_verification_are_rejected_before_packet(self):
        original = matching._collect
        for artifact in ('attempt-1.response', 'identity.json', 'receipt.json'):
            changed = {}
            def mutate(directory, names, prefix):
                if prefix.startswith('comparisons/'):
                    source = next(directory.rglob(artifact)) if artifact.startswith('attempt') else directory / artifact
                    changed.update(path=source, raw=source.read_bytes())
                    source.chmod(0o600); source.write_bytes(changed['raw'] + b' '); source.chmod(0o400)
                return original(directory, names, prefix)
            try:
                with self.subTest(artifact=artifact):
                    with patch.object(matching, '_collect', side_effect=mutate), self.assertRaises(ExtractionError) as caught:
                        self.matching()
                    self.assertEqual(caught.exception.code, 'MATCHING_SOURCE_CHANGED')
            finally:
                source = changed['path']; source.chmod(0o600); source.write_bytes(changed['raw']); source.chmod(0o400)

    def test_retest_initial_full_image_and_changed_case_delta_rules(self):
        selected = self.freeze_matching_initial()
        value = copy.deepcopy(self.matching_selection); value.update(phase='retest', matching_eval_id=uid(1950), initial=selected)
        packet = self.matching(value, at='2026-11-03T05:00:00Z')
        initial = packet['result']['initial_comparison']
        self.assertTrue(initial['cases'][0]['paired'])
        self.assertEqual(initial['cases'][0]['paired_deltas']['gold_engine']['delta_percent'], 0.0)
        self.assertTrue(any(name.startswith('initial/' + selected['matching_ref'] + '/comparisons/') for name in packet['sources']))
        changed = copy.deepcopy(value); changed['cases'][0]['point']['longitude'] = 127.28
        with self.assertRaises(ExtractionError) as caught: self.matching(changed, at='2026-11-03T05:00:00Z')
        self.assertEqual(caught.exception.code, 'MATCHING_CASE_VERSION_CONFLICT')
        changed['case_version'] = 'synthetic-cases-v2'
        initial = self.matching(changed, at='2026-11-03T05:00:00Z')['result']['initial_comparison']
        self.assertFalse(initial['cases'][0]['paired']); self.assertIsNone(initial['cases'][0]['paired_deltas'])
        self.assertEqual(set(initial['cases'][0]['initial_metrics']), set(VIEWS))
        self.assertEqual(set(initial['cases'][0]['current_metrics']), set(VIEWS))

    def test_dictionary_only_retest_reports_changed_conditions(self):
        selected = self.freeze_matching_initial()
        value = copy.deepcopy(self.matching_selection)
        value.update(phase='retest', matching_eval_id=uid(2990), initial=selected,
                     case_version='synthetic-dictionary-corrected-v2')
        value['dictionary']['entries'][0]['geometry']['coordinates'] = [[128.27, 37.01], [128.271, 37.01]]
        result = self.matching(value, at='2026-11-03T05:00:00Z')['result']
        comparison = result['initial_comparison']; case = comparison['cases'][0]
        self.assertTrue(comparison['dictionary_changed'])
        self.assertFalse(any(comparison[key] for key in ('cases_changed', 'gold_changed', 'source_changed')))
        self.assertFalse(case['paired']); self.assertIsNone(case['paired_deltas'])
        self.assertEqual(case['initial_metrics']['gold_engine']['complete_classification']['correct'], 1)
        self.assertEqual(case['current_metrics']['gold_engine']['complete_classification']['correct'], 0)
        self.assertTrue(result['summary']['initial_changed'])

    def test_source_retest_phase_and_all_method_warnings_remain_visible(self):
        old = copy.deepcopy(self.references); self.new_evaluations()
        for method, control in self.controls.items():
            control.update(phase='retest', initial_ref=old[method]['evaluation_ref'])
            control['review']['reviewed_at'] = '2020-01-01T06:00:00Z'
        self.freeze_methods(hour=7)
        self.selection['comparison_id'] = uid(1960)
        class CompareClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 8, tzinfo=tz)
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 8, 30, tzinfo=tz)
        path = self.work / 'retest-comparison.json'; path.write_bytes(_json(self.selection))
        with patch('processing.evaluation.comparison.datetime', CompareClock), patch('processing.extraction.archive.datetime', FreezeClock):
            receipt = comparison_storage.freeze_comparison(path, self.comparison_root, self.evaluation_root)
        ref = receipt['comparison_ref']; self.matching_selection['comparison'] = dict(comparison_ref=ref,
            receipt_sha256=hashlib.sha256((self.comparison_root / ref / 'receipt.json').read_bytes()).hexdigest())
        summary = self.matching()['result']['summary']
        self.assertEqual((summary['phase'], summary['source_phase']), ('initial', 'retest'))
        self.assertIn('SOURCE_RETEST_NOT_INITIAL_GENERALIZATION', summary['warnings'])
        self.assertTrue(all('RETEST_NOT_INITIAL_GENERALIZATION' in method['warnings'] for method in summary['methods'].values()))
        self.assertEqual(summary['human_review_time']['total_duration_ns'], 600_000_000_000)



class MatchingMetricTest(unittest.TestCase):
    def row(self, state='classified', classification='candidate', reasons=(), kind='match', version='v1', local='i1'):
        return dict(kind=kind, document_version_id=version, slot_id=None if kind == 'additional' else 's1',
            local_item_id=local, event_id=None if kind == 'additional' else 'e1', split='dev', state=state,
            classification=classification if state == 'classified' else None,
            reason_codes=list(reasons) if state == 'classified' else None)

    def test_candidate_and_failure_is_retrieval_tp_but_partial_classification(self):
        rows = [self.row(), self.row('failed', version='v2')]
        event = matching._consensus(rows)
        self.assertEqual((event['state'], event['classification']), ('partial', None))
        expected = {'e1': dict(classification='candidate', reason_codes=[])}
        metric = matching._metrics(rows, [dict(event_id='e1', **event)], expected)
        self.assertEqual(metric['retrieval_presence'], dict(tp=1, fp=0, fn=0, predicted=1, expected=1, precision_percent=100.0, recall_percent=100.0))
        self.assertEqual((metric['complete_classification']['correct'], metric['complete_classification']['total']), (0, 1))

    def test_conflicting_duplicate_and_old_new_versions_prevent_consensus(self):
        for second in (self.row(classification='cancelled', reasons=['CANCELLED'], kind='duplicate', local='i2'),
                       self.row(classification='cancelled', reasons=['CANCELLED'], version='v2')):
            with self.subTest(second=second):
                result = matching._consensus([self.row(), second])
                self.assertEqual((result['state'], result['classification']), ('conflict', None))

    def test_candidate_duplicate_cannot_replace_missing_primary(self):
        rows = [self.row('missing'), self.row(kind='duplicate', local='i2')]
        result = matching._consensus(rows)
        self.assertEqual((result['state'], result['classification']), ('missing', None))
        m = matching._metrics(rows, [dict(event_id='e1', **result)], {'e1': dict(classification='candidate', reason_codes=[])})
        self.assertEqual((m['retrieval_presence']['tp'], m['anchors'], m['duplicate_outputs'], m['candidate_duplicates']), (1, 1, 1, 1))

    def test_reason_disagreement_is_not_union_and_nulls_are_never_correct(self):
        rows = [self.row(classification='needs_check', reasons=['SOURCE_STALE']),
                self.row(classification='needs_check', reasons=['RELATION_UNCERTAIN'], version='v2')]
        result = matching._consensus(rows)
        self.assertEqual((result['state'], result['classification'], result['reason_codes']), ('classified', 'needs_check', None))
        expected = {'e1': dict(classification='needs_check', reason_codes=['SOURCE_STALE'])}
        m = matching._metrics(rows, [dict(event_id='e1', **result)], expected)
        self.assertEqual((m['complete_classification']['correct'], m['classification_and_reasons']['correct']), (1, 0))
        self.assertEqual(matching._effect([dict(event_id='e1', state='failed', classification=None, reason_codes=None)],
            [dict(event_id='e1', state='failed', classification=None, reason_codes=None)])['classification_agreement']['correct'], 0)

    def test_empty_gold_and_each_orphan_preserve_zero_denominators(self):
        rows = [self.row(kind='additional'), self.row(kind='additional', local='i2')]
        m = matching._metrics(rows, [], {})
        self.assertEqual((m['retrieval_presence']['fp'], m['events'], m['anchors']), (2, 0, 0))
        self.assertEqual(m['retrieval_presence']['precision_percent'], 0.0)
        self.assertIsNone(m['retrieval_presence']['recall_percent'])
        self.assertIsNone(m['complete_classification']['accuracy_percent'])

    def test_needs_check_overconfirmation_and_cancellation_exposure_are_counted(self):
        expected = {'e1': dict(classification='needs_check', reason_codes=['SOURCE_STALE'])}
        rows = [self.row()]; events = [dict(event_id='e1', **matching._consensus(rows))]
        m = matching._metrics(rows, events, expected)
        self.assertEqual(m['needs_check'], dict(expected=1, correct=0, candidate_overconfirmation=1, missing=1))
        expected['e1']['classification'] = 'cancelled'
        m = matching._metrics(rows, events, expected)
        self.assertEqual(m['cancelled'], dict(expected=1, missing=1, candidate_exposure=1))

    def test_desired_status_omission_uses_all_linked_observations_including_duplicates(self):
        cases = [
            ('excluded', [self.row(classification='excluded')], 'classified', 1, 0),
            ('candidate', [self.row()], 'classified', 1, 1),
            ('failed', [self.row('failed')], 'failed', 1, 0),
            ('cancelled', [self.row(classification='cancelled', reasons=['CANCELLED'])], 'classified', 0, 0),
            ('candidate_cancelled', [self.row(), self.row(classification='cancelled', reasons=['CANCELLED'], kind='duplicate', local='i2')], 'conflict', 0, 1),
            ('missing_cancelled_duplicate', [self.row('missing'), self.row(classification='cancelled', reasons=['CANCELLED'], kind='duplicate', local='i2')], 'missing', 0, 0),
        ]
        for label, rows, state, missing, exposure in cases:
            with self.subTest(label=label):
                events = [dict(event_id='e1', **matching._consensus(rows))]
                metric = matching._metrics(rows, events, {'e1': dict(classification='cancelled', reason_codes=['CANCELLED'])})
                self.assertEqual(events[0]['state'], state)
                self.assertEqual(metric['cancelled'], dict(expected=1, missing=missing, candidate_exposure=exposure))
                self.assertEqual(metric['complete_classification']['correct'], int(label == 'cancelled'))
        rows = [self.row('missing'), self.row(classification='needs_check', reasons=['SOURCE_STALE'], kind='duplicate', local='i2')]
        events = [dict(event_id='e1', **matching._consensus(rows))]
        metric = matching._metrics(rows, events, {'e1': dict(classification='needs_check', reason_codes=['SOURCE_STALE'])})
        self.assertEqual(metric['needs_check'], dict(expected=1, correct=0, candidate_overconfirmation=0, missing=0))
        self.assertEqual(metric['states']['missing'], 1)
