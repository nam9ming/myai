"""비공개 D09 기록의 전체 분모와 정확한 paired 시간 지표를 계산한다."""

import copy
from fractions import Fraction
import hashlib

from processing.extraction.archive import _json
from processing.extraction.validation import MAX_BYTES, array, decode, require, shape, text
from processing.matching.engine import OutputLimitError, _encoded_size
from .dataset import _id, _label
from .study_protocol import _artifact, check_retention, day_kst, duration_ns, stamp_ns

METHODS = ('board', 'prototype')
TYPES = ('merchant', 'resident', 'staff', 'expert', 'other')
OUTCOMES = ('correct', 'incorrect', 'timeout', 'withdrawn', 'technical_failure', 'not_started')
STATUSES = ('invited', 'declined', 'no_show', 'consented', 'withdrawn')
CORRECTNESS = ('date_correct', 'place_correct', 'target_correct', 'exceptions_correct')
SETS = ('reported_event_ids', 'missed_event_ids', 'false_positive_ids', 'out_of_scope_ids')
ORDER = ((('board', 'A'), ('prototype', 'B')), (('prototype', 'A'), ('board', 'B')),
         (('board', 'B'), ('prototype', 'A')), (('prototype', 'B'), ('board', 'A')))


def _check(condition, code='STUDY_RECORDS_INVALID'):
    require(condition, kind='input', code=code)


def _boolean(value, nullable=False):
    _check(type(value) is bool or nullable and value is None)


def _optional_text(value):
    if value is not None: text(value, kind='input')


def _ids(value, *, nullable=False):
    if value is None and nullable: return None
    result = array(value, '$', 'input')
    for item in result: _id(item)
    _check(len(set(result)) == len(result))
    return set(result)


class _Budget:
    def __init__(self): self.size = 0

    def add(self, value):
        try: self.size += _encoded_size(value, MAX_BYTES - self.size) + 1
        except OutputLimitError: _check(False, 'STUDY_RESULT_TOO_LARGE')
        _check(self.size <= MAX_BYTES, 'STUDY_RESULT_TOO_LARGE')


def _consent(value, version, now):
    shape(value, 'version consented_at', kind='input')
    _check(value['version'] == version and version is not None)
    at = stamp_ns(value['consented_at']); _check(at <= now)
    return at


def _record(value, prepared, tasks, consent, budget):
    shape(value, 'task_id started_at ended_at elapsed_seconds outcome date_correct place_correct target_correct exceptions_correct reported_event_ids missed_event_ids false_positive_ids out_of_scope_ids assistance_notes answer_feedback_given operation_taken_over', kind='input')
    _id(value['task_id']); _check(value['task_id'] in tasks)
    expected = set(prepared['tasks'][value['task_id']]['expected_event_ids'])
    _check(value['outcome'] in OUTCOMES)
    for key in CORRECTNESS: _boolean(value[key], True)
    for key in ('answer_feedback_given', 'operation_taken_over'): _boolean(value[key], True)
    _optional_text(value['assistance_notes'])
    lists = {key: _ids(value[key], nullable=True) for key in SETS}
    elapsed = None; interval = None
    if value['started_at'] is None:
        _check(value['outcome'] in ('not_started', 'withdrawn', 'technical_failure'))
        _check(all(value[key] is None for key in ('ended_at', 'elapsed_seconds', *CORRECTNESS, *SETS)))
    else:
        _check(value['outcome'] != 'not_started' and value['ended_at'] is not None)
        start, end = stamp_ns(value['started_at']), stamp_ns(value['ended_at'])
        elapsed = duration_ns(value['elapsed_seconds'])
        _check(max(consent, stamp_ns(prepared['protocol']['declared_frozen_at'])) <= start < end <= prepared['evaluated_ns'])
        _check(end - start == elapsed)
        interval = (start, end)
        if value['outcome'] in ('correct', 'incorrect'): _check(elapsed < prepared['time_limit_ns'])
        if value['outcome'] == 'timeout': _check(elapsed >= prepared['time_limit_ns'])
    universe = prepared['events']
    _check(lists['missed_event_ids'] is None or lists['missed_event_ids'] <= expected)
    _check(lists['false_positive_ids'] is None or lists['false_positive_ids'] <= universe - expected)
    _check(lists['out_of_scope_ids'] is None or not lists['out_of_scope_ids'] & universe)
    if lists['reported_event_ids'] is not None:
        got = lists['reported_event_ids']
        _check(lists['missed_event_ids'] == expected - got and lists['false_positive_ids'] == got & universe - expected
               and lists['out_of_scope_ids'] == got - universe)
    complete = all(value[key] is True for key in CORRECTNESS) and lists['missed_event_ids'] == set() and lists['false_positive_ids'] == set()
    if value['outcome'] == 'correct': _check(complete)
    if value['outcome'] == 'incorrect': _check(not complete)
    normalized = {key: copy.deepcopy(item) for key, item in value.items() if key != 'elapsed_seconds'}
    normalized.update(elapsed_ns=elapsed, expected_event_ids=sorted(expected))
    budget.add(normalized)
    return normalized, interval


