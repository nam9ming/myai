import copy
import hashlib
import json
from pathlib import Path
import unittest

from processing.extraction.validation import ExtractionError, MAX_BYTES, parse_input, parse_output as parse_legacy


ROOT = Path(__file__).resolve().parents[2]
CATEGORIES = ('education', 'support', 'culture', 'construction_traffic', 'living')
FACTS = ('application_period', 'occurrences', 'regions', 'locations', 'residency_requirement',
         'target', 'eligibility', 'application_method', 'preparation', 'cost', 'recruitment', 'lifecycle')


def encoded(value):
    return json.dumps(value, ensure_ascii=False).encode('utf-8')


class CitizenExtractionTest(unittest.TestCase):
    def setUp(self):
        from processing.extraction import citizen
        self.citizen = citizen
        self.input_bytes = (ROOT / 'contracts/examples/citizen-ai-input.json').read_bytes()
        self.document = parse_input(self.input_bytes)
        self.output_bytes = (ROOT / 'contracts/examples/citizen-ai-extraction.json').read_bytes()
        self.output = json.loads(self.output_bytes)

    def invalid(self, value, kind='schema', path=None, document=None):
        with self.assertRaises(ExtractionError) as caught:
            self.citizen.parse_output(value if isinstance(value, bytes) else encoded(value),
                                      self.document if document is None else document)
        error = caught.exception
        self.assertEqual(error.kind, kind)
        self.assertEqual(error.retryable, kind == 'schema')
        if path is not None:
            self.assertEqual(error.path, path)
        self.assertNotIn('PRIVATE_VALUE', str(error))
        return error

    def test_public_fixture_preserves_all_five_categories_twelve_raw_facts_and_multiple_events(self):
        before = copy.deepcopy(self.document)
        result = self.citizen.parse_output(self.output_bytes, self.document)
        self.assertEqual(result, self.output)
        self.assertEqual(self.document, before)
        self.assertGreaterEqual(len(result['items']), 2)
        self.assertEqual(set(CATEGORIES), {c for item in result['items'] for c in item['categories']['value']})
        for item in result['items']:
            self.assertEqual(set(item), {'local_item_id', 'title', 'categories', *FACTS})
        item = result['items'][0]
        self.assertNotEqual(item['application_period']['value'], item['occurrences']['value'])
        self.assertNotEqual(item['regions']['value'], item['residency_requirement']['value'])
        self.assertIsNone(item['cost']['value'])
        self.assertIn('무료', {str(item['cost']['value']) for item in result['items']})

    def test_unknown_values_and_known_empty_array_remain_distinct(self):
        item = self.output['items'][0]
        item['categories'].update(value=None, knowledge='ambiguous', reason='분류 미상')
        for name in FACTS:
            for knowledge in ('not_stated', 'ambiguous', 'not_applicable'):
                body = copy.deepcopy(self.output)
                body['items'][0][name] = dict(value=None, knowledge=knowledge, evidence_ids=[], reason='원문에서 미확인')
                self.assertEqual(self.citizen.parse_output(encoded(body), self.document), body)
        item['preparation'] = dict(value=[], knowledge='known', evidence_ids=['e1'], reason=None)
        result = self.citizen.parse_output(encoded(self.output), self.document)['items'][0]
        self.assertEqual(result['preparation']['value'], [])
        self.assertIsNone(result['categories']['value'])

    def test_each_raw_fact_accepts_only_text_unique_text_array_or_unknown(self):
        for name in FACTS:
            for value in ('원문 표현', ['원문 표현', '다른 표현'], []):
                with self.subTest(name=name, value=value):
                    body = copy.deepcopy(self.output)
                    body['items'][0][name] = dict(value=value, knowledge='known', evidence_ids=['e1'], reason=None)
                    self.assertEqual(self.citizen.parse_output(encoded(body), self.document), body)
            for value in (True, 0, {}, ['중복', '중복'], [''], [1], ['원문', None]):
                body = copy.deepcopy(self.output)
                body['items'][0][name] = dict(value=value, knowledge='known', evidence_ids=['e1'], reason=None)
                self.invalid(body)

    def test_categories_reject_empty_duplicates_legacy_and_nonambiguous_unknown(self):
        for value in ([], ['education', 'education'], ['construction'], ['unknown'], 'education', [1], {}):
            body = copy.deepcopy(self.output); body['items'][0]['categories']['value'] = value
            self.invalid(body)
        for knowledge in ('not_stated', 'not_applicable', 'known'):
            body = copy.deepcopy(self.output)
            body['items'][0]['categories'].update(value=None, knowledge=knowledge, reason='분류 미상')
            self.invalid(body)
        body = copy.deepcopy(self.output)
        body['items'][0]['categories']['value'] = list(CATEGORIES)
        self.assertEqual(self.citizen.parse_output(encoded(body), self.document), body)

    def test_field_values_require_knowledge_reason_and_existing_evidence(self):
        for name in ('title', 'categories', *FACTS):
            for change in (dict(evidence_ids=[]), dict(knowledge='missing'), dict(value=None),
                           dict(reason=' '), dict(evidence_ids=['e1', 'e1'])):
                body = copy.deepcopy(self.output)
                body['items'][0][name] = dict(value='원문', knowledge='known', evidence_ids=['e1'], reason=None)
                if name == 'categories': body['items'][0][name]['value'] = ['education']
                body['items'][0][name].update(change)
                self.invalid(body)
            body = copy.deepcopy(self.output); body['items'][0][name]['evidence_ids'] = ['missing']
            self.invalid(body, 'review')
            for change in (dict(value='추정', knowledge='ambiguous', reason='미상'),
                           dict(value=None, knowledge='ambiguous', reason=None)):
                body = copy.deepcopy(self.output); body['items'][0][name].update(change)
                self.invalid(body)
        body = copy.deepcopy(self.output); body['items'][0]['title']['value'] = []
        self.invalid(body)

    def test_missing_extra_keys_and_duplicate_item_evidence_ids_are_rejected(self):
        for keys in ((), ('items', 0), ('items', 0, 'title'), ('items', 0, 'cost'), ('evidence', 0)):
            for extra in (True, False):
                body = copy.deepcopy(self.output); node = body
                for key in keys: node = node[key]
                if extra: node['PRIVATE_VALUE'] = '미지원'
                else: del node[next(iter(node))]
                self.invalid(body)
        body = copy.deepcopy(self.output); body['items'].append(copy.deepcopy(body['items'][0])); self.invalid(body)
        body = copy.deepcopy(self.output); body['evidence'].append(copy.deepcopy(body['evidence'][0])); self.invalid(body)

    def test_evidence_binds_exact_unicode_codepoints_blocks_and_hashes(self):
        document = copy.deepcopy(self.document)
        document['blocks'].append(dict(block_id='unicode', page=2, text='가😀나'))
        body = copy.deepcopy(self.output)
        body['evidence'].append(dict(evidence_id='unicode-e', block_id='unicode', quote='😀', start_char=1,
                                     end_char=2, text_sha256=hashlib.sha256('가😀나'.encode()).hexdigest()))
        body['items'][0]['title']['evidence_ids'] = ['unicode-e']
        self.assertEqual(self.citizen.parse_output(encoded(body), document), body)
        for change in (dict(end_char=3), dict(quote='PRIVATE_VALUE'), dict(block_id='missing'),
                       dict(text_sha256='0' * 64)):
            changed = copy.deepcopy(body); changed['evidence'][-1].update(change)
            self.invalid(changed, 'review', document=document)
        body['evidence'][-1]['start_char'] = True
        self.invalid(body, document=document)

    def test_family_and_document_mismatches_are_rejected(self):
        legacy = (ROOT / 'contracts/examples/ai-extraction.json').read_bytes()
        self.invalid(legacy, path='$.schema_version')
        with self.assertRaises(ExtractionError): parse_legacy(self.output_bytes, self.document)
        for schema in ('extract-schema-v1', 'extract-citizen-v2'):
            body = copy.deepcopy(self.output); body['schema_version'] = schema
            self.invalid(body, path='$.schema_version')
        body = copy.deepcopy(self.output); body['document_version_id'] = '00000000-0000-4000-8000-000000000001'
        self.invalid(body, 'review', '$.document_version_id')

    def test_empty_events_need_no_event_warning(self):
        self.output['items'] = []; self.output['warnings'] = []
        self.invalid(self.output, path='$.warnings')
        self.output['warnings'] = ['NO_EVENT_FOUND']
        self.assertEqual(self.citizen.parse_output(encoded(self.output), self.document), self.output)

    def test_wire_limits_duplicates_bad_unicode_and_depth_use_shared_guards(self):
        for raw in (b'\xff', b'{} {}', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}',
                    b'"\\ud800"', b'[' * 110 + b'0' + b']' * 110):
            self.invalid(raw)
        self.assertEqual(self.invalid(b' ' * (MAX_BYTES + 1)).code, 'JSON_LIMIT')

    def test_generated_schema_is_closed_matches_parser_and_public_artifact(self):
        schema = self.citizen.output_schema()
        self.assertEqual(json.loads((ROOT / 'contracts/schemas/extract-citizen-v1.json').read_bytes()), schema)
        self.assertEqual(schema['properties']['schema_version']['const'], 'extract-citizen-v1')
        self.assertEqual(schema['$schema'], 'https://json-schema.org/draft/2020-12/schema')
        self.assertFalse(schema['additionalProperties'])
        item = schema['properties']['items']['items']
        self.assertEqual(set(item['required']), {'local_item_id', 'title', 'categories', *FACTS})
        self.assertFalse(item['additionalProperties'])
        self.assertEqual(item['properties']['categories']['properties']['value']['anyOf'][0]['items']['enum'], list(CATEGORIES))
        for name in FACTS:
            choices = item['properties'][name]['properties']['value']['anyOf']
            self.assertEqual([entry['type'] for entry in choices], ['string', 'array', 'null'])
            self.assertTrue(choices[1]['uniqueItems'])

    def test_prompt_is_deterministic_binds_source_hashes_and_has_no_user_provider_inputs(self):
        before = copy.deepcopy(self.document)
        raw = self.citizen.render_prompt(self.document)
        self.assertEqual(raw, self.citizen.render_prompt(copy.deepcopy(self.document)))
        self.assertEqual(self.document, before)
        prompt = json.loads(raw)
        self.assertEqual(set(prompt), {'prompt_version', 'instructions', 'schema', 'source', 'block_metadata'})
        self.assertEqual(prompt['prompt_version'], 'citizen-prompt-v1')
        self.assertEqual(prompt['source'], {key: self.document[key] for key in ('document_version_id', 'title', 'published_date', 'blocks')})
        self.assertEqual(prompt['schema']['properties']['document_version_id']['const'], self.document['document_version_id'])
        self.assertEqual(prompt['block_metadata'], {b['block_id']: dict(text_sha256=hashlib.sha256(b['text'].encode()).hexdigest(), length=len(b['text'])) for b in self.document['blocks']})
        properties = prompt['schema']['properties']['evidence']['items']['properties']
        self.assertEqual(properties['block_id']['enum'], [b['block_id'] for b in self.document['blocks']])
        self.assertEqual(set(properties['text_sha256']['enum']), {v['text_sha256'] for v in prompt['block_metadata'].values()})
        self.assertIn('자료', prompt['instructions']); self.assertIn('명령', prompt['instructions'])
        self.assertIn('무료', prompt['instructions']); self.assertIn('거주', prompt['instructions'])
        changed = copy.deepcopy(self.document); changed['data_kind'] = 'real'
        self.assertEqual(raw, self.citizen.render_prompt(changed))


if __name__ == '__main__':
    unittest.main()
