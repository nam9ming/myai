"""D09 원본을 복제하지 않고 명시한 비공개 결과 파일만 내보낸다."""

import csv
from datetime import datetime, timezone
import hashlib
import io
import stat

from processing.extraction.archive import _json, _read, _write
from processing.extraction.validation import MAX_BYTES, ExtractionError, decode, require
from .study import evaluate_study
from .study_protocol import _path, check_retention, stamp_ns

FORMAT = 'user-study-export-v1'
COLUMNS = ('row_kind study_id protocol_version records_version protocol_sha256 records_sha256 data_kind phase '
           'app_version snapshot_id rules_version dictionary_version access_owner retention_deadline '
           'participant_id participant_type participation_role assignment_sequence method task_set task_set_version '
           'task_id outcome elapsed_ns date_correct place_correct target_correct exceptions_correct expected_event_ids '
           'missed_event_ids false_positive_ids out_of_scope_ids eligible_pair exclusion_reasons deviations board_ns prototype_ns reduction_percent').split()


def _check(condition, code, kind='archive'):
    require(condition, kind=kind, code=code)


def _cell(value):
    if value is None: return ''
    if type(value) is bool: return 'true' if value else 'false'
    if type(value) is list: value = _json(value).decode('utf-8').rstrip('\n')
    if type(value) is str and (value.lstrip().startswith(('=', '+', '-', '@')) or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def _rows(result):
    common = {key: result[key] for key in ('study_id', 'protocol_version', 'records_version', 'protocol_sha256', 'records_sha256', 'data_kind', 'phase')}
    common.update({key: result['versions'][key] for key in ('app_version', 'snapshot_id', 'rules_version', 'dictionary_version')})
    common.update({key: result['privacy'][key] for key in ('access_owner', 'retention_deadline')})
    for person in result['participants']:
        base = common | {key: person[key] for key in ('participant_id', 'participant_type', 'participation_role', 'assignment_sequence')}
        analysis = {key: person['analysis'][key] for key in ('eligible_pair', 'exclusion_reasons', 'deviations', 'board_ns', 'prototype_ns', 'reduction_percent')}
        yield base | analysis | dict(row_kind='participant')
        for session in person['sessions']:
            fields = {key: session[key] for key in ('method', 'task_set', 'task_set_version')}
            for record in session['records']:
                fields_record = {key: record[key] for key in ('task_id', 'outcome', 'elapsed_ns', 'date_correct', 'place_correct',
                    'target_correct', 'exceptions_correct', 'expected_event_ids', 'missed_event_ids', 'false_positive_ids', 'out_of_scope_ids')}
                yield base | fields | fields_record | dict(row_kind='task')


def _csv(result):
    output = bytearray(); buffer = io.StringIO(newline=''); writer = csv.writer(buffer)
    def append(values):
        writer.writerow([_cell(value) for value in values])
        raw = buffer.getvalue().encode('utf-8')
        _check(len(output) + len(raw) <= MAX_BYTES, 'STUDY_RESULT_TOO_LARGE', 'input')
        output.extend(raw); buffer.seek(0); buffer.truncate(0)
    append(COLUMNS)
    for row in _rows(result): append([row.get(key) for key in COLUMNS])
    return bytes(output)


def export_study(packet, protocol, output, format):
    _check(format in ('json', 'csv'), 'STUDY_EXPORT_FORMAT_INVALID', 'input')
    check_retention(protocol)
    canonical = _json(packet['result'])
    _check(len(canonical) <= MAX_BYTES, 'STUDY_RESULT_TOO_LARGE', 'input')
    decode(canonical, 'input')
    raw = canonical if format == 'json' else _csv(packet['result'])
    target = _path(protocol['root'], output)
    content = packet['records_content']
    _check(type(content) is bytes and hashlib.sha256(content).hexdigest() == packet['result']['records_sha256'],
           'STUDY_EXPORT_INPUT_INVALID', 'input')

    def existing():
        check_retention(protocol)
        metadata = target.lstat()
        _check(stat.S_ISREG(metadata.st_mode) and stat.S_IMODE(metadata.st_mode) in (0o400, 0o600), 'STUDY_EXPORT_INTEGRITY')
        stored = _read(target)
        _check(len(stored) <= MAX_BYTES, 'STUDY_EXPORT_INTEGRITY')
        if format == 'csv':
            _check(stored == raw, 'STUDY_EXPORT_CONFLICT')
            return stored, packet['summary']
        try:
            previous = decode(stored, 'archive')
            _check(type(previous) is dict, 'STUDY_EXPORT_INTEGRITY')
            _check(all(previous.get(key) == packet['result'][key] for key in ('protocol_sha256', 'records_sha256')),
                   'STUDY_EXPORT_CONFLICT')
            at = previous.get('evaluated_at'); ns = stamp_ns(at)
            now = stamp_ns(datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
            _check(stamp_ns(protocol['protocol']['declared_frozen_at']) <= ns <= max(protocol['evaluated_ns'], now),
                   'STUDY_EXPORT_INTEGRITY')
            replay = dict(protocol, evaluated_at=at, evaluated_ns=ns)
            verified = evaluate_study(content, replay)
            _check(stored == _json(verified['result']), 'STUDY_EXPORT_INTEGRITY')
        except ExtractionError as error:
            if error.kind == 'archive' and error.code in ('STUDY_EXPORT_CONFLICT', 'STUDY_EXPORT_INTEGRITY'): raise
            raise ExtractionError('STUDY_EXPORT_INTEGRITY', kind='archive') from None
        return stored, verified['summary']

    check_retention(protocol)
    if target.exists(): raw, summary = existing()
    else:
        folder = protocol['root']
        for part in target.parent.relative_to(folder).parts:
            folder /= part
            folder.mkdir(mode=0o700, exist_ok=True)
        _path(protocol['root'], output)
        check_retention(protocol)
        try: _write(target, raw)
        except ExtractionError as error:
            if error.kind != 'archive': raise
            if not target.exists(): raise ExtractionError('STUDY_EXPORT_CONFLICT', kind='archive') from None
        raw, summary = existing()
    return dict(protocol_version=FORMAT, status='exported', format=format,
                output_sha256=hashlib.sha256(raw).hexdigest(), output_size=len(raw), summary=summary)
