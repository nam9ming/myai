"""D08 manifest 원본을 버전별로 고정한다. 원문·금표 보관과는 별개다."""

from datetime import datetime, timezone
import errno
import hashlib
import os
from pathlib import Path
import shutil
import stat
import tempfile

from processing.extraction.archive import REPO, _identity, _json, _read, _root, _write
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import ExtractionError, decode, require, shape, text
from .dataset import _parse_manifest

DEFAULT_ROOT = REPO / 'data/private/evaluation/datasets'
FORMAT = 'dataset-archive-v1'
FILES = ('manifest.json', 'identity.json', 'receipt.json')


def _check(condition, code='DATASET_INTEGRITY'):
    require(condition, kind='archive', code=code)


def _times(manifest, frozen_at):
    cutoff = stamp(frozen_at, '$.frozen_at')
    values = [a['assigned_at'] for a in manifest['split_assignments']]
    values.extend(r['created_at'] for r in manifest['relations'])
    if manifest['grouping_review']['reviewed_at'] is not None:
        values.append(manifest['grouping_review']['reviewed_at'])
    require(all(stamp(v, '$') <= cutoff for v in values), kind='input', code='DATASET_TIMESTAMP_INVALID')


def _receipt(content, identity):
    manifest, summary = _parse_manifest(content)
    shape(identity, 'format_version dataset_ref manifest_sha256 manifest_size recorded_at', kind='archive')
    _check(identity['format_version'] == FORMAT and identity['dataset_ref'] == summary['dataset_ref']
           and identity['manifest_sha256'] == summary['manifest_sha256']
           and type(identity['manifest_size']) is int and identity['manifest_size'] == len(content))
    _times(manifest, identity['recorded_at'])
    return dict(format_version=FORMAT, status='frozen', dataset_ref=summary['dataset_ref'],
                manifest_sha256=summary['manifest_sha256'], manifest_size=len(content),
                frozen_at=identity['recorded_at'], summary=summary)


def _sealed(directory):
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o222:
        return False
    if set(p.name for p in directory.iterdir()) != set(FILES):
        return False
    return all(stat.S_ISREG((directory / name).stat(follow_symlinks=False).st_mode)
               and not (directory / name).stat(follow_symlinks=False).st_mode & 0o222 for name in FILES)


def _verify_directory(directory, dataset_ref):
    try:
        _check(_sealed(directory))
        content = _read(directory / 'manifest.json')
        identity = decode(_read(directory / 'identity.json'), 'archive')
        expected = _receipt(content, identity)
        _check(expected['dataset_ref'] == dataset_ref and _read(directory / 'receipt.json') == _json(expected))
    except (ExtractionError, FileNotFoundError):
        raise ExtractionError('DATASET_INTEGRITY', kind='archive') from None
    return expected


def verify_dataset(dataset_ref, root=DEFAULT_ROOT):
    text(dataset_ref, kind='input', pattern=HASH)
    return _verify_directory(_root(root, create=False) / dataset_ref, dataset_ref)


def freeze_dataset(input_path, root=DEFAULT_ROOT):
    content = _read(input_path)
    manifest, summary = _parse_manifest(content)
    _times(manifest, datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    base = _root(root)
    destination = base / summary['dataset_ref']

    def existing():
        receipt = verify_dataset(summary['dataset_ref'], base)
        _check(receipt['manifest_sha256'] == summary['manifest_sha256'], 'DATASET_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink():
        return existing()
    temporary = Path(tempfile.mkdtemp(prefix='.dataset-', dir=base))
    try:
        _write(temporary / 'manifest.json', content)
        identity = _identity(temporary, dict(format_version=FORMAT, dataset_ref=summary['dataset_ref'],
                                             manifest_sha256=hashlib.sha256(content).hexdigest(), manifest_size=len(content)))
        _write(temporary / 'receipt.json', _json(_receipt(content, identity)))
        for name in FILES:
            (temporary / name).chmod(0o400)
        temporary.chmod(0o500)
        _verify_directory(temporary, summary['dataset_ref'])
        try:
            os.rename(temporary, destination)
        except OSError as error:
            # macOS는 읽기 전용 목적지의 동시 배치에도 EACCES를 반환한다.
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not destination.exists():
                raise
        return existing()
    finally:
        if temporary.exists():
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
