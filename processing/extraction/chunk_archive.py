"""분할 HTTP 원출력과 문서 전체 파생 cycle을 함께 보관·재계산한다."""
import hashlib

from . import api, archive
from .chunks import (REQUEST_LIMIT_BYTES, assemble_outputs, chunk_document,
                     plan_chunks)
from .metadata import parse_metadata, stamp
from .prompt import API_PROMPT_VERSION
from .schema import HASH
from .validation import ExtractionError, decode, parse_input, shape, text

FORMAT = 'extraction-archive-v2'


def _not_attempted(chunk, code):
    return dict(chunk_id=chunk['chunk_id'], attempted=False, status='not_attempted', error_code=code,
                error_path=None, failure_kind='review', retryable=False)


def _cycle(directory, document, plan, number, previous, *, key=None, artifacts=None):
    executing = artifacts is None
    names, chunks, outputs, usages, exchanges, requests = set(), [], [], [], [], []
    previous = {item['chunk_id']: item for item in previous}

    def saved(name, expected=None):
        names.add(name)
        if executing:
            archive._write(directory / name, expected)
            return expected
        archive._archive_check(name in artifacts)
        content = archive._read_checked(directory / name, artifacts[name])
        if expected is not None:
            archive._archive_check(content == expected)
        return content

    aborted = False
    for chunk in plan['chunks']:
        feedback = None
        if plan['status'] != 'ready':
            item = _not_attempted(chunk, 'CHUNK_REQUEST_LIMIT')
        elif aborted:
            item = _not_attempted(chunk, 'CHUNK_NOT_ATTEMPTED')
        else:
            before = previous.get(chunk['chunk_id'])
            feedback = before['error_path'] if before and before['failure_kind'] == 'schema' else None
            partial = chunk_document(document, chunk)
            request = api.request_bytes(partial, plan['model'], feedback, 'prompt-v3', chunk)
            if len(request) > plan['request_limit_bytes']:
                item = _not_attempted(chunk, 'CHUNK_REQUEST_LIMIT')
                feedback = None
                aborted = True
            else:
                prefix = f"attempt-{number}-{chunk['chunk_id']}"
                saved(prefix + '.prompt', request)
                if executing:
                    started = api._now()
                    status, response, error, complete = api._exchange(request, key)
                    exchange = dict(http_status=status, transport_error=error, response_complete=complete,
                                    started_at=started, finished_at=api._now())
                    saved(prefix + '.response', response)
                    saved(prefix + '.exchange', archive._json(exchange))
                else:
                    response = saved(prefix + '.response')
                    exchange = decode(saved(prefix + '.exchange'), 'archive')
                output, result, usage = api.check_api_attempt(request, response, exchange, partial, plan['model'],
                                                             feedback, 'prompt-v3', chunk)
                saved(prefix + '.output', output)
                item = dict(chunk_id=chunk['chunk_id'], attempted=True, **result)
                outputs.append((prefix + '.output', dict(sha256=hashlib.sha256(output).hexdigest(), size=len(output)))
                               if result['status'] == 'validated' else None)
                usages.append(usage); exchanges.append(exchange)
                if result['status'] == 'failed' and not result['retryable']:
                    aborted = True
        chunks.append(item)
        requests.append(dict(chunk_id=chunk['chunk_id'], attempted=item['attempted'], error_path=feedback))
    manifest = dict(schema_version='chunk-cycle-v1', cycle=number,
                    chunk_plan_sha256=hashlib.sha256(archive._json(plan)).hexdigest(), requests=requests)
    saved(f'attempt-{number}.prompt', archive._json(manifest))
    failures = [item for item in chunks if item['status'] != 'validated'
                and item['error_code'] != 'CHUNK_NOT_ATTEMPTED']
    output = b''
    if failures:
        first = next((item for item in failures if not item['retryable']), failures[0])
        result = {field: first[field] for field in ('status', 'error_code', 'error_path', 'failure_kind', 'retryable')}
        result['status'] = 'failed'
    else:
        try:
            values = (decode(archive._read_checked(directory / name, fingerprint), 'archive')
                      for name, fingerprint in outputs)
            output = archive._json(assemble_outputs(document, plan, values))
            result = dict(status='validated', error_code=None, error_path=None, failure_kind=None, retryable=False)
        except ExtractionError as error:
            output = b''
            result = api._failure(error.code, error.retryable, error.kind, error.path)
    saved(f'attempt-{number}.output', output)
    return dict(attempt=number, **result, chunks=chunks), names, usages, exchanges


