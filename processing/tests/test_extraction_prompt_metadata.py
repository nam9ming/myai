import copy
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from processing.extraction.metadata import parse_metadata
from processing.extraction.prompt import render_prompt
from processing.extraction.validation import ExtractionError, parse_input

ROOT = Path(__file__).resolve().parents[2]


def metadata():
    return dict(run_id='71fb66f0-e610-4f9c-8f26-4bb77655ee8c',
                document_version_id='e9dc7495-7186-5318-a054-4fc54e9b78cc',
                execution_mode='manual_import', attempts=1, provider='synthetic-fixture',
                model_label=None, model_version=None,
                unavailable_reasons=dict(model_label='실제 모델 호출 없음', model_version='실제 모델 호출 없음'),
                prompt_version='prompt-v1', schema_version='extract-schema-v1', preprocessing_version='fixture-nfc-v1',
                started_at=None, finished_at=None, usage_in=None, usage_out=None, cost=None, currency=None)


class PromptMetadataTest(unittest.TestCase):
    def setUp(self):
        self.document = parse_input((ROOT / 'contracts/examples/ai-input.json').read_bytes())

    def test_prompt_is_deterministic_bound_and_contains_only_source_fields(self):
        prompt = render_prompt(self.document)
        self.assertEqual(prompt, render_prompt(copy.deepcopy(self.document)))
        content = json.loads(prompt)
        self.assertEqual(set(content), {'prompt_version', 'instructions', 'schema', 'source'})
        self.assertEqual(content['prompt_version'], 'prompt-v1')
        self.assertEqual(content['source'], {k: v for k, v in self.document.items() if k != 'data_kind'})
        self.assertNotIn('data_kind', prompt.decode())
        self.assertIn('명령', content['instructions'])
        self.assertIn('NO_EVENT_FOUND', content['instructions'])
        schema = content['schema']
        self.assertEqual(schema['properties']['document_version_id']['const'], self.document['document_version_id'])
        ev = schema['properties']['evidence']['items']['properties']
        self.assertEqual(ev['block_id']['enum'], ['b1'])
        self.assertEqual(ev['text_sha256']['enum'], [hashlib.sha256(self.document['blocks'][0]['text'].encode()).hexdigest()])
        changed = copy.deepcopy(self.document); changed['data_kind'] = 'real'
        self.assertEqual(prompt, render_prompt(changed))

    def test_v1_bytes_remain_fixed_when_api_prompt_changes(self):
        self.assertEqual(hashlib.sha256(render_prompt(self.document)).hexdigest(),
                         '93eddcb3554dca8fc9a10091db672946edef1e5742161fd159b3f7bb311af734')

    def test_v2_binds_each_block_to_hash_and_unicode_length(self):
        doc = copy.deepcopy(self.document)
        doc['blocks'] = [dict(block_id='b1', page=None, text='한😀e\u0301\n둘'),
                         dict(block_id='b2', page=1, text='다른 블록')]
        prompt = render_prompt(doc, 'prompt-v2')
        packet = json.loads(prompt)
        self.assertEqual(packet['prompt_version'], 'prompt-v2')
        self.assertEqual(packet['source']['blocks'], doc['blocks'])
        self.assertEqual(packet['block_metadata'], {
            b['block_id']: dict(text_sha256=hashlib.sha256(b['text'].encode()).hexdigest(), length=len(b['text']))
            for b in doc['blocks']})
        self.assertEqual(packet['block_metadata']['b1']['length'], 6)
        self.assertIn('block_metadata', packet['instructions'])
        changed = copy.deepcopy(doc); changed['data_kind'] = 'real'
        self.assertEqual(prompt, render_prompt(changed, 'prompt-v2'))
        self.assertEqual(render_prompt(self.document), render_prompt(self.document, 'prompt-v1'))

    def test_unknown_prompt_version_fails_closed(self):
        with self.assertRaises(ExtractionError):
            render_prompt(self.document, 'prompt-v99')

    def test_null_labels_need_reasons_and_fixture_artifact_matches(self):
        body = metadata()
        parsed = parse_metadata(json.dumps(body).encode(), self.document, 1)
        self.assertEqual(parsed, body)
        self.assertEqual(json.loads((ROOT / 'processing/examples/extraction-metadata.json').read_text()), body)
        for key in ('provider', 'model_label', 'model_version'):
            broken = copy.deepcopy(body); broken[key] = None; broken['unavailable_reasons'].pop(key, None)
            with self.subTest(key=key), self.assertRaises(ExtractionError):
                parse_metadata(json.dumps(broken).encode(), self.document, 1)

    def test_metadata_rejects_wrong_binding_attempts_versions_and_private_fields(self):
        mutations = [dict(run_id='bad'), dict(document_version_id='00000000-0000-4000-8000-000000000001'),
                     dict(execution_mode='api'), dict(attempts=True), dict(attempts=1.0), dict(attempts=0),
                     dict(attempts=2), dict(attempts=4), dict(schema_version='other'), dict(prompt_version=' '),
                     dict(preprocessing_version='x' * 101), dict(usage_in=True), dict(usage_out=-1),
                     dict(cost=-0.1), dict(unavailable_reasons={'PRIVATE_VALUE': 'secret'}), dict(PRIVATE_VALUE='secret')]
        for change in mutations:
            body = metadata(); body.update(change)
            with self.subTest(change=list(change)), self.assertRaises(ExtractionError) as caught:
                parse_metadata(json.dumps(body).encode(), self.document, 1)
            self.assertEqual(caught.exception.kind, 'input')
            self.assertNotIn('PRIVATE_VALUE', str(caught.exception))

    def test_nanosecond_order_and_cost_precision_remain_exact(self):
        body = metadata()
        body.update(started_at='2026-11-03T01:00:00.123456789Z', finished_at='2026-11-03T01:00:00.123456788Z')
        with self.assertRaises(ExtractionError):
            parse_metadata(json.dumps(body).encode(), self.document, 1)
        body['finished_at'] = body['started_at']
        content = json.dumps(body).replace('"cost": null', '"cost": 0.1234567890123456789').encode()
        self.assertEqual(parse_metadata(content, self.document, 1)['cost'], Decimal('0.1234567890123456789'))
        for stamp in ('2026-02-30T01:00:00Z', '2026-11-03T01:00:00+00:00', '2026-11-03T01:00:00.1234567890Z'):
            body['started_at'] = stamp
            with self.subTest(stamp=stamp), self.assertRaises(ExtractionError):
                parse_metadata(json.dumps(body).encode(), self.document, 1)


if __name__ == '__main__':
    unittest.main()