def _session(value, method, set_id, prepared, consent, budget):
    shape(value, 'method task_set task_set_version device_browser network instruction_seconds timing_includes_loading source_check records', kind='input')
    expected_set = next(item for item in prepared['protocol']['task_sets'] if item['set_id'] == set_id)
    _check(value['method'] == method and value['task_set'] == set_id and value['task_set_version'] == expected_set['version'])
    for field in ('device_browser', 'network'): _label(value[field], MAX_BYTES)
    instruction = None if value['instruction_seconds'] is None else duration_ns(value['instruction_seconds'], positive=False)
    _boolean(value['timing_includes_loading'], True)
    check = value['source_check']; checked = None
    if check is not None:
        shape(check, 'checked_at originals_changed', kind='input')
        checked = stamp_ns(check['checked_at']); _check(checked <= prepared['evaluated_ns'])
        _boolean(check['originals_changed'], True)
    tasks = prepared['task_sets'][set_id]; seen = set(); rows, intervals = [], []
    for raw in array(value['records'], '$.records', 'input'):
        row, interval = _record(raw, prepared, tasks, consent, budget)
        _check(row['task_id'] not in seen); seen.add(row['task_id']); rows.append(row)
        if interval: intervals.append(interval)
    _check(seen == set(tasks))
    deviations = []
    if instruction is None: deviations.append('INSTRUCTION_TIME_UNKNOWN')
    if value['timing_includes_loading'] is None: deviations.append('LOADING_TIME_UNKNOWN')
    elif not value['timing_includes_loading']: deviations.append('LOADING_TIME_EXCLUDED')
    if check is None: deviations.append('SOURCE_CHECK_MISSING')
    elif check['originals_changed'] is None: deviations.append('ORIGINAL_CHANGE_STATUS_UNKNOWN')
    elif check['originals_changed']: deviations.append('ORIGINALS_CHANGED')
    if checked is not None and any(checked > start or day_kst(checked) != day_kst(start) for start, _ in intervals):
        deviations.append('SOURCE_CHECK_NOT_SAME_DAY_BEFORE_START')
    if any(row[key] is None for row in rows for key in ('answer_feedback_given', 'operation_taken_over')):
        deviations.append('ASSISTANCE_STATUS_UNKNOWN')
    if any(row['answer_feedback_given'] for row in rows): deviations.append('ANSWER_FEEDBACK_GIVEN')
    if any(row['operation_taken_over'] for row in rows): deviations.append('OPERATION_TAKEN_OVER')
    normalized = {key: copy.deepcopy(item) for key, item in value.items() if key not in ('records', 'instruction_seconds')}
    normalized['instruction_ns'] = instruction; budget.add(normalized)
    normalized['records'] = rows
    return normalized, intervals, deviations


