"""고정 OpenAI 주소의 개발용 추출. 인증정보는 전송 헤더에서만 사용한다."""

from datetime import datetime, timezone
import hashlib
import os
import subprocess
import sys
import time
import uuid

from . import archive
from .metadata import stamp
from .prompt import API_PROMPT_VERSION, instructions, render_prompt
from .schema import SCHEMA_VERSION, UUID
from .validation import MAX_BYTES, ExtractionError, decode, parse_input, parse_output, require, shape, text

REQUEST_TIMEOUT = 120
DEFAULT_MODEL = 'gpt-6.1-sol'


def request_bytes(document, model, error_path=None, prompt_version=API_PROMPT_VERSION, chunk=None):
    if prompt_version == 'prompt-v3':
        from .chunks import chunk_request_bytes
        return chunk_request_bytes(document, model, chunk, error_path)
    system = instructions(prompt_version)
    if error_path is not None:
        system += '\n직전 구조 오류 경로만 참고하여 같은 원문을 다시 추출한다: ' + error_path
    return archive._json(dict(model=model, instructions=system,
                              input=render_prompt(document, prompt_version).decode('utf-8'),
                              max_output_tokens=8192, store=False))


def _exchange(request, key):
    environment = os.environ.copy()
    environment['OPENAI_API_KEY'] = key
    process, expired, output = None, False, b''
    try:
        process = subprocess.Popen([sys.executable, '-m', 'processing.extraction.transport'], cwd=archive.REPO,
                                   env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            output, _ = process.communicate(request, timeout=REQUEST_TIMEOUT)
        except subprocess.TimeoutExpired:
            expired = True
            process.kill()
            try:
                output, _ = process.communicate(timeout=1)
            except subprocess.TimeoutExpired as error:
                output = error.output or b''
        line, separator, body = output.partition(b'\n')
        status = int(line) if separator and line.isdigit() else None
        if status is None or not 100 <= status <= 599 or len(body) > MAX_BYTES + 1:
            return None, b'', 'API_TIMEOUT' if expired else 'API_TRANSPORT_ERROR', False
        error = ('API_TIMEOUT' if expired or process.returncode == 2 else
                 'API_RESPONSE_LIMIT' if process.returncode == 4 else
                 'API_TRANSPORT_ERROR' if process.returncode != 0 else None)
        return status, body, error, error is None
    except OSError:
        return None, b'', 'API_TRANSPORT_ERROR', False
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            for stream in (process.stdin, process.stdout):
                stream.close()


def _failure(code, retryable, kind='transport', path=None):
    return dict(status='failed', error_code=code, error_path=path, failure_kind=kind, retryable=retryable)


def check_api_attempt(request, response, exchange, document, model, error_path=None, prompt_version=API_PROMPT_VERSION,
                      chunk=None):
    archive._archive_check(request == request_bytes(document, model, error_path, prompt_version, chunk))
    shape(exchange, 'http_status transport_error response_complete started_at finished_at', kind='archive')
    archive._archive_check(stamp(exchange['started_at'], '$.started_at') <= stamp(exchange['finished_at'], '$.finished_at'))
    status, error, complete = [exchange[k] for k in ('http_status', 'transport_error', 'response_complete')]
    archive._archive_check(status is None or type(status) is int and 100 <= status <= 599)
    archive._archive_check(error in (None, 'API_TIMEOUT', 'API_TRANSPORT_ERROR', 'API_RESPONSE_LIMIT'))
    archive._archive_check(type(complete) is bool and len(response) <= MAX_BYTES + 1)
    archive._archive_check((complete and error is None and status is not None and len(response) <= MAX_BYTES)
                           or (not complete and error is not None))
    archive._archive_check(status is not None or response == b'')
    archive._archive_check(error != 'API_RESPONSE_LIMIT' or len(response) == MAX_BYTES + 1)
    usage = (None, None)
    if status is not None and status != 200 and status not in (408, 429) and status < 500:
        return b'', _failure(f'API_HTTP_{status}', False), usage
    if error is not None:
        return b'', _failure(error, error != 'API_RESPONSE_LIMIT'), usage
    if status != 200:
        return b'', _failure(f'API_HTTP_{status}', status in (408, 429) or status >= 500), usage
    try:
        packet = decode(response, 'schema')
    except ExtractionError:
        return b'', _failure('API_RESPONSE_INVALID', True), usage
    if type(packet) is not dict:
        return b'', _failure('API_RESPONSE_INVALID', True), usage
    measured = packet.get('usage')
    if type(measured) is dict:
        usage = tuple(v if type(v) is int and v >= 0 else None for v in
                      (measured.get('input_tokens'), measured.get('output_tokens')))
    if packet.get('status') != 'completed':
        details = packet.get('incomplete_details')
        if type(details) is dict and details.get('reason') == 'content_filter':
            return b'', _failure('API_REFUSAL', False, 'review'), usage
        return b'', _failure('API_RESPONSE_INCOMPLETE', True), usage
    if (packet.get('object') != 'response' or packet.get('error') is not None
            or type(packet.get('model')) is not str or not packet['model'].strip()
            or type(packet.get('output')) is not list):
        return b'', _failure('API_RESPONSE_INVALID', True), usage
    parts = []
    for item in packet['output']:
        if type(item) is not dict or item.get('type') not in ('message', 'reasoning'):
            return b'', _failure('API_RESPONSE_INVALID', True), usage
        if item['type'] == 'reasoning':
            continue
        if item.get('role') != 'assistant' or item.get('status') != 'completed' or type(item.get('content')) is not list:
            return b'', _failure('API_RESPONSE_INVALID', True), usage
        for part in item['content']:
            if type(part) is dict and part.get('type') == 'refusal':
                return b'', _failure('API_REFUSAL', False, 'review'), usage
            if type(part) is not dict or part.get('type') != 'output_text' or type(part.get('text')) is not str:
                return b'', _failure('API_RESPONSE_INVALID', True), usage
            parts.append(part['text'])
    if not parts:
        return b'', _failure('API_RESPONSE_INVALID', True), usage
    # decode가 모든 문자열의 UTF-8 표현 가능 여부를 이미 검사했다.
    output = '\n'.join(parts).encode('utf-8')
    try:
        if prompt_version == 'prompt-v3':
            from .chunks import validate_chunk_output
            validate_chunk_output(output, document)
        else:
            parse_output(output, document)
        result = dict(status='validated', error_code=None, error_path=None, failure_kind=None, retryable=False)
    except ExtractionError as failure:
        result = _failure(failure.code, failure.retryable, failure.kind, failure.path)
    return output, result, usage


def usage_totals(usages):
    return tuple(sum(values) if None not in values else None for values in zip(*usages, strict=True))


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def run_api(input_path, preprocessing_version, root=archive.DEFAULT_ROOT, run_id=None, model=None):
    content = archive._read(input_path)
    document = parse_input(content)
    model = model if model is not None else os.environ.get('OPENAI_MODEL', DEFAULT_MODEL)
    for value in (preprocessing_version, model):
        text(value, kind='input')
        require(len(value) <= 100, kind='input')
    run_id = run_id if run_id is not None else str(uuid.uuid4())
    text(run_id, '$.run_id', 'input', UUID)
    base = archive._root(root, create=False)
    directory = base / run_id

    def reuse():
        receipt = archive.verify_run(run_id, base)
        metadata = decode(archive._read(directory / 'metadata.json'), 'archive')
        archive._archive_check(receipt['execution_mode'] == 'api'
                               and receipt['input_sha256'] == hashlib.sha256(content).hexdigest()
                               and metadata['preprocessing_version'] == preprocessing_version
                               and metadata['model_label'] == model, 'ARCHIVE_CONFLICT')
        return receipt

    if directory.exists() or directory.is_symlink():
        return reuse()
    key = os.environ.get('OPENAI_API_KEY')
    require(bool(key), kind='input', code='OPENAI_API_KEY_MISSING')
    require(all(33 <= ord(c) <= 126 for c in key), kind='input', code='OPENAI_API_KEY_INVALID')
    archive._root(base)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return reuse()
    archive._write(directory / 'input.json', content)
    from .chunks import REQUEST_LIMIT_BYTES
    if len(request_bytes(document, model, None, API_PROMPT_VERSION)) > REQUEST_LIMIT_BYTES:
        from .chunk_archive import run_chunked
        return run_chunked(directory, content, document, preprocessing_version, model, key)
    pairs, api_artifacts, exchanges, usages = [], [], [], []
    previous = None
    for number in range(1, 4):
        feedback = previous['error_path'] if previous and previous['failure_kind'] == 'schema' else None
        request = request_bytes(document, model, feedback, API_PROMPT_VERSION)
        prompt = directory / f'attempt-{number}.prompt'
        archive._write(prompt, request)
        started = _now()
        status, response, error, complete = _exchange(request, key)
        exchange = dict(http_status=status, transport_error=error, response_complete=complete,
                        started_at=started, finished_at=_now())
        raw, info = directory / f'attempt-{number}.response', directory / f'attempt-{number}.exchange'
        archive._write(raw, response)
        archive._write(info, archive._json(exchange))
        output, previous, usage = check_api_attempt(request, response, exchange, document, model, feedback,
                                                   API_PROMPT_VERSION)
        target = directory / f'attempt-{number}.output'
        archive._write(target, output)
        pairs.append((prompt, target)); api_artifacts.append((raw, info))
        exchanges.append(exchange); usages.append(usage)
        if not previous['retryable']:
            break
        if number < 3:
            time.sleep(number)
    usage_in, usage_out = usage_totals(usages)
    metadata = dict(run_id=run_id, document_version_id=document['document_version_id'], execution_mode='api',
                    attempts=len(pairs), provider='openai', model_label=model, model_version=None,
                    unavailable_reasons=dict(model_version='공급자의 상세 모델 버전을 확인하지 못함'),
                    prompt_version=API_PROMPT_VERSION, schema_version=SCHEMA_VERSION, preprocessing_version=preprocessing_version,
                    started_at=exchanges[0]['started_at'], finished_at=exchanges[-1]['finished_at'],
                    usage_in=usage_in, usage_out=usage_out, cost=None, currency=None)
    archive._write(directory / 'metadata.json', archive._json(metadata))
    return archive.import_run(directory / 'input.json', directory / 'metadata.json', pairs, base, api_artifacts)
