"""검토된 불변 사실을 조회 조건에 따라 계산한다. 외부 상태를 읽거나 쓰지 않는다."""

from collections import Counter, defaultdict
import copy
from datetime import date, datetime, timezone
import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

from .geometry import locate
from .intervals import KST, DAY, midnight, business_hours, occurrence_intervals, union, intersect, subtract, instant_ns

FIELDS = ('applicability', 'exceptions', 'route_names', 'stop_names', 'directions')
FACTS = ('event_id', 'revision_id', 'title', 'types', 'lifecycle', 'lifecycle_evidence_ids',
         'area_membership', 'document_links', 'relations', 'source_version_ids', 'occurrences')
SOURCE_FIELDS = ('document_id', 'document_version_id', 'publisher', 'title', 'official_number',
                 'published_date', 'collected_at', 'last_verified_at', 'latest_check_attempt_at', 'check_result',
                 'current_last_verified_at', 'current_latest_check_attempt_at', 'current_check_result')
WARNINGS = {
    'DATE_UNKNOWN': '날짜가 미상입니다. 원문에서 기간을 확인해 주세요.',
    'TIME_UNKNOWN': '정확한 시간이 미상입니다. 종일 안내로 해석하지 않습니다.',
    'BUSINESS_UNKNOWN': '영업시간 미입력 구간이 있어 중첩을 확정할 수 없습니다.',
    'LOCATION_UNKNOWN': '위치나 전체 구간이 확인되지 않아 거리를 확정할 수 없습니다.',
    'AREA_UNCERTAIN': '시범 구역 관련성도 확인이 필요합니다.',
    'SOURCE_STALE': '마지막 원문 확인 이후 최신 상태 재확인이 필요합니다.',
    'SOURCE_UNREACHABLE': '원문 연결에 실패했습니다. 마지막 성공 확인과 링크를 유지합니다.',
    'RELATION_UNCERTAIN': '정정·취소 관계가 미확정입니다. 원문을 확인해 주세요.',
    'CANCELLED': '취소 전 안내의 기간·장소는 범위 조회에만 사용합니다.',
}
MAX_BYTES = 8 * 1024 * 1024


class OutputLimitError(ValueError):
    pass


def _encoded_size(value, limit):
    size = 0
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode('utf-8'))
        if size > limit:
            raise OutputLimitError('CALCULATION_OUTPUT_TOO_LARGE')
    return size


