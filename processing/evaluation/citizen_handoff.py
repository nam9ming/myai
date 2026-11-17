"""검증한 시민 수정 원본을 정규화·workflow 없는 D06 사실로 투영한다."""

import copy
import json
import uuid

from processing.extraction.citizen import FACT_FIELDS
from processing.extraction.validation import require


def project_output(run_id, source, extracted, split_group_id):
    doc = source['documents'][0]
    namespace = uuid.UUID(run_id)

    def identity(kind, local):
        return str(uuid.uuid5(namespace, json.dumps([kind, local], ensure_ascii=False)))

    evidence_ids = {entry['evidence_id']: identity('evidence', entry['evidence_id']) for entry in extracted['evidence']}

    def field(value):
        return dict(copy.deepcopy(value), evidence_ids=[evidence_ids[key] for key in value['evidence_ids']])

    evidence = [dict(entry, evidence_id=evidence_ids[entry['evidence_id']], document_version_id=doc['document_version_id'],
                     text_sha256=doc['text_sha256']) for entry in extracted['evidence']]
    events = []
    for item in extracted['items']:
        for name in ('title', 'categories'):
            require(item[name]['knowledge'] == 'known', kind='input', code='HANDOFF_CITIZEN_FACTS_UNRESOLVED')
        references = {key for name in ('title', 'categories', *FACT_FIELDS) for key in item[name]['evidence_ids']}
        event_id = identity('event', item['local_item_id'])
        facts = dict(event_id=event_id, title=item['title']['value'], categories=list(item['categories']['value']),
                     **{name: field(item[name]) for name in FACT_FIELDS},
                     source_version_ids=[doc['document_version_id']], originating_run_ids=[run_id])
        events.append(dict(event_id=event_id, document_links=[dict(document_id=doc['document_id'], role='original',
                           evidence_ids=[mapped for key, mapped in evidence_ids.items() if key in references])], relations=[], suspected_duplicate_ids=[],
                           split_group_id=split_group_id, facts=facts))
    return dict(data_kind=source['data_kind'], documents=source['documents'], evidence=evidence, events=events)
