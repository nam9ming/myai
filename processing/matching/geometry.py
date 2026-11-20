"""검토된 WGS84 geometry의 직선거리. 경로 접근성은 판정하지 않는다."""

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine(p, q):
    lon1, lat1, lon2, lat2 = map(math.radians, (*p, *q))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    a = min(1.0, max(0.0, a))
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _vector(point):
    lon, lat = map(math.radians, point)
    return (math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat))


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _length(a):
    return math.sqrt(_dot(a, a))


def _angle(a, b):
    return math.atan2(_length(_cross(a, b)), max(-1.0, min(1.0, _dot(a, b))))


def segment_distance(point, start, end):
    p, a, b = map(_vector, (point, start, end))
    cross = _cross(a, b)
    size = _length(cross)
    if size < 1e-15:
        if _dot(a, b) < 0:
            raise ValueError('반대편 선분은 검토가 필요합니다.')
        return haversine(point, start)
    n = tuple(x / size for x in cross)
    projection = tuple(x - _dot(p, n) * y for x, y in zip(p, n))
    size = _length(projection)
    result = min(haversine(point, start), haversine(point, end))
    if size < 1e-15:
        return result
    q = tuple(x / size for x in projection)
    arc = _angle(a, b)
    for projected in (q, tuple(-x for x in q)):
        if abs(_angle(a, projected) + _angle(projected, b) - arc) <= 1e-10:
            result = min(result, EARTH_RADIUS_M * _angle(p, projected))
    return result


def locate(point, location):
    if (location['status'] != 'verified' or location['coverage'] == 'unknown'
            or location['kind'] in ('area', 'unknown') or location['geometry'] is None):
        return None, None, None
    coords = location['geometry']['coordinates']
    kind = location['kind']
    if kind == 'point':
        raw, basis = haversine(point, coords), 'haversine_point'
    elif kind == 'stops':
        raw, basis = min(haversine(point, q) for q in coords), 'minimum_verified_stops'
    else:
        raw = min(segment_distance(point, a, b) for a, b in zip(coords, coords[1:]))
        basis = 'great_circle_segment'
    inside = raw <= 500.0
    if location['coverage'] == 'partial':
        # 완성된 geometry가 아니므로 최솟값 자체도 확정하지 않는다.
        return (True if inside else None), None, None
    return inside, raw, basis