def _participant(value, status, prepared, sequences, budget):
    shape(value, 'participant_id participant_type participation_role consent photo_consent assignment_sequence sessions interview observations feedback', kind='input')
    identity = _id(value['participant_id'])
    _check(value['participant_type'] in TYPES and value['participation_role'] in ('user', 'expert'))
    expert = value['participation_role'] == 'expert'
    _check(value['participant_type'] != 'expert' or expert)
    consent = _consent(value['consent'], prepared['protocol']['privacy']['consent_version'], prepared['evaluated_ns'])
    if value['photo_consent'] is not None:
        _consent(value['photo_consent'], prepared['protocol']['privacy']['photo_consent_version'], prepared['evaluated_ns'])
    for key, fields in (('interview', 'convenience usefulness continued_use'),
                        ('observations', 'needs_check_understood distance_distinction_understood source_access_succeeded'),
                        ('feedback', 'satisfied required_changes')):
        shape(value[key], fields, kind='input')
        for item in value[key].values():
            if key == 'interview': _check(item is None or type(item) is int and 1 <= item <= 5)
            elif key == 'observations': _boolean(item, True)
            else: _optional_text(item)
    sequence = value['assignment_sequence']
    sessions = array(value['sessions'], '$.sessions', 'input')
    normalized = {key: copy.deepcopy(item) for key, item in value.items() if key != 'sessions'}
    budget.add(normalized)
    deviations, normalized_sessions, intervals = [], [], []
    if expert: _check(sequence is None and not sessions)
    else:
        _check(type(sequence) is int and sequence > 0 and sequence not in sequences); sequences.add(sequence)
        review = prepared['protocol']['pilot_review']
        _check(prepared['protocol']['phase'] != 'main' or identity not in review['excluded_participant_ids'])
        _check(len(sessions) == 2)
        for raw, (method, set_id) in zip(sessions, ORDER[(sequence - 1) % 4]):
            session, times, errors = _session(raw, method, set_id, prepared, consent, budget)
            normalized_sessions.append(session); intervals.append(times); deviations.extend(errors)
        a, b = normalized_sessions
        for field, code in (('device_browser', 'DEVICE_BROWSER_MISMATCH'), ('network', 'NETWORK_MISMATCH'),
                            ('instruction_ns', 'INSTRUCTION_TIME_MISMATCH')):
            if a[field] != b[field] and (field != 'instruction_ns' or a[field] is not None and b[field] is not None):
                deviations.append(code)
        flat = sorted(time for times in intervals for time in times)
        _check(all(before[1] <= after[0] for before, after in zip(flat, flat[1:])))
        _check(not all(intervals) or max(end for _, end in intervals[0]) <= min(start for start, _ in intervals[1]))
    rows = [record for session in normalized_sessions for record in session['records']]
    started = any(row['started_at'] is not None for row in rows)
    finished = bool(rows) and all(row['outcome'] in ('correct', 'incorrect') for row in rows)
    correct = bool(rows) and all(row['outcome'] == 'correct' for row in rows)
    reasons = []
    if expert: reasons.append('EXPERT_ROLE')
    else:
        if not finished: reasons.append('INCOMPLETE_TASKS')
        if not correct: reasons.append('TASKS_NOT_ALL_CORRECT')
        if deviations: reasons.append('PROTOCOL_DEVIATION')
        if status != 'consented': reasons.append('RECRUITMENT_NOT_CONSENTED')
    totals = {method: None for method in METHODS}
    for session in normalized_sessions:
        elapsed = [row['elapsed_ns'] for row in session['records'] if row['elapsed_ns'] is not None]
        totals[session['method']] = sum(elapsed) if elapsed else None
    eligible = not reasons
    reduction = Fraction((totals['board'] - totals['prototype']) * 100, totals['board']) if eligible else None
    normalized['sessions'] = normalized_sessions
    normalized['analysis'] = dict(started=started, finished_all=finished, all_correct=correct, eligible_pair=eligible,
        exclusion_reasons=reasons, board_ns=totals['board'], prototype_ns=totals['prototype'],
        reduction_percent=float(reduction) if reduction is not None else None, deviations=sorted(set(deviations)))
    budget.add(normalized['analysis'])
    return normalized, reduction


