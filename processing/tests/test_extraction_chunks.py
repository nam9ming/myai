import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from processing.extraction import chunks
from processing.extraction.prompt import render_prompt
from processing.extraction.validation import ExtractionError, parse_input, parse_output

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'synthetic-model'
CORE_KEYS = {'chunk_id', 'core_start', 'core_end', 'context_start', 'core_block_ids', 'context_block_ids'}


def raw(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()


def document(count=4, text=None):
    value = parse_input((ROOT / 'contracts/examples/ai-input.json').read_bytes())
    value['blocks'] = [dict(block_id=f'b{i}', page=i + 1,
                            text=text if text is not None else value['blocks'][0]['text'] + '😀' + '가' * 1500)
                       for i in range(count)]
    return value


def boundary_chunk():
    return dict(chunk_id='chunk-000001', core_start=0, core_end=2, context_start=0,
                core_block_ids=['b0', 'b1'], context_block_ids=[])


def output_for(doc, block, empty=False):
    value = json.loads((ROOT / 'contracts/examples/ai-extraction.json').read_bytes())

    def partial(node):
        if type(node) is dict:
            if node.get('knowledge') == 'not_stated':
                node.update(knowledge='ambiguous', reason='부분 문맥에서 확정 불가')
            for child in node.values():
                partial(child)
        elif type(node) is list:
            for child in node:
                partial(child)

    partial(value)
    value['document_version_id'] = doc['document_version_id']
    value['warnings'] = ['CHUNK_CONTEXT_PARTIAL']
    if empty:
        value.update(items=[], evidence=[], warnings=['CHUNK_CONTEXT_PARTIAL', 'NO_EVENT_FOUND'])
    else:
        value['evidence'][0].update(block_id=block['block_id'], quote=block['text'], start_char=0,
                                     end_char=len(block['text']),
                                     text_sha256=hashlib.sha256(block['text'].encode()).hexdigest())
    return value


class ExtractionChunksTest(unittest.TestCase):
    def setUp(self):
        self.document = document()
        self.input_hash = hashlib.sha256(raw(self.document)).hexdigest()

    def plan(self, doc=None):
        doc = doc or self.document
        candidate = boundary_chunk()
        limit = len(chunks.chunk_request_bytes({**doc, 'blocks': doc['blocks'][:2]}, MODEL, candidate)) + 4096
        return chunks.plan_chunks(doc, MODEL, hashlib.sha256(raw(doc)).hexdigest(), request_limit=limit)

    def test_plan_uses_longest_core_exact_overlap_and_reproducible_wire_hashes(self):
        before = copy.deepcopy(self.document)
        plan = self.plan()
        self.assertEqual(plan, self.plan(copy.deepcopy(self.document)))
        self.assertEqual(set(plan), {'schema_version', 'policy_version', 'input_sha256', 'model', 'prompt_version',
                                     'request_limit_bytes', 'feedback_reserve_bytes', 'overlap_blocks',
                                     'status', 'error_code', 'chunks'})
        self.assertEqual((plan['schema_version'], plan['policy_version'], plan['prompt_version']),
                         ('extraction-chunk-plan-v1', 'request-bytes-v1', 'prompt-v3'))
        self.assertEqual((plan['status'], plan['error_code'], plan['input_sha256']), ('ready', None, self.input_hash))
        self.assertEqual([(c['core_start'], c['core_end'], c['context_start']) for c in plan['chunks']],
                         [(0, 2, 0), (2, 3, 1), (3, 4, 2)])
        coverage = []
        for index, chunk in enumerate(plan['chunks'], 1):
            self.assertEqual(chunk['chunk_id'], f'chunk-{index:06d}')
            self.assertEqual(set(chunk), CORE_KEYS | {'request_sha256', 'request_bytes'})
            subset = chunks.chunk_document(self.document, chunk)
            self.assertEqual(set(subset), set(self.document))
            self.assertEqual(subset['blocks'], self.document['blocks'][chunk['context_start']:chunk['core_end']])
            request = chunks.chunk_request_bytes(subset, MODEL, chunk)
            self.assertEqual(chunk['request_bytes'], len(request))
            self.assertEqual(chunk['request_sha256'], hashlib.sha256(request).hexdigest())
            self.assertLessEqual(len(request), plan['request_limit_bytes'] - 4096)
            coverage.extend(range(chunk['core_start'], chunk['core_end']))
            if chunk['core_end'] < len(self.document['blocks']):
                larger = copy.deepcopy(chunk)
                larger['core_block_ids'].append(self.document['blocks'][larger['core_end']]['block_id'])
                larger['core_end'] += 1
                request = chunks.chunk_request_bytes(chunks.chunk_document(self.document, larger), MODEL, larger)
                self.assertGreater(len(request), plan['request_limit_bytes'] - 4096)
        self.assertEqual(coverage, [0, 1, 2, 3])
        self.assertEqual(self.document, before)

    def test_exact_byte_boundary_and_oversized_block_keep_all_core_coverage(self):
        plan = self.plan()
        smaller = chunks.plan_chunks(self.document, MODEL, self.input_hash,
                                     request_limit=plan['request_limit_bytes'] - 1)
        self.assertEqual(smaller['chunks'][0]['core_end'], 1)
        doc = document(3, '짧은 블록')
        doc['blocks'][0]['text'] = '가😀' * 10000
        oversized = chunks.plan_chunks(doc, MODEL, self.input_hash, request_limit=40000)
        self.assertEqual((oversized['status'], oversized['error_code']), ('requires_review', 'CHUNK_REQUEST_LIMIT'))
        self.assertEqual([(c['core_start'], c['core_end']) for c in oversized['chunks']], [(0, 1), (1, 2), (2, 3)])
        self.assertEqual(oversized['chunks'][0]['core_block_ids'], ['b0'])
        self.assertGreater(oversized['chunks'][0]['request_bytes'], 40000 - 4096)
        self.assertGreater(oversized['chunks'][1]['request_bytes'], 40000 - 4096)
        self.assertLessEqual(oversized['chunks'][2]['request_bytes'], 40000 - 4096)
        self.assertEqual(chunks.chunk_document(doc, oversized['chunks'][0])['blocks'][0], doc['blocks'][0])
        with self.assertRaises(ExtractionError):
            chunks.assemble_outputs(doc, oversized, [])

    def test_many_blocks_do_not_repeatedly_serialize_the_remaining_document(self):
        doc = document(4500, '가😀' * 256)
        self.assertLessEqual(len(raw(doc)), 8 * 1024 * 1024)
        self.assertGreater(len(raw(doc)), 8 * 1024 * 1024 - 200000)
        serialized_blocks = 0
        original = chunks.chunk_request_bytes

        def measured(subset, *args, **kwargs):
            nonlocal serialized_blocks
            serialized_blocks += len(subset['blocks'])
            return original(subset, *args, **kwargs)

        with patch.object(chunks, 'chunk_request_bytes', side_effect=measured):
            plan = chunks.plan_chunks(doc, MODEL, self.input_hash, request_limit=40000)
        self.assertEqual(plan['status'], 'ready')
        self.assertGreater(len(plan['chunks']), 100)
        self.assertLess(serialized_blocks, 12 * len(doc['blocks']))

    def test_prompt_versions_preserve_bytes_and_v3_binds_only_sent_blocks(self):
        original = parse_input((ROOT / 'contracts/examples/ai-input.json').read_bytes())
        expected = {'prompt-v1': '93eddcb3554dca8fc9a10091db672946edef1e5742161fd159b3f7bb311af734',
                    'prompt-v2': '9ccc05c068736e274b280fd94196a57ee455488fc11a79a72b184ff9742f23f4'}
        for version, digest in expected.items():
            self.assertEqual(hashlib.sha256(render_prompt(original, version)).hexdigest(), digest)
        chunk = self.plan()['chunks'][1]
        subset = chunks.chunk_document(self.document, chunk)
        body = chunks.chunk_request_bytes(subset, MODEL, chunk, '$.items')
        packet = json.loads(body)
        self.assertEqual(set(packet), {'model', 'instructions', 'input', 'max_output_tokens', 'store'})
        self.assertEqual((packet['model'], packet['max_output_tokens'], packet['store']), (MODEL, 8192, False))
        self.assertTrue(packet['instructions'].endswith('직전 구조 오류 경로만 참고하여 같은 원문을 다시 추출한다: $.items'))
        prompt = json.loads(packet['input'])
        self.assertEqual(prompt['chunk'], {k: chunk[k] for k in CORE_KEYS})
        self.assertEqual(prompt['source']['blocks'], self.document['blocks'][1:3])
        self.assertEqual(set(prompt['block_metadata']), {'b1', 'b2'})
        self.assertEqual(prompt['block_metadata']['b2']['length'], len(self.document['blocks'][2]['text']))
        self.assertIn('CHUNK_CONTEXT_PARTIAL', prompt['instructions'])
        self.assertEqual(prompt['schema']['properties']['evidence']['items']['properties']['block_id']['enum'], ['b1', 'b2'])
        self.assertEqual(body, raw(packet))

    def test_partial_output_rejects_missing_warning_not_stated_and_unsent_evidence(self):
        subset = chunks.chunk_document(self.document, self.plan()['chunks'][0])
        value = output_for(subset, subset['blocks'][0])
        self.assertEqual(chunks.validate_chunk_output(raw(value), subset), value)
        missing = copy.deepcopy(value); missing['warnings'] = []
        with self.assertRaises(ExtractionError) as caught:
            chunks.validate_chunk_output(raw(missing), subset)
        self.assertEqual((caught.exception.code, caught.exception.kind, caught.exception.retryable),
                         ('CHUNK_CONTEXT_PARTIAL_REQUIRED', 'schema', True))
        for path in [('route_names',), ('occurrences', 0, 'recurrence_text'), ('locations', 0, 'address')]:
            broken = copy.deepcopy(value); node = broken['items'][0]
            for key in path:
                node = node[key]
            node['knowledge'] = 'not_stated'
            with self.subTest(path=path), self.assertRaises(ExtractionError) as caught:
                chunks.validate_chunk_output(raw(broken), subset)
            self.assertEqual((caught.exception.code, caught.exception.kind, caught.exception.retryable),
                             ('CHUNK_NOT_STATED', 'review', False))
        outside = output_for(self.document, self.document['blocks'][3])
        with self.assertRaises(ExtractionError) as caught:
            chunks.validate_chunk_output(raw(outside), subset)
        self.assertEqual(caught.exception.kind, 'review')

    def test_assembly_namespaces_duplicate_ids_without_merging_items_or_occurrences(self):
        plan = self.plan()
        outputs = []
        for chunk in plan['chunks']:
            subset = chunks.chunk_document(self.document, chunk)
            value = output_for(subset, subset['blocks'][-1])
            second = copy.deepcopy(value['items'][0])
            second['local_item_id'] = 'item2'
            second['locations'][0]['local_location_id'] = 'l2'
            second['occurrences'][0].update(local_occurrence_id='o2', location_refs=['l2'])
            value['items'].append(second)
            outputs.append(chunks.validate_chunk_output(raw(value), subset))
        before = copy.deepcopy(outputs)
        result = chunks.assemble_outputs(self.document, plan, outputs)
        self.assertEqual(len(result['items']), 6)
        self.assertEqual(len(result['evidence']), 3)
        for key, values in [('local_item_id', result['items']),
                            ('local_occurrence_id', [o for item in result['items'] for o in item['occurrences']]),
                            ('local_location_id', [l for item in result['items'] for l in item['locations']])]:
            self.assertEqual(len({value[key] for value in values}), 6)
        self.assertEqual(len({e['evidence_id'] for e in result['evidence']}), 3)
        for index, item in enumerate(result['items']):
            self.assertEqual(item['title']['evidence_ids'], [result['evidence'][index // 2]['evidence_id']])
            self.assertEqual(item['occurrences'][0]['location_refs'], [item['locations'][0]['local_location_id']])
        self.assertEqual(result['warnings'], ['CHUNK_CONTEXT_PARTIAL', 'CHUNK_RELATIONS_REQUIRE_REVIEW'])
        self.assertEqual(parse_output(raw(result), self.document), result)
        self.assertEqual(chunks.assemble_outputs(self.document, plan, outputs), result)
        self.assertEqual(outputs, before)

    def test_assembly_preserves_codepoint_offsets_and_no_event_warning_scope(self):
        plan = self.plan()
        outputs = [output_for(self.document, self.document['blocks'][c['core_start']], empty=True)
                   for c in plan['chunks']]
        empty = chunks.assemble_outputs(self.document, plan, outputs)
        self.assertEqual(empty['items'], [])
        self.assertIn('NO_EVENT_FOUND', empty['warnings'])
        block = self.document['blocks'][0]
        outputs[0] = output_for(self.document, block)
        start = block['text'].index('😀')
        outputs[0]['evidence'][0].update(quote='😀', start_char=start, end_char=start + 1)
        result = chunks.assemble_outputs(self.document, plan, outputs)
        self.assertNotIn('NO_EVENT_FOUND', result['warnings'])
        self.assertEqual(result['evidence'][0]['start_char'], start)
        self.assertEqual(result['evidence'][0]['end_char'], start + 1)
        self.assertEqual(result['evidence'][0]['text_sha256'], hashlib.sha256(block['text'].encode()).hexdigest())
        with self.assertRaises(ExtractionError):
            chunks.assemble_outputs(self.document, plan, outputs[:-1])

    def test_assembly_rejects_total_size_when_each_chunk_fits(self):
        plan = self.plan()
        outputs = [output_for(self.document, self.document['blocks'][c['core_end'] - 1])
                   for c in plan['chunks']]
        for chunk, output in zip(plan['chunks'], outputs):
            self.assertLess(len(raw(output)), 12000)
            chunks.validate_chunk_output(raw(output), chunks.chunk_document(self.document, chunk))
        with patch.object(chunks, 'MAX_BYTES', 12000, create=True):
            with self.assertRaises(ExtractionError) as caught:
                chunks.assemble_outputs(self.document, plan, outputs)
        self.assertEqual((caught.exception.code, caught.exception.kind, caught.exception.retryable),
                         ('CHUNK_OUTPUT_LIMIT', 'review', False))

    def test_assembly_stops_before_pulling_next_chunk_after_output_limit(self):
        plan = self.plan()
        pulled = []

        def outputs():
            for index, chunk in enumerate(plan['chunks']):
                pulled.append(index)
                if index == 2:
                    self.fail('결합 예산 초과 뒤 다음 청크를 읽었다')
                value = output_for(self.document, self.document['blocks'][chunk['core_end'] - 1])
                yield chunks.validate_chunk_output(raw(value), chunks.chunk_document(self.document, chunk))

        with patch.object(chunks, 'MAX_BYTES', 12000, create=True):
            with self.assertRaises(ExtractionError) as caught:
                chunks.assemble_outputs(self.document, plan, outputs())
        self.assertEqual((caught.exception.code, caught.exception.kind), ('CHUNK_OUTPUT_LIMIT', 'review'))
        self.assertEqual(pulled, [0, 1])

    def test_assembly_iterator_and_list_preserve_existing_canonical_bytes(self):
        plan = self.plan()
        outputs = [output_for(self.document, self.document['blocks'][c['core_end'] - 1])
                   for c in plan['chunks']]
        expected_hash = '3ab4cf704ffc984bf8ddae8b749fbb3ea27922b0bcd4fb5a4de2ecdfcbdc9b78'
        from_list = raw(chunks.assemble_outputs(self.document, plan, outputs))
        self.assertEqual(hashlib.sha256(from_list).hexdigest(), expected_hash)
        from_iterator = raw(chunks.assemble_outputs(self.document, plan, (value for value in outputs)))
        self.assertEqual(from_iterator, from_list)

    def test_assembly_iterator_rejects_missing_or_extra_chunk_outputs(self):
        plan = self.plan()
        outputs = [output_for(self.document, self.document['blocks'][c['core_end'] - 1])
                   for c in plan['chunks']]
        for values in (outputs[:-1], outputs + [outputs[-1]]):
            with self.subTest(count=len(values)):
                with self.assertRaises(ExtractionError) as caught:
                    chunks.assemble_outputs(self.document, plan, iter(values))
                self.assertEqual((caught.exception.code, caught.exception.kind), ('CHUNK_OUTPUT_INCOMPLETE', 'review'))

    def test_assembly_exact_budget_includes_final_warning_filter_and_order(self):
        plan = self.plan()
        outputs = [output_for(self.document, self.document['blocks'][c['core_end'] - 1], empty=True)
                   for c in plan['chunks']]
        outputs[0]['warnings'].append('앞선 경고😀')
        outputs[1] = output_for(self.document, self.document['blocks'][plan['chunks'][1]['core_end'] - 1])
        outputs[1]['warnings'].extend(['뒤 경고', 'CHUNK_RELATIONS_REQUIRE_REVIEW', '앞선 경고😀'])
        outputs[2]['warnings'].append('마지막 경고')
        expected = chunks.assemble_outputs(self.document, plan, outputs)
        self.assertEqual(expected['warnings'], ['CHUNK_CONTEXT_PARTIAL', '앞선 경고😀', '뒤 경고',
                                                'CHUNK_RELATIONS_REQUIRE_REVIEW', '마지막 경고'])
        limit = len(raw(expected))
        with patch.object(chunks, 'MAX_BYTES', limit, create=True):
            self.assertEqual(chunks.assemble_outputs(self.document, plan, outputs), expected)
        with patch.object(chunks, 'MAX_BYTES', limit - 1, create=True):
            with self.assertRaises(ExtractionError) as caught:
                chunks.assemble_outputs(self.document, plan, outputs)
        self.assertEqual((caught.exception.code, caught.exception.kind), ('CHUNK_OUTPUT_LIMIT', 'review'))


if __name__ == '__main__':
    unittest.main()
