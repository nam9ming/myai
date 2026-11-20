import copy
from decimal import Decimal
import hashlib
import importlib
import json
import unittest

from processing.extraction.validation import ExtractionError, parse_input, parse_output
from processing.matching import protocol
from support import ROOT, payload

try:
    projection = importlib.import_module('processing.evaluation.matching_projection')
except ModuleNotFoundError:
    projection = None


AT = '2026-11-07T03:00:00Z'
CASE = '30000000-0000-4000-8000-000000000001'
EVENT = '30000000-0000-4000-8000-000000000002'
PROJECTION = '30000000-0000-4000-8000-000000000003'
ENTRY = '30000000-0000-4000-8000-000000000005'


def unknown(field):
    field.update(value=None, knowledge='not_stated', evidence_ids=[], reason='합성 원문에 미기재')


class MatchingProjectionTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(projection, 'matching_projection API is missing')
        self.document = parse_input((ROOT / 'contracts/examples/ai-input.json').read_bytes())
        self.output = json.loads((ROOT / 'contracts/examples/ai-extraction.json').read_bytes())
        self.output['items'][0]['lifecycle'].update(value='active', knowledge='known', evidence_ids=['e1'], reason=None)
        p = payload()
        self.version = self.document['document_version_id']
        source = p['source_versions'][0]
        source.update(document_version_id=self.version, title=self.document['title'],
                      published_date=self.document['published_date'], collected_at='2026-11-06T01:00:00Z',
                      last_verified_at='2026-11-07T02:00:00Z', latest_check_attempt_at='2026-11-07T02:00:00Z',
                      current_last_verified_at='2026-11-07T02:00:00Z', current_latest_check_attempt_at='2026-11-07T02:00:00Z')
        source['checks'][0]['checked_at'] = '2026-11-07T02:00:00Z'
        p['context'].update(server_now='2026-11-07T02:00:00Z', anchor_date='2026-11-07')
        p['query']['snapshot_id'] = None
        self.case = dict(case_id=CASE, context=p['context'], point=p['point'], query=p['query'],
                         source_versions=[source], area_memberships=[dict(entry_id=ENTRY, status='verified')],
                         expected=[dict(event_id=EVENT, classification='candidate', reason_codes=[], note='합성 수동 기대')])
        self.cohort = {self.version: dict(document_id=source['document_id'], official_url=source['official_url'],
            split='dev', split_group_id='30000000-0000-4000-8000-000000000004', input=self.document,
            input_sha256=hashlib.sha256((ROOT / 'contracts/examples/ai-input.json').read_bytes()).hexdigest(),
            anchors={'item1': EVENT}, gold_output=copy.deepcopy(self.output))}
        self.annotation = dict(schema_version='score-links-v1', item_links=[dict(slot_id='item1',
            local_item_id='item1', kind='match', occurrence_links=[])], generation_reviews=[])
        self.dictionary = dict(dictionary_version=p['context']['dictionary_version'], entries=[dict(
            entry_id=ENTRY, name='가상 시장 앞 연결도로 일부 구간',
            name_aliases=['도로 별칭'], address='가상로 1', address_aliases=[], kind='segment',
            geometry=dict(type='LineString', coordinates=[[127.27, 37.01], [127.271, 37.01]]),
            coverage='complete', source='합성 검토 사전', checked_by='합성 검토자', checked_at='2026-11-07T01:00:00Z')])

    def prepared(self):
        dictionary = projection.validate_dictionary(self.dictionary, AT)
        return projection.prepare_case(self.case, self.cohort, dictionary, data_kind='synthetic', evaluated_at=AT), dictionary

    def classified(self):
        case, dictionary = self.prepared()
        output = parse_output(json.dumps(self.output, ensure_ascii=False).encode(), self.document)
        return projection.classify_output(output, self.annotation, self.cohort[self.version], case,
                                          dictionary, projection_id=PROJECTION)['item1']

    def replay(self):
        self.case['context'].update(mode='replay', case_id=CASE, reference_instant='2026-11-07T02:00:00Z',
            knowledge_cutoff='2026-11-07T02:00:00Z', history_fidelity='verified_snapshot')
        self.case['query'].update(mode='replay', case_id=CASE)

    def unchecked(self):
        self.case['source_versions'][0].update(checks=[], last_verified_at=None, latest_check_attempt_at=None,
            check_result='unchecked', current_last_verified_at=None, current_latest_check_attempt_at=None,
            current_check_result='unchecked')

    def test_known_own_location_yields_candidate_without_mutating_inputs(self):
        before = copy.deepcopy((self.case, self.dictionary, self.output, self.cohort))
        row = self.classified()
        self.assertEqual((row['state'], row['classification'], row['reason_codes'], row['disposition']),
                         ('classified', 'candidate', [], 'engine'))
        self.assertEqual(before, (self.case, self.dictionary, self.output, self.cohort))
        self.assertEqual(set(row), {'state', 'classification', 'reason_codes', 'disposition',
            'projection_limitations', 'projection_body_sha256', 'source_text_sha256'})

    def test_cancelled_and_window_excluded_keep_engine_reasons(self):
        self.output['items'][0]['lifecycle']['value'] = 'cancelled'
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('cancelled', ['CANCELLED']))
        self.output['items'][0]['occurrences'][0]['date_start']['value'] = '2026-12-01'
        self.output['items'][0]['occurrences'][0]['date_end']['value'] = '2026-12-01'
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('excluded', ['WINDOW_OUTSIDE']))

    def test_unknown_title_and_types_do_not_block_unfiltered_classification(self):
        unknown(self.output['items'][0]['title']); unknown(self.output['items'][0]['types'])
        self.output['items'][0]['types']['knowledge'] = 'ambiguous'
        self.assertEqual(self.classified()['classification'], 'candidate')

    def test_unknown_types_with_filter_remain_not_computable(self):
        self.case['query']['types'] = ['construction']; unknown(self.output['items'][0]['types'])
        self.output['items'][0]['types']['knowledge'] = 'ambiguous'
        row = self.classified()
        self.assertEqual((row['state'], row['classification'], row['reason_codes'], row['disposition']),
                         ('not_computable', None, None, 'type_unknown'))

    def test_known_type_mismatch_has_empty_filter_reasons(self):
        self.case['query']['types'] = ['event']
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes'], row['disposition']), ('excluded', [], 'type_filter'))

    def test_date_only_time_and_empty_refs_preserve_unknown(self):
        for name in ('time_start', 'time_end', 'end_day_offset', 'all_day'):
            unknown(self.output['items'][0]['occurrences'][0][name])
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('needs_check', ['TIME_UNKNOWN']))
        self.output['items'][0]['occurrences'][0]['location_refs'] = []
        self.output['warnings'].append('LOCATION_BINDING_UNKNOWN')
        self.assertEqual(self.classified()['reason_codes'], ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN', 'TIME_UNKNOWN'])

    def test_failure_and_valid_empty_output_remain_distinct(self):
        case, dictionary = self.prepared()
        self.assertIsNone(projection.classify_output(None, {}, self.cohort[self.version], case, dictionary, projection_id=PROJECTION))
        self.output.update(items=[], warnings=['NO_EVENT_FOUND'])
        output = parse_output(json.dumps(self.output).encode(), self.document)
        self.assertEqual(projection.classify_output(output, {}, self.cohort[self.version], case, dictionary, projection_id=PROJECTION), {})

    def test_area_outside_applies_identically_to_match_and_additional(self):
        self.case['area_memberships'][0]['status'] = 'outside'
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes'], row['disposition']), ('excluded', [], 'area_filter'))
        self.annotation['item_links'][0].update(slot_id=None, kind='additional')
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes'], row['disposition']), ('excluded', [], 'area_filter'))

    def test_duplicate_uses_same_reviewed_geography(self):
        self.annotation['item_links'][0]['kind'] = 'duplicate'
        self.assertEqual(self.classified()['classification'], 'candidate')

    def test_same_raw_candidate_remains_candidate_for_additional_annotation(self):
        expected = self.classified()
        self.annotation['item_links'][0].update(kind='duplicate')
        self.assertEqual(self.classified(), expected)
        self.annotation['item_links'][0].update(kind='additional', slot_id=None)
        self.assertEqual(self.classified(), expected)

    def test_wrong_gold_match_does_not_change_geographic_classification(self):
        self.cohort[self.version]['anchors']['other-slot'] = PROJECTION
        self.case['expected'].append(dict(event_id=PROJECTION, classification='excluded', reason_codes=[], note='다른 합성 기대'))
        expected = self.classified()
        self.annotation['item_links'][0]['slot_id'] = 'other-slot'
        self.assertEqual(self.classified(), expected)

    def add_location(self, *, status, referenced):
        entry = copy.deepcopy(self.dictionary['entries'][0])
        entry.update(entry_id=PROJECTION, name='다른 검토 장소', name_aliases=[])
        self.dictionary['entries'].append(entry)
        self.case['area_memberships'].append(dict(entry_id=PROJECTION, status=status))
        loc = copy.deepcopy(self.output['items'][0]['locations'][0])
        loc['local_location_id'] = 'l2'; loc['name']['value'] = '다른 검토 장소'
        self.output['items'][0]['locations'].append(loc)
        if referenced:
            self.output['items'][0]['occurrences'][0]['location_refs'].append('l2')

    def test_unused_verified_location_cannot_promote_outside_referenced_area(self):
        self.case['area_memberships'][0]['status'] = 'outside'
        self.add_location(status='verified', referenced=False)
        self.assertEqual((self.classified()['classification'], self.classified()['disposition']), ('excluded', 'area_filter'))

    def test_any_referenced_verified_location_promotes_shared_area(self):
        self.case['area_memberships'][0]['status'] = 'outside'
        self.add_location(status='verified', referenced=True)
        self.assertEqual(self.classified()['classification'], 'candidate')

    def test_all_referenced_outside_locations_filter_but_unresolved_location_keeps_uncertainty(self):
        self.case['area_memberships'][0]['status'] = 'outside'
        self.add_location(status='outside', referenced=True)
        self.assertEqual(self.classified()['disposition'], 'area_filter')
        unknown(self.output['items'][0]['locations'][1]['name'])
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('needs_check', ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN']))

    def test_type_filter_results_do_not_depend_on_annotation(self):
        self.case['query']['types'] = ['event']
        for unknown_types in (False, True):
            with self.subTest(unknown_types=unknown_types):
                self.annotation['item_links'][0].update(kind='match', slot_id='item1')
                if unknown_types:
                    unknown(self.output['items'][0]['types'])
                    self.output['items'][0]['types']['knowledge'] = 'ambiguous'
                expected = self.classified()
                self.annotation['item_links'][0].update(kind='additional', slot_id=None)
                self.assertEqual(self.classified(), expected)

    def test_area_memberships_cover_dictionary_entries_not_gold_event_ids(self):
        case, _ = self.prepared()
        self.assertEqual(case['area_memberships'], {ENTRY: 'verified'})
        for memberships in [[dict(event_id=EVENT, status='verified')], [dict(entry_id=EVENT, status='verified')],
                            [dict(entry_id=ENTRY, status='verified'), dict(entry_id=ENTRY, status='outside')]]:
            with self.subTest(memberships=memberships):
                self.case['area_memberships'] = memberships
                with self.assertRaises(ExtractionError): self.prepared()

    def test_name_and_address_normalize_but_do_not_choose_conflicting_entry(self):
        loc = self.output['items'][0]['locations'][0]
        loc['name']['value'] = '  도로\t별칭  '
        loc['address'].update(value=' 가상로\u00a01 ', knowledge='known', evidence_ids=['e1'], reason=None)
        self.assertEqual(self.classified()['classification'], 'candidate')
        loc['address']['value'] = '다른 주소'
        self.assertEqual(self.classified()['reason_codes'], ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN'])

    def test_duplicate_alias_and_known_kind_conflict_leave_geometry_unknown(self):
        second = copy.deepcopy(self.dictionary['entries'][0]); second['entry_id'] = PROJECTION
        self.dictionary['entries'].append(second)
        self.case['area_memberships'].append(dict(entry_id=PROJECTION, status='verified'))
        self.assertEqual(self.classified()['reason_codes'], ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN'])
        self.dictionary['entries'].pop()
        self.case['area_memberships'].pop()
        self.output['items'][0]['locations'][0]['kind']['value'] = 'point'
        self.assertEqual(self.classified()['reason_codes'], ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN'])

    def test_unknown_kind_can_use_unique_reviewed_geometry_without_mutation(self):
        unknown(self.output['items'][0]['locations'][0]['kind'])
        self.assertEqual(self.classified()['classification'], 'candidate')
        self.assertIsNone(self.output['items'][0]['locations'][0]['kind']['value'])

    def test_gold_location_never_supplies_missing_own_location(self):
        loc = self.output['items'][0]['locations'][0]
        unknown(loc['name']); unknown(loc['address'])
        self.assertEqual(self.classified()['reason_codes'], ['AREA_UNCERTAIN', 'LOCATION_UNKNOWN'])

    def test_projection_block_hash_does_not_impersonate_declared_d03_hash(self):
        self.document['blocks'].append(dict(block_id='b2', page=None, text='별도 합성 블록'))
        row = self.classified()
        body = '\n'.join(block['text'] for block in self.document['blocks']).encode()
        self.assertEqual(row['projection_body_sha256'], hashlib.sha256(body).hexdigest())
        self.assertEqual(row['source_text_sha256'], self.case['source_versions'][0]['text_sha256'])
        self.assertNotEqual(row['projection_body_sha256'], row['source_text_sha256'])

    def test_known_recurrence_stays_unknown_and_reports_projection_limit(self):
        self.output['items'][0]['occurrences'][0]['recurrence_text'].update(
            value='매주 토요일', knowledge='known', evidence_ids=['e1'], reason=None)
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('needs_check', ['TIME_UNKNOWN']))
        self.assertTrue(row['projection_limitations'])

    def test_decimal_dictionary_and_point_convert_only_after_raw_bounds(self):
        self.dictionary['entries'][0]['geometry']['coordinates'][0] = [Decimal('127.27'), Decimal('37.01')]
        self.case['point'].update(longitude=Decimal('127.27'), latitude=Decimal('37.01'))
        before = copy.deepcopy((self.dictionary, self.case))
        self.assertEqual(self.classified()['classification'], 'candidate')
        self.assertEqual(before, (self.dictionary, self.case))
        for bad in [Decimal('180.000000000000000000000001'), Decimal('NaN'), Decimal('Infinity'), True, '127.27']:
            with self.subTest(bad=bad):
                self.dictionary['entries'][0]['geometry']['coordinates'][0][0] = bad
                with self.assertRaises(ExtractionError): self.prepared()

    def test_point_decimal_tiny_outside_and_bool_are_rejected(self):
        for bad in [Decimal('90.00000000000000000000001'), Decimal('-90.00000000000000000001'), True, '37.01']:
            with self.subTest(bad=bad):
                self.case['point']['latitude'] = bad
                with self.assertRaises(ExtractionError): self.prepared()

    def test_dictionary_review_and_geometry_shape_must_be_valid(self):
        for change in [dict(checked_at='2026-11-08T00:00:00Z'), dict(name=None, address=None),
                       dict(name_aliases=['같음', '같음']), dict(geometry=dict(type='Point', coordinates=[127, 37]))]:
            with self.subTest(change=change):
                original = copy.deepcopy(self.dictionary)
                self.dictionary['entries'][0].update(change)
                with self.assertRaises(ExtractionError): self.prepared()
                self.dictionary = original

    def test_unchecked_private_source_uses_actual_nulls_and_source_stale(self):
        self.unchecked()
        row = self.classified()
        self.assertEqual((row['classification'], row['reason_codes']), ('needs_check', ['SOURCE_STALE']))
        self.assertEqual(self.case['source_versions'][0]['checks'], [])
        self.assertIsNone(self.case['source_versions'][0]['last_verified_at'])

    def test_late_collected_replay_source_is_unavailable_not_classified(self):
        self.replay(); self.case['context']['server_now'] = '2026-11-07T03:00:00Z'
        self.case['source_versions'][0]['collected_at'] = '2026-11-07T02:00:00.000000001Z'
        case, _ = self.prepared()
        self.assertFalse(case['source_availability'][self.version])
        row = self.classified()
        self.assertEqual((row['state'], row['classification'], row['reason_codes'], row['disposition']),
                         ('unavailable', None, None, 'not_available_at_cutoff'))

    def test_future_historical_checks_and_collected_after_now_rejected(self):
        self.replay()
        for field in ('checks', 'collected'):
            with self.subTest(field=field):
                original = copy.deepcopy(self.case)
                source = self.case['source_versions'][0]
                if field == 'checks': source['checks'][0]['checked_at'] = '2026-11-07T02:00:00.000000001Z'
                else: source['collected_at'] = '2026-11-07T02:00:00.000000001Z'
                with self.assertRaises(ExtractionError): self.prepared()
                self.case = original

    def test_source_hash_order_and_current_derivatives_rejected(self):
        for action in ('hash', 'order', 'current'):
            with self.subTest(action=action):
                original = copy.deepcopy(self.case)
                source = self.case['source_versions'][0]
                if action == 'hash': source['checks'][0]['text_sha256'] = '0' * 64
                elif action == 'order': source['checks'].append(copy.deepcopy(source['checks'][0]))
                else: source['current_latest_check_attempt_at'] = '2026-11-07T01:00:00Z'
                with self.assertRaises(ExtractionError): self.prepared()
                self.case = original

    def test_source_identity_and_full_cohort_coverage_rejected(self):
        for field, value in [('official_url', 'https://example.org/other'), ('document_id', CASE),
                             ('title', '다른 제목'), ('published_date', '2026-11-05')]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.case)
                self.case['source_versions'][0][field] = value
                with self.assertRaises(ExtractionError): self.prepared()
                self.case = original
        self.case['source_versions'] = []
        with self.assertRaises(ExtractionError): self.prepared()

    def test_case_context_membership_expected_and_evaluated_time_rejected(self):
        for action in ('future', 'dictionary', 'snapshot', 'area', 'expected', 'kind'):
            with self.subTest(action=action):
                original = copy.deepcopy(self.case)
                if action == 'future': self.case['context']['server_now'] = '2026-11-07T03:00:00.000000001Z'
                elif action == 'dictionary': self.case['context']['dictionary_version'] = 'other'
                elif action == 'snapshot': self.case['query']['snapshot_id'] = CASE
                elif action == 'area': self.case['area_memberships'] = []
                elif action == 'expected': self.case['expected'] = []
                else: self.case['context']['data_kind'] = 'real'
                with self.assertRaises(ExtractionError): self.prepared()
                self.case = original

    def test_source_freshness_24_hours_plus_one_ns_and_replay_current_state(self):
        self.replay()
        source = self.case['source_versions'][0]
        source.update(last_verified_at='2026-11-06T02:00:00Z', latest_check_attempt_at='2026-11-06T02:00:00Z')
        source['checks'][0]['checked_at'] = '2026-11-06T02:00:00Z'
        source.update(current_check_result='unreachable', current_latest_check_attempt_at='2026-11-07T02:00:00Z')
        self.assertEqual(self.classified()['classification'], 'candidate')
        self.case['context']['reference_instant'] = '2026-11-07T02:00:00.000000001Z'
        self.case['context']['server_now'] = '2026-11-07T02:00:00.000000001Z'
        self.assertEqual(self.classified()['reason_codes'], ['SOURCE_STALE'])


class SharedScenarioTest(unittest.TestCase):
    def test_public_unchecked_and_late_sources_remain_rejected(self):
        p = payload(); source = p['source_versions'][0]
        source.update(checks=[], last_verified_at=None, latest_check_attempt_at=None, check_result='unchecked',
            current_last_verified_at=None, current_latest_check_attempt_at=None, current_check_result='unchecked')
        with self.assertRaises(protocol.ProtocolError): protocol.validate(p)
        source['collected_at'] = '2026-11-04T02:00:00Z'
        with self.assertRaises(protocol.ProtocolError): protocol.validate(p)

    def test_shared_scenario_and_literal_private_source_api(self):
        self.assertTrue(callable(getattr(protocol, 'validate_scenario', None)), 'shared scenario API is missing')
        p = payload(); source = p['source_versions'][0]
        now, cutoff = protocol.validate_scenario(p['context'], p['point'], p['query'], p['snapshot_id'])
        source.update(checks=[], last_verified_at=None, latest_check_attempt_at=None, check_result='unchecked',
            current_last_verified_at=None, current_latest_check_attempt_at=None, current_check_result='unchecked')
        self.assertEqual(protocol._source(source, p['context'], now, cutoff, evaluation=True), 1793581200000000000)
        for value in (False, 1, 'true', None):
            with self.subTest(value=value), self.assertRaises(protocol.ProtocolError):
                protocol._source(source, p['context'], now, cutoff, evaluation=value)


if __name__ == '__main__':
    unittest.main()
