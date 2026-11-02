"""원본을 수정하지 않는 계약 전용 검증. 오류에는 원문 값을 넣지 않는다."""

from datetime import date, time
from decimal import Decimal
import hashlib
import json
import re
import unicodedata

from .schema import (SCHEMA_VERSION, UUID, HASH, DAY, CLOCK, KNOWLEDGE, CHOICES,
                     ITEM_FIELDS, OCCURRENCE_FIELDS, LOCATION_FIELDS)

MAX_BYTES = 8 * 1024 * 1024


class ExtractionError(ValueError):
    def __init__(self, code, path='$', kind='schema'):
        self.code, self.path, self.kind = code, path, kind
        self.retryable = kind == 'schema'
        super().__init__(f'{code} at {path}')


def require(condition, path='$', kind='schema', code='EXTRACTION_INVALID'):
    if not condition:
        raise ExtractionError(code, path, kind)


def shape(value, keys, path='$', kind='schema'):
    require(type(value) is dict and set(value) == set(keys.split()), path, kind)


def text(value, path='$', kind='schema', pattern=None):
    require(type(value) is str and bool(value.strip()), path, kind)
    if pattern:
        require(re.fullmatch(pattern, value) is not None, path, kind)
    return value


def array(value, path, kind='schema', minimum=0):
    require(type(value) is list and len(value) >= minimum, path, kind)
    return value


def ids(value, path, kind='schema', minimum=0):
    for i, entry in enumerate(array(value, path, kind, minimum)):
        text(entry, f'{path}[{i}]', kind)
    require(len(value) == len(set(value)), path, kind)
    return set(value)


def day(value, path, kind):
    text(value, path, kind, DAY)
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ExtractionError('EXTRACTION_INVALID', path, kind) from None


def decode(content, kind):
    def pairs(entries):
        result = {}
        for key, value in entries:
            require(key not in result, kind=kind, code='JSON_INVALID')
            result[key] = value
        return result

    def tree(value, depth=0):
        require(depth <= 100, kind=kind, code='JSON_INVALID')
        if type(value) is str:
            value.encode('utf-8', errors='strict')
        elif isinstance(value, Decimal):
            require(value.is_finite() and value.adjusted() <= 308, kind=kind, code='JSON_INVALID')
        elif type(value) is list:
            for entry in value:
                tree(entry, depth + 1)
        elif type(value) is dict:
            for key, entry in value.items():
                tree(key, depth + 1)
                tree(entry, depth + 1)

    require(type(content) is bytes and len(content) <= MAX_BYTES, kind=kind, code='JSON_LIMIT')
    try:
        value = json.loads(content.decode('utf-8', errors='strict'), object_pairs_hook=pairs,
                           parse_float=Decimal,
                           parse_constant=lambda _: require(False, kind=kind, code='JSON_INVALID'))
        tree(value)
        return value
    except ExtractionError:
        raise
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ExtractionError('JSON_INVALID', kind=kind) from None


def parse_input(content):
    value = decode(content, 'input')
    shape(value, 'data_kind document_version_id title published_date blocks', kind='input')
    require(value['data_kind'] in ('synthetic', 'real'), '$.data_kind', 'input')
    text(value['document_version_id'], '$.document_version_id', 'input', UUID)
    title = text(value['title'], '$.title', 'input')
    require('\r' not in title and unicodedata.is_normalized('NFC', title), '$.title', 'input')
    if value['published_date'] is not None:
        day(value['published_date'], '$.published_date', 'input')
    seen = set()
    for i, block in enumerate(array(value['blocks'], '$.blocks', 'input', 1)):
        path = f'$.blocks[{i}]'
        shape(block, 'block_id page text', path, 'input')
        key = text(block['block_id'], path + '.block_id', 'input')
        require(key not in seen, path + '.block_id', 'input'); seen.add(key)
        require(block['page'] is None or type(block['page']) is int and block['page'] > 0, path + '.page', 'input')
        content = text(block['text'], path + '.text', 'input')
        require('\r' not in content and unicodedata.is_normalized('NFC', content), path + '.text', 'input')
    return value


def field(value, kind, evidence, path):
    shape(value, 'value knowledge evidence_ids reason', path)
    require(value['knowledge'] in KNOWLEDGE, path + '.knowledge')
    refs = ids(value['evidence_ids'], path + '.evidence_ids', minimum=1 if value['knowledge'] == 'known' else 0)
    require(refs <= evidence, path + '.evidence_ids', 'review')
    if value['reason'] is not None:
        text(value['reason'], path + '.reason')
    v = value['value']
    if value['knowledge'] != 'known':
        require(v is None and value['reason'] is not None, path)
        require(kind != 'types' or value['knowledge'] == 'ambiguous', path + '.knowledge')
        return
    if kind == 'boolean':
        require(type(v) is bool, path + '.value')
    elif kind == 'offset':
        require(type(v) is int and v in (0, 1), path + '.value')
    elif kind in ('types', 'texts'):
        for i, entry in enumerate(array(v, path + '.value', minimum=1 if kind == 'types' else 0)):
            text(entry, f'{path}.value[{i}]')
        if kind == 'types':
            require(len(v) == len(set(v)) and set(v) <= set(CHOICES['types']), path + '.value')
    elif kind in CHOICES:
        require(type(v) is str and v in CHOICES[kind], path + '.value')
    elif kind == 'day':
        day(v, path + '.value', 'schema')
    else:
        text(v, path + '.value', pattern=CLOCK if kind == 'clock' else None)


