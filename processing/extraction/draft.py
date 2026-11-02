"""검증된 원출력을 승인 불가능한 비공개 검토 초안으로 변환한다."""

import hashlib
import json
from pathlib import Path
import uuid

from .archive import DEFAULT_ROOT, _json, _read, _read_checked, _root, _write, freeze_run
from .schema import UUID
from .validation import MAX_BYTES, array, decode, parse_input, parse_output, require, shape, text


def _project_draft(run_id, source, area_id, split_group_id, dictionary_version, root):
    for value in (run_id, area_id, split_group_id):
        text(value, kind='input', pattern=UUID)
    text(dictionary_version, kind='input')
    require(len(dictionary_version) <= 100
            and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in dictionary_version), kind='input')
    shape(source, 'schema_version data_kind documents evidence events', kind='input')
    require(source['schema_version'] == 'source-import-v1' and type(source['documents']) is list
            and len(source['documents']) == 1 and source['evidence'] == [] and source['events'] == [], kind='input')
    doc = source['documents'][0]
    shape(doc, 'document_id publisher official_url title official_number published_date collected_at document_version_id '
          'version_no raw_asset_path raw_sha256 cleaned_text text_sha256 block_index redaction_log preprocessing_version '
          'use_review use_note collection_method latest_check_attempt_at last_verified_at check_result checks', kind='input')
    text(doc['document_id'], kind='input', pattern=UUID)
    packet = freeze_run(run_id, root)
    receipt = packet['receipt']
    require(receipt['status'] == 'validated', kind='input', code='DRAFT_REQUIRES_VALIDATED')
    directory = _root(root, create=False) / packet['snapshot_ref']
    artifacts = receipt['artifacts']
    document = parse_input(_read_checked(directory / 'input.json', artifacts['input.json']))
    metadata = decode(_read_checked(directory / 'metadata.json', artifacts['metadata.json']), 'input')
    projection = dict(data_kind=source['data_kind'], document_version_id=doc['document_version_id'],
                      title=doc['title'], published_date=doc['published_date'], blocks=doc['block_index'])
    require(projection == document and doc['preprocessing_version'] == metadata['preprocessing_version'],
            kind='input', code='DRAFT_SOURCE_MISMATCH')
    cleaned = text(doc['cleaned_text'], kind='input')
    require(hashlib.sha256(cleaned.encode('utf-8')).hexdigest() == doc['text_sha256']
            and all(block['text'] in cleaned for block in document['blocks']), kind='input', code='DRAFT_SOURCE_MISMATCH')
    last = f"attempt-{len(receipt['attempts'])}.output"
    extracted = parse_output(_read_checked(directory / last, artifacts[last]), document)
    namespace = uuid.UUID(run_id)

    def identity(kind, local):
        return str(uuid.uuid5(namespace, json.dumps([kind, local], ensure_ascii=False)))

    evidence_ids = {e['evidence_id']: identity('evidence', e['evidence_id']) for e in extracted['evidence']}

    def field(value):
        return dict(value, evidence_ids=[evidence_ids[e] for e in value['evidence_ids']])

    def citations(values):
        return list(dict.fromkeys(evidence_ids[e] for value in values for e in value['evidence_ids']))

    evidence = [dict(e, evidence_id=evidence_ids[e['evidence_id']], document_version_id=doc['document_version_id'],
                     text_sha256=doc['text_sha256']) for e in extracted['evidence']]
    events = []
    for item in extracted['items']:
        event_id = identity('event', item['local_item_id'])
        locations = [dict(location_id=identity('location', loc['local_location_id']), name=field(loc['name']),
                          address=field(loc['address']), kind=loc['kind']['value'] or 'unknown',
                          status='ambiguous' if any(v['knowledge'] == 'ambiguous' for k, v in loc.items()
                                                    if k != 'local_location_id') else 'unknown',
                          geometry=None, coverage='unknown', source=None, checked_by=None, checked_at=None,
                          evidence_ids=citations([loc[k] for k in ('name', 'address', 'kind')]))
                     for loc in item['locations']]
        occurrences = []
        for occ in item['occurrences']:
            temporal = {k: v for k, v in occ.items() if k not in ('local_occurrence_id', 'location_refs')}
            a, b, lo, hi, offset, all_day, recurrence = [occ[k]['value'] for k in (
                'date_start', 'date_end', 'time_start', 'time_end', 'end_day_offset', 'all_day', 'recurrence_text')]
            precision = 'unknown'
            if a is not None and b is not None and recurrence is None and all(
                    value['knowledge'] != 'ambiguous' for value in temporal.values()):
                if all_day is True and lo is None and hi is None and offset is None:
                    precision = 'explicit_all_day'
                elif all_day is False and lo is not None and hi is not None and offset is not None:
                    precision = 'exact_time'
                elif all(occ[k]['knowledge'] == 'not_stated' for k in ('time_start', 'time_end', 'end_day_offset', 'all_day')):
                    precision = 'date_only'
            refs = [identity('location', ref) for ref in occ['location_refs']]
            if not refs:
                unknown = dict(value=None, knowledge='not_stated', evidence_ids=[], reason='AI 장소 대응 미상')
                location_id = identity('unbound-location', occ['local_occurrence_id'])
                locations.append(dict(location_id=location_id, name=unknown, address=unknown, kind='unknown',
                                      status='unknown', geometry=None, coverage='unknown', source=None,
                                      checked_by=None, checked_at=None, evidence_ids=[]))
                refs = [location_id]
            knowledge = ('ambiguous' if any(v['knowledge'] in ('known', 'ambiguous') for v in temporal.values())
                         else 'not_applicable' if all(v['knowledge'] == 'not_applicable' for v in temporal.values())
                         else 'not_stated')
            occurrences.append(dict(occurrence_id=identity('occurrence', occ['local_occurrence_id']),
                                    date_start=a, date_end=b, time_start=lo, time_end=hi, end_day_offset=offset,
                                    precision=precision, recurrence_dates=None, location_ids=refs,
                                    evidence_ids=citations(temporal.values()),
                                    knowledge='known' if precision != 'unknown' else knowledge,
                                    normalization_note='AI 초안; 사람 정규화 검토 필요: ' + _json(temporal).decode().rstrip()))
        revision = dict(revision_id=identity('revision', item['local_item_id']), event_id=event_id, revision_no=1,
                        title=item['title']['value'], types=item['types']['value'] or [], occurrences=occurrences,
                        locations=locations, lifecycle=item['lifecycle']['value'] or 'uncertain',
                        lifecycle_evidence_ids=citations([item['lifecycle']]), human_overrides=[],
                        review_status='draft', reviewer_id=None, reviewed_at=None, publication_intent='hidden',
                        origin='ai_draft', source_version_ids=[doc['document_version_id']], originating_run_ids=[run_id],
                        rules_version='rules-v1', dictionary_version=dictionary_version)
        for name in ('applicability', 'exceptions', 'route_names', 'stop_names', 'directions'):
            revision[name] = field(item[name])
        events.append(dict(event_id=event_id, area_id=area_id, area_membership='uncertain',
                           document_links=[dict(document_id=doc['document_id'], role='original',
                                                evidence_ids=list(evidence_ids.values()))],
                           relations=[], suspected_duplicate_ids=[], split_group_id=split_group_id,
                           expected_revision_no=0, revision=revision))
    return dict(schema_version='ai-draft-import-v1', data_kind=source['data_kind'], originating_run_id=run_id,
                documents=source['documents'], evidence=evidence, events=events)


