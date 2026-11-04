"""수동 AI 실행의 원본을 배타적으로 기록하고 매번 검증한다."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import errno
import json
import os
from pathlib import Path
import stat
import shutil
import tempfile

from .metadata import parse_metadata, stamp
from .prompt import render_prompt
from .schema import HASH, UUID
from .validation import MAX_BYTES, ExtractionError, decode, parse_input, parse_output, require, shape, text

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = REPO / 'data/private/extraction-runs'
FORMAT = 'extraction-archive-v1'


def _archive_check(condition, code='ARCHIVE_INTEGRITY'):
    require(condition, kind='archive', code=code)


def _directory(path):
    if not path.exists():
        _directory(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
    _archive_check(path.is_dir() and not path.is_symlink())
    return path


def _root(root, create=True):
    path = Path(root).expanduser().absolute()
    require(not path.is_symlink(), kind='input', code='ARCHIVE_ROOT_INVALID')
    resolved = path.resolve()

    def ancestor(value, target):
        if target.exists():
            for parent in (value, *value.parents):
                if parent.exists() and parent.samefile(target):
                    return parent
        return None

    # macOS의 한글 정규화·대소문자 별칭도 같은 저장소 디렉터리로 판정한다.
    repository = ancestor(resolved, REPO)
    if ancestor(path, REPO) is not None:
        require(path == resolved, kind='input', code='ARCHIVE_ROOT_INVALID')
    if repository is not None:
        private = REPO / 'data/private'
        require(private == private.resolve(), kind='input', code='ARCHIVE_ROOT_INVALID')
        inside = ancestor(resolved, private) is not None
        fresh = not private.exists() and resolved.relative_to(repository).parts[:2] == ('data', 'private')
        require(inside or fresh, kind='input', code='ARCHIVE_ROOT_INVALID')
    return _directory(resolved) if create else resolved


@contextmanager
def _open(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        _archive_check(stat.S_ISREG(os.fstat(descriptor).st_mode), 'ARCHIVE_FILE_INVALID')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            yield stream
    finally:
        os.close(descriptor)


def _fingerprint(path):
    digest, size = hashlib.sha256(), 0
    with _open(path) as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk); size += len(chunk)
    return dict(sha256=digest.hexdigest(), size=size)


def _read(path, limit=MAX_BYTES):
    with _open(path) as stream:
        return stream.read(limit + 1)


def _read_checked(path, expected):
    digest, size, content = hashlib.sha256(), 0, bytearray()
    with _open(path) as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk); size += len(chunk)
            content.extend(chunk[:max(0, MAX_BYTES + 1 - len(content))])
    _archive_check(dict(sha256=digest.hexdigest(), size=size) == expected)
    return bytes(content)


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')


def _install(temporary, destination, expected):
    try:
        os.link(temporary, destination)
    except FileExistsError:
        _archive_check(_fingerprint(destination) == expected, 'ARCHIVE_CONFLICT')


def _write(destination, content):
    descriptor, temporary = tempfile.mkstemp(prefix='.', suffix='.tmp', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        _install(temporary, destination, dict(sha256=hashlib.sha256(content).hexdigest(), size=len(content)))
    finally:
        os.unlink(temporary)


def _copy(source, destination, expected):
    descriptor, temporary = tempfile.mkstemp(prefix='.', suffix='.tmp', dir=destination.parent)
    try:
        digest, size = hashlib.sha256(), 0
        with os.fdopen(descriptor, 'wb') as target, _open(source) as origin:
            while chunk := origin.read(64 * 1024):
                target.write(chunk); digest.update(chunk); size += len(chunk)
            target.flush(); os.fsync(target.fileno())
        _archive_check(dict(sha256=digest.hexdigest(), size=size) == expected, 'ARCHIVE_SOURCE_CHANGED')
        _install(temporary, destination, expected)
    finally:
        os.unlink(temporary)


def _identity(directory, identity):
    path = directory / 'identity.json'
    if not path.exists():
        content = _json(dict(**identity, recorded_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')))
        descriptor, temporary = tempfile.mkstemp(prefix='.', suffix='.tmp', dir=directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                pass
        finally:
            os.unlink(temporary)
    stored = decode(_read(path), 'archive')
    _archive_check(type(stored) is dict and set(stored) == set(identity) | {'recorded_at'})
    _archive_check({k: v for k, v in stored.items() if k != 'recorded_at'} == identity, 'ARCHIVE_CONFLICT')
    try:
        stamp(stored['recorded_at'], '$.recorded_at')
    except ExtractionError:
        raise ExtractionError('ARCHIVE_INTEGRITY', kind='archive') from None
    return stored


def prepare(input_path, root=DEFAULT_ROOT):
    content = _read(input_path)
    document = parse_input(content)
    fingerprint = _fingerprint(input_path)
    _archive_check(fingerprint['sha256'] == hashlib.sha256(content).hexdigest(), 'ARCHIVE_SOURCE_CHANGED')
    directory = _directory(_directory(_root(root) / 'prepared') / fingerprint['sha256'])
    prompt = render_prompt(document)
    _write(directory / 'input.json', content)
    _write(directory / 'prompt.json', prompt)
    return dict(status='prepared', document_version_id=document['document_version_id'], data_kind=document['data_kind'],
                input_sha256=fingerprint['sha256'], prompt_sha256=hashlib.sha256(prompt).hexdigest(),
                artifacts=['input.json', 'prompt.json'])


def _receipt(directory, identity):
    if type(identity) is dict and identity.get('format_version') == 'extraction-archive-v2':
        from .chunk_archive import verify_receipt
        return verify_receipt(directory, identity)
    shape(identity, 'format_version run_id document_version_id data_kind attempt_count artifacts recorded_at', kind='archive')
    _archive_check(identity['format_version'] == FORMAT and identity['run_id'] == directory.name)
    count = identity['attempt_count']
    _archive_check(type(count) is int and 1 <= count <= 3)
    artifacts = identity['artifacts']
    _archive_check(type(artifacts) is dict and {'input.json', 'metadata.json'} <= set(artifacts))
    stamp(identity['recorded_at'], '$.recorded_at')
    for expected in artifacts.values():
        shape(expected, 'sha256 size', kind='archive')
        text(expected['sha256'], kind='archive', pattern=HASH)
        _archive_check(type(expected['size']) is int and expected['size'] >= 0)
    contents = {name: _read_checked(directory / name, artifacts[name]) for name in ('input.json', 'metadata.json')}
    document = parse_input(contents['input.json'])
    metadata = parse_metadata(contents['metadata.json'], document, count)
    api = metadata['execution_mode'] == 'api'
    suffixes = ('prompt', 'output', 'response', 'exchange') if api else ('prompt', 'output')
    names = ['input.json', 'metadata.json'] + [f'attempt-{i}.{suffix}' for i in range(1, count + 1) for suffix in suffixes]
    _archive_check(set(artifacts) == set(names))
    for name in names[2:]:
        if name.endswith('.prompt'):
            _archive_check(_fingerprint(directory / name) == artifacts[name])
        else:
            contents[name] = _read_checked(directory / name, artifacts[name])
    _archive_check(metadata['run_id'] == identity['run_id'] and document['document_version_id'] == identity['document_version_id']
                   and document['data_kind'] == identity['data_kind'])
    attempts, exchanges, usages = [], [], []
    for i in range(1, count + 1):
        if api:
            from .api import check_api_attempt, request_bytes
            previous = attempts[-1] if attempts else None
            _archive_check(previous is None or previous['retryable'])
            exchange = decode(contents[f'attempt-{i}.exchange'], 'archive')
            feedback = previous['error_path'] if previous and previous['failure_kind'] == 'schema' else None
            request = request_bytes(document, metadata['model_label'], feedback, metadata['prompt_version'])
            _archive_check(artifacts[f'attempt-{i}.prompt'] == dict(sha256=hashlib.sha256(request).hexdigest(), size=len(request)))
            output, result, usage = check_api_attempt(request, contents[f'attempt-{i}.response'],
                                                      exchange, document, metadata['model_label'], feedback,
                                                      metadata['prompt_version'])
            _archive_check(output == contents[f'attempt-{i}.output'])
            _archive_check(not exchanges or stamp(exchanges[-1]['finished_at'], '$') <= stamp(exchange['started_at'], '$'))
            exchanges.append(exchange); usages.append(usage)
            attempts.append(dict(attempt=i, **result))
            continue
        try:
            parse_output(contents[f'attempt-{i}.output'], document)
            result = dict(status='validated', error_code=None, error_path=None, failure_kind=None, retryable=False)
        except ExtractionError as error:
            result = dict(status='failed', error_code=error.code, error_path=error.path,
                          failure_kind=error.kind, retryable=error.retryable)
        attempts.append(dict(attempt=i, **result))
    if api:
        from .api import usage_totals
        _archive_check(not attempts[-1]['retryable'] or count == 3)
        _archive_check(metadata['provider'] == 'openai'
                       and metadata['model_version'] is None and metadata['cost'] is None and metadata['currency'] is None
                       and metadata['started_at'] == exchanges[0]['started_at']
                       and metadata['finished_at'] == exchanges[-1]['finished_at']
                       and (metadata['usage_in'], metadata['usage_out']) == usage_totals(usages))
    return dict(format_version=FORMAT, run_id=identity['run_id'], document_version_id=document['document_version_id'],
                data_kind=document['data_kind'], execution_mode=metadata['execution_mode'], recorded_at=identity['recorded_at'],
                status=attempts[-1]['status'], review_required=True, input_sha256=artifacts['input.json']['sha256'],
                metadata_sha256=artifacts['metadata.json']['sha256'], artifacts=artifacts, attempts=attempts)


def import_run(input_path, metadata_path, attempt_pairs, root=DEFAULT_ROOT, api_artifacts=None):
    pairs = list(attempt_pairs)
    content, metadata_bytes = _read(input_path), _read(metadata_path)
    document = parse_input(content)
    metadata = parse_metadata(metadata_bytes, document, len(pairs))
    sources = dict([('input.json', Path(input_path)), ('metadata.json', Path(metadata_path))] +
                   [(f'attempt-{i}.{suffix}', Path(path)) for i, pair in enumerate(pairs, 1)
                    for suffix, path in zip(('prompt', 'output'), pair, strict=True)])
    require((metadata['execution_mode'] == 'api') == (api_artifacts is not None), kind='input')
    if api_artifacts is not None:
        require(len(api_artifacts) == len(pairs), kind='input')
        sources.update((f'attempt-{i}.{suffix}', Path(path)) for i, pair in enumerate(api_artifacts, 1)
                       for suffix, path in zip(('response', 'exchange'), pair, strict=True))
    fingerprints = {name: _fingerprint(path) for name, path in sources.items()}
    for name, original in [('input.json', content), ('metadata.json', metadata_bytes)]:
        _archive_check(fingerprints[name]['sha256'] == hashlib.sha256(original).hexdigest(), 'ARCHIVE_SOURCE_CHANGED')
    directory = _directory(_root(root) / metadata['run_id'])
    identity = _identity(directory, dict(format_version=FORMAT, run_id=metadata['run_id'],
                                         document_version_id=document['document_version_id'], data_kind=document['data_kind'],
                                         attempt_count=len(pairs), artifacts=fingerprints))
    for name, source in sources.items():
        _copy(source, directory / name, fingerprints[name])
    result = _receipt(directory, identity)
    _write(directory / 'receipt.json', _json(result))
    return verify_run(metadata['run_id'], root)


def verify_run(run_id, root=DEFAULT_ROOT):
    text(run_id, '$.run_id', 'input', UUID)
    directory = _root(root, create=False) / run_id
    _archive_check(directory.is_dir() and not directory.is_symlink(), 'ARCHIVE_INCOMPLETE')
    _archive_check((directory / 'identity.json').exists() and (directory / 'receipt.json').exists(), 'ARCHIVE_INCOMPLETE')
    try:
        identity = decode(_read(directory / 'identity.json'), 'archive')
        expected = _receipt(directory, identity)
        _archive_check(_read(directory / 'receipt.json') == _json(expected))
    except (ExtractionError, FileNotFoundError):
        raise ExtractionError('ARCHIVE_INTEGRITY', kind='archive') from None
    return expected


def _sealed(directory, receipt):
    if directory.stat(follow_symlinks=False).st_mode & 0o222:
        return False
    for name in [*receipt['artifacts'], 'identity.json', 'receipt.json']:
        mode = (directory / name).stat(follow_symlinks=False).st_mode
        if not stat.S_ISREG(mode) or mode & 0o222:
            return False
    return True


def verify_sealed_run(run_id, root=DEFAULT_ROOT):
    receipt = verify_run(run_id, root)
    directory = _root(root, create=False) / run_id
    _archive_check(_sealed(directory, receipt), 'ARCHIVE_REQUIRES_SEALED')
    return dict(protocol_version='extraction-registration-v1', snapshot_ref=run_id, receipt=receipt)


def freeze_run(run_id, root=DEFAULT_ROOT):
    receipt = verify_run(run_id, root)
    base = _root(root, create=False)
    source = base / run_id

    def result(directory):
        return dict(protocol_version='extraction-registration-v1', snapshot_ref=directory.relative_to(base).as_posix(), receipt=receipt)

    if _sealed(source, receipt):
        return result(source)
    content = _json(receipt)
    registered = _directory(base / 'registered')
    destination_root = registered / hashlib.sha256(content).hexdigest()
    destination = destination_root / run_id

    def check_destination():
        _archive_check(verify_run(run_id, destination_root) == receipt and _sealed(destination, receipt))

    if destination_root.exists():
        check_destination()
        return result(destination)
    temporary = Path(tempfile.mkdtemp(prefix='.freeze-', dir=registered))
    try:
        staged = _directory(temporary / run_id)
        _write(staged / 'identity.json', _read(source / 'identity.json'))
        for name, expected in receipt['artifacts'].items():
            _copy(source / name, staged / name, expected)
        _write(staged / 'receipt.json', content)
        _archive_check(verify_run(run_id, temporary) == receipt)
        for path in staged.iterdir():
            path.chmod(0o400)
        staged.chmod(0o500)
        try:
            os.rename(temporary, destination_root)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
        check_destination()
        return result(destination)
    finally:
        # 이 함수가 만든 staging만 정리하며 읽기 전용 하위 디렉터리를 먼저 해제한다.
        if temporary.exists():
            for directory, _, _ in os.walk(temporary):
                Path(directory).chmod(0o700)
            shutil.rmtree(temporary)
