"""문서·사건 연결을 보존하는 D08 분할 검증. 원문·금표는 읽지 않는다."""

from collections import deque
import hashlib
from urllib.parse import urlsplit, urlunsplit

from processing.extraction.metadata import stamp
from processing.extraction.schema import CHOICES, HASH, UUID
from processing.extraction.validation import array, decode, ids, require, shape, text

FEATURES = ('unknown_date', 'unknown_time', 'multiple_times', 'multiple_locations')
RELATIONS = ('corrects', 'cancels', 'reposts', 'duplicates')


def _check(condition, code='DATASET_INVALID'):
    require(condition, kind='input', code=code)


def _id(value):
    return text(value, kind='input', pattern=UUID)


def _label(value, limit=128):
    text(value, kind='input')
    _check(len(value) <= limit and not any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value))
    return value


def _ids(value, minimum=0):
    result = ids(value, '$', 'input', minimum)
    for entry in result:
        _id(entry)
    return result


def _choices(value, choices):
    result = ids(value, '$', 'input')
    _check(result <= set(choices))
    return result


def _parse_manifest(content):
    value = decode(content, 'input')
    shape(value, 'schema_version dataset_version data_kind documents events relations split_assignments grouping_review', kind='input')
    _check(value['schema_version'] == 'dataset-manifest-v1' and value['data_kind'] in ('real', 'synthetic'))
    version = _label(value['dataset_version'], 100)
    documents, versions, urls = {}, set(), set()
    for doc in array(value['documents'], '$.documents', 'input', 1):
        shape(doc, 'document_id official_url versions types feature_tags exposure_status exposure_note', kind='input')
        identity = _id(doc['document_id'])
        _check(identity not in documents, 'DATASET_DOCUMENT_DUPLICATE')
        url = text(doc['official_url'], kind='input')
        _check(not any(c.isspace() or ord(c) < 32 for c in url))
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme in ('http', 'https') and parsed.hostname and parsed.username is None and parsed.password is None
            port = parsed.port
        except ValueError:
            _check(False)
        _check(valid and (port is None or 1 <= port <= 65535))
        canonical = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, parsed.query, ''))
        _check(canonical not in urls, 'DATASET_DOCUMENT_DUPLICATE'); urls.add(canonical)
        for entry in array(doc['versions'], '$.documents.versions', 'input', 1):
            shape(entry, 'document_version_id input_sha256', kind='input')
            key = _id(entry['document_version_id'])
            _check(key not in versions, 'DATASET_VERSION_DUPLICATE'); versions.add(key)
            text(entry['input_sha256'], kind='input', pattern=HASH)
        _choices(doc['types'], CHOICES['types']); _choices(doc['feature_tags'], FEATURES)
        _check(doc['exposure_status'] in ('development', 'unexposed', 'unknown'))
        text(doc['exposure_note'], kind='input')
        documents[identity] = doc

    parents = {identity: identity for identity in documents}

    def find(identity):
        while parents[identity] != identity:
            parents[identity] = parents[parents[identity]]
            identity = parents[identity]
        return identity

    def join(a, b):
        parents[find(a)] = find(b)

    events, doc_events = {}, {identity: set() for identity in documents}
    for event in array(value['events'], '$.events', 'input'):
        shape(event, 'event_id document_ids split_group_id suspected_duplicate_ids', kind='input')
        identity = _id(event['event_id'])
        _check(identity not in events)
        references = _ids(event['document_ids'], 1)
        _check(references <= documents.keys())
        _id(event['split_group_id'])
        suspects = _ids(event['suspected_duplicate_ids'])
        _check(identity not in suspects)
        first = event['document_ids'][0]
        for reference in references:
            join(first, reference); doc_events[reference].add(identity)
        events[identity] = event
    for event in events.values():
        _check(set(event['suspected_duplicate_ids']) <= events.keys())

    corrections, indegree, edges = {key: [] for key in documents}, dict.fromkeys(documents, 0), set()
    for edge in array(value['relations'], '$.relations', 'input'):
        shape(edge, 'from_document_id to_document_id type reviewed_by reason created_at', kind='input')
        a, b = _id(edge['from_document_id']), _id(edge['to_document_id'])
        _check(a != b and a in documents and b in documents and edge['type'] in RELATIONS)
        key = (a, b, edge['type'])
        _check(key not in edges); edges.add(key)
        _label(edge['reviewed_by']); text(edge['reason'], kind='input'); stamp(edge['created_at'], '$.created_at')
        join(a, b)
        if edge['type'] == 'corrects':
            corrections[a].append(b); indegree[b] += 1
    pending = deque(key for key, degree in indegree.items() if degree == 0)
    visited = 0
    while pending:
        identity = pending.popleft(); visited += 1
        for target in corrections[identity]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    _check(visited == len(documents), 'DATASET_CORRECTION_CYCLE')

    assignments = {}
    for assignment in array(value['split_assignments'], '$.split_assignments', 'input', 1):
        shape(assignment, 'split_group_id document_id split assigned_at assigned_by', kind='input')
        identity = _id(assignment['document_id'])
        _check(identity in documents and identity not in assignments)
        _id(assignment['split_group_id']); _label(assignment['assigned_by'])
        _check(assignment['split'] in ('dev', 'holdout'))
        stamp(assignment['assigned_at'], '$.assigned_at')
        assignments[identity] = assignment
    _check(assignments.keys() == documents.keys())
    components = {}
    for identity in documents:
        components.setdefault(find(identity), []).append(identity)
    group_components = {}
    for component, members in components.items():
        _check(len({assignments[m]['split'] for m in members}) == 1, 'DATASET_SPLIT_LEAK')
        groups = {assignments[m]['split_group_id'] for m in members}
        _check(len(groups) == 1, 'DATASET_GROUP_INVALID')
        group = groups.pop()
        _check(group not in group_components, 'DATASET_GROUP_INVALID')
        group_components[group] = component
    for event in events.values():
        _check(all(assignments[d]['split_group_id'] == event['split_group_id'] for d in event['document_ids']),
               'DATASET_GROUP_INVALID')

    review = value['grouping_review']
    shape(review, 'reviewed_by reviewed_at note', kind='input')
    text(review['note'], kind='input')
    _check((review['reviewed_by'] is None) == (review['reviewed_at'] is None))
    if review['reviewed_by'] is not None:
        _label(review['reviewed_by']); stamp(review['reviewed_at'], '$.reviewed_at')

    splits = {}
    for split in ('dev', 'holdout'):
        selected = {key for key, assignment in assignments.items() if assignment['split'] == split}
        docs = [documents[key] for key in selected]
        splits[split] = dict(documents=len(docs), document_versions=sum(len(d['versions']) for d in docs),
                             events=len(set().union(*(doc_events[key] for key in selected))),
                             groups=len({find(key) for key in selected}),
                             types={kind: sum(kind in d['types'] for d in docs) for kind in CHOICES['types']},
                             features={tag: sum(tag in d['feature_tags'] for d in docs) for tag in FEATURES})
        splits[split]['types']['unknown'] = sum(not d['types'] for d in docs)
    warnings = set()
    holdout = [documents[key] for key, assignment in assignments.items() if assignment['split'] == 'holdout']
    if holdout:
        if review['reviewed_by'] is None: warnings.add('GROUPING_UNREVIEWED')
        elif any(stamp(r['created_at'], '$') > stamp(review['reviewed_at'], '$') for r in value['relations']):
            warnings.add('GROUPING_REVIEW_OUTDATED')
        if any(d['exposure_status'] == 'development' for d in holdout): warnings.add('HOLDOUT_DEVELOPMENT_EXPOSURE')
        if any(d['exposure_status'] == 'unknown' for d in holdout): warnings.add('HOLDOUT_EXPOSURE_UNKNOWN')
        for event in events.values():
            split = assignments[event['document_ids'][0]]['split']
            if any(assignments[events[s]['document_ids'][0]]['split'] != split for s in event['suspected_duplicate_ids']):
                warnings.add('SUSPECTED_DUPLICATE_CROSSES_SPLIT')
    report = dict(protocol_version='dataset-check-v1', status='validated',
                  dataset_ref=hashlib.sha256(version.encode('utf-8')).hexdigest(),
                  manifest_sha256=hashlib.sha256(content).hexdigest(), data_kind=value['data_kind'],
                  counts=dict(documents=len(documents), document_versions=len(versions), events=len(events), groups=len(components)),
                  splits=splits, targets=dict(documents=40, dev=20, holdout=20, data_kind='real'),
                  shortfall=dict(documents=max(0, 40-len(documents)), dev=max(0,20-splits['dev']['documents']),
                                 holdout=max(0,20-splits['holdout']['documents'])),
                  holdout_status='absent' if not holdout else 'review_required' if warnings else 'unexposed_as_declared',
                  holdout_warnings=sorted(warnings))
    return value, report


def validate_manifest(content):
    return _parse_manifest(content)[1]
