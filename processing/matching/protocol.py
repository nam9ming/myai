"""calc-v1의 크기·형식·참조·시각 경계를 검증한다."""

from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from .engine import MAX_BYTES, OutputLimitError, calculate
from .geometry import segment_distance
from .intervals import KST, WEEKDAYS, midnight, instant_ns

UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
HASH = r'[0-9a-f]{64}'
STAMP = r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z'
KNOWLEDGE = ('known', 'not_stated', 'ambiguous', 'not_applicable')
RESULTS = ('unchecked', 'verified', 'changed', 'unreachable', 'uncertain')
TYPES = ('construction', 'event', 'traffic')


class ProtocolError(ValueError):
    pass


def check(condition):
    if not condition:
        raise ProtocolError('CALCULATION_INPUT_INVALID')


def shape(node, fields):
    check(type(node) is dict and set(node) == set(fields.split()))


def text(value, pattern=None, nullable=False):
    if value is None and nullable:
        return value
    check(type(value) is str and bool(value.strip()))
    if pattern is not None:
        check(re.fullmatch(pattern, value) is not None)
    return value


def choice(value, values):
    check(type(value) is str and value in values)
    return value


def array(value, required=False):
    check(type(value) is list and (not required or bool(value)))
    return value


def ids(values, pattern=None, required=False):
    for value in array(values, required):
        text(value, pattern)
    check(len(values) == len(set(values)))
    return set(values)


def integer(value, lo, hi):
    check(type(value) is int and lo <= value <= hi)
    return value


def day(value, nullable=False):
    if value is None and nullable:
        return None
    return date.fromisoformat(text(value, r'[0-9]{4}-[0-9]{2}-[0-9]{2}'))


def stamp(value, nullable=False):
    if value is None and nullable:
        return None
    text(value, STAMP)
    datetime.fromisoformat(value)
    return instant_ns(value)


def local_time(value, seconds=True, nullable=False):
    if value is None and nullable:
        return None
    pattern = r'(?:[01][0-9]|2[0-3]):[0-5][0-9]' + (r'(?::[0-5][0-9])?' if seconds else '')
    return time.fromisoformat(text(value, pattern))


def _coordinate(value):
    check(type(value) is list and len(value) == 2)
    for number, limit in zip(value, (180, 90)):
        check(type(number) in (int, float) and math.isfinite(number) and -limit <= number <= limit)


def _field(value, evidence, list_only=False):
    shape(value, 'value knowledge evidence_ids reason')
    known = choice(value['knowledge'], KNOWLEDGE) == 'known'
    check(ids(value['evidence_ids'], required=known) <= evidence)
    text(value['reason'], nullable=True)
    if not known:
        check(value['value'] is None and value['reason'] is not None)
    elif list_only or type(value['value']) is list:
        ids(value['value'])
    else:
        text(value['value'])


def _hours(weekly):
    shape(weekly, ' '.join(WEEKDAYS))
    for hours in weekly.values():
        shape(hours, 'state full_day intervals')
        state = choice(hours['state'], ('open', 'closed', 'unknown'))
        check(type(hours['full_day']) is bool)
        intervals = array(hours['intervals'])
        check(len(intervals) <= 3)
        if state != 'open' or hours['full_day']:
            check(not intervals and (state == 'open' or not hours['full_day']))
            continue
        check(bool(intervals))
        for interval in intervals:
            shape(interval, 'start end end_day_offset')
            lo = local_time(interval['start'], seconds=False)
            hi = local_time(interval['end'], seconds=False)
            offset = integer(interval['end_day_offset'], 0, 1)
            duration = (hi.hour * 60 + hi.minute) + offset * 1440 - (lo.hour * 60 + lo.minute)
            check(0 < duration <= 1440 and lo != hi)