def chronology(occ, path):
    a, b, lo, hi, offset = [occ[k]['value'] for k in ('date_start', 'date_end', 'time_start', 'time_end', 'end_day_offset')]
    if a is None or b is None:
        return
    require(a <= b, path, 'review', 'TIME_ORDER_INVALID')
    if a == b and lo is not None and hi is not None and offset is not None:
        def seconds(v):
            t = time.fromisoformat(v)
            return t.hour * 3600 + t.minute * 60 + t.second
        require(0 < seconds(hi) + offset * 86400 - seconds(lo) <= 86400, path, 'review', 'TIME_ORDER_INVALID')


def parse_output(content, document):
    value = decode(content, 'schema')
    shape(value, 'schema_version document_version_id items evidence warnings')
    require(value['schema_version'] == SCHEMA_VERSION, '$.schema_version')
    text(value['document_version_id'], '$.document_version_id', pattern=UUID)
    require(value['document_version_id'] == document['document_version_id'], '$.document_version_id', 'review')
    for i, warning in enumerate(array(value['warnings'], '$.warnings')):
        text(warning, f'$.warnings[{i}]')
    blocks = {b['block_id']: b['text'] for b in document['blocks']}
    evidence = set()
    for i, entry in enumerate(array(value['evidence'], '$.evidence')):
        path = f'$.evidence[{i}]'
        shape(entry, 'evidence_id block_id quote start_char end_char text_sha256', path)
        key = text(entry['evidence_id'], path + '.evidence_id')
        require(key not in evidence, path + '.evidence_id'); evidence.add(key)
        text(entry['block_id'], path + '.block_id')
        text(entry['quote'], path + '.quote')
        text(entry['text_sha256'], path + '.text_sha256', pattern=HASH)
        for k in ('start_char', 'end_char'):
            require(type(entry[k]) is int and entry[k] >= 0, path + '.' + k)
        block = blocks.get(entry['block_id'])
        require(block is not None, path + '.block_id', 'review')
        start, end = entry['start_char'], entry['end_char']
        require(0 <= start < end <= len(block) and block[start:end] == entry['quote'], path, 'review', 'EVIDENCE_MISMATCH')
        require(hashlib.sha256(block.encode('utf-8')).hexdigest() == entry['text_sha256'], path + '.text_sha256', 'review', 'EVIDENCE_MISMATCH')
    seen_items, seen_occurrences, seen_locations = set(), set(), set()
    items = array(value['items'], '$.items')
    require(items or 'NO_EVENT_FOUND' in value['warnings'], '$.warnings')
    for i, item in enumerate(items):
        path = f'$.items[{i}]'
        shape(item, 'local_item_id occurrences locations ' + ' '.join(ITEM_FIELDS), path)
        key = text(item['local_item_id'], path + '.local_item_id')
        require(key not in seen_items, path + '.local_item_id'); seen_items.add(key)
        for k, kind in ITEM_FIELDS.items():
            field(item[k], kind, evidence, path + '.' + k)
        locations = set()
        for j, location in enumerate(array(item['locations'], path + '.locations', minimum=1)):
            p = f'{path}.locations[{j}]'
            shape(location, 'local_location_id ' + ' '.join(LOCATION_FIELDS), p)
            key = text(location['local_location_id'], p + '.local_location_id')
            require(key not in seen_locations, p + '.local_location_id'); seen_locations.add(key); locations.add(key)
            for k, kind in LOCATION_FIELDS.items():
                field(location[k], kind, evidence, p + '.' + k)
        for j, occ in enumerate(array(item['occurrences'], path + '.occurrences', minimum=1)):
            p = f'{path}.occurrences[{j}]'
            shape(occ, 'local_occurrence_id location_refs ' + ' '.join(OCCURRENCE_FIELDS), p)
            key = text(occ['local_occurrence_id'], p + '.local_occurrence_id')
            require(key not in seen_occurrences, p + '.local_occurrence_id'); seen_occurrences.add(key)
            for k, kind in OCCURRENCE_FIELDS.items():
                field(occ[k], kind, evidence, p + '.' + k)
            refs = ids(occ['location_refs'], p + '.location_refs')
            require(refs <= locations, p + '.location_refs', 'review')
            require(refs or 'LOCATION_BINDING_UNKNOWN' in value['warnings'], '$.warnings')
            chronology(occ, p)
    return value
