"""정답·판정 지침·manifest·원본 입력을 별도 읽기 전용 버전으로 보관한다."""

from datetime import datetime, timezone
import errno
import hashlib
from pathlib import Path
import re
import shutil
import stat
import tempfile

from processing.extraction.archive import REPO, _identity, _json, _read, _read_checked, _root, _write
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH, UUID
from processing.extraction.validation import ExtractionError, decode, require, shape, text
from .gold import _header, _load_gold, _validate_gold
from .storage import DEFAULT_ROOT as DATASET_ROOT, _rename_exclusive

GOLD_ROOT = REPO/'data/private/evaluation/gold'
FORMAT = 'gold-archive-v1'


def _check(condition,code='GOLD_INTEGRITY'):
    require(condition,kind='archive',code=code)


def _times(content,frozen_at):
    value = _header(content)
    require(stamp(value['authorship']['reviewed_at'],'$') <= stamp(frozen_at,'$'),
            kind='input',code='GOLD_TIMESTAMP_INVALID')


def _sealed_file(path):
    mode = path.stat(follow_symlinks=False).st_mode
    return stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o400


def _verify_directory(directory,gold_ref):
    try:
        _check(not directory.is_symlink() and directory.is_dir() and stat.S_IMODE(directory.stat().st_mode) == 0o500)
        _check(_sealed_file(directory/'identity.json'))
        identity = decode(_read(directory/'identity.json'),'archive')
        shape(identity,'format_version gold_ref artifacts recorded_at',kind='archive')
        _check(identity['format_version'] == FORMAT and identity['gold_ref'] == gold_ref)
        artifacts = identity['artifacts']
        _check(type(artifacts) is dict and {'gold.json','manifest.json'} <= set(artifacts))
        for name,metadata in artifacts.items():
            _check(name in ('gold.json','manifest.json') or re.fullmatch(rf'input-{UUID}\.json',name) is not None)
            shape(metadata,'sha256 size',kind='archive');text(metadata['sha256'],kind='archive',pattern=HASH)
            _check(type(metadata['size']) is int and metadata['size'] >= 0)
        names = {*artifacts,'identity.json','receipt.json'}
        _check({p.name for p in directory.iterdir()} == names and all(_sealed_file(directory/name) for name in names))
        contents = {name:_read_checked(directory/name,expected) for name,expected in artifacts.items()}
        value = _header(contents['gold.json'])
        versions = [d['document_version_id'] for d in value['documents']]
        _check(set(artifacts) == {'gold.json','manifest.json',*(f'input-{version}.json' for version in versions)})
        summary = _validate_gold(contents['gold.json'],contents['manifest.json'],
                                 {v:contents[f'input-{v}.json'] for v in versions})
        _check(summary['gold_ref'] == gold_ref)
        _times(contents['gold.json'],identity['recorded_at'])
        expected = dict(format_version=FORMAT,status='frozen',gold_ref=gold_ref,
                        frozen_at=identity['recorded_at'],artifacts=artifacts,summary=summary)
        _check(_read(directory/'receipt.json') == _json(expected))
    except (ExtractionError,FileNotFoundError):
        raise ExtractionError('GOLD_INTEGRITY',kind='archive') from None
    return expected


def verify_gold(gold_ref,root=GOLD_ROOT):
    text(gold_ref,kind='input',pattern=HASH)
    return _verify_directory(_root(root,create=False)/gold_ref,gold_ref)


def freeze_gold(input_path,root=GOLD_ROOT,dataset_root=DATASET_ROOT):
    content = _read(input_path)
    manifest,sources,summary = _load_gold(content,dataset_root)
    _times(content,datetime.now(timezone.utc).isoformat().replace('+00:00','Z'))
    payloads = {'gold.json':content,'manifest.json':manifest,
                **{f'input-{version}.json':raw for version,raw in sources.items()}}
    artifacts = {name:dict(sha256=hashlib.sha256(raw).hexdigest(),size=len(raw)) for name,raw in payloads.items()}
    base = _root(root);destination = base/summary['gold_ref']

    def existing():
        receipt = verify_gold(summary['gold_ref'],base)
        _check(receipt['artifacts'] == artifacts,'GOLD_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink():return existing()
    temporary = Path(tempfile.mkdtemp(prefix='.gold-',dir=base))
    try:
        for name,raw in payloads.items():_write(temporary/name,raw)
        identity = _identity(temporary,dict(format_version=FORMAT,gold_ref=summary['gold_ref'],artifacts=artifacts))
        _write(temporary/'receipt.json',_json(dict(format_version=FORMAT,status='frozen',gold_ref=summary['gold_ref'],
            frozen_at=identity['recorded_at'],artifacts=artifacts,summary=summary)))
        for path in temporary.iterdir():path.chmod(0o400)
        temporary.chmod(0o500)
        _verify_directory(temporary,summary['gold_ref'])
        try:
            _rename_exclusive(temporary,destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST,errno.ENOTEMPTY,errno.EACCES) or not destination.exists():raise
        return existing()
    finally:
        if temporary.exists():
            temporary.chmod(0o700);shutil.rmtree(temporary)