def _source(source, context, now, cutoff, *, evaluation=False):
    shape(source, 'document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256 last_verified_at latest_check_attempt_at check_result current_last_verified_at current_latest_check_attempt_at current_check_result checks')
    for key in ('document_id', 'document_version_id'):
        text(source[key], UUID)
    for key in ('publisher', 'title'):
        text(source[key])
    text(source['official_number'], nullable=True)
    day(source['published_date'], nullable=True)
    text(source['official_url'])
    url = urlsplit(source['official_url'])
    check(url.scheme in ('http', 'https') and bool(url.hostname) and url.username is None
          and re.search(r'[\s\x00-\x1f\x7f]', source['official_url']) is None)
    text(source['text_sha256'], HASH)
    collected = stamp(source['collected_at'])
    check(collected <= (now if evaluation is True or cutoff is None else cutoff))
    previous = verified = None
    result = 'unchecked'
    for attempt in array(source['checks']):
        shape(attempt, 'checked_at result text_sha256')
        at = stamp(attempt['checked_at'])
        result = choice(attempt['result'], RESULTS[1:])
        text(attempt['text_sha256'], HASH)
        check((previous is None or previous < at) and at <= (cutoff if cutoff is not None else now))
        if result == 'verified':
            check(attempt['text_sha256'] == source['text_sha256'])
            verified = at
        previous = at
    check(stamp(source['last_verified_at'], True) == verified
          and stamp(source['latest_check_attempt_at'], True) == previous and source['check_result'] == result)
    check(evaluation is True or verified is not None or context['history_fidelity'] == 'reconstructed')
    current_verified = stamp(source['current_last_verified_at'], True)
    current_latest = stamp(source['current_latest_check_attempt_at'], True)
    current_result = choice(source['current_check_result'], RESULTS)
    check((current_latest is None) == (current_result == 'unchecked'))
    check(current_latest is None or current_latest <= now)
    check(current_verified is None or current_latest is not None and current_verified <= current_latest)
    check(current_result != 'verified' or current_verified == current_latest)
    check(verified is None or current_verified is not None and verified <= current_verified)
    if context['mode'] == 'current':
        check((current_verified, current_latest, current_result) == (verified, previous, result))
    return collected


def _location(location, evidence):
    shape(location, 'location_id name address kind status geometry coverage evidence_ids')
    text(location['location_id'], UUID)
    for field in ('name', 'address'):
        _field(location[field], evidence)
        check(location[field]['value'] is None or type(location[field]['value']) is str)
    kind = choice(location['kind'], ('point', 'segment', 'stops', 'area', 'unknown'))
    status = choice(location['status'], ('verified', 'ambiguous', 'unknown'))
    choice(location['coverage'], ('complete', 'partial', 'unknown'))
    check(ids(location['evidence_ids'], required=status == 'verified') <= evidence)
    geometry = location['geometry']
    check(kind != 'unknown' or geometry is None and status != 'verified')
    if geometry is None:
        check(status != 'verified')
        return
    shape(geometry, 'type coordinates')
    type_ = choice(geometry['type'], ('Point', 'LineString', 'MultiPoint'))
    expected = dict(point='Point', segment='LineString', stops='MultiPoint').get(kind)
    check(expected is None or type_ == expected)
    if type_ == 'Point':
        _coordinate(geometry['coordinates'])
    else:
        coords = array(geometry['coordinates'], required=True)
        check(type_ != 'LineString' or len(coords) >= 2)
        for point in coords:
            _coordinate(point)
        if type_ == 'LineString':
            for a, b in zip(coords, coords[1:]):
                segment_distance(a, a, b)