def _content(batch):
    try:
        content = _json(batch)
    except (TypeError, ValueError):
        require(False, kind='input', code='DRAFT_SOURCE_INVALID')
    require(len(content) <= MAX_BYTES, kind='input', code='DRAFT_OUTPUT_TOO_LARGE')
    return content


def draft_run(run_id, source_path, output_path, area_id, split_group_id, dictionary_version, root=DEFAULT_ROOT):
    source = decode(_read(source_path), 'input')
    batch = _project_draft(run_id, source, area_id, split_group_id, dictionary_version, root)
    content = _content(batch)
    path = Path(output_path).expanduser().absolute()
    require(path.name not in ('', '.', '..'), kind='input')
    destination = _root(path.parent) / path.name
    _write(destination, content)
    return dict(schema_version='ai-draft-result-v1', run_id=run_id, data_kind=batch['data_kind'],
                status='draft', review_required=True, event_ids=[event['event_id'] for event in batch['events']],
                output_sha256=hashlib.sha256(content).hexdigest())


def check_draft(run_id, content, root=DEFAULT_ROOT):
    batch = decode(content, 'input')
    shape(batch, 'schema_version data_kind originating_run_id documents evidence events', kind='input')
    require(batch['schema_version'] == 'ai-draft-import-v1' and batch['originating_run_id'] == run_id, kind='input')
    events = array(batch['events'], '$.events', 'input')
    area, split, dictionary = '00000000-0000-0000-0000-000000000000', '00000000-0000-0000-0000-000000000000', 'no-event'
    if events:
        event = events[0]
        require(type(event) is dict and type(event.get('revision')) is dict, kind='input')
        area, split, dictionary = event.get('area_id'), event.get('split_group_id'), event['revision'].get('dictionary_version')
    source = dict(schema_version='source-import-v1', data_kind=batch['data_kind'],
                  documents=batch['documents'], evidence=[], events=[])
    expected = _project_draft(run_id, source, area, split, dictionary, root)
    require(_content(batch) == _content(expected), kind='input', code='DRAFT_MISMATCH')
    return dict(protocol_version='ai-draft-check-v1', status='validated', run_id=run_id,
                input_sha256=hashlib.sha256(content).hexdigest())
