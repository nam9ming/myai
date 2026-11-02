"""extract-schema-v1의 필드 정의와 배포용 JSON Schema."""

SCHEMA_VERSION = 'extract-schema-v1'
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
HASH = r'[0-9a-f]{64}'
DAY = r'[0-9]{4}-[0-9]{2}-[0-9]{2}'
CLOCK = r'(?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9])?'
KNOWLEDGE = ('known', 'not_stated', 'ambiguous', 'not_applicable')
CHOICES = dict(types=('construction', 'event', 'traffic'), lifecycle=('active', 'cancelled'),
               kind=('point', 'segment', 'stops', 'area'))
ITEM_FIELDS = dict(title='text', types='types', applicability='text', exceptions='texts',
                   route_names='texts', stop_names='texts', directions='texts', lifecycle='lifecycle')
OCCURRENCE_FIELDS = dict(date_start='day', date_end='day', time_start='clock', time_end='clock',
                         end_day_offset='offset', all_day='boolean', recurrence_text='text')
LOCATION_FIELDS = dict(name='text', address='text', kind='kind')


def string(pattern=None):
    result = dict(type='string', minLength=1, pattern=r'\S')
    if pattern:
        result['pattern'] = '^' + pattern + '$'
    return result


def array(items, minimum=0, unique=False):
    result = dict(type='array', items=items, minItems=minimum)
    if unique:
        result['uniqueItems'] = True
    return result


def obj(properties):
    return dict(type='object', properties=properties, required=list(properties), additionalProperties=False)


def value_schema(kind):
    if kind in ('text', 'day', 'clock'):
        return string(dict(day=DAY, clock=CLOCK).get(kind))
    if kind in ('texts', 'types'):
        item = dict(type='string', enum=list(CHOICES['types'])) if kind == 'types' else string()
        return array(item, minimum=1 if kind == 'types' else 0, unique=kind == 'types')
    if kind in CHOICES:
        return dict(type='string', enum=list(CHOICES[kind]))
    if kind == 'offset':
        return dict(type='integer', minimum=0, maximum=1)
    return dict(type='boolean')


def field(kind):
    result = obj(dict(value={'anyOf': [value_schema(kind), {'type': 'null'}]},
                      knowledge={'enum': list(KNOWLEDGE)}, evidence_ids=array(string(), unique=True),
                      reason={'anyOf': [string(), {'type': 'null'}]}))
    result['allOf'] = [
        {'if': {'properties': {'knowledge': {'const': 'known'}}},
         'then': {'properties': {'value': value_schema(kind), 'evidence_ids': {'minItems': 1}}},
         'else': {'properties': {'value': {'type': 'null'}, 'reason': string()}}}]
    if kind == 'types':
        result['allOf'].append({'if': {'properties': {'value': {'type': 'null'}}},
                                'then': {'properties': {'knowledge': {'const': 'ambiguous'}}}})
    return result


def document(properties, name):
    return {'$schema': 'https://json-schema.org/draft/2020-12/schema',
            '$id': 'https://myai.invalid/contracts/' + name, **obj(properties)}


def input_schema():
    return document(dict(data_kind={'enum': ['synthetic', 'real']}, document_version_id=string(UUID),
                         title=string(), published_date={'anyOf': [string(DAY), {'type': 'null'}]},
                         blocks=array(obj(dict(block_id=string(), page={'type': ['integer', 'null'], 'minimum': 1},
                                               text=string())), minimum=1)), 'ai-input-v1.json')


def output_schema():
    occurrence = obj(dict(local_occurrence_id=string(), **{k: field(v) for k, v in OCCURRENCE_FIELDS.items()},
                          location_refs=array(string(), unique=True)))
    location = obj(dict(local_location_id=string(), **{k: field(v) for k, v in LOCATION_FIELDS.items()}))
    item = obj(dict(local_item_id=string(), **{k: field(v) for k, v in ITEM_FIELDS.items()},
                    occurrences=array(occurrence, minimum=1), locations=array(location, minimum=1)))
    evidence = obj(dict(evidence_id=string(), block_id=string(), quote=string(),
                        start_char={'type': 'integer', 'minimum': 0}, end_char={'type': 'integer', 'minimum': 0},
                        text_sha256=string(HASH)))
    return document(dict(schema_version={'const': SCHEMA_VERSION}, document_version_id=string(UUID),
                         items=array(item), evidence=array(evidence), warnings=array(string())), 'extract-schema-v1.json')
