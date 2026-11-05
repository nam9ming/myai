"""사람 수정 원본을 workflow 없는 D06 사실로 투영하고 전체 출처를 연결한다."""

from datetime import datetime, timezone
import hashlib

from processing.extraction.archive import REPO, _fingerprint, _json, _read, _read_checked, _root, verify_run
from processing.extraction.draft import _content, _context, _project_output, _source
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH
from processing.extraction.validation import decode, parse_input, parse_output, require, shape, text
from .dataset import _id
from .reviews import REVIEW_ROOT, verify_review

HANDOFF_ROOT = REPO / 'data/private/evaluation/handoffs'


def _check(condition, code='HANDOFF_INVALID'):
    require(condition, kind='input', code=code)


def _header(content):
    value = decode(content, 'input')
    shape(value, 'schema_version handoff_id review_ref review_receipt_sha256 source area_id split_group_id dictionary_version', kind='input')
    _check(value['schema_version'] == 'human-handoff-v1')
    _id(value['handoff_id'])
    for key in ('review_ref', 'review_receipt_sha256'): text(value[key], kind='input', pattern=HASH)
    return value


def project_handoff(content, review_root=REVIEW_ROOT, *, projected_at=None):
    value = _header(content)
    if projected_at is None: projected_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    reference = value['review_ref']; base = _root(review_root, create=False); directory = base / reference
    receipt = verify_review(reference, base)
    raw = _read(directory / 'receipt.json')
    _check(raw == _json(receipt) and hashlib.sha256(raw).hexdigest() == value['review_receipt_sha256'], 'HANDOFF_REVIEW_MISMATCH')
    _check(stamp(receipt['frozen_at'], '$') <= stamp(projected_at, '$'), 'HANDOFF_TIME_INVALID')
    artifacts = receipt['artifacts']
    review = decode(_read_checked(directory / 'review.json', artifacts['review.json']), 'archive')
    prefix = 'source/' + review['source']['snapshot_ref']
    parent_folder = directory / prefix
    parent = verify_run(review['source']['run_id'], parent_folder.parent)
    _check(_fingerprint(parent_folder / 'receipt.json') == artifacts[f'{prefix}/receipt.json'], 'HANDOFF_REVIEW_MISMATCH')
    metadata = decode(_read_checked(directory / f'{prefix}/metadata.json', artifacts[f'{prefix}/metadata.json']), 'archive')
    document = parse_input(_read_checked(directory / f'{prefix}/input.json', artifacts[f'{prefix}/input.json']))
    output = parse_output(_read_checked(directory / 'output.json', artifacts['output.json']), document)
    context = {key: value[key] for key in ('area_id', 'split_group_id', 'dictionary_version')}
    doc = _context(parent['run_id'], value['source'], **context)
    _source(value['source'], doc, document, metadata)
    batch = _project_output(parent['run_id'], value['source'], output, **context, label='사람 수정 원본')
    events = []
    for event in batch['events']:
        facts = event.pop('revision'); event.pop('expected_revision_no')
        # 실제 DB 전후 값·revision 번호는 Java 연결 단계에서 결정한다.
        for key in ('revision_id', 'revision_no', 'origin', 'review_status', 'publication_intent',
                    'reviewer_id', 'reviewed_at', 'human_overrides'): facts.pop(key)
        events.append(dict(event, facts=facts))
    projection = dict(schema_version='human-handoff-projection-v1', handoff_id=value['handoff_id'],
        handoff_ref=hashlib.sha256(value['handoff_id'].encode()).hexdigest(), projected_at=projected_at,
        review=dict(review_id=receipt['summary']['review_id'], review_ref=reference,
                    receipt_sha256=value['review_receipt_sha256']),
        parent=dict(run_id=parent['run_id'], receipt_sha256=review['source']['receipt_sha256'],
                    status=parent['status'], execution_mode=parent['execution_mode']),
        context=context, data_kind=batch['data_kind'], documents=batch['documents'], evidence=batch['evidence'], events=events)
    raw_projection = _content(projection)
    summary = dict(protocol_version='human-handoff-summary-v1', status='projection_only', backend_import_supported=False,
        review_required=True, handoff_ref=projection['handoff_ref'], data_kind=projection['data_kind'],
        review_ref=reference, source_run_id=parent['run_id'], source_status=parent['status'],
        source_execution_mode=parent['execution_mode'], event_count=len(events), evidence_count=len(batch['evidence']),
        projection_sha256=hashlib.sha256(raw_projection).hexdigest(),
        review_basis=receipt['summary']['review_basis'], review_duration_ns=receipt['summary']['review_duration_ns'])
    sources = {f'review/{reference}/{name}': (directory / name, _fingerprint(directory / name))
               for name in (*artifacts, 'identity.json', 'receipt.json')}
    return dict(projection=projection, summary=summary, sources=sources)