def _occurrence(occ, locations, evidence):
    shape(occ, 'occurrence_id date_start date_end time_start time_end end_day_offset precision recurrence_dates location_ids evidence_ids knowledge')
    text(occ['occurrence_id'], UUID)
    first, last = day(occ['date_start'], True), day(occ['date_end'], True)
    check(first is None or last is None or first <= last)
    lo, hi = local_time(occ['time_start'], nullable=True), local_time(occ['time_end'], nullable=True)
    offset = integer(occ['end_day_offset'], 0, 1) if occ['end_day_offset'] is not None else None
    precision = choice(occ['precision'], ('exact_time', 'date_only', 'explicit_all_day', 'unknown'))
    knowledge = choice(occ['knowledge'], KNOWLEDGE)
    check((precision == 'unknown') != (knowledge == 'known'))
    check(ids(occ['evidence_ids'], required=precision != 'unknown') <= evidence)
    if precision != 'unknown':
        check(first is not None and last is not None)
    if precision == 'exact_time':
        check(lo is not None and hi is not None and offset is not None)
    elif precision != 'unknown':
        check(lo is None and hi is None and offset is None)
    explicit_dates = first is not None and last is not None and first < last and occ['recurrence_dates'] is None
    if lo is not None and hi is not None and offset is not None and not explicit_dates:
        seconds = lambda t: t.hour * 3600 + t.minute * 60 + t.second
        check(0 < seconds(hi) + offset * 86400 - seconds(lo) <= 86400)
    recurrence = occ['recurrence_dates']
    if recurrence is not None:
        ids(recurrence)
        for value in recurrence:
            d = day(value)
            check((first is None or first <= d) and (last is None or d <= last))
    check(ids(occ['location_ids'], UUID, required=True) <= locations)


def _event(event, sources):
    shape(event, 'event_id revision_id title types applicability exceptions route_names stop_names directions lifecycle lifecycle_evidence_ids source_version_ids area_membership document_links relations occurrences locations evidence')
    text(event['event_id'], UUID)
    text(event['revision_id'], UUID)
    text(event['title'])
    check(ids(event['types'], required=True) <= set(TYPES))
    choice(event['area_membership'], ('verified', 'uncertain'))
    versions = ids(event['source_version_ids'], UUID, required=True)
    check(versions <= sources.keys())
    documents = {sources[v]['document_id'] for v in versions}
    evidence = set()
    for item in array(event['evidence']):
        shape(item, 'evidence_id document_version_id block_id quote start_char end_char text_sha256')
        text(item['evidence_id'])
        check(item['evidence_id'] not in evidence)
        evidence.add(item['evidence_id'])
        check(text(item['document_version_id'], UUID) in versions)
        text(item['block_id'])
        text(item['quote'])
        lo, hi = integer(item['start_char'], 0, MAX_BYTES), integer(item['end_char'], 0, MAX_BYTES)
        check(hi - lo == len(item['quote']) and item['text_sha256'] == sources[item['document_version_id']]['text_sha256'])
    for field in ('applicability', 'exceptions', 'route_names', 'stop_names', 'directions'):
        _field(event[field], evidence, list_only=field in ('route_names', 'stop_names', 'directions'))
    lifecycle = choice(event['lifecycle'], ('active', 'cancelled', 'uncertain'))
    check(ids(event['lifecycle_evidence_ids'], required=lifecycle == 'cancelled') <= evidence)
    locations, occurrences = set(), set()
    for location in array(event['locations'], required=True):
        _location(location, evidence)
        check(location['location_id'] not in locations)
        locations.add(location['location_id'])
    for occ in array(event['occurrences'], required=True):
        _occurrence(occ, locations, evidence)
        check(occ['occurrence_id'] not in occurrences)
        occurrences.add(occ['occurrence_id'])
    linked = set()
    for link in array(event['document_links'], required=True):
        shape(link, 'document_id role evidence_ids')
        check(text(link['document_id'], UUID) in documents and link['document_id'] not in linked)
        linked.add(link['document_id'])
        choice(link['role'], ('original', 'correction', 'cancellation', 'repost'))
        check(ids(link['evidence_ids'], required=True) <= evidence)
    check(linked == documents)
    for relation in array(event['relations']):
        shape(relation, 'from_document_id to_document_id type reason created_at')
        check(relation['from_document_id'] in documents and relation['to_document_id'] in documents
              and relation['from_document_id'] != relation['to_document_id'])
        choice(relation['type'], ('corrects', 'cancels', 'reposts', 'duplicates'))
        text(relation['reason'])
        stamp(relation['created_at'])


