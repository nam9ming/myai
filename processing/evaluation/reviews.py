"""사람 수정값·검토 선언과 원래 D05 전체를 별도 불변 이미지로 보관한다."""

from datetime import datetime, timezone
import errno
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from processing.extraction.archive import (REPO, _copy, _fingerprint, _identity, _json, _read,
                                            _read_checked, _root, _write, verify_run)
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH, UUID
from processing.extraction.validation import (ExtractionError, array, decode, ids, parse_input,
                                              parse_output, require, shape, text)
from processing.matching.intervals import instant_ns
from .bindings import EXTRACTION_ROOT, _frozen
from .dataset import _id, _label
from .storage import _rename_exclusive

REVIEW_ROOT = REPO / 'data/private/evaluation/human-reviews'
FORMAT = 'human-review-archive-v1'


def _check(condition, code='HUMAN_REVIEW_INVALID'):
    require(condition, kind='input', code=code)


def _header(content):
    value = decode(content, 'input')
    shape(value, 'schema_version review_id source review output changes', kind='input')
    _check(value['schema_version'] == 'human-review-v1')
    _id(value['review_id'])
    source = value['source']
    shape(source, 'run_id snapshot_ref receipt_sha256', kind='input')
    _id(source['run_id'])
    reference = text(source['snapshot_ref'], kind='input', pattern=rf'(?:registered/{HASH}/)?{UUID}')
    _check(reference.split('/')[-1] == source['run_id'])
    text(source['receipt_sha256'], kind='input', pattern=HASH)
    review = value['review']
    shape(review, 'reviewed_by started_at finished_at basis note', kind='input')
    _label(review['reviewed_by']); text(review['note'], kind='input')
    _check(review['basis'] in ('source_only', 'gold_feedback', 'unknown'))
    _check(stamp(review['started_at'], '$') <= stamp(review['finished_at'], '$'), 'HUMAN_REVIEW_TIME_INVALID')
    return value


def _same(a, b):
    if type(a) is not type(b): return False
    if type(a) is dict: return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if type(a) is list: return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _changes(value, before, after):
    review, records = value['review'], {}
    evidence = {e['evidence_id'] for output in (before, after) if output for e in output['evidence']}
    previous, current = dict(output=before), dict(output=after)

    def at(root, path):
        for key in path.split('.'):
            _check(type(root) is dict and key in root, 'HUMAN_REVIEW_CHANGE_INVALID')
            root = root[key]
        return root

    for change in array(value['changes'], '$.changes', 'input'):
        shape(change, 'field_path before after reason evidence_ids reviewer time', kind='input')
        path = _label(change['field_path'])
        _check(path not in records and all(not path.startswith(other + '.') and not other.startswith(path + '.')
                                         for other in records), 'HUMAN_REVIEW_CHANGE_INVALID')
        a, b = at(previous, path), at(current, path)
        _check(not _same(a, b) and _same(a, change['before']) and _same(b, change['after'])
               and change['reviewer'] == review['reviewed_by']
               and stamp(change['time'], '$') == stamp(review['finished_at'], '$'), 'HUMAN_REVIEW_CHANGE_INVALID')
        text(change['reason'], kind='input')
        _check(ids(change['evidence_ids'], '$.changes.evidence_ids', 'input') <= evidence, 'HUMAN_REVIEW_CHANGE_INVALID')
        records[path] = change

    def covered(a, b, path):
        if _same(a, b) or path in records: return
        _check(type(a) is dict and type(b) is dict and a.keys() == b.keys(), 'HUMAN_REVIEW_CHANGE_MISSING')
        for key in a: covered(a[key], b[key], path + '.' + key)

    covered(before, after, 'output')


def _load_review(content, run_root, checked_at):
    value = _header(content)
    source, review = value['source'], value['review']
    base = _root(run_root, create=False)
    folder = _root(base / source['snapshot_ref'], create=False)
    _check(folder == base / source['snapshot_ref'])
    receipt = verify_run(source['run_id'], folder.parent)
    _frozen(folder, receipt)
    raw_receipt = _read(folder / 'receipt.json')
    _check(raw_receipt == _json(receipt) and hashlib.sha256(raw_receipt).hexdigest() == source['receipt_sha256'],
           'HUMAN_REVIEW_SOURCE_MISMATCH')
    if source['snapshot_ref'].startswith('registered/'):
        _check(source['snapshot_ref'].split('/')[1] == source['receipt_sha256'], 'HUMAN_REVIEW_SOURCE_MISMATCH')
    metadata = decode(_read_checked(folder / 'metadata.json', receipt['artifacts']['metadata.json']), 'archive')
    started = stamp(review['started_at'], '$')
    _check(stamp(receipt['recorded_at'], '$') <= started
           and (metadata['finished_at'] is None or stamp(metadata['finished_at'], '$') <= started)
           and stamp(review['finished_at'], '$') <= stamp(checked_at, '$'), 'HUMAN_REVIEW_TIME_INVALID')
    input_bytes = _read_checked(folder / 'input.json', receipt['artifacts']['input.json'])
    document = parse_input(input_bytes)
    try:
        output_bytes = _json(value['output'])
        output = parse_output(output_bytes, document)
    except (ExtractionError, TypeError, ValueError):
        raise ExtractionError('HUMAN_REVIEW_OUTPUT_INVALID', kind='input') from None
    previous = None
    if receipt['status'] == 'validated':
        name = f"attempt-{len(receipt['attempts'])}.output"
        previous = parse_output(_read_checked(folder / name, receipt['artifacts'][name]), document)
    _changes(value, previous, output)
    summary = dict(protocol_version='human-review-check-v1', status='declared_reviewed',
        review_id=value['review_id'], review_ref=hashlib.sha256(value['review_id'].encode()).hexdigest(),
        review_sha256=hashlib.sha256(content).hexdigest(), output_sha256=hashlib.sha256(output_bytes).hexdigest(),
        document_version_id=document['document_version_id'], data_kind=document['data_kind'],
        source_run_id=source['run_id'], source_receipt_sha256=source['receipt_sha256'], source_status=receipt['status'],
        review_basis=review['basis'], review_duration_ns=instant_ns(review['finished_at']) - instant_ns(review['started_at']),
        change_count=len(value['changes']), human_verification='declared_only')
    sources = {f"source/{source['snapshot_ref']}/{name}": (folder / name, _fingerprint(folder / name))
               for name in (*receipt['artifacts'], 'identity.json', 'receipt.json')}
    return dict(summary=summary, output=output_bytes, sources=sources)


