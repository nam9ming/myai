"""D06 사실 투영과 사람 수정·부모 D05 전체를 별도 인계 이미지로 동결한다."""

import errno
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from processing.extraction.archive import _copy, _fingerprint, _identity, _json, _read, _read_checked, _root, _write
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import ExtractionError, decode, require, shape, text
from .evaluation_storage import _sealed, _tree
from .human_handoff import HANDOFF_ROOT, REVIEW_ROOT, _header, project_handoff
from .storage import _rename_exclusive

FORMAT = 'human-handoff-archive-v1'


def _check(condition, code='HANDOFF_INTEGRITY'):
    require(condition, kind='archive', code=code)


def _receipt(identity, summary):
    return dict(format_version=FORMAT, status='frozen', handoff_ref=summary['handoff_ref'],
        frozen_at=identity['recorded_at'], artifacts=identity['artifacts'], summary=summary)


def _verify_directory(directory, reference):
    try:
        _check(_sealed(directory, 0o500, stat.S_ISDIR))
        _check(all(_sealed(directory / name, 0o400, stat.S_ISREG) for name in ('identity.json', 'receipt.json')))
        identity_bytes = _read(directory / 'identity.json'); identity = decode(identity_bytes, 'archive')
        shape(identity, 'format_version handoff_ref artifacts recorded_at', kind='archive')
        _check(identity['format_version'] == FORMAT and identity['handoff_ref'] == reference)
        _check(_json(identity) == identity_bytes)
        artifacts = identity['artifacts']
        _check(type(artifacts) is dict and {'selection.json', 'projection.json'} <= set(artifacts))
        _tree(directory, artifacts)
        _check(all(_fingerprint(directory / name) == metadata for name, metadata in artifacts.items()))
        selection = _read_checked(directory / 'selection.json', artifacts['selection.json']); _header(selection)
        stored = _read_checked(directory / 'projection.json', artifacts['projection.json']); recorded = decode(stored, 'archive')
        _check(type(recorded) is dict and 'projected_at' in recorded)
        _check(stamp(recorded['projected_at'], '$') <= stamp(identity['recorded_at'], '$'))
        packet = project_handoff(selection, directory / 'review', projected_at=recorded['projected_at'])
        _check(packet['summary']['handoff_ref'] == reference and stored == _json(packet['projection']))
        _check(artifacts == {name: metadata for name, (_, metadata) in packet['sources'].items()} | {
            'selection.json': artifacts['selection.json'], 'projection.json': artifacts['projection.json']})
        expected = _receipt(identity, packet['summary'])
        _check(_read(directory / 'receipt.json') == _json(expected))
    except (ExtractionError, FileNotFoundError, NotADirectoryError, TypeError):
        raise ExtractionError('HANDOFF_INTEGRITY', kind='archive') from None
    return expected


def verify_handoff(handoff_ref, root=HANDOFF_ROOT):
    text(handoff_ref, kind='input', pattern=HASH)
    return _verify_directory(_root(root, create=False) / handoff_ref, handoff_ref)


def freeze_handoff(input_path, root=HANDOFF_ROOT, review_root=REVIEW_ROOT):
    content = _read(input_path); value = _header(content)
    reference = hashlib.sha256(value['handoff_id'].encode()).hexdigest()
    fingerprint = dict(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    base = _root(root); destination = base / reference

    def existing():
        receipt = verify_handoff(reference, base)
        _check(receipt['artifacts']['selection.json'] == fingerprint, 'HANDOFF_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink(): return existing()
    packet = project_handoff(content, review_root)
    payloads = {'selection.json': content, 'projection.json': _json(packet['projection'])}
    artifacts = {name: metadata for name, (_, metadata) in packet['sources'].items()}
    artifacts.update({name: dict(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)) for name, raw in payloads.items()})
    temporary = Path(tempfile.mkdtemp(prefix='.handoff-', dir=base))
    try:
        for name, raw in payloads.items(): _write(temporary / name, raw)
        for name, (source, metadata) in packet['sources'].items():
            target = temporary / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _copy(source, target, metadata)
        identity = _identity(temporary, dict(format_version=FORMAT, handoff_ref=reference, artifacts=artifacts))
        _write(temporary / 'receipt.json', _json(_receipt(identity, packet['summary'])))
        for current, _, names in os.walk(temporary, topdown=False):
            folder = Path(current)
            for name in names: (folder / name).chmod(0o400)
            folder.chmod(0o500)
        _verify_directory(temporary, reference)
        try: _rename_exclusive(temporary, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not destination.exists(): raise
        return existing()
    finally:
        if temporary.exists():
            for current, _, _ in os.walk(temporary): Path(current).chmod(0o700)
            shutil.rmtree(temporary)
