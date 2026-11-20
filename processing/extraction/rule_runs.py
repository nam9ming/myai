"""AI D05와 분리한 규칙 실행의 입력·프로필·실제 출력 불변 보관."""

from datetime import datetime, timezone
import errno
import hashlib
from pathlib import Path
import shutil
import stat
import tempfile
from uuid import uuid4

from .archive import REPO, _identity, _json, _read, _root, _write
from .metadata import stamp
from .rules import RULE_VERSION, extract_rules, parse_profile
from .schema import UUID
from .validation import ExtractionError, decode, parse_input, require, shape, text
from processing.evaluation.storage import _rename_exclusive

RULE_ROOT = REPO / 'data/private/rule-runs'
FORMAT = 'rules-run-v1'
PAYLOADS = ('input.json', 'profile.json', 'output.json', 'metadata.json')
FILES = (*PAYLOADS, 'identity.json', 'receipt.json')
METADATA = ('schema_version run_id document_version_id execution_mode rule_version profile_version '
            'data_kind preprocessing_version started_at finished_at')


def _check(condition, code='RULE_RUN_INTEGRITY'):
    require(condition, kind='archive', code=code)


def _fingerprint(content):
    return dict(sha256=hashlib.sha256(content).hexdigest(), size=len(content))


def _sealed(directory):
    if directory.is_symlink() or not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) != 0o500:
        return False
    if {p.name for p in directory.iterdir()} != set(FILES):
        return False
    return all(stat.S_ISREG((directory / name).stat(follow_symlinks=False).st_mode)
               and stat.S_IMODE((directory / name).stat(follow_symlinks=False).st_mode) == 0o400 for name in FILES)


def _receipt(payloads, identity, run_id):
    document, profile = parse_input(payloads['input.json']), parse_profile(payloads['profile.json'])
    metadata = decode(payloads['metadata.json'], 'archive')
    shape(metadata, METADATA, kind='archive')
    _check(metadata['schema_version'] == 'rules-metadata-v1' and metadata['run_id'] == run_id
           and metadata['document_version_id'] == document['document_version_id']
           and metadata['execution_mode'] == 'rules' and metadata['rule_version'] == RULE_VERSION
           and metadata['profile_version'] == profile['profile_version']
           and metadata['data_kind'] == document['data_kind'] and _json(metadata) == payloads['metadata.json'])
    text(metadata['preprocessing_version'], kind='archive')
    _check(len(metadata['preprocessing_version']) <= 100)
    shape(identity, 'format_version run_id artifacts recorded_at', kind='archive')
    artifacts = {name: _fingerprint(content) for name, content in payloads.items()}
    _check(identity['format_version'] == FORMAT and identity['run_id'] == run_id and identity['artifacts'] == artifacts)
    _check(stamp(metadata['started_at'], '$') <= stamp(metadata['finished_at'], '$') <= stamp(identity['recorded_at'], '$'))
    expected, error = extract_rules(payloads['input.json'], payloads['profile.json'])
    _check(expected == payloads['output.json'])
    return dict(format_version=FORMAT, run_id=run_id, document_version_id=document['document_version_id'],
                execution_mode='rules', data_kind=document['data_kind'], rule_version=RULE_VERSION,
                profile_version=profile['profile_version'], preprocessing_version=metadata['preprocessing_version'],
                input_sha256=artifacts['input.json']['sha256'], profile_sha256=artifacts['profile.json']['sha256'],
                metadata_sha256=artifacts['metadata.json']['sha256'], artifacts=artifacts,
                started_at=metadata['started_at'], finished_at=metadata['finished_at'], recorded_at=identity['recorded_at'],
                attempts=1, status='failed' if error else 'validated', validation_error=error, review_required=True)


def _verify_directory(directory, run_id):
    try:
        _check(_sealed(directory))
        payloads = {name: _read(directory / name) for name in PAYLOADS}
        identity_bytes = _read(directory / 'identity.json')
        identity = decode(identity_bytes, 'archive')
        _check(_json(identity) == identity_bytes)
        receipt = _receipt(payloads, identity, run_id)
        _check(_read(directory / 'receipt.json') == _json(receipt))
        return receipt
    except (ExtractionError, FileNotFoundError, TypeError):
        raise ExtractionError('RULE_RUN_INTEGRITY', kind='archive') from None


def verify_rules_run(run_id, root=RULE_ROOT):
    text(run_id, kind='input', pattern=UUID)
    return _verify_directory(_root(root, create=False) / run_id, run_id)


def run_rules(input_path, profile_path, preprocessing_version, root=RULE_ROOT, run_id=None):
    text(preprocessing_version, kind='input')
    require(len(preprocessing_version) <= 100, kind='input')
    run_id = str(uuid4()) if run_id is None else text(run_id, kind='input', pattern=UUID)
    input_bytes, profile_bytes = _read(input_path), _read(profile_path)
    document, profile = parse_input(input_bytes), parse_profile(profile_bytes)
    require(document['data_kind'] == profile['data_kind'], kind='input')
    base = _root(root)
    destination = base / run_id
    wanted = (hashlib.sha256(input_bytes).hexdigest(), hashlib.sha256(profile_bytes).hexdigest(), preprocessing_version)

    def existing():
        receipt = verify_rules_run(run_id, base)
        _check((receipt['input_sha256'], receipt['profile_sha256'], receipt['preprocessing_version']) == wanted, 'RULE_RUN_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink():
        return existing()
    temporary = Path(tempfile.mkdtemp(prefix='.rules-', dir=base))
    try:
        started_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        output_bytes, _ = extract_rules(input_bytes, profile_bytes)
        metadata = dict(schema_version='rules-metadata-v1', run_id=run_id,
                        document_version_id=document['document_version_id'], execution_mode='rules',
                        rule_version=RULE_VERSION, profile_version=profile['profile_version'], data_kind=document['data_kind'],
                        preprocessing_version=preprocessing_version, started_at=started_at,
                        finished_at=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
        payloads = dict(zip(PAYLOADS, (input_bytes, profile_bytes, output_bytes, _json(metadata))))
        for name, content in payloads.items():
            _write(temporary / name, content)
        identity = _identity(temporary, dict(format_version=FORMAT, run_id=run_id,
                                             artifacts={name: _fingerprint(content) for name, content in payloads.items()}))
        _write(temporary / 'receipt.json', _json(_receipt(payloads, identity, run_id)))
        for name in FILES:
            (temporary / name).chmod(0o400)
        temporary.chmod(0o500)
        _verify_directory(temporary, run_id)
        try:
            _rename_exclusive(temporary, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not destination.exists():
                raise
        return existing()
    finally:
        if temporary.exists():
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