def utc(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _select(node, fields):
    return {key: copy.deepcopy(node[key]) for key in fields}


def _public_event(event, sources, synthetic):
    result = _select(event, FACTS)
    result['field_values'] = _select(event, FIELDS)
    result.update({key: copy.deepcopy(event[key]['value']) for key in FIELDS})
    result['locations'] = []
    for location in event['locations']:
        loc = _select(location, ('location_id', 'kind', 'status', 'geometry', 'coverage', 'evidence_ids'))
        loc.update(name=location['name']['value'], address=location['address']['value'],
                   field_values=_select(location, ('name', 'address')))
        result['locations'].append(loc)
    result['source_refs'] = []
    for version in event['source_version_ids']:
        source = sources[version]
        ref = _select(source, SOURCE_FIELDS)
        ref.update(url=source['official_url'], is_fixture=synthetic)
        result['source_refs'].append(ref)
    result['evidence'] = []
    for evidence in event['evidence']:
        public = copy.deepcopy(evidence)
        public.update(source_document_id=sources[evidence['document_version_id']]['document_id'], is_fixture=synthetic)
        result['evidence'].append(public)
    return result


def _source_reasons(event, sources, context):
    reasons = set()
    now = instant_ns(context['server_now'])
    for version in event['source_version_ids']:
        source = sources[version]
        verified = source['last_verified_at']
        bad = source['check_result'] != 'verified'
        if context['mode'] == 'current' and verified:
            bad |= now - instant_ns(verified) > 86_400_000_000_000
        if verified is None or bad:
            reasons.add('SOURCE_STALE')
        if source['check_result'] == 'unreachable':
            reasons.add('SOURCE_UNREACHABLE')
    return reasons


def _spatial(occ, locations):
    values = [locations[key] for key in occ['location_ids']]
    if any(state is True for state, _, _ in values):
        state = True
    elif values and all(state is False for state, _, _ in values):
        state = False
    else:
        state = None
    return state, values


def _classify(event, locations, known, unknown, start, end, sources, context):
    reasons, confirmed, uncertain, matched, distances, starts = set(), [], [], [], [], []
    any_true = any_unknown = False
    for occ in event['occurrences']:
        exact, spans = occurrence_intervals(occ, start, end)
        if not spans:
            reasons.add('WINDOW_OUTSIDE')
            continue
        overlaps = intersect(spans, known)
        maybe_business = intersect(spans, unknown)
        if not overlaps and not maybe_business:
            reasons.add('BUSINESS_CLOSED' if not known and not unknown else 'TIME_NO_OVERLAP')
            continue
        state, measures = _spatial(occ, locations)
        if state is False:
            reasons.add('DISTANCE_OUTSIDE')
            continue
        distances.extend(measures)
        if occ['date_start'] is not None:
            starts.append(spans[0][0])
        if state is None or any(raw is None for _, raw, _ in measures):
            reasons.add('LOCATION_UNKNOWN')
        if not exact:
            reasons.add('DATE_UNKNOWN' if occ['date_start'] is None or occ['date_end'] is None else 'TIME_UNKNOWN')
        if maybe_business:
            reasons.add('BUSINESS_UNKNOWN')
        if exact and overlaps and state is True:
            any_true = True
            confirmed.extend(overlaps)
            matched.append(occ['occurrence_id'])
        else:
            any_unknown = True
        if not exact or state is None:
            uncertain.extend(overlaps)
        uncertain.extend(maybe_business)
    if not any_true and not any_unknown:
        return None, reasons, [], None, None, None, [], None
    reasons.update(_source_reasons(event, sources, context))
    if event['area_membership'] == 'uncertain':
        reasons.add('AREA_UNCERTAIN')
    if event['lifecycle'] == 'uncertain':
        reasons.add('RELATION_UNCERTAIN')
    if event['lifecycle'] == 'cancelled':
        classification = 'cancelled'
        reasons.add('CANCELLED')
    elif any_true and not reasons.intersection({'SOURCE_STALE', 'AREA_UNCERTAIN', 'RELATION_UNCERTAIN'}):
        classification = 'candidate'
    else:
        classification = 'needs_check'
    confirmed = union(confirmed)
    minutes = None if subtract(uncertain, confirmed) else round(sum((hi - lo).total_seconds() for lo, hi in confirmed) / 60, 1)
    raw = basis = None
    if distances and all(value is not None for _, value, _ in distances):
        _, raw, basis = min(distances, key=lambda item: (item[1], item[2]))
    return classification, reasons, confirmed, minutes, raw, basis, sorted(matched), min(starts) if starts else None


def _overlap_groups(snapshot_id, query, classified, max_bytes):
    changes = defaultdict(lambda: [set(), set()])
    for event_id, info in classified.items():
        if info['classification'] != 'candidate':
            continue
        for lo, hi in info['intervals']:
            changes[lo][1].add(event_id)
            changes[hi][0].add(event_id)
    # 화면 선택·정렬은 동시간 구간의 의미를 바꾸지 않는다.
    conditions = _select(query, ('point_id', 'weekly_hours', 'mode', 'case_id', 'types'))
    conditions['types'] = sorted(set(conditions['types']))
    for day in conditions['weekly_hours'].values():
        day['intervals'].sort(key=lambda x: (x['start'], x['end'], x['end_day_offset']))
    digest = hashlib.sha256(json.dumps(conditions, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    groups, budget = [], 2
    def emit(span):
        nonlocal budget
        lo, hi, ids = span
        identity = json.dumps([snapshot_id, digest, utc(lo), utc(hi), ids], separators=(',', ':'))
        group = dict(group_id=str(uuid5(NAMESPACE_URL, identity)), start_at=utc(lo), end_at=utc(hi), event_ids=ids)
        budget += len(json.dumps(group, separators=(',', ':')).encode('utf-8')) + bool(groups)
        if budget > max_bytes:
            raise OutputLimitError('CALCULATION_OUTPUT_TOO_LARGE')
        groups.append(group)
    active, pending = set(), None
    times = sorted(changes)
    for i, current in enumerate(times[:-1]):
        stops, starts = changes[current]
        active.difference_update(stops)
        active.update(starts)
        following = times[i + 1]
        ids = sorted(active)
        if len(ids) < 2:
            if pending:
                emit(pending)
                pending = None
        elif pending and pending[1] == current and pending[2] == ids:
            pending = (pending[0], following, ids)
        else:
            if pending:
                emit(pending)
            pending = (current, following, ids)
    if pending:
        emit(pending)
    return groups


def _cancel_time(event, sources):
    versions = {e['document_version_id'] for e in event['evidence'] if e['evidence_id'] in event['lifecycle_evidence_ids']}
    times = [instant_ns(sources[v]['last_verified_at']) for v in versions if sources[v]['last_verified_at']]
    return max(times, default=float('-inf'))


def _clock_warning(event, start, end, context):
    if event['lifecycle'] != 'active':
        return []
    spans = []
    for occ in event['occurrences']:
        exact, intervals = occurrence_intervals(occ, start, end)
        if not exact:
            return []
        spans.extend(intervals)
    spans = union(spans)
    if not spans:
        return []
    reference = datetime.fromisoformat(context['reference_instant'] if context['mode'] == 'replay' else context['server_now'])
    if spans[-1][1] <= reference:
        today = spans[-1][1].astimezone(KST).date() == reference.astimezone(KST).date()
        label = '오늘 종료' if today and context['mode'] == 'current' else '기준 시각 이전 종료'
        return [label + ': 안내된 확정 시간 기준이며 오늘 포함 조회창에는 유지합니다.']
    if any(lo <= reference < hi for lo, hi in spans):
        return ['기준 시각에 안내된 확정 시간 구간이 진행 중입니다. 실제 적용 대상은 원문에서 확인해 주세요.']
    return ['기준 시각 이후에 안내된 다음 확정 시간 구간이 있습니다.']


def calculate(payload):
    """protocol.validate에서 검증된 calc-v1 객체를 계산한다."""
    context, query = payload['context'], payload['query']
    start = midnight(date.fromisoformat(context['anchor_date']))
    end = start + 14 * DAY
    known, unknown = business_hours(query['weekly_hours'], start, end)
    point = (payload['point']['longitude'], payload['point']['latitude'])
    sources = {s['document_version_id']: s for s in payload['source_versions']}
    classified, diagnostics = {}, []
    counts = Counter(candidate=0, needs_check=0, cancelled=0)
    item_budget = 2
    for event in payload['events']:
        if query['types'] and not set(query['types']).intersection(event['types']):
            continue
        locations = {loc['location_id']: locate(point, loc) for loc in event['locations']}
        status, reasons, intervals, minutes, raw, basis, matched, first = _classify(
            event, locations, known, unknown, start, end, sources, context)
        if status is None:
            diagnostics.append(dict(event_id=event['event_id'], revision_id=event['revision_id'], reason_codes=sorted(reasons)))
            continue
        item = None
        if status == query['selection']:
            item = _public_event(event, sources, context['data_kind'] == 'synthetic')
            item.update(classification=status, reason_codes=sorted(reasons),
                        warnings=['직선 500m는 후보 검색 기준이며 실제 통행·영업 영향을 보증하지 않습니다.']
                                 + [WARNINGS[code] for code in sorted(reasons) if code in WARNINGS],
                        distance_m=None if raw is None else (round(raw, 1) if 495 <= raw <= 505 else int(raw + 0.5)),
                        distance_basis=basis, time_overlap_minutes=minutes, matched_occurrence_ids=matched)
            if any(event[key]['value'] for key in ('applicability', 'exceptions', 'route_names', 'stop_names', 'directions')):
                item['warnings'].append('대상·예외·노선·운행 방향은 원문과 함께 직접 확인해 주세요.')
            if context['mode'] == 'replay' and context['history_fidelity'] == 'reconstructed':
                item['warnings'].append('현재 확보한 자료로 재구성한 과거 사례이며 당시 실시간 정확도 평가 대상이 아닙니다.')
            if context['mode'] == 'replay' and any(sources[v]['current_check_result'] != 'verified' for v in event['source_version_ids']):
                item['warnings'].append('현재 원문 연결·확인 상태는 당시 지식과 별도로 확인해 주세요.')
            item['warnings'].extend(_clock_warning(event, start, end, context))
            separator = int(item_budget > 2)
            item_budget += separator + _encoded_size(item, MAX_BYTES - item_budget - separator)
        classified[event['event_id']] = dict(item=item, classification=status, intervals=intervals,
                                             first=first, raw=raw, cancel_time=_cancel_time(event, sources))
        counts[status] += 1
    selected = [info for info in classified.values() if info['classification'] == query['selection']]
    def sort_key(info):
        first = info['first'] or datetime.max.replace(tzinfo=KST)
        distance = info['raw'] if info['raw'] is not None else float('inf')
        if query['selection'] == 'cancelled':
            return (-info['cancel_time'], first, distance, info['item']['event_id'])
        values = (distance, first) if query['sort'] == 'distance' else (first, distance)
        return (*values, info['item']['event_id'])
    selected.sort(key=sort_key)
    query_context = _select(query, ('point_id', 'weekly_hours', 'mode', 'case_id'))
    query_context.update(anchor_date=context['anchor_date'], window_start=utc(start), window_end_exclusive=utc(end),
                         radius_m=500, timezone='Asia/Seoul')
    if context['mode'] == 'replay':
        query_context.update(_select(context, ('reference_instant', 'knowledge_cutoff', 'history_fidelity')))
    data = dict(data_kind=context['data_kind'], query_context=query_context, counts=dict(counts),
                items=[info['item'] for info in selected], overlap_groups=_overlap_groups(payload['snapshot_id'], query, classified, MAX_BYTES - item_budget),
                rules_version=context['rules_version'])
    return dict(data=data, diagnostics=sorted(diagnostics, key=lambda row: row['event_id']))