def validate_scenario(c, point, q, snapshot_id=None):
    shape(c, 'mode case_id server_now anchor_date reference_instant knowledge_cutoff history_fidelity data_kind window_days radius_m rules_version dictionary_version')
    mode = choice(c['mode'], ('current', 'replay'))
    choice(c['data_kind'], ('synthetic', 'real'))
    check(type(c['window_days']) is int and c['window_days'] == 14 and type(c['radius_m']) is int and c['radius_m'] == 500)
    check(c['rules_version'] == 'rules-v1')
    text(c['dictionary_version'])
    now, anchor = stamp(c['server_now']), day(c['anchor_date'])
    # 조회창과 전날 이월을 datetime으로 표현할 수 있어야 한다.
    midnight(anchor) - timedelta(days=1)
    midnight(anchor) + timedelta(days=15)
    cutoff = None
    if mode == 'current':
        check(all(c[key] is None for key in ('case_id', 'reference_instant', 'knowledge_cutoff', 'history_fidelity')))
        check(datetime.fromisoformat(c['server_now']).astimezone(KST).date() == anchor)
    else:
        text(c['case_id'], UUID)
        choice(c['history_fidelity'], ('verified_snapshot', 'reconstructed'))
        reference, cutoff = stamp(c['reference_instant']), stamp(c['knowledge_cutoff'])
        check(cutoff <= reference <= now and datetime.fromisoformat(c['reference_instant']).astimezone(KST).date() == anchor)
    shape(point, 'point_id longitude latitude')
    text(point['point_id'], UUID)
    _coordinate([point['longitude'], point['latitude']])
    shape(q, 'point_id weekly_hours mode case_id types snapshot_id selection sort')
    check(q['point_id'] == point['point_id'] and q['mode'] == mode and q['case_id'] == c['case_id']
          and q['snapshot_id'] in (None, snapshot_id))
    check(ids(q['types']) <= set(TYPES))
    choice(q['selection'], ('candidate', 'needs_check', 'cancelled'))
    choice(q['sort'], ('start', 'distance'))
    _hours(q['weekly_hours'])
    return now, cutoff


def validate(payload):
    shape(payload, 'protocol_version request_id snapshot_id snapshot_checksum context point query events source_versions')
    check(payload['protocol_version'] == 'calc-v1')
    text(payload['request_id'])
    check(len(payload['request_id']) <= 128)
    text(payload['snapshot_id'], UUID)
    text(payload['snapshot_checksum'], HASH)
    c = payload['context']
    now, cutoff = validate_scenario(c, payload['point'], payload['query'], payload['snapshot_id'])
    sources = {}
    for source in array(payload['source_versions']):
        _source(source, c, now, cutoff)
        check(source['document_version_id'] not in sources)
        sources[source['document_version_id']] = source
    event_ids, revision_ids = set(), set()
    for event in array(payload['events']):
        _event(event, sources)
        check(event['event_id'] not in event_ids and event['revision_id'] not in revision_ids)
        event_ids.add(event['event_id'])
        revision_ids.add(event['revision_id'])


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        check(key not in result)
        result[key] = value
    return result


def _tree(value, depth=0):
    check(depth <= 100)
    if type(value) is str:
        value.encode('utf-8', errors='strict')
    elif type(value) is float:
        check(math.isfinite(value))
    elif type(value) is list:
        for item in value:
            _tree(item, depth + 1)
    elif type(value) is dict:
        for key, item in value.items():
            _tree(key, depth + 1)
            _tree(item, depth + 1)


def run(content):
    try:
        check(type(content) is bytes and len(content) <= MAX_BYTES)
        payload = json.loads(content.decode('utf-8', errors='strict'), object_pairs_hook=_pairs,
                             parse_constant=lambda _: check(False))
        _tree(payload)
        validate(payload)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
        raise ProtocolError('CALCULATION_INPUT_INVALID') from exc
    result = calculate(payload)
    result.update(protocol_version='calc-v1', request_id=payload['request_id'], snapshot_id=payload['snapshot_id'],
                  input_sha256=hashlib.sha256(content).hexdigest(), rules_version=payload['context']['rules_version'])
    return result
