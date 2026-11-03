"""비공개 평가의 검토 문맥과 각 원출력의 사실만 기존 계산기에 전달한다."""

import copy
from datetime import date
from decimal import Decimal
import hashlib
import math
import unicodedata

from processing.extraction.draft import _project_output
from processing.extraction.validation import require
from processing.matching import protocol
from processing.matching.engine import _classify
from processing.matching.geometry import locate, segment_distance
from processing.matching.intervals import DAY, business_hours, midnight

CLASSES = ('candidate', 'needs_check', 'cancelled', 'excluded')
REASONS = ('WINDOW_OUTSIDE', 'BUSINESS_CLOSED', 'TIME_NO_OVERLAP', 'DISTANCE_OUTSIDE',
           'DATE_UNKNOWN', 'TIME_UNKNOWN', 'BUSINESS_UNKNOWN', 'LOCATION_UNKNOWN',
           'AREA_UNCERTAIN', 'SOURCE_STALE', 'SOURCE_UNREACHABLE', 'RELATION_UNCERTAIN', 'CANCELLED')
STATES = ('classified', 'not_computable', 'unavailable')


def _check(condition, code='MATCHING_CONTEXT_INVALID'):
    require(condition, kind='input', code=code)


def _coordinate(value):
    protocol.check(type(value) is list and len(value) == 2)
    for number, bound in zip(value, (180, 90)):
        protocol.check(type(number) in (int, float, Decimal))
        finite = number.is_finite() if type(number) is Decimal else math.isfinite(number)
        protocol.check(finite and -bound <= number <= bound)
    return [float(number) for number in value]


def _geometry(value, kind):
    if value is None:
        return None
    protocol.check(kind != 'unknown')
    protocol.shape(value, 'type coordinates')
    type_ = protocol.choice(value['type'], ('Point', 'LineString', 'MultiPoint'))
    expected = dict(point='Point', segment='LineString', stops='MultiPoint').get(kind)
    protocol.check(expected is None or type_ == expected)
    if type_ == 'Point':
        coordinates = _coordinate(value['coordinates'])
    else:
        coordinates = [_coordinate(point) for point in protocol.array(value['coordinates'], required=True)]
        if type_ == 'LineString':
            protocol.check(len(coordinates) >= 2)
            for a, b in zip(coordinates, coordinates[1:]):
                segment_distance(a, a, b)
    return dict(type=type_, coordinates=coordinates)


def validate_dictionary(value, evaluated_at):
    """원래 수의 범위를 검사한 뒤 계산용 복사본의 좌표만 float로 변환한다."""
    try:
        protocol.shape(value, 'dictionary_version entries')
        protocol.text(value['dictionary_version'])
        protocol.check(len(value['dictionary_version']) <= 100)
        at = protocol.stamp(evaluated_at)
        result = copy.deepcopy(value)
        entries = set()
        for entry in protocol.array(result['entries']):
            protocol.shape(entry, 'entry_id name name_aliases address address_aliases kind geometry coverage source checked_by checked_at')
            key = protocol.text(entry['entry_id'], protocol.UUID)
            protocol.check(key not in entries); entries.add(key)
            for field in ('name', 'address'):
                protocol.text(entry[field], nullable=True)
                protocol.ids(entry[field + '_aliases'])
            protocol.check(entry['name'] is not None or entry['address'] is not None)
            kind = protocol.choice(entry['kind'], ('point', 'segment', 'stops', 'area', 'unknown'))
            protocol.choice(entry['coverage'], ('complete', 'partial', 'unknown'))
            for field in ('source', 'checked_by'):
                protocol.text(entry[field])
            protocol.check(protocol.stamp(entry['checked_at']) <= at)
            entry['geometry'] = _geometry(entry['geometry'], kind)
        return result
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _check(False, 'MATCHING_DICTIONARY_INVALID')


def prepare_case(case, cohort, dictionary, *, data_kind, evaluated_at):
    """전체 cohort와 고정 case를 대조하며 cutoff 뒤 수집도 관측으로 유지한다."""
    try:
        protocol.shape(case, 'case_id context point query source_versions area_memberships expected')
        protocol.text(case['case_id'], protocol.UUID)
        point = copy.deepcopy(case['point'])
        point['longitude'], point['latitude'] = _coordinate([point['longitude'], point['latitude']])
        context, query = case['context'], case['query']
        now, cutoff = protocol.validate_scenario(context, point, query)
        protocol.check(now <= protocol.stamp(evaluated_at) and query['snapshot_id'] is None)
        protocol.check(context['dictionary_version'] == dictionary['dictionary_version'] and context['data_kind'] == data_kind)
        protocol.check(context['mode'] != 'replay' or context['case_id'] == case['case_id'])
        sources, availability = {}, {}
        for source in protocol.array(case['source_versions']):
            collected = protocol._source(source, context, now, cutoff, evaluation=True)
            version = source['document_version_id']
            protocol.check(version in cohort and version not in sources)
            document = cohort[version]
            protocol.check(source['document_id'] == document['document_id']
                           and source['official_url'] == document['official_url']
                           and source['title'] == document['input']['title']
                           and source['published_date'] == document['input']['published_date']
                           and version == document['input']['document_version_id'])
            sources[version] = copy.deepcopy(source)
            availability[version] = cutoff is None or collected <= cutoff
        protocol.check(sources.keys() == cohort.keys())
        events = {event for document in cohort.values() for event in document['anchors'].values()}
        memberships = {}
        for item in protocol.array(case['area_memberships']):
            protocol.shape(item, 'entry_id status')
            key = protocol.text(item['entry_id'], protocol.UUID)
            protocol.check(key not in memberships)
            memberships[key] = protocol.choice(item['status'], ('verified', 'uncertain', 'outside'))
        protocol.check(memberships.keys() == {entry['entry_id'] for entry in dictionary['entries']})
        expected = set()
        for item in protocol.array(case['expected']):
            protocol.shape(item, 'event_id classification reason_codes note')
            key = protocol.text(item['event_id'], protocol.UUID)
            protocol.check(key not in expected); expected.add(key)
            protocol.choice(item['classification'], CLASSES)
            protocol.check(protocol.ids(item['reason_codes']) <= set(REASONS))
            protocol.text(item['note'])
        protocol.check(expected == events)
        start = midnight(date.fromisoformat(context['anchor_date']))
        end = start + 14 * DAY
        known, unknown = business_hours(query['weekly_hours'], start, end)
        return dict(case_id=case['case_id'], context=copy.deepcopy(context), point=point, query=copy.deepcopy(query),
                    source_versions=sources, source_availability=availability, area_memberships=memberships,
                    _start=start, _end=end, _known=known, _unknown=unknown)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _check(False)


