"""원문 블록을 자르지 않는 결정적 요청 계획과 부분 출력 결합."""

import copy
import hashlib
import uuid

from .archive import _json
from .prompt import CHUNK_PROMPT_VERSION, instructions, render_prompt
from .schema import HASH, SCHEMA_VERSION
from .validation import parse_output, require, text

REQUEST_LIMIT_BYTES = 131072
FEEDBACK_RESERVE_BYTES = 4096


def chunk_document(document, chunk):
    return {**document, 'blocks': document['blocks'][chunk['context_start']:chunk['core_end']]}


def chunk_request_bytes(document, model, chunk, error_path=None):
    """document는 실제 전송할 context+core 부분집합이다."""
    system = instructions(CHUNK_PROMPT_VERSION)
    if error_path is not None:
        system += '\n직전 구조 오류 경로만 참고하여 같은 원문을 다시 추출한다: ' + error_path
    return _json(dict(model=model, instructions=system,
                      input=render_prompt(document, CHUNK_PROMPT_VERSION, chunk).decode('utf-8'),
                      max_output_tokens=8192, store=False))


def plan_chunks(document, model, input_sha256, *, request_limit=REQUEST_LIMIT_BYTES):
    text(model, '$.model', 'input')
    text(input_sha256, '$.input_sha256', 'input', HASH)
    require(type(request_limit) is int and request_limit > 0, kind='input', code='CHUNK_REQUEST_LIMIT')
    blocks, chunks = document['blocks'], []
    budget, start, oversized = request_limit - FEEDBACK_RESERVE_BYTES, 0, False
    while start < len(blocks):
        context_start = max(0, start - 1)

        def measure(end):
            chunk = dict(chunk_id=f'chunk-{len(chunks) + 1:06d}', core_start=start, core_end=end,
                         context_start=context_start, core_block_ids=[b['block_id'] for b in blocks[start:end]],
                         context_block_ids=[b['block_id'] for b in blocks[context_start:start]])
            request = chunk_request_bytes(chunk_document(document, chunk), model, chunk)
            return dict(**chunk, request_sha256=hashlib.sha256(request).hexdigest(), request_bytes=len(request))

        best = measure(start + 1)
        if best['request_bytes'] > budget:
            oversized = True
        else:
            step, upper = 1, None
            # 남은 전체 문서를 매번 직렬화하지 않고 이번 core 근방만 탐색한다.
            while best['core_end'] < len(blocks):
                end = min(len(blocks), start + step * 2)
                candidate = measure(end)
                if candidate['request_bytes'] > budget:
                    upper = end
                    break
                best, step = candidate, step * 2
            if upper is not None:
                lo, hi = best['core_end'] + 1, upper - 1
                while lo <= hi:
                    middle = (lo + hi) // 2
                    candidate = measure(middle)
                    if candidate['request_bytes'] <= budget:
                        best, lo = candidate, middle + 1
                    else:
                        hi = middle - 1
        chunks.append(best)
        start = best['core_end']
    return dict(schema_version='extraction-chunk-plan-v1', policy_version='request-bytes-v1',
                input_sha256=input_sha256, model=model, prompt_version=CHUNK_PROMPT_VERSION,
                request_limit_bytes=request_limit, feedback_reserve_bytes=FEEDBACK_RESERVE_BYTES, overlap_blocks=1,
                status='requires_review' if oversized else 'ready',
                error_code='CHUNK_REQUEST_LIMIT' if oversized else None, chunks=chunks)


def validate_chunk_output(content, document):
    result = parse_output(content, document)
    require('CHUNK_CONTEXT_PARTIAL' in result['warnings'], '$.warnings', code='CHUNK_CONTEXT_PARTIAL_REQUIRED')

    def partial(value, path):
        if type(value) is dict:
            require(value.get('knowledge') != 'not_stated', path + '.knowledge', 'review', 'CHUNK_NOT_STATED')
            for key, child in value.items():
                partial(child, path + '.' + key)
        elif type(value) is list:
            for index, child in enumerate(value):
                partial(child, f'{path}[{index}]')

    partial(result, '$')
    return result


def assemble_outputs(document, plan, outputs):
    require(plan['status'] == 'ready', kind='review', code='CHUNK_REQUEST_LIMIT')
    require(len(outputs) == len(plan['chunks']), kind='review', code='CHUNK_OUTPUT_INCOMPLETE')
    result = dict(schema_version=SCHEMA_VERSION, document_version_id=document['document_version_id'],
                  items=[], evidence=[], warnings=[])
    namespace = uuid.UUID(document['document_version_id'])
    for chunk, output in zip(plan['chunks'], outputs):
        def identifier(kind, local_id):
            return str(uuid.uuid5(namespace, _json([chunk['chunk_id'], kind, local_id]).decode('utf-8')))

        evidence_ids = {entry['evidence_id']: identifier('evidence', entry['evidence_id'])
                        for entry in output['evidence']}

        def references(value):
            if type(value) is dict:
                for key, child in value.items():
                    if key == 'evidence_ids':
                        value[key] = [evidence_ids[ref] for ref in child]
                    else:
                        references(child)
            elif type(value) is list:
                for child in value:
                    references(child)

        for source in output['items']:
            item = copy.deepcopy(source)
            references(item)
            item['local_item_id'] = identifier('item', source['local_item_id'])
            locations = {entry['local_location_id']: identifier('location', entry['local_location_id'])
                         for entry in source['locations']}
            for location in item['locations']:
                location['local_location_id'] = locations[location['local_location_id']]
            for occurrence in item['occurrences']:
                occurrence['local_occurrence_id'] = identifier('occurrence', occurrence['local_occurrence_id'])
                occurrence['location_refs'] = [locations[ref] for ref in occurrence['location_refs']]
            result['items'].append(item)
        result['evidence'].extend(dict(entry, evidence_id=evidence_ids[entry['evidence_id']])
                                  for entry in output['evidence'])
        result['warnings'].extend(output['warnings'])
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    if result['items']:
        result['warnings'] = [warning for warning in result['warnings'] if warning != 'NO_EVENT_FOUND']
    if 'CHUNK_RELATIONS_REQUIRE_REVIEW' not in result['warnings']:
        result['warnings'].append('CHUNK_RELATIONS_REQUIRE_REVIEW')
    return parse_output(_json(result), document)
