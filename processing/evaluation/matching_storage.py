"""매칭 선택·결과·비교/최초 원본 전체를 별도 불변 이미지로 보관한다."""

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
from .matching import COMPARISON_ROOT, MATCHING_ROOT, _header, evaluate_matching
from .storage import _rename_exclusive

FORMAT = 'matching-evaluation-archive-v1'


def _check(condition, code='MATCHING_INTEGRITY'):
    require(condition, kind='archive', code=code)


def _receipt(identity, result):
    return dict(format_version=FORMAT, status='frozen', matching_ref=result['matching_ref'],
                frozen_at=identity['recorded_at'], artifacts=identity['artifacts'], summary=result['summary'])


def _verify_directory(directory, reference, *, initial_only=False):
    try:
        _check(_sealed(directory, 0o500, stat.S_ISDIR))
        _check(all(_sealed(directory / name, 0o400, stat.S_ISREG) for name in ('identity.json', 'receipt.json')))
        identity = decode(_read(directory / 'identity.json'), 'archive')
        shape(identity, 'format_version matching_ref artifacts recorded_at', kind='archive')
        _check(identity['format_version'] == FORMAT and identity['matching_ref'] == reference)
        artifacts = identity['artifacts']
        _check(type(artifacts) is dict and {'selection.json', 'result.json'} <= set(artifacts))
        _tree(directory, artifacts)
        _check(all(_fingerprint(directory / name) == metadata for name, metadata in artifacts.items()))
        selection = _read_checked(directory / 'selection.json', artifacts['selection.json'])
        value = _header(selection)
        _check(not initial_only or value['phase'] == 'initial')
        stored = _read_checked(directory / 'result.json', artifacts['result.json'])
        recorded = decode(stored, 'archive')
        _check(type(recorded) is dict and 'evaluated_at' in recorded)
        _check(stamp(recorded['evaluated_at'], '$') <= stamp(identity['recorded_at'], '$'))
        packet = evaluate_matching(selection, directory / 'comparisons', directory / 'initial',
                                   evaluated_at=recorded['evaluated_at'])
        result = packet['result']
        _check(result['matching_ref'] == reference and stored == _json(result))
        _check(artifacts == {name: metadata for name, (_, metadata) in packet['sources'].items()} | {
            'selection.json': artifacts['selection.json'], 'result.json': artifacts['result.json']})
        expected = _receipt(identity, result)
        _check(_read(directory / 'receipt.json') == _json(expected))
    except (ExtractionError, FileNotFoundError, NotADirectoryError):
        raise ExtractionError('MATCHING_INTEGRITY', kind='archive') from None
    return expected


def verify_matching(matching_ref, root=MATCHING_ROOT):
    text(matching_ref, kind='input', pattern=HASH)
    return _verify_directory(_root(root, create=False) / matching_ref, matching_ref)


def freeze_matching(input_path, root=MATCHING_ROOT, comparison_root=COMPARISON_ROOT, initial_root=MATCHING_ROOT):
    content = _read(input_path); value = _header(content)
    reference = hashlib.sha256(value['matching_eval_id'].encode()).hexdigest()
    fingerprint = dict(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    base = _root(root); destination = base / reference

    def existing():
        receipt = verify_matching(reference, base)
        _check(receipt['artifacts']['selection.json'] == fingerprint, 'MATCHING_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink(): return existing()
    packet = evaluate_matching(content, comparison_root, initial_root)
    result = packet['result']; payloads = {'selection.json': content, 'result.json': _json(result)}
    artifacts = {name: metadata for name, (_, metadata) in packet['sources'].items()}
    artifacts.update({name: dict(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)) for name, raw in payloads.items()})
    temporary = Path(tempfile.mkdtemp(prefix='.matching-', dir=base))
    try:
        for name, raw in payloads.items(): _write(temporary / name, raw)
        for name, (source, metadata) in packet['sources'].items():
            target = temporary / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _copy(source, target, metadata)
        identity = _identity(temporary, dict(format_version=FORMAT, matching_ref=reference, artifacts=artifacts))
        _write(temporary / 'receipt.json', _json(_receipt(identity, result)))
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