def _normalized(value):
    return ' '.join(unicodedata.normalize('NFC', value).split()).casefold()


def _reviewed_location(raw, projected, dictionary):
    candidates = None
    for field in ('name', 'address'):
        if raw[field]['knowledge'] != 'known':
            continue
        value = _normalized(raw[field]['value'])
        matches = {i for i, entry in enumerate(dictionary['entries'])
                   if value in {_normalized(text) for text in [entry[field], *entry[field + '_aliases']] if text is not None}}
        candidates = matches if candidates is None else candidates & matches
    if candidates is None or len(candidates) != 1:
        return projected, None
    entry = dictionary['entries'][next(iter(candidates))]
    if raw['kind']['knowledge'] == 'known' and raw['kind']['value'] != entry['kind']:
        return projected, None
    # 위치·종류의 원출력은 보존하고 검토 사전의 계산용 geometry만 연결한다.
    return (dict(projected, kind=entry['kind'], status='verified' if entry['geometry'] is not None else 'unknown',
                 geometry=entry['geometry'], coverage=entry['coverage']), entry['entry_id'])


def classify_output(output, annotation, document, case, dictionary, *, projection_id):
    """실패와 빈 출력을 구별하고 공개 selection/sort 없이 모든 item을 계산한다."""
    if output is None:
        return None
    protocol.text(projection_id, protocol.UUID)
    version = document['input']['document_version_id']
    body_hash = hashlib.sha256('\n'.join(block['text'] for block in document['input']['blocks']).encode('utf-8')).hexdigest()
    source = case['source_versions'][version]
    # 이 UUID와 블록 hash는 내부 투영용이며 실제 D05 실행·D03 본문을 뜻하지 않는다.
    carrier = dict(data_kind=case['context']['data_kind'], documents=[dict(document_id=document['document_id'],
        document_version_id=version, text_sha256=body_hash)])
    batch = _project_output(projection_id, carrier, output, case['case_id'], document['split_group_id'],
                            dictionary['dictionary_version'], label='매칭 평가 사실 투영')
    links = {link['local_item_id']: link for link in annotation.get('item_links', [])}
    _check(set(links) == {item['local_item_id'] for item in output['items']})
    result = {}
    for item, projected in zip(output['items'], batch['events']):
        local = item['local_item_id']
        event = projected['revision']
        link = links[local]
        _check(link['kind'] in ('match', 'duplicate', 'additional')
               and (link['slot_id'] is None if link['kind'] == 'additional' else link['slot_id'] in document['anchors']))
        resolved = [_reviewed_location(raw, loc, dictionary) for raw, loc in zip(item['locations'], event['locations'])]
        # 빈 refs의 미상 위치와 사용하지 않은 위치를 구역 확정 근거로 삼지 않는다.
        resolved.extend((loc, None) for loc in event['locations'][len(item['locations']):])
        entries = {loc['location_id']: entry_id for loc, entry_id in resolved}
        memberships = [case['area_memberships'].get(entries[location_id])
                       for occurrence in event['occurrences'] for location_id in occurrence['location_ids']]
        membership = ('verified' if 'verified' in memberships else
                      'outside' if memberships and all(status == 'outside' for status in memberships) else 'uncertain')
        limitations = ['recurrence_text_not_normalized'] if any(
            occurrence['recurrence_text']['knowledge'] == 'known' for occurrence in item['occurrences']) else []
        row = dict(state='classified', classification=None, reason_codes=None, disposition='engine',
                   projection_limitations=limitations, projection_body_sha256=body_hash, source_text_sha256=source['text_sha256'])
        if not case['source_availability'][version]:
            row.update(state='unavailable', disposition='not_available_at_cutoff')
        elif case['query']['types'] and item['types']['knowledge'] != 'known':
            row.update(state='not_computable', disposition='type_unknown')
        elif case['query']['types'] and not set(case['query']['types']).intersection(item['types']['value']):
            row.update(classification='excluded', reason_codes=[], disposition='type_filter')
        elif membership == 'outside':
            row.update(classification='excluded', reason_codes=[], disposition='area_filter')
        else:
            event['area_membership'] = membership
            point = (case['point']['longitude'], case['point']['latitude'])
            located = {loc['location_id']: locate(point, loc) for loc, _ in resolved}
            classification, reasons, *_ = _classify(event, located, case['_known'], case['_unknown'],
                case['_start'], case['_end'], case['source_versions'], case['context'])
            row.update(classification=classification or 'excluded', reason_codes=sorted(reasons))
        result[local] = row
    return result
