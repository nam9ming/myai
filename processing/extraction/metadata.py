"""수동 도구가 제공한 D05 측정값만 검증하고 추정하지 않는다."""

from datetime import datetime
from decimal import Decimal

from .schema import UUID, SCHEMA_VERSION
from .validation import decode, require, shape, text

STAMP = r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z'
NULLABLE = ('provider', 'model_label', 'model_version', 'started_at', 'finished_at',
            'usage_in', 'usage_out', 'cost', 'currency')
FIELDS = ('run_id document_version_id execution_mode attempts provider model_label model_version '
          'unavailable_reasons prompt_version schema_version preprocessing_version started_at finished_at '
          'usage_in usage_out cost currency')


def stamp(value, path):
    text(value, path, 'input', STAMP)
    try:
        datetime.fromisoformat(value)
    except ValueError:
        require(False, path, 'input')
    base, _, fraction = value[:-1].partition('.')
    return base, fraction.ljust(9, '0')


def parse_metadata(content, document, attempt_count):
    value = decode(content, 'input')
    shape(value, FIELDS, kind='input')
    for key in ('run_id', 'document_version_id'):
        text(value[key], '$.' + key, 'input', UUID)
    require(value['document_version_id'] == document['document_version_id'], '$.document_version_id', 'input')
    require(value['execution_mode'] in ('manual_import', 'api'), '$.execution_mode', 'input')
    if value['execution_mode'] == 'api':
        require(value['provider'] == 'openai' and value['model_label'] is not None, '$.provider', 'input')
    require(type(attempt_count) is int and 1 <= attempt_count <= 3 and type(value['attempts']) is int
            and value['attempts'] == attempt_count, '$.attempts', 'input')
    for key in ('prompt_version', 'schema_version', 'preprocessing_version'):
        text(value[key], '$.' + key, 'input')
        require(len(value[key]) <= 100, '$.' + key, 'input')
    require(value['schema_version'] == SCHEMA_VERSION, '$.schema_version', 'input')
    reasons = value['unavailable_reasons']
    require(type(reasons) is dict and set(reasons) <= set(NULLABLE), '$.unavailable_reasons', 'input')
    for key, reason in reasons.items():
        text(reason, '$.unavailable_reasons.' + key, 'input')
        require(value[key] is None, '$.unavailable_reasons.' + key, 'input')
    for key in ('provider', 'model_label', 'model_version'):
        if value[key] is None:
            require(key in reasons, '$.' + key, 'input')
        else:
            text(value[key], '$.' + key, 'input')
            require(len(value[key]) <= 100, '$.' + key, 'input')
    for key in ('usage_in', 'usage_out'):
        require(value[key] is None or type(value[key]) is int and value[key] >= 0, '$.' + key, 'input')
    cost = value['cost']
    require(cost is None or type(cost) in (int, Decimal) and cost >= 0, '$.cost', 'input')
    if value['currency'] is not None:
        text(value['currency'], '$.currency', 'input')
    times = [stamp(value[k], '$.' + k) if value[k] is not None else None for k in ('started_at', 'finished_at')]
    require(None in times or times[0] <= times[1], '$.finished_at', 'input')
    return value
