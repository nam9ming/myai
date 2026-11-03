"""고정 리터럴 프로필의 약한 추출 기준선. 외부 실행·정답 참조 없음."""

from datetime import date
import hashlib
from itertools import islice
import json
import re
import unicodedata

from .schema import SCHEMA_VERSION, CHOICES, ITEM_FIELDS, OCCURRENCE_FIELDS, LOCATION_FIELDS
from .validation import MAX_BYTES, decode, parse_input, parse_output, require, shape, text

RULE_VERSION = 'rule-extract-v1'
PROFILE_VERSION = 'rule-profile-v1'
DATE = re.compile(r'(?<![0-9])([0-9]{4})\s*([-./년])\s*([0-9]{1,2})\s*([-./월])\s*([0-9]{1,2})(?:\s*일)?(?![0-9])')
CLOCK = re.compile(r'(?<![0-9:])([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?(?![0-9:])')
RANGE = re.compile(r'\s*(?:~|～|〜|–|—|-|부터)\s*(?:(익일|다음날)\s*)?')
LIMIT_FAILURE = b'{"rule_error":"RULE_OUTPUT_LIMIT"}\n', 'RULE_OUTPUT_LIMIT'


def parse_profile(content):
    value = decode(content, 'input')
    shape(value, 'schema_version profile_version rule_version data_kind type_keywords target_keywords exception_keywords places', kind='input')
    require(value['schema_version'] == PROFILE_VERSION and value['rule_version'] == RULE_VERSION, kind='input')
    require(value['data_kind'] in ('real', 'synthetic'), kind='input')

    def label(entry, limit=160):
        text(entry, kind='input')
        require(len(entry) <= limit and entry == entry.strip() and unicodedata.is_normalized('NFC', entry)
                and not any(ord(c) < 32 or ord(c) == 127 for c in entry), kind='input')
        return entry

    def literals(entries, maximum):
        require(type(entries) is list and len(entries) <= maximum, kind='input')
        for entry in entries:
            label(entry)
        require(len(entries) == len(set(entries)), kind='input')
        return entries

    label(value['profile_version'], 100)
    shape(value['type_keywords'], ' '.join(CHOICES['types']), kind='input')
    for keywords in value['type_keywords'].values():
        literals(keywords, 32)
    for key in ('target_keywords', 'exception_keywords'):
        literals(value[key], 32)
    require(type(value['places']) is list and len(value['places']) <= 256, kind='input')
    seen = set()
    for place in value['places']:
        shape(place, 'name aliases kind', kind='input')
        tokens = [label(place['name']), *literals(place['aliases'], 16)]
        require(len(tokens) == len(set(tokens)) and not seen.intersection(tokens), kind='input')
        seen.update(tokens)
        require(place['kind'] is None or type(place['kind']) is str and place['kind'] in CHOICES['kind'], kind='input')
    return value