def _percent(numerator, denominator):
    return float(Fraction(numerator * 100, denominator)) if denominator else None


def _method(rows):
    started = [row for row in rows if row['started_at'] is not None]
    expected = sum(len(row['expected_event_ids']) for row in rows)
    unknown = sum(len(row['expected_event_ids']) for row in rows if row['missed_event_ids'] is None)
    missed = sum(len(row['missed_event_ids']) for row in rows if row['missed_event_ids'] is not None)
    unknown_tasks = sum(row['missed_event_ids'] is None for row in rows)
    return dict(assigned_tasks=len(rows), started_tasks=len(started), not_started_tasks=sum(row['outcome'] == 'not_started' for row in rows),
        outcomes={outcome: sum(row['outcome'] == outcome for row in rows) for outcome in OUTCOMES},
        exact_correct=sum(row['outcome'] == 'correct' for row in started),
        accuracy_percent=_percent(sum(row['outcome'] == 'correct' for row in started), len(started)),
        correctness={key: dict(correct=sum(row[key] is True for row in started), false=sum(row[key] is False for row in started),
            unknown=sum(row[key] is None for row in started), total=len(started),
            accuracy_percent=_percent(sum(row[key] is True for row in started), len(started))) for key in CORRECTNESS},
        missed_incidence=dict(expected=expected, known=expected - unknown, unknown=unknown, missed=missed,
            unknown_tasks=unknown_tasks, rate_percent=_percent(missed, expected) if not unknown_tasks else None,
            lower_bound_percent=_percent(missed, expected), upper_bound_percent=_percent(missed + unknown, expected)),
        false_positive_unknown_tasks=sum(row['false_positive_ids'] is None for row in rows),
        out_of_scope_unknown_tasks=sum(row['out_of_scope_ids'] is None for row in rows),
        false_positive_ids=sum(len(row['false_positive_ids']) for row in rows if row['false_positive_ids'] is not None),
        out_of_scope_ids=sum(len(row['out_of_scope_ids']) for row in rows if row['out_of_scope_ids'] is not None))


def _survey(participants, field, boolean=False):
    keys = ('needs_check_understood', 'distance_distinction_understood', 'source_access_succeeded') if boolean else ('convenience', 'usefulness', 'continued_use')
    output = {}
    for role in ('user', 'expert'):
        group = [p for p in participants if p['participation_role'] == role]
        output[role] = {}
        for key in keys:
            values = [p[field][key] for p in group]; known = [value for value in values if value is not None]
            if boolean:
                result = dict(true=sum(value is True for value in known), false=sum(value is False for value in known), unknown=len(values) - len(known), total=len(values))
            else:
                result = dict(answered=len(known), unknown=len(values) - len(known), total=len(values),
                    mean=float(Fraction(sum(known), len(known))) if known else None,
                    distribution={str(score): sum(value == score for value in known) for score in range(1, 6)})
            output[role][key] = result
    return output


def _median(values):
    if not values: return None
    values = sorted(values); middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def _quality(methods):
    board, prototype = (methods[method] for method in METHODS)
    rates_known = board['started_tasks'] > 0 and prototype['started_tasks'] > 0
    worse = rates_known and Fraction(prototype['exact_correct'], prototype['started_tasks']) < Fraction(board['exact_correct'], board['started_tasks'])
    b, p = board['missed_incidence'], prototype['missed_incidence']
    omissions_known = not b['unknown_tasks'] and not p['unknown_tasks']
    comparable = omissions_known and (b['expected'] > 0 and p['expected'] > 0 or b['expected'] == p['expected'] == 0)
    if comparable and b['expected'] and p['expected']:
        worse |= Fraction(p['missed'], p['expected']) > Fraction(b['missed'], b['expected'])
    correctness_known = all(not item['unknown'] for method in methods.values() for item in method['correctness'].values())
    return bool(worse), bool(rates_known and comparable and correctness_known)