def run_chunked(directory, content, document, preprocessing_version, model, key):
    started = api._now()
    plan = plan_chunks(document, model, hashlib.sha256(content).hexdigest())
    archive._write(directory / 'chunk-plan.json', archive._json(plan))
    names = {'input.json', 'metadata.json', 'chunk-plan.json'}
    attempts, usages, exchanges = [], [], []
    for number in range(1, 4):
        previous = attempts[-1]['chunks'] if attempts else []
        attempt, files, measured, wire = _cycle(directory, document, plan, number, previous, key=key)
        attempts.append(attempt); names.update(files); usages.extend(measured); exchanges.extend(wire)
        if not attempt['retryable']:
            break
        if number < 3:
            api.time.sleep(number)
    usage_in, usage_out = api.usage_totals(usages) if usages else (0, 0)
    metadata = dict(run_id=directory.name, document_version_id=document['document_version_id'], execution_mode='api',
                    attempts=len(attempts), provider='openai', model_label=model, model_version=None,
                    unavailable_reasons=dict(model_version='공급자의 상세 모델 버전을 확인하지 못함'),
                    prompt_version='prompt-v3', schema_version='extract-schema-v1', preprocessing_version=preprocessing_version,
                    started_at=exchanges[0]['started_at'] if exchanges else started,
                    finished_at=exchanges[-1]['finished_at'] if exchanges else api._now(),
                    usage_in=usage_in, usage_out=usage_out, cost=None, currency=None)
    archive._write(directory / 'metadata.json', archive._json(metadata))
    fingerprints = {name: archive._fingerprint(directory / name) for name in names}
    identity = archive._identity(directory, dict(format_version=FORMAT, run_id=directory.name,
        document_version_id=document['document_version_id'], data_kind=document['data_kind'],
        attempt_count=len(attempts), artifacts=fingerprints))
    receipt = verify_receipt(directory, identity)
    archive._write(directory / 'receipt.json', archive._json(receipt))
    return archive.verify_run(directory.name, directory.parent)


def verify_receipt(directory, identity):
    shape(identity, 'format_version run_id document_version_id data_kind attempt_count artifacts recorded_at', kind='archive')
    archive._archive_check(identity['format_version'] == FORMAT and identity['run_id'] == directory.name)
    count, artifacts = identity['attempt_count'], identity['artifacts']
    archive._archive_check(type(count) is int and 1 <= count <= 3)
    archive._archive_check(type(artifacts) is dict and {'input.json', 'metadata.json', 'chunk-plan.json'} <= set(artifacts))
    for value in artifacts.values():
        shape(value, 'sha256 size', kind='archive'); text(value['sha256'], kind='archive', pattern=HASH)
        archive._archive_check(type(value['size']) is int and value['size'] >= 0)
    content = archive._read_checked(directory / 'input.json', artifacts['input.json'])
    document = parse_input(content)
    metadata = parse_metadata(archive._read_checked(directory / 'metadata.json', artifacts['metadata.json']), document, count)
    archive._archive_check(metadata['run_id'] == identity['run_id']
                           and document['document_version_id'] == identity['document_version_id']
                           and document['data_kind'] == identity['data_kind'])
    archive._archive_check(metadata['execution_mode'] == 'api' and metadata['prompt_version'] == 'prompt-v3'
                           and metadata['provider'] == 'openai' and metadata['model_version'] is None
                           and metadata['cost'] is None and metadata['currency'] is None)
    archive._archive_check(len(api.request_bytes(document, metadata['model_label'], None, API_PROMPT_VERSION)) > REQUEST_LIMIT_BYTES)
    plan = plan_chunks(document, metadata['model_label'], hashlib.sha256(content).hexdigest())
    plan_bytes = archive._json(plan)
    expected_plan = dict(sha256=hashlib.sha256(plan_bytes).hexdigest(), size=len(plan_bytes))
    archive._archive_check(archive._fingerprint(directory / 'chunk-plan.json')
                           == artifacts['chunk-plan.json'] == expected_plan)
    names, attempts, usages, exchanges = {'input.json', 'metadata.json', 'chunk-plan.json'}, [], [], []
    for number in range(1, count + 1):
        archive._archive_check(not attempts or attempts[-1]['retryable'])
        previous = attempts[-1]['chunks'] if attempts else []
        attempt, files, measured, wire = _cycle(directory, document, plan, number, previous, artifacts=artifacts)
        attempts.append(attempt); names.update(files); usages.extend(measured); exchanges.extend(wire)
    archive._archive_check(set(artifacts) == names and (not attempts[-1]['retryable'] or count == 3))
    actual = {path.name for path in directory.iterdir()}
    required = names | {'identity.json'}
    archive._archive_check(required <= actual <= required | {'receipt.json'})
    for previous, following in zip(exchanges, exchanges[1:]):
        archive._archive_check(stamp(previous['finished_at'], '$') <= stamp(following['started_at'], '$'))
    usage = api.usage_totals(usages) if usages else (0, 0)
    archive._archive_check((metadata['usage_in'], metadata['usage_out']) == usage)
    archive._archive_check(metadata['started_at'] is not None and metadata['finished_at'] is not None
                           and stamp(metadata['finished_at'], '$') <= stamp(identity['recorded_at'], '$'))
    if exchanges:
        archive._archive_check(metadata['started_at'] == exchanges[0]['started_at']
                               and metadata['finished_at'] == exchanges[-1]['finished_at'])
    return dict(format_version=FORMAT, run_id=identity['run_id'], document_version_id=document['document_version_id'],
                data_kind=document['data_kind'], execution_mode='api', recorded_at=identity['recorded_at'],
                status=attempts[-1]['status'], review_required=True, input_sha256=artifacts['input.json']['sha256'],
                metadata_sha256=artifacts['metadata.json']['sha256'], artifacts=artifacts, attempts=attempts,
                chunk_plan_sha256=hashlib.sha256(plan_bytes).hexdigest(), total_calls=len(exchanges))
