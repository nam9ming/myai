import copy
import hashlib
import json
from pathlib import Path
import unittest

from processing.extraction.schema import input_schema, output_schema
from processing.extraction.validation import ExtractionError, parse_input, parse_output


ROOT = Path(__file__).resolve().parents[2]


def raw(value):
    return json.dumps(value, ensure_ascii=True).encode('utf-8')


class ExtractionValidationTest(unittest.TestCase):
    def setUp(self):
        self.input_bytes = (ROOT / 'contracts/examples/ai-input.json').read_bytes()
        self.document = parse_input(self.input_bytes)
        self.output_bytes = (ROOT / 'contracts/examples/ai-extraction.json').read_bytes()
        self.output = json.loads(self.output_bytes)

    def invalid(self, body, kind='schema', document=None):
        with self.assertRaises(ExtractionError) as caught:
            parse_output(body if isinstance(body, bytes) else raw(body), document or self.document)
        error = caught.exception
        self.assertEqual(error.kind, kind)
        self.assertEqual(error.retryable, kind == 'schema')
        self.assertTrue(error.path.startswith('$'))
        self.assertNotIn('PRIVATE_VALUE', str(error))
        return error

    def test_accepts_existing_contract_without_mutating_values(self):
        before = copy.deepcopy(self.document)
        self.assertEqual(parse_output(self.output_bytes, self.document), self.output)
        self.assertEqual(self.document, before)

    def test_generated_schema_artifacts_are_exact(self):
        for name, build in [('ai-input-v1.json', input_schema), ('extract-schema-v1.json', output_schema)]:
            with self.subTest(name=name):
                self.assertEqual(json.loads((ROOT / 'contracts/schemas' / name).read_text()), build())
                self.assertEqual(build()['$schema'], 'https://json-schema.org/draft/2020-12/schema')

    def test_preserves_unknown_and_known_empty_without_guessing(self):
        item = self.output['items'][0]
        item['exceptions']['value'] = []
        item['types'].update(value=None, knowledge='ambiguous', reason='원문만으로 유형 확정 불가')
        result = parse_output(raw(self.output), self.document)['items'][0]
        self.assertEqual(result['exceptions']['value'], [])
        self.assertIsNone(result['types']['value'])
        self.assertIsNone(result['occurrences'][0]['recurrence_text']['value'])
        self.assertIsNone(result['locations'][0]['address']['value'])

    def test_empty_items_and_unknown_location_binding_require_warnings(self):
        self.output['items'] = []
        self.invalid(self.output)
        self.output['warnings'].append('NO_EVENT_FOUND')
        self.assertEqual(parse_output(raw(self.output), self.document)['items'], [])
        self.output = json.loads(self.output_bytes)
        self.output['items'][0]['occurrences'][0]['location_refs'] = []
        self.invalid(self.output)
        self.output['warnings'].append('LOCATION_BINDING_UNKNOWN')
        self.assertEqual(parse_output(raw(self.output), self.document)['items'][0]['occurrences'][0]['location_refs'], [])

    def test_missing_extra_and_forbidden_keys_are_not_echoed(self):
        for path in [(), ('items', 0), ('items', 0, 'title'), ('items', 0, 'occurrences', 0), ('items', 0, 'locations', 0), ('evidence', 0)]:
            for action in ['extra', 'missing']:
                with self.subTest(path=path, action=action):
                    body = copy.deepcopy(self.output); node = body
                    for key in path:
                        node = node[key]
                    if action == 'extra':
                        node['PRIVATE_VALUE'] = {'coordinates': [127.0, 37.0]}
                    else:
                        del node[next(iter(node))]
                    self.invalid(body)
        self.output['items'][0]['distance_m'] = 0
        self.invalid(self.output)

    def test_strict_wire_json_unicode_numbers_and_depth(self):
        for value in [b'\xff', b'{} {}', b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":1e999}', b'"\\ud800"', b'{"\\ud800":1}', b'[' * 110 + b'0' + b']' * 110]:
            with self.subTest(value=value[:30]):
                self.invalid(value)
        self.invalid(b' ' * (8 * 1024 * 1024 + 1))
        for value in [b'\xff', b'{"a":1,"a":2}', b'"\\ud800"']:
            with self.assertRaises(ExtractionError) as caught:
                parse_input(value)
            self.assertEqual(caught.exception.kind, 'input')

    def test_input_rejects_extra_fields_bad_uuid_blocks_and_preprocessing(self):
        cases = []
        body = copy.deepcopy(self.document); body['weekly_hours'] = {}; cases.append(body)
        body = copy.deepcopy(self.document); body['document_version_id'] = body['document_version_id'].upper(); cases.append(body)
        body = copy.deepcopy(self.document); body['blocks'].append(copy.deepcopy(body['blocks'][0])); cases.append(body)
        body = copy.deepcopy(self.document); body['blocks'][0]['page'] = True; cases.append(body)
        body = copy.deepcopy(self.document); body['blocks'][0]['text'] = '\u1100\u1161'; cases.append(body)
        body = copy.deepcopy(self.document); body['blocks'][0]['text'] += '\r\n'; cases.append(body)
        body = copy.deepcopy(self.document); body['published_date'] = '2026-02-30'; cases.append(body)
        for body in cases:
            with self.subTest(body=body.keys()), self.assertRaises(ExtractionError) as caught:
                parse_input(raw(body))
            self.assertEqual(caught.exception.kind, 'input')

    def test_field_value_types_knowledge_and_boolean_integer_distinction(self):
        for field, value in [('types', ['unknown']), ('types', []), ('title', []), ('exceptions', '없음'), ('lifecycle', 'uncertain')]:
            body = copy.deepcopy(self.output); body['items'][0][field]['value'] = value; self.invalid(body)
        for name, value in [('end_day_offset', True), ('end_day_offset', 1.0), ('end_day_offset', 2), ('all_day', 1), ('time_start', '24:00'), ('date_start', '2026-02-30')]:
            body = copy.deepcopy(self.output); body['items'][0]['occurrences'][0][name]['value'] = value; self.invalid(body)
        for change in [dict(knowledge='known', value=None), dict(evidence_ids=[]), dict(knowledge='ambiguous', value='추정'), dict(knowledge='not_stated', value=None, reason=None)]:
            body = copy.deepcopy(self.output); body['items'][0]['title'].update(change); self.invalid(body)

    def test_evidence_offsets_hashes_and_references_need_review_not_retry(self):
        for change in [dict(start_char=1), dict(end_char=9999), dict(quote='PRIVATE_VALUE'), dict(text_sha256='0' * 64), dict(block_id='missing')]:
            body = copy.deepcopy(self.output); body['evidence'][0].update(change); self.invalid(body, 'review')
        body = copy.deepcopy(self.output); body['items'][0]['title']['evidence_ids'] = ['missing']; self.invalid(body, 'review')
        body = copy.deepcopy(self.output); body['evidence'][0]['start_char'] = True; self.invalid(body)
        body = copy.deepcopy(self.output); body['document_version_id'] = '00000000-0000-4000-8000-000000000001'; self.invalid(body, 'review')

    def test_emoji_offsets_and_multiple_block_hashes(self):
        self.document['blocks'].append(dict(block_id='emoji', page=2, text='가😀나'))
        body = copy.deepcopy(self.output)
        body['evidence'].append(dict(evidence_id='emoji-evidence', block_id='emoji', quote='😀', start_char=1, end_char=2,
                                     text_sha256=hashlib.sha256('가😀나'.encode()).hexdigest()))
        self.assertEqual(parse_output(raw(body), self.document)['evidence'][1]['quote'], '😀')
        body['evidence'][1]['end_char'] = 3
        self.invalid(body, 'review')

    def test_local_ids_are_document_unique_and_refs_stay_in_same_item(self):
        second = copy.deepcopy(self.output['items'][0]); second['local_item_id'] = 'item2'
        second['occurrences'][0]['local_occurrence_id'] = 'o2'
        second['locations'][0]['local_location_id'] = 'l2'; second['occurrences'][0]['location_refs'] = ['l2']
        self.output['items'].append(second)
        self.assertEqual(len(parse_output(raw(self.output), self.document)['items']), 2)
        for group, key in [('items', 'local_item_id'), ('occurrences', 'local_occurrence_id'), ('locations', 'local_location_id')]:
            body = copy.deepcopy(self.output)
            if group == 'items':
                body['items'][1][key] = body['items'][0][key]
            else:
                body['items'][1][group][0][key] = body['items'][0][group][0][key]
            self.invalid(body)
        body = copy.deepcopy(self.output); body['items'][1]['occurrences'][0]['location_refs'] = ['l1']; self.invalid(body, 'review')
        body = copy.deepcopy(self.output); body['evidence'].append(copy.deepcopy(body['evidence'][0])); self.invalid(body)

    def test_temporal_order_preserves_overnight_and_explicit_continuous_end(self):
        occurrence = self.output['items'][0]['occurrences'][0]
        occurrence['date_end']['value'] = '2026-11-06'; self.invalid(self.output, 'review')
        occurrence['date_end']['value'] = '2026-11-07'
        occurrence['time_start']['value'] = '23:00'; occurrence['time_end']['value'] = '01:00'; self.invalid(self.output, 'review')
        occurrence['end_day_offset']['value'] = 1
        self.assertEqual(parse_output(raw(self.output), self.document)['items'][0]['occurrences'][0]['end_day_offset']['value'], 1)
        occurrence['date_end']['value'] = '2026-11-09'
        self.assertEqual(parse_output(raw(self.output), self.document)['items'][0]['occurrences'][0]['date_end']['value'], '2026-11-09')
        occurrence['end_day_offset'].update(value=None, knowledge='not_stated', reason='익일 표기 없음', evidence_ids=[])
        occurrence['date_end']['value'] = occurrence['date_start']['value']
        self.assertIsNone(parse_output(raw(self.output), self.document)['items'][0]['occurrences'][0]['end_day_offset']['value'])


if __name__ == '__main__':
    unittest.main()
