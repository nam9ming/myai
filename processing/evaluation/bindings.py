"""동결 manifest의 입력 바이트와 명시 선택한 D05 원본을 읽기 전용 대조한다."""

import hashlib
from pathlib import Path
import stat

from processing.extraction.archive import (DEFAULT_ROOT as EXTRACTION_ROOT, _json, _read,
                                            _read_checked, _root, verify_run)
from processing.extraction.schema import HASH, UUID
from processing.extraction.validation import array, decode, parse_input, require, shape, text
from .dataset import _id, _parse_manifest
from .storage import DEFAULT_ROOT, verify_dataset


def _check(condition, code='BINDING_INVALID'):
    require(condition, kind='input', code=code)


def _frozen(directory, receipt):
    names = {*receipt['artifacts'], 'identity.json', 'receipt.json'}
    _check(not directory.is_symlink() and stat.S_IMODE(directory.stat().st_mode) == 0o500
           and {p.name for p in directory.iterdir()} == names, 'BINDING_REQUIRES_FROZEN')
    for name in names:
        mode = (directory/name).stat(follow_symlinks=False).st_mode
        _check(stat.S_ISREG(mode) and stat.S_IMODE(mode) == 0o400, 'BINDING_REQUIRES_FROZEN')


def check_bindings(content, dataset_root=DEFAULT_ROOT, run_root=EXTRACTION_ROOT):
    value = decode(content, 'input')
    shape(value, 'schema_version dataset_ref manifest_sha256 bindings', kind='input')
    _check(value['schema_version'] == 'dataset-bindings-v1')
    for key in ('dataset_ref', 'manifest_sha256'):
        text(value[key], kind='input', pattern=HASH)
    frozen = verify_dataset(value['dataset_ref'], dataset_root)
    manifest_bytes = _read(_root(dataset_root, create=False)/value['dataset_ref']/'manifest.json')
    _check(hashlib.sha256(manifest_bytes).hexdigest() == frozen['manifest_sha256'] == value['manifest_sha256'],
           'BINDING_DATASET_MISMATCH')
    manifest, summary = _parse_manifest(manifest_bytes)
    versions = {v['document_version_id']: v['input_sha256'] for d in manifest['documents'] for v in d['versions']}
    seen, run_ids, runs = set(), set(), []
    base = _root(run_root, create=False)
    for entry in array(value['bindings'], '$.bindings', 'input', 1):
        shape(entry, 'document_version_id input_path runs', kind='input')
        version = _id(entry['document_version_id'])
        _check(version in versions and version not in seen); seen.add(version)
        input_path = text(entry['input_path'], kind='input')
        _check('\x00' not in input_path)
        path = Path(input_path).expanduser().absolute()
        source_bytes = _read(_root(path.parent, create=False)/path.name)
        document = parse_input(source_bytes)
        source_hash = hashlib.sha256(source_bytes).hexdigest()
        _check(document['document_version_id'] == version and document['data_kind'] == manifest['data_kind']
               and source_hash == versions[version], 'BINDING_SOURCE_MISMATCH')
        for selected in array(entry['runs'], '$.runs', 'input', 1):
            shape(selected, 'run_id snapshot_ref receipt_sha256', kind='input')
            run_id = _id(selected['run_id'])
            _check(run_id not in run_ids); run_ids.add(run_id)
            reference = text(selected['snapshot_ref'], kind='input', pattern=rf'(?:registered/{HASH}/)?{UUID}')
            _check(reference.split('/')[-1] == run_id)
            text(selected['receipt_sha256'], kind='input', pattern=HASH)
            directory = _root(base/reference, create=False)
            _check(directory == base/reference)
            receipt = verify_run(run_id, directory.parent)
            _frozen(directory, receipt)
            raw = _read(directory/'receipt.json')
            receipt_hash = hashlib.sha256(raw).hexdigest()
            _check(raw == _json(receipt) and receipt_hash == selected['receipt_sha256'], 'BINDING_RUN_MISMATCH')
            if reference.startswith('registered/'):
                _check(reference.split('/')[1] == receipt_hash, 'BINDING_RUN_MISMATCH')
            run_input = _read_checked(directory/'input.json', receipt['artifacts']['input.json'])
            _check(receipt['document_version_id'] == version and receipt['data_kind'] == manifest['data_kind']
                   and receipt['input_sha256'] == source_hash and run_input == source_bytes, 'BINDING_SOURCE_MISMATCH')
            runs.append(dict(run_id=run_id, document_version_id=version, receipt_sha256=receipt_hash,
                             status=receipt['status'], execution_mode=receipt['execution_mode'],
                             attempt_count=len(receipt['attempts']), first_status=receipt['attempts'][0]['status']))
    _check(seen == versions.keys(), 'BINDING_COVERAGE_INVALID')
    return dict(protocol_version='dataset-bindings-check-v1', status='validated',
                bindings_sha256=hashlib.sha256(content).hexdigest(), dataset_ref=value['dataset_ref'],
                manifest_sha256=value['manifest_sha256'], data_kind=manifest['data_kind'],
                counts=dict(documents=summary['counts']['documents'], document_versions=len(versions), runs=len(runs),
                            validated_runs=sum(r['status'] == 'validated' for r in runs),
                            failed_runs=sum(r['status'] == 'failed' for r in runs)),
                holdout_status=summary['holdout_status'], holdout_warnings=summary['holdout_warnings'],
                runs=runs)