def check_review(content, run_root=EXTRACTION_ROOT, *, checked_at=None):
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z') if checked_at is None else checked_at
    return _load_review(content, run_root, now)['summary']


def _receipt(identity, summary):
    return dict(format_version=FORMAT, status='frozen', review_ref=summary['review_ref'],
                frozen_at=identity['recorded_at'], artifacts=identity['artifacts'], summary=summary)


def _verify_directory(directory, reference):
    # 평가 보관기와 향후 records→reviews 호출 사이의 import cycle을 피한다.
    from .evaluation_storage import _sealed, _tree
    import stat
    try:
        require(_sealed(directory, 0o500, stat.S_ISDIR), kind='archive')
        require(all(_sealed(directory / name, 0o400, stat.S_ISREG) for name in ('identity.json', 'receipt.json')), kind='archive')
        identity_bytes = _read(directory / 'identity.json'); identity = decode(identity_bytes, 'archive')
        shape(identity, 'format_version review_ref artifacts recorded_at', kind='archive')
        require(identity['format_version'] == FORMAT and identity['review_ref'] == reference
                and _json(identity) == identity_bytes, kind='archive')
        artifacts = identity['artifacts']
        require(type(artifacts) is dict and {'review.json', 'output.json'} <= set(artifacts), kind='archive')
        _tree(directory, artifacts)
        require(all(_fingerprint(directory / name) == metadata for name, metadata in artifacts.items()), kind='archive')
        packet = _load_review(_read_checked(directory / 'review.json', artifacts['review.json']),
                              directory / 'source', identity['recorded_at'])
        require(packet['summary']['review_ref'] == reference
                and _read(directory / 'output.json') == packet['output'], kind='archive')
        require(artifacts == {name: metadata for name, (_, metadata) in packet['sources'].items()}
                | {name: artifacts[name] for name in ('review.json', 'output.json')}, kind='archive')
        expected = _receipt(identity, packet['summary'])
        require(_read(directory / 'receipt.json') == _json(expected), kind='archive')
    except (ExtractionError, FileNotFoundError, NotADirectoryError):
        raise ExtractionError('HUMAN_REVIEW_INTEGRITY', kind='archive') from None
    return expected


def verify_review(review_ref, root=REVIEW_ROOT):
    text(review_ref, kind='input', pattern=HASH)
    return _verify_directory(_root(root, create=False) / review_ref, review_ref)


def freeze_review(input_path, root=REVIEW_ROOT, run_root=EXTRACTION_ROOT):
    content = _read(input_path); value = _header(content)
    reference = hashlib.sha256(value['review_id'].encode()).hexdigest()
    fingerprint = dict(sha256=hashlib.sha256(content).hexdigest(), size=len(content))
    base = _root(root); destination = base / reference

    def existing():
        receipt = verify_review(reference, base)
        require(receipt['artifacts']['review.json'] == fingerprint, kind='archive', code='HUMAN_REVIEW_CONFLICT')
        return receipt

    if destination.exists() or destination.is_symlink(): return existing()
    packet = _load_review(content, run_root, datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
    payloads = dict(zip(('review.json', 'output.json'), (content, packet['output'])))
    artifacts = {name: metadata for name, (_, metadata) in packet['sources'].items()}
    artifacts.update({name: dict(sha256=hashlib.sha256(raw).hexdigest(), size=len(raw)) for name, raw in payloads.items()})
    temporary = Path(tempfile.mkdtemp(prefix='.human-review-', dir=base))
    try:
        for name, raw in payloads.items(): _write(temporary / name, raw)
        for name, (source, metadata) in packet['sources'].items():
            target = temporary / name; target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _copy(source, target, metadata)
        identity = _identity(temporary, dict(format_version=FORMAT, review_ref=reference, artifacts=artifacts))
        _write(temporary / 'receipt.json', _json(_receipt(identity, packet['summary'])))
        for current, _, names in os.walk(temporary, topdown=False):
            for name in names: (Path(current) / name).chmod(0o400)
            Path(current).chmod(0o500)
        _verify_directory(temporary, reference)
        try: _rename_exclusive(temporary, destination)
        except OSError as error:
            if error.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EACCES) or not destination.exists(): raise
        return existing()
    finally:
        if temporary.exists():
            for current, _, _ in os.walk(temporary): Path(current).chmod(0o700)
            shutil.rmtree(temporary)
