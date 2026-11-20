"""조회창 안의 반개구간만 연산하여 긴 원문 날짜 범위를 일별 전개하지 않는다."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')
WEEKDAYS = ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')
DAY = timedelta(days=1)


def instant_ns(text):
    base, _, fractional = text.removesuffix('Z').partition('.')
    seconds = int(datetime.fromisoformat(base + '+00:00').timestamp())
    return seconds * 1_000_000_000 + int((fractional + '000000000')[:9])


def union(intervals):
    result = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if result and start <= result[-1][1]:
            result[-1] = (result[-1][0], max(end, result[-1][1]))
        else:
            result.append((start, end))
    return result


def intersect(left, right):
    left, right = union(left), union(right)
    result, i, j = [], 0, 0
    while i < len(left) and j < len(right):
        start, end = max(left[i][0], right[j][0]), min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] <= right[j][1]:
            i += 1
        else:
            j += 1
    return result


def subtract(intervals, known):
    result = []
    known = union(known)
    for start, end in union(intervals):
        for lo, hi in known:
            if hi <= start:
                continue
            if lo >= end:
                break
            if start < lo:
                result.append((start, lo))
            start = max(start, hi)
        if start < end:
            result.append((start, end))
    return result


def midnight(day):
    return datetime.combine(day, time(), KST)


def business_hours(weekly, start, end):
    known, unknown = [], []
    for offset in range(-1, 14):
        base = start + offset * DAY
        hours = weekly[WEEKDAYS[base.weekday()]]
        if hours['state'] == 'unknown':
            unknown.append((base, base + 2 * DAY))
        elif hours['state'] == 'open':
            if hours['full_day']:
                known.append((base, base + DAY))
            else:
                for span in hours['intervals']:
                    lo = datetime.combine(base.date(), time.fromisoformat(span['start']), KST)
                    hi = datetime.combine(base.date(), time.fromisoformat(span['end']), KST) + span['end_day_offset'] * DAY
                    known.append((lo, hi))
    known = intersect(known, [(start, end)])
    return known, subtract(intersect(unknown, [(start, end)]), known)


def _after(day, days):
    try:
        return midnight(day) + days * DAY
    except OverflowError:
        return datetime.max.replace(tzinfo=KST)


def occurrence_intervals(occ, start, end):
    exact = occ['precision'] in ('exact_time', 'explicit_all_day')
    first = date.fromisoformat(occ['date_start']) if occ['date_start'] else None
    last = date.fromisoformat(occ['date_end']) if occ['date_end'] else None
    recurrence = occ['recurrence_dates']
    if recurrence is not None:
        dates = [date.fromisoformat(d) for d in recurrence]
        spans = [(d, d) for d in dates if start.date() - DAY <= d < end.date()]
    else:
        spans = [(first, last)]
    intervals = []
    for lo_day, hi_day in spans:
        if occ['precision'] == 'exact_time':
            lo = datetime.combine(lo_day, time.fromisoformat(occ['time_start']), KST)
            hi = datetime.combine(hi_day, time.fromisoformat(occ['time_end']), KST)
            try:
                # 종료 날짜가 별도로 명시됐으면 익일 offset을 이중 적용하지 않는다.
                if recurrence is not None or lo_day == hi_day:
                    hi += occ['end_day_offset'] * DAY
            except OverflowError:
                hi = datetime.max.replace(tzinfo=KST)
        else:
            lo = midnight(lo_day) if lo_day else start
            explicit_end = hi_day is not None and (lo_day is None or lo_day < hi_day) and recurrence is None
            day_offset = occ['end_day_offset']
            if occ['precision'] == 'unknown' and lo_day == hi_day and lo_day is not None and day_offset is None:
                offsets = [0, 1]
                if occ['time_start'] and occ['time_end']:
                    a, b = time.fromisoformat(occ['time_start']), time.fromisoformat(occ['time_end'])
                    seconds = lambda t: t.hour * 3600 + t.minute * 60 + t.second
                    offsets = [v for v in offsets if 0 < seconds(b) + v * 86400 - seconds(a) <= 86400]
                # 가능한 종료 상한만 계산하며 미상 offset 자체는 채우지 않는다.
                day_offset = max(offsets)
            offset = 1 + (0 if explicit_end else (day_offset or 0))
            hi = _after(hi_day, offset) if hi_day else end
            if occ['precision'] == 'unknown':
                if lo_day and occ['time_start']:
                    lo = datetime.combine(lo_day, time.fromisoformat(occ['time_start']), KST)
                if hi_day and occ['time_end'] and (explicit_end or day_offset is not None):
                    hi = datetime.combine(hi_day, time.fromisoformat(occ['time_end']), KST)
                    if not explicit_end:
                        try:
                            hi += day_offset * DAY
                        except OverflowError:
                            hi = datetime.max.replace(tzinfo=KST)
        if max(start, lo) < min(end, hi):
            intervals.append((max(start, lo), min(end, hi)))
    return exact, union(intervals)