def _evidence(entries, participants, prepared):
    ids, artifacts = set(), set()
    for entry in array(entries, '$.evidence', 'input'):
        shape(entry, 'evidence_id artifact kind participant_id captured_at issue_ids change_refs note', kind='input')
        identity = _id(entry['evidence_id']); _check(identity not in ids); ids.add(identity)
        _check(entry['kind'] in ('screen_capture', 'deidentified_photo'))
        at = stamp_ns(entry['captured_at']); _check(at <= prepared['evaluated_ns'])
        text(entry['note'], kind='input')
        for field in ('issue_ids', 'change_refs'):
            values = array(entry[field], '$', 'input')
            for value in values: text(value, kind='input')
            _check(len(values) == len(set(values)))
        if entry['participant_id'] is not None:
            identity = _id(entry['participant_id']); _check(identity in participants)
            participant = participants[identity]; photo = participant['photo_consent']
            _check(photo is not None and stamp_ns(photo['consented_at']) <= at and stamp_ns(participant['consent']['consented_at']) <= at)
        artifact = _artifact(entry['artifact'], prepared['root'])
        artifacts.add((artifact['sha256'], artifact['size']))
    return dict(records=len(ids), verified_artifacts=len(artifacts), target_artifacts=2, meets_2_artifacts_as_declared=len(artifacts) >= 2)


