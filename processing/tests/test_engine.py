import copy
import unittest

from processing.matching.engine import calculate
from support import payload, event_copy, unknown_time, select


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.p = payload()
        self.event = self.p['events'][0]

    def result(self, selection='candidate'):
        select(self.p, selection)
        return calculate(self.p)

    def test_exact_candidate_has_real_computed_distance_and_minutes(self):
        result = self.result()
        data = result['data']
        self.assertEqual(dict(candidate=1, needs_check=0, cancelled=0), data['counts'])
        self.assertEqual('2026-11-02T15:00:00Z', data['query_context']['window_start'])
        self.assertEqual('2026-11-16T15:00:00Z', data['query_context']['window_end_exclusive'])
        item = data['items'][0]
        self.assertEqual(0, item['distance_m'])
        self.assertEqual('haversine_point', item['distance_basis'])
        self.assertEqual(120.0, item['time_overlap_minutes'])
        self.assertEqual([self.event['occurrences'][0]['occurrence_id']], item['matched_occurrence_ids'])
        self.assertEqual('합성 공지 😀', item['title'])

    def test_date_only_is_needs_check_not_all_day(self):
        unknown_time(self.event)
        item = self.result('needs_check')['data']['items'][0]
        self.assertIn('TIME_UNKNOWN', item['reason_codes'])
        self.assertIsNone(item['time_overlap_minutes'])
        self.assertEqual([], item['matched_occurrence_ids'])

    def test_all_closed_excludes_even_unknown_date(self):
        for h in self.p['query']['weekly_hours'].values():
            h.update(state='closed', intervals=[])
        self.event['occurrences'][0].update(precision='unknown', knowledge='ambiguous', date_start=None, date_end=None)
        result = self.result('needs_check')
        self.assertEqual([], result['data']['items'])
        self.assertIn('BUSINESS_CLOSED', result['diagnostics'][0]['reason_codes'])

    def test_unknown_and_false_is_excluded(self):
        unknown_time(self.event)
        self.event['locations'][0]['geometry']['coordinates'] = [128, 37]
        result = self.result('needs_check')
        self.assertEqual(0, sum(result['data']['counts'].values()))
        self.assertIn('DISTANCE_OUTSIDE', result['diagnostics'][0]['reason_codes'])

    def test_do_not_mix_occurrence_time_and_location(self):
        a = self.event['occurrences'][0]
        b = copy.deepcopy(a)
        b.update(occurrence_id='30000000-0000-4000-8000-000000000001', time_start='01:00', time_end='02:00')
        distant = copy.deepcopy(self.event['locations'][0])
        distant.update(location_id='30000000-0000-4000-8000-000000000002')
        distant['geometry']['coordinates'] = [128, 37]
        a['location_ids'] = [distant['location_id']]
        self.event['locations'].append(distant)
        self.event['occurrences'].append(b)
        self.assertEqual([], self.result('needs_check')['data']['items'])

    def test_candidate_with_unknown_other_occurrence_keeps_warning(self):
        other = copy.deepcopy(self.event['occurrences'][0])
        other.update(occurrence_id='30000000-0000-4000-8000-000000000003', precision='date_only',
                     time_start=None, time_end=None, end_day_offset=None)
        self.event['occurrences'].append(other)
        item = self.result()['data']['items'][0]
        self.assertEqual('candidate', item['classification'])
        self.assertIn('TIME_UNKNOWN', item['reason_codes'])
        self.assertIsNone(item['time_overlap_minutes'])

    def test_overlapping_occurrences_count_union(self):
        other = copy.deepcopy(self.event['occurrences'][0])
        other['occurrence_id'] = '30000000-0000-4000-8000-000000000004'
        self.event['occurrences'].append(other)
        self.assertEqual(120.0, self.result()['data']['items'][0]['time_overlap_minutes'])

    def test_area_and_relation_uncertain_demote(self):
        self.event.update(area_membership='uncertain', lifecycle='uncertain')
        item = self.result('needs_check')['data']['items'][0]
        self.assertIn('AREA_UNCERTAIN', item['reason_codes'])
        self.assertIn('RELATION_UNCERTAIN', item['reason_codes'])

    def test_stale_after_exact_24_hours(self):
        self.assertEqual(1, self.result()['data']['counts']['candidate'])
        self.p['context']['server_now'] = '2026-11-03T02:00:00.000001Z'
        item = self.result('needs_check')['data']['items'][0]
        self.assertIn('SOURCE_STALE', item['reason_codes'])

    def test_unreachable_keeps_source_url_and_success(self):
        source = self.p['source_versions'][0]
        source.update(check_result='unreachable', latest_check_attempt_at='2026-11-03T01:00:00Z')
        item = self.result('needs_check')['data']['items'][0]
        self.assertIn('SOURCE_UNREACHABLE', item['reason_codes'])
        self.assertEqual(source['official_url'], item['source_refs'][0]['url'])
        self.assertEqual(source['last_verified_at'], item['source_refs'][0]['last_verified_at'])

    def test_cancelled_never_becomes_candidate_when_stale(self):
        self.event.update(lifecycle='cancelled', lifecycle_evidence_ids=['body-quote'])
        self.p['context']['server_now'] = '2026-11-03T03:00:00Z'
        data = self.result('cancelled')['data']
        self.assertEqual(dict(candidate=0, needs_check=0, cancelled=1), data['counts'])
        self.assertIn('CANCELLED', data['items'][0]['reason_codes'])
        self.assertIn('SOURCE_STALE', data['items'][0]['reason_codes'])

    def test_replay_does_not_compare_current_age_to_historical_day(self):
        case = '40000000-0000-4000-8000-000000000001'
        self.p['context'].update(mode='replay', case_id=case, server_now='2026-12-03T02:00:00Z',
                                 reference_instant='2026-11-03T02:00:00Z', knowledge_cutoff='2026-11-03T02:00:00Z',
                                 history_fidelity='verified_snapshot')
        self.p['query'].update(mode='replay', case_id=case)
        self.assertEqual(1, self.result()['data']['counts']['candidate'])
        self.assertEqual('verified_snapshot', self.result()['data']['query_context']['history_fidelity'])

    def test_reconstructed_without_historical_check_stays_unknown(self):
        self.test_replay_does_not_compare_current_age_to_historical_day()
        self.p['context']['history_fidelity'] = 'reconstructed'
        self.p['source_versions'][0].update(last_verified_at=None, latest_check_attempt_at=None, check_result='unchecked', checks=[])
        item = self.result('needs_check')['data']['items'][0]
        self.assertIsNone(item['source_refs'][0]['last_verified_at'])
        self.assertIn('SOURCE_STALE', item['reason_codes'])

    def test_partial_geometry_inside_can_candidate_without_fabricated_minimum(self):
        self.event['locations'][0]['coverage'] = 'partial'
        item = self.result()['data']['items'][0]
        self.assertIsNone(item['distance_m'])
        self.assertTrue(item['warnings'])

    def test_inside_or_unknown_location_true_but_minimum_unknown(self):
        unknown = copy.deepcopy(self.event['locations'][0])
        unknown.update(location_id='30000000-0000-4000-8000-000000000005', status='unknown', geometry=None, kind='unknown')
        self.event['locations'].append(unknown)
        self.event['occurrences'][0]['location_ids'].append(unknown['location_id'])
        self.assertIsNone(self.result()['data']['items'][0]['distance_m'])

    def test_counts_before_selection_after_or_type_filter(self):
        second = event_copy(self.event, 22)
        second.update(types=['traffic'], lifecycle='cancelled', lifecycle_evidence_ids=['body-quote'])
        self.p['events'].append(second)
        data = self.result()['data']
        self.assertEqual(dict(candidate=1, needs_check=0, cancelled=1), data['counts'])
        self.assertEqual(1, len(data['items']))
        self.p['query']['types'] = ['traffic', 'event']
        data = self.result()['data']
        self.assertEqual(dict(candidate=0, needs_check=0, cancelled=1), data['counts'])

    def test_overlap_sweep_splits_sets_at_contact(self):
        a, b, c = (event_copy(self.event, n) for n in (31, 32, 33))
        for e, start, end in [(a, '10:00', '12:00'), (b, '11:00', '13:00'), (c, '12:00', '14:00')]:
            e['occurrences'][0].update(time_start=start, time_end=end)
        self.p['events'] = [c, a, b]
        data = self.result()['data']
        groups = data['overlap_groups']
        self.assertEqual([[a['event_id'], b['event_id']], [b['event_id'], c['event_id']]], [g['event_ids'] for g in groups])
        self.assertEqual(['2026-11-03T02:00:00Z', '2026-11-03T03:00:00Z'], [g['start_at'] for g in groups])
        self.p['events'].reverse()
        self.assertEqual(groups, self.result()['data']['overlap_groups'])

    def test_needs_check_excluded_from_confirmed_overlap_groups(self):
        second = event_copy(self.event, 44)
        second['area_membership'] = 'uncertain'
        self.p['events'].append(second)
        self.assertEqual([], self.result()['data']['overlap_groups'])

    def test_default_sort_and_distance_sort_have_stable_tie_break(self):
        second = event_copy(self.event, 55)
        second['occurrences'][0].update(time_start='09:00', time_end='10:00')
        second['locations'][0]['geometry']['coordinates'][0] += 0.001
        self.p['events'].append(second)
        self.assertEqual([second['event_id'], self.event['event_id']], [i['event_id'] for i in self.result()['data']['items']])
        self.p['query']['sort'] = 'distance'
        self.assertEqual([self.event['event_id'], second['event_id']], [i['event_id'] for i in self.result()['data']['items']])

    def test_fact_projection_preserves_field_values_and_codepoint_evidence(self):
        item = self.result()['data']['items'][0]
        self.assertIsNone(item['exceptions'])
        self.assertEqual('not_stated', item['field_values']['exceptions']['knowledge'])
        self.assertEqual('합성 공지 😀', item['evidence'][0]['quote'])
        self.assertEqual(7, item['evidence'][0]['end_char'])
        self.assertEqual(self.p['source_versions'][0]['document_id'], item['evidence'][0]['source_document_id'])

    def test_empty_events_is_valid_zero_not_failure(self):
        self.p.update(events=[], source_versions=[])
        self.assertEqual(dict(candidate=0, needs_check=0, cancelled=0), self.result()['data']['counts'])

    def test_unknown_date_sorts_after_known_date(self):
        self.event['occurrences'][0].update(date_start=None, date_end=None, precision='unknown', knowledge='ambiguous')
        second = event_copy(self.event, 71)
        second['occurrences'][0].update(date_start='2026-11-05', date_end='2026-11-05', precision='date_only',
                                        knowledge='known', time_start=None, time_end=None, end_day_offset=None)
        self.p['events'].append(second)
        ids = [item['event_id'] for item in self.result('needs_check')['data']['items']]
        self.assertEqual([second['event_id'], self.event['event_id']], ids)

    def test_24hour_freshness_preserves_nanoseconds(self):
        self.p['context']['server_now'] = '2026-11-03T02:00:00.000000001Z'
        self.assertEqual(1, self.result('needs_check')['data']['counts']['needs_check'])

    def test_one_minute_overlap_and_lunch_gap(self):
        self.event['occurrences'][0].update(time_start='17:59', time_end='18:01')
        self.assertEqual(1.0, self.result()['data']['items'][0]['time_overlap_minutes'])
        self.p['query']['weekly_hours']['tuesday']['intervals'] = [
            dict(start='09:00', end='12:00', end_day_offset=0), dict(start='14:00', end='18:00', end_day_offset=0)]
        self.event['occurrences'][0].update(time_start='11:00', time_end='15:00')
        self.assertEqual(120.0, self.result()['data']['items'][0]['time_overlap_minutes'])
        self.event['occurrences'][0].update(time_start='12:00', time_end='14:00')
        self.assertEqual([], self.result()['data']['items'])

    def test_explicit_all_day_computes_known_business_overlap(self):
        unknown_time(self.event)
        self.event['occurrences'][0]['precision'] = 'explicit_all_day'
        self.assertEqual(540.0, self.result()['data']['items'][0]['time_overlap_minutes'])

    def test_today_ended_stays_in_window_with_warning(self):
        self.p['context']['server_now'] = '2026-11-03T04:00:00Z'
        item = self.result('needs_check')['data']['items'][0]
        self.assertTrue(any('오늘 종료' in message for message in item['warnings']))

    def test_second_level_positive_overlap_does_not_round_to_excluded(self):
        self.event['occurrences'][0].update(time_start='10:00:01', time_end='10:00:02')
        item = self.result()['data']['items'][0]
        self.assertEqual('candidate', item['classification'])
        self.assertEqual(0.0, item['time_overlap_minutes'])

    def test_cancelled_sort_uses_cancel_evidence_verification(self):
        self.event.update(lifecycle='cancelled', lifecycle_evidence_ids=['body-quote'])
        second = event_copy(self.event, 82)
        source = copy.deepcopy(self.p['source_versions'][0])
        source.update(document_id='50000000-0000-4000-8000-000000000001', document_version_id='50000000-0000-4000-8000-000000000002',
                      last_verified_at='2026-11-03T01:00:00Z', latest_check_attempt_at='2026-11-03T01:00:00Z')
        self.p['source_versions'].append(source)
        second['source_version_ids'] = [source['document_version_id']]
        for e in second['evidence']:
            e['document_version_id'] = source['document_version_id']
        self.p['events'].append(second)
        self.assertEqual([second['event_id'], self.event['event_id']], [i['event_id'] for i in self.result('cancelled')['data']['items']])
