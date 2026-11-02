"""수동 AI 실행의 원본을 배타적으로 기록하고 매번 검증한다."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
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
    # 저장소 안의 별칭 경로도 실제 목적지를 확인해 공개 디렉터리에 쓰지 않는다.
    resolved = path.resolve()
    require(not resolved.is_relative_to(REPO) or resolved.is_relative_to(REPO / 'data/private'),
            kind='input', code='ARCHIVE_ROOT_INVALID')
    if path.is_relative_to(REPO):
        require(path.is_relative_to(REPO / 'data/private') and path == resolved,
                kind='input', code='ARCHIVE_ROOT_INVALID')
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
    shape(identity, 'format_version run_id document_version_id data_kind attempt_count artifacts recorded_at', kind='archive')
    _archive_check(identity['format_version'] == FORMAT and identity['run_id'] == directory.name)
    count = identity['attempt_count']
    _archive_check(type(count) is int and 1 <= count <= 3)
    names = ['input.json', 'metadata.json'] + [f'attempt-{i}.{suffix}' for i in range(1, count + 1) for suffix in ('prompt', 'output')]
    artifacts = identity['artifacts']
    _archive_check(type(artifacts) is dict and set(artifacts) == set(names))
    stamp(identity['recorded_at'], '$.recorded_at')
    contents = {}
    for name in names:
        expected = artifacts[name]
        shape(expected, 'sha256 size', kind='archive')
        text(expected['sha256'], kind='archive', pattern=HASH)
        _archive_check(type(expected['size']) is int and expected['size'] >= 0)
        if name.endswith('.prompt'):
            _archive_check(_fingerprint(directory / name) == expected)
        else:
            contents[name] = _read_checked(directory / name, expected)
    document = parse_input(contents['input.json'])
    metadata = parse_metadata(contents['metadata.json'], document, count)
    _archive_check(metadata['run_id'] == identity['run_id'] and document['document_version_id'] == identity['document_version_id']
                   and document['data_kind'] == identity['data_kind'])
    attempts = []
    for i in range(1, count + 1):
        try:
            parse_output(contents[f'attempt-{i}.output'], document)
            result = dict(status='validated', error_code=None, error_path=None, failure_kind=None, retryable=False)
        except ExtractionError as error:
            result = dict(status='failed', error_code=error.code, error_path=error.path,
                          failure_kind=error.kind, retryable=error.retryable)
        attempts.append(dict(attempt=i, **result))
    return dict(format_version=FORMAT, run_id=identity['run_id'], document_version_id=document['document_version_id'],
                data_kind=document['data_kind'], execution_mode='manual_import', recorded_at=identity['recorded_at'],
                status=attempts[-1]['status'], review_required=True, input_sha256=artifacts['input.json']['sha256'],
                metadata_sha256=artifacts['metadata.json']['sha256'], artifacts=artifacts, attempts=attempts)


def import_run(input_path, metadata_path, attempt_pairs, root=DEFAULT_ROOT):
    pairs = list(attempt_pairs)
    content, metadata_bytes = _read(input_path), _read(metadata_path)
    document = parse_input(content)
    metadata = parse_metadata(metadata_bytes, document, len(pairs))
    sources = dict([('input.json', Path(input_path)), ('metadata.json', Path(metadata_path))] +
                   [(f'attempt-{i}.{suffix}', Path(path)) for i, pair in enumerate(pairs, 1)
                    for suffix, path in zip(('prompt', 'output'), pair, strict=True)])
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