def evaluate_study(content, prepared):
    check_retention(prepared, evaluated_at=prepared['evaluated_at'])
    value = decode(content, 'input')
    shape(value, 'schema_version study_id protocol_sha256 records_version recruitment participants evidence', kind='input')
    protocol = prepared['protocol']
    _check(value['schema_version'] == 'user-study-records-v1' and value['study_id'] == protocol['study_id']
           and value['protocol_sha256'] == prepared['protocol_sha256'])
    _label(value['records_version'], MAX_BYTES)
    for item in protocol['source_set']['documents']: _artifact(item['artifact'], prepared['root'])
    for field in ('location_reference_artifact', 'snapshot_artifact'): _artifact(protocol['source_set'][field], prepared['root'])
    recruitment = {}
    for row in array(value['recruitment'], '$.recruitment', 'input'):
        shape(row, 'participant_id status', kind='input')
        identity = _id(row['participant_id']); _check(identity not in recruitment and row['status'] in STATUSES)
        recruitment[identity] = row['status']
    budget = _Budget(); participants = []; identities = set(); sequences = set(); reductions = []
    for raw in array(value['participants'], '$.participants', 'input'):
        _check(type(raw) is dict)
        identity = _id(raw.get('participant_id')); _check(identity in recruitment)
        _check(identity not in identities and recruitment[identity] in ('consented', 'no_show', 'withdrawn')); identities.add(identity)
        participant, reduction = _participant(raw, recruitment[identity], prepared, sequences, budget)
        participants.append(participant)
        if reduction is not None: reductions.append(reduction)
    _check(all(status != 'consented' or identity in identities for identity, status in recruitment.items()))
    missing_details = sum(status in ('no_show', 'withdrawn') and identity not in identities for identity, status in recruitment.items())
    evidence = _evidence(value['evidence'], {p['participant_id']: p for p in participants}, prepared)
    users = [p for p in participants if p['participation_role'] == 'user']
    methods = {}
    for method in METHODS:
        rows = lambda group: [row for p in group for s in p['sessions'] if s['method'] == method for row in s['records']]
        methods[method] = dict(**_method(rows(users)), by_type={kind: _method(rows([p for p in users if p['participant_type'] == kind])) for kind in TYPES})
    def counts(group):
        return dict(participants=len(group), users=sum(p['participation_role'] == 'user' for p in group), experts=sum(p['participation_role'] == 'expert' for p in group),
            started_users=sum(p['participation_role'] == 'user' and p['analysis']['started'] for p in group),
            finished_all_users=sum(p['participation_role'] == 'user' and p['analysis']['finished_all'] for p in group),
            all_correct_users=sum(p['participation_role'] == 'user' and p['analysis']['all_correct'] for p in group),
            eligible_pairs=sum(p['analysis']['eligible_pair'] for p in group))
    population = counts(participants)
    population['by_type'] = {kind: counts([p for p in participants if p['participant_type'] == kind]) for kind in TYPES}
    cycle = {str(position): sum((sequence - 1) % 4 + 1 == position for sequence in sequences) for position in range(1, 5)}
    population['assignment'] = dict(assigned_users=len(sequences), missing_slots=max(sequences, default=0) - len(sequences), cycle_counts=cycle)
    median = _median(reductions)
    real_main = protocol['data_kind'] == 'real' and protocol['phase'] == 'main'
    gate = median >= 20 if real_main and median is not None else None
    worse, quality_known = _quality(methods)
    confirmed = quality_known and not missing_details and not any(p['analysis']['started'] and
        (p['analysis']['deviations'] or recruitment[p['participant_id']] != 'consented') for p in users)
    supported = None
    if real_main:
        if worse or gate is False: supported = False
        elif confirmed and gate is True: supported = True
    warnings = []
    if protocol['data_kind'] == 'synthetic': warnings.append('SYNTHETIC_DATA')
    if protocol['phase'] == 'pilot': warnings.append('PILOT_NOT_MAIN_EVALUATION')
    if missing_details: warnings.append('RECRUITMENT_DETAILS_INCOMPLETE')
    if population['assignment']['missing_slots']: warnings.append('ASSIGNMENT_SEQUENCE_GAPS')
    if max(cycle.values()) - min(cycle.values()) > 0: warnings.append('ASSIGNMENT_CYCLE_IMBALANCE')
    if not confirmed: warnings.append('COMPARISON_CONDITIONS_UNCONFIRMED')
    if evidence['verified_artifacts'] < 2: warnings.append('EVIDENCE_TARGET_SHORTFALL')
    summary = dict(protocol_version='user-study-summary-v1', data_kind=protocol['data_kind'], phase=protocol['phase'],
        recruitment=dict(total=len(recruitment), status_counts={status: sum(value == status for value in recruitment.values()) for status in STATUSES}, missing_participant_details=missing_details),
        participants=population, m04=dict(target_users=6, minimum_users=3, started_users=population['started_users'],
            main_started_users=population['started_users'] if protocol['phase'] == 'main' else 0,
            consented_users=sum(recruitment[p['participant_id']] == 'consented' for p in users),
            finished_all_users=population['finished_all_users'], all_correct_users=population['all_correct_users'],
            eligible_pairs=population['eligible_pairs'], merchant_started_users=population['by_type']['merchant']['started_users'],
            meets_minimum_3_as_declared=population['started_users'] >= 3 if real_main else None,
            meets_target_6_as_declared=population['started_users'] >= 6 if real_main else None), methods=methods,
        primary=dict(eligible_pairs=len(reductions), ineligible_users=len(users) - len(reductions),
            median_reduction_percent=float(median) if median is not None else None, meets_20_percent_as_declared=gate,
            improvement_supported_as_declared=supported, comparison_conditions_confirmed=confirmed),
        interviews=_survey(participants, 'interview'), observations=_survey(participants, 'observations', True),
        evidence=evidence, warnings=warnings, generalization_claim=False)
    result = dict(schema_version='user-study-result-v1', study_id=protocol['study_id'], protocol_version=protocol['protocol_version'],
        records_version=value['records_version'], protocol_sha256=prepared['protocol_sha256'], records_sha256=hashlib.sha256(content).hexdigest(),
        evaluated_at=prepared['evaluated_at'], phase=protocol['phase'], data_kind=protocol['data_kind'],
        privacy=copy.deepcopy(protocol['privacy']), versions=copy.deepcopy(protocol['versions']), summary=summary, participants=participants)
    _Budget().add(result)
    _check(len(_json(result)) <= MAX_BYTES, 'STUDY_RESULT_TOO_LARGE')
    return dict(result=result, summary=summary, records_content=content)
