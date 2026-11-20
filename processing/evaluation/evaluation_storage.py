"""실행 선택·채점 결과·전체 출처와 최초 평가를 한 묶음으로 동결한다."""

import errno
import hashlib
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile

from processing.extraction.archive import _copy, _fingerprint, _identity, _json, _read, _read_checked, _root, _write
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import ExtractionError, decode, require, shape, text
from .gold_storage import GOLD_ROOT
from .records import EVALUATION_ROOT, RUN_ROOT, _header, evaluate_record
from .storage import _rename_exclusive

FORMAT='extraction-evaluation-archive-v1'


def _check(condition,code='EVALUATION_INTEGRITY'):
    require(condition,kind='archive',code=code)


def _sealed(path,mode,kind):
    actual=path.stat(follow_symlinks=False).st_mode
    return kind(actual) and stat.S_IMODE(actual)==mode


def _tree(directory,artifacts):
    files=set(artifacts)|{'identity.json','receipt.json'}
    directories={'.'}
    for name,metadata in artifacts.items():
        _check(type(name) is str)
        path=PurePosixPath(name)
        _check(not path.is_absolute() and path.as_posix()==name and '..' not in path.parts and '\\' not in name)
        shape(metadata,'sha256 size',kind='archive');text(metadata['sha256'],kind='archive',pattern=HASH)
        _check(type(metadata['size']) is int and metadata['size']>=0)
        directories.update(str(parent) for parent in path.parents)
    found_files,found_dirs=set(),set()
    for current,children,names in os.walk(directory,followlinks=False):
        folder=Path(current);_check(_sealed(folder,0o500,stat.S_ISDIR))
        found_dirs.add(str(folder.relative_to(directory)))
        for child in children:_check(_sealed(folder/child,0o500,stat.S_ISDIR))
        for name in names:
            path=folder/name;_check(_sealed(path,0o400,stat.S_ISREG))
            found_files.add(path.relative_to(directory).as_posix())
    _check(found_files==files and found_dirs==directories)


def _receipt(identity,result):
    return dict(format_version=FORMAT,status='frozen',evaluation_ref=result['evaluation_ref'],
        frozen_at=identity['recorded_at'],artifacts=identity['artifacts'],summary=result['summary'])


def _verify_directory(directory,reference,*,initial_only=False):
    try:
        _check(_sealed(directory,0o500,stat.S_ISDIR))
        _check(all(_sealed(directory/name,0o400,stat.S_ISREG) for name in ('identity.json','receipt.json')))
        identity=decode(_read(directory/'identity.json'),'archive')
        shape(identity,'format_version evaluation_ref artifacts recorded_at',kind='archive')
        _check(identity['format_version']==FORMAT and identity['evaluation_ref']==reference)
        artifacts=identity['artifacts']
        _check(type(artifacts) is dict and {'selection.json','result.json'}<=set(artifacts))
        _tree(directory,artifacts)
        # 큰 실패 응답도 잘라내지 않고 전체 hash를 검사한다.
        _check(all(_fingerprint(directory/name)==metadata for name,metadata in artifacts.items()))
        selection=_read_checked(directory/'selection.json',artifacts['selection.json']);value=_header(selection)
        if initial_only:
            require(value['phase']=='initial',kind='input',code='EVALUATION_INITIAL_REQUIRED')
        stored=_read_checked(directory/'result.json',artifacts['result.json'])
        recorded=decode(stored,'archive')
        _check(type(recorded) is dict and 'evaluated_at' in recorded)
        _check(stamp(recorded['evaluated_at'],'$')<=stamp(identity['recorded_at'],'$'))
        packet=evaluate_record(selection,directory/'gold',directory/'runs',directory/'initial',
                               evaluated_at=recorded['evaluated_at'])
        result=packet['result']
        _check(result['evaluation_ref']==reference and stored==_json(result))
        _check(artifacts=={name:metadata for name,(_,metadata) in packet['sources'].items()}|{
            'selection.json':artifacts['selection.json'],'result.json':artifacts['result.json']})
        expected=_receipt(identity,result)
        _check(_read(directory/'receipt.json')==_json(expected))
    except (ExtractionError,FileNotFoundError,NotADirectoryError) as error:
        if initial_only and isinstance(error,ExtractionError) and error.code=='EVALUATION_INITIAL_REQUIRED':raise
        raise ExtractionError('EVALUATION_INTEGRITY',kind='archive') from None
    return expected


def verify_evaluation(evaluation_ref,root=EVALUATION_ROOT):
    text(evaluation_ref,kind='input',pattern=HASH)
    return _verify_directory(_root(root,create=False)/evaluation_ref,evaluation_ref)


def freeze_evaluation(input_path,root=EVALUATION_ROOT,gold_root=GOLD_ROOT,run_root=None,initial_root=EVALUATION_ROOT):
    content=_read(input_path);value=_header(content)
    reference=hashlib.sha256(value['extraction_eval_id'].encode()).hexdigest()
    fingerprint=dict(sha256=hashlib.sha256(content).hexdigest(),size=len(content))
    base=_root(root);destination=base/reference

    def existing():
        receipt=verify_evaluation(reference,base)
        _check(receipt['artifacts']['selection.json']==fingerprint,'EVALUATION_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink():return existing()
    packet=evaluate_record(content,gold_root,run_root,initial_root)
    result=packet['result'];payloads={'selection.json':content,'result.json':_json(result)}
    artifacts={name:metadata for name,(_,metadata) in packet['sources'].items()}
    artifacts.update({name:dict(sha256=hashlib.sha256(raw).hexdigest(),size=len(raw)) for name,raw in payloads.items()})
    temporary=Path(tempfile.mkdtemp(prefix='.evaluation-',dir=base))
    try:
        for name,raw in payloads.items():_write(temporary/name,raw)
        for name,(source,metadata) in packet['sources'].items():
            target=temporary/name;target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            _copy(source,target,metadata)
        identity=_identity(temporary,dict(format_version=FORMAT,evaluation_ref=reference,artifacts=artifacts))
        _write(temporary/'receipt.json',_json(_receipt(identity,result)))
        for current,_,names in os.walk(temporary,topdown=False):
            folder=Path(current)
            for name in names:(folder/name).chmod(0o400)
            folder.chmod(0o500)
        _verify_directory(temporary,reference)
        try:_rename_exclusive(temporary,destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST,errno.ENOTEMPTY,errno.EACCES) or not destination.exists():raise
        return existing()
    finally:
        if temporary.exists():
            for current,_,_ in os.walk(temporary):Path(current).chmod(0o700)
            shutil.rmtree(temporary)
