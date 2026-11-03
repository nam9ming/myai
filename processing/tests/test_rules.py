import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from processing.evaluation.scoring import score_document
from processing.extraction import rules
from processing.extraction.validation import ExtractionError, parse_input, parse_output
from processing.tests.test_scoring import fixture


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode()


def profile():
    return dict(schema_version='rule-profile-v1', profile_version='synthetic-places-v1',
        rule_version='rule-extract-v1', data_kind='synthetic',
        type_keywords=dict(construction=['공사'], event=['행사'], traffic=['통제']),
        target_keywords=['대상'], exception_keywords=['예외', '제외'],
        places=[dict(name='가상로 A', aliases=['가상길'], kind='point')])


class RulesTest(unittest.TestCase):
    def setUp(self):
        self.document, self.gold, self.links, self.instructions = fixture()
        self.profile = profile()

    def run_rule(self, body=None):
        if body is not None:
            self.document['blocks'][0]['text'] = body
        raw, error = rules.extract_rules(encoded(self.document), encoded(self.profile))
        self.assertIsNone(error)
        return parse_output(raw, self.document), raw

    def test_literal_profile_emits_valid_reproducible_fields_and_evidence(self):
        result, raw = self.run_rule()
        item = result['items'][0]; occurrence = item['occurrences'][0]
        self.assertEqual(item['types']['value'], ['construction'])
        self.assertEqual([occurrence[k]['value'] for k in ('date_start', 'date_end', 'time_start', 'time_end', 'end_day_offset')],
                         ['2026-11-07', '2026-11-07', '10:00', '16:00', 0])
        self.assertEqual(item['locations'][0]['name']['value'], '가상로 A')
        self.assertIsNone(item['locations'][0]['address']['value'])
        self.assertEqual(item['exceptions']['value'], [])
        self.assertIsNone(item['lifecycle']['value'])
        self.assertEqual(raw, self.run_rule()[1])

    def test_types_are_fixed_literals_and_no_body_keyword_is_empty(self):
        for body, expected in [('합성 행사', ['event']), ('합성 통제', ['traffic']),
                               ('공사로 통제, 행사 병행', ['construction', 'event', 'traffic'])]:
            with self.subTest(body=body):
                self.assertEqual(self.run_rule(body)[0]['items'][0]['types']['value'], expected)
        self.document['title'] = '공사 행사 통제'
        result, _ = self.run_rule('관련 일정은 아직 안내하지 않았다.')
        self.assertEqual(result['items'], [])
        self.assertIn('NO_EVENT_FOUND', result['warnings'])

    def test_full_date_formats_and_explicit_date_range(self):
        for body, expected in [('공사 2026년 11월 7일', ('2026-11-07', '2026-11-07')),
            ('공사 2026.11.07', ('2026-11-07', '2026-11-07')),
            ('공사 2026/11/07 ~ 2026/11/09', ('2026-11-07', '2026-11-09')),
            ('공사 2026-11-07부터 2026-11-08까지', ('2026-11-07', '2026-11-08'))]:
            with self.subTest(body=body):
                occurrence = self.run_rule(body)[0]['items'][0]['occurrences'][0]
                self.assertEqual(tuple(occurrence[k]['value'] for k in ('date_start', 'date_end')), expected)

    def test_partial_invalid_unpaired_multiple_dates_do_not_invent_dates(self):
        for body in ('공사 11월 7일', '공사 2026-02-30', '공사 2026-11-07, 2026-11-09',
                     '공사 2026-11-07 ~ 11월 9일', '공사 2026-11-09 ~ 2026-11-07',
                     '공사 2026-11-07 ~ 2026-11-08, 추가 2026-11-09'):
            with self.subTest(body=body):
                occurrence = self.run_rule(body)[0]['items'][0]['occurrences'][0]
                self.assertIsNone(occurrence['date_start']['value'])
                self.assertEqual(occurrence['date_start']['knowledge'], 'ambiguous')
        occurrence = self.run_rule('공사 일정 미정')[0]['items'][0]['occurrences'][0]
        self.assertEqual(occurrence['date_start']['knowledge'], 'not_stated')

    def test_clock_ranges_overnight_all_day_and_unknown(self):
        for body, expected in [('공사 9:00 ~ 16:00', ('09:00', '16:00', 0, False)),
            ('공사 23:00부터 익일 01:30까지', ('23:00', '01:30', 1, False)),
            ('공사 10:00:05 ~ 11:00:10', ('10:00:05', '11:00:10', 0, False)),
            ('공사 종일', (None, None, None, True)),
            ('공사 시각 미정', (None, None, None, None))]:
            with self.subTest(body=body):
                occurrence = self.run_rule(body)[0]['items'][0]['occurrences'][0]
                self.assertEqual(tuple(occurrence[k]['value'] for k in ('time_start', 'time_end', 'end_day_offset', 'all_day')), expected)

    def test_unsupported_or_conflicting_clocks_are_not_silently_coerced(self):
        for body in ('공사 10:00', '공사 24:00 ~ 01:00', '공사 10:00, 11:00',
                     '공사 종일 10:00 ~ 11:00', '공사 10:00 ~ 11:00 / 13:00 ~ 14:00'):
            with self.subTest(body=body):
                occurrence = self.run_rule(body)[0]['items'][0]['occurrences'][0]
                self.assertIsNone(occurrence['time_start']['value'])
                self.assertEqual(occurrence['time_start']['knowledge'], 'ambiguous')
        occurrence = self.run_rule('공사 23:00 ~ 01:00')[0]['items'][0]['occurrences'][0]
        self.assertEqual(occurrence['end_day_offset']['knowledge'], 'ambiguous')

    def test_sentence_excerpts_preserve_target_and_exceptions_without_guessing(self):
        item = self.run_rule('공사. 대상: 주변 점포. 예외: 긴급 차량 제외.')[0]['items'][0]
        self.assertEqual(item['applicability']['value'], '대상: 주변 점포')
        self.assertEqual(item['exceptions']['value'], ['예외: 긴급 차량 제외'])
        item = self.run_rule('공사. 대상: 점포. 대상: 차량. 예외 없음. 긴급 차량 제외.')[0]['items'][0]
        self.assertEqual(item['applicability']['knowledge'], 'ambiguous')
        self.assertEqual(item['exceptions']['knowledge'], 'ambiguous')
        item = self.run_rule('공사')[0]['items'][0]
        self.assertIsNone(item['exceptions']['value'])

    def test_aliases_unknown_places_and_unicode_evidence_use_source_codepoints(self):
        result, _ = self.run_rule('😀 합성 공사, 가상길에서 시행.')
        self.assertEqual(result['items'][0]['locations'][0]['name']['value'], '가상로 A')
        evidence = result['evidence'][0]
        self.assertEqual(evidence['quote'], self.document['blocks'][0]['text'])
        self.assertEqual(evidence['end_char'], len(evidence['quote']))
        self.assertEqual(evidence['text_sha256'], hashlib.sha256(evidence['quote'].encode()).hexdigest())
        result, _ = self.run_rule('공사 장소 미정')
        self.assertIsNone(result['items'][0]['locations'][0]['name']['value'])
        self.assertEqual(result['items'][0]['occurrences'][0]['location_refs'], [])
        self.assertIn('LOCATION_BINDING_UNKNOWN', result['warnings'])

    def test_profile_rejects_extra_keys_bad_versions_alias_collisions_and_regex(self):
        variants = []
        for key, value in [('extra', True), ('rule_version', 'future'), ('data_kind', 'unknown')]:
            p = profile(); p[key] = value; variants.append(p)
        p = profile(); p['places'].append(dict(name='다른 곳', aliases=['가상길'], kind=None)); variants.append(p)
        p = profile(); p['target_keywords'] = ['']; variants.append(p)
        p = profile(); p['type_keywords']['regex'] = ['.*']; variants.append(p)
        for invalid in variants:
            with self.subTest(invalid=invalid), self.assertRaises(ExtractionError):
                rules.parse_profile(encoded(invalid))
        with self.assertRaises(ExtractionError):
            rules.parse_profile(b'{"schema_version":"rule-profile-v1","schema_version":"rule-profile-v1"}')
        self.profile['data_kind'] = 'real'
        with self.assertRaises(ExtractionError):
            rules.extract_rules(encoded(self.document), encoded(self.profile))

    def test_size_budget_emits_failed_raw_diagnostic_instead_of_truncated_success(self):
        with patch.object(rules, 'MAX_BYTES', 200):
            raw, error = rules.extract_rules(encoded(self.document), encoded(self.profile))
        self.assertEqual(error, 'RULE_OUTPUT_LIMIT')
        self.assertEqual(json.loads(raw), {'rule_error': 'RULE_OUTPUT_LIMIT'})

    def test_many_distinct_excerpts_fail_explicitly_instead_of_dropping_claims(self):
        self.document['blocks'][0]['text'] = '공사. ' + '\n'.join(f'예외: 합성 조건{i}' for i in range(257))
        raw, error = rules.extract_rules(encoded(self.document), encoded(self.profile))
        self.assertEqual(error, 'RULE_OUTPUT_LIMIT')
        self.assertEqual(json.loads(raw), {'rule_error': 'RULE_OUTPUT_LIMIT'})

    def test_existing_scorer_accepts_baseline_and_keeps_honest_denominator(self):
        result, raw = self.run_rule()
        item = result['items'][0]
        links = copy.deepcopy(self.links)
        links['item_links'][0].update(local_item_id=item['local_item_id'], occurrence_links=[dict(
            gold_occurrence_id='o1', local_occurrence_id=item['occurrences'][0]['local_occurrence_id'])])
        score = score_document(encoded(self.document), encoded(self.gold), raw, encoded(links), self.instructions)
        self.assertEqual((score['summary']['known_fields'], score['summary']['correct_fields']), (8, 7))
        self.assertIsNone(score['summary']['generation_rate_percent'])
        self.assertFalse(score['summary']['document_failed'])