def _dates(body):
    matches = list(islice(DATE.finditer(body), 3))
    remaining = DATE.sub(' ', body)
    partial = re.search(r'[0-9]{1,2}\s*(?:월|일)|[0-9]{1,2}[./-][0-9]{1,2}', remaining)
    unknown = 'ambiguous' if matches or partial else 'not_stated'
    if partial or not 1 <= len(matches) <= 2:
        return None, None, unknown
    days = []
    for match in matches:
        year, first, month, second, day = match.groups()
        if not (first == second and first in '-./' or first == '년' and second == '월'):
            return None, None, 'ambiguous'
        try:
            days.append(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            return None, None, 'ambiguous'
    if len(days) == 2 and (not RANGE.fullmatch(body[matches[0].end():matches[1].start()]) or days[0] > days[1]):
        return None, None, 'ambiguous'
    return days[0], days[-1], 'known'


def _clocks(body, distinct_dates):
    matches = list(islice(CLOCK.finditer(body), 3))
    all_day = re.search(r'종일', body) is not None
    if all_day and not matches:
        return None, None, None, True, 'not_stated'
    unknown = 'ambiguous' if matches or re.search(r'[0-9]+\s*시', body) else 'not_stated'
    if len(matches) != 2 or all_day:
        return None, None, None, None, unknown
    separator = RANGE.fullmatch(body[matches[0].end():matches[1].start()])
    values, seconds = [], []
    for match in matches:
        hour, minute, second = match.groups()
        h, m, s = int(hour), int(minute), int(second or 0)
        if h > 23 or m > 59 or s > 59 or separator is None:
            return None, None, None, None, 'ambiguous'
        values.append(f'{h:02}:{m:02}' + (f':{s:02}' if second is not None else ''))
        seconds.append(h * 3600 + m * 60 + s)
    offset = 0 if distinct_dates else 1 if separator.group(1) else 0
    duration = seconds[1] + offset * 86400 - seconds[0]
    if not distinct_dates and not 0 < duration <= 86400:
        offset = None
    return *values, offset, False if distinct_dates or 0 < duration < 86400 else None, 'known'


def _sentences(body):
    start = 0
    for match in re.finditer(r'[。！？!?\n]|\.(?=\s|$)', body):
        sentence = body[start:match.start()].strip()
        if sentence:
            yield sentence
        start = match.end()
    if body[start:].strip():
        yield body[start:].strip()


def _encode(value):
    content = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    for chunk in encoder.iterencode(value):
        part = chunk.encode('utf-8')
        if len(content) + len(part) + 1 > MAX_BYTES:
            return LIMIT_FAILURE
        content.extend(part)
    content.extend(b'\n')
    return bytes(content), None


def extract_rules(input_bytes, profile_bytes):
    document, profile = parse_input(input_bytes), parse_profile(profile_bytes)
    require(document['data_kind'] == profile['data_kind'], kind='input')
    body = '\n'.join(block['text'] for block in document['blocks'])
    types = [kind for kind in CHOICES['types'] if any(word in body for word in profile['type_keywords'][kind])]
    result = dict(schema_version=SCHEMA_VERSION, document_version_id=document['document_version_id'],
                  items=[], evidence=[], warnings=[])
    if not types:
        result['warnings'].append('NO_EVENT_FOUND')
        return _encode(result)
    for i, block in enumerate(document['blocks'], 1):
        result['evidence'].append(dict(evidence_id=f'rule-evidence-{i}', block_id=block['block_id'],
            quote=block['text'], start_char=0, end_char=len(block['text']),
            text_sha256=hashlib.sha256(block['text'].encode('utf-8')).hexdigest()))
    refs = [e['evidence_id'] for e in result['evidence']]

    def fv(value=None, knowledge='not_stated'):
        return dict(value=value, knowledge='known' if value is not None else knowledge,
                    evidence_ids=refs if value is not None else [],
                    reason=None if value is not None else '규칙 기준선: 미기재' if knowledge == 'not_stated' else '규칙 기준선: 모호하거나 미지원')

    # shortcut: 문서당 사건/일정1건, 복수 사건 분리가 필요하면 기준선 버전을 올린다.
    item = dict(local_item_id='rule-item-1', **{key: fv() for key in ITEM_FIELDS}, occurrences=[], locations=[])
    item['types'] = fv(types)
    first = next(block['text'] for block in document['blocks']
                 if any(word in block['text'] for kind in types for word in profile['type_keywords'][kind]))
    item['title'] = fv(first.strip()[:120])
    occurrence = dict(local_occurrence_id='rule-occurrence-1', **{key: fv() for key in OCCURRENCE_FIELDS}, location_refs=[])
    start, end, knowledge = _dates(body)
    occurrence.update(date_start=fv(start, knowledge), date_end=fv(end, knowledge))
    lo, hi, offset, all_day, knowledge = _clocks(body, start is not None and end != start)
    occurrence.update(time_start=fv(lo, knowledge), time_end=fv(hi, knowledge), all_day=fv(all_day),
                      end_day_offset=fv(offset, 'ambiguous' if lo is not None and offset is None else 'not_stated'))
    for place in profile['places']:
        if any(token in body for token in [place['name'], *place['aliases']]):
            key = f'rule-location-{len(item["locations"]) + 1}'
            item['locations'].append(dict(local_location_id=key, name=fv(place['name']),
                                          address=fv(), kind=fv(place['kind'])))
            occurrence['location_refs'].append(key)
    if not item['locations']:
        item['locations'].append(dict(local_location_id='rule-location-1', **{key: fv() for key in LOCATION_FIELDS}))
        result['warnings'].append('LOCATION_BINDING_UNKNOWN')
    targets, exceptions = {}, {}
    for sentence in _sentences(body):
        if any(word in sentence for word in profile['target_keywords']):
            targets[sentence] = None
        if any(word in sentence for word in profile['exception_keywords']):
            exceptions[sentence] = None
        if len(targets) > 256 or len(exceptions) > 256:
            return LIMIT_FAILURE
    if targets:
        item['applicability'] = fv(next(iter(targets))) if len(targets) == 1 else fv(knowledge='ambiguous')
    if exceptions:
        empty = [s for s in exceptions if re.fullmatch(r'(?:예외|제외)\s*[:：]?\s*없(?:음|다|습니다)', s)]
        item['exceptions'] = fv([] if empty else list(exceptions)) if not empty or len(empty) == len(exceptions) else fv(knowledge='ambiguous')
    item['occurrences'].append(occurrence)
    result['items'].append(item)
    result['warnings'].append('RULE_SINGLE_EVENT_BASELINE')
    raw, error = _encode(result)
    if error is None:
        parse_output(raw, document)
    return raw, error
