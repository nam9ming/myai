"""D09 private pack의 선언·기한·자료 identity만 검사한다. 원본은 복사하지 않는다."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import PurePosixPath
import stat
from urllib.parse import urlsplit

from processing.extraction.archive import REPO, _fingerprint, _read_checked, _root
from processing.extraction.metadata import stamp
from processing.extraction.schema import HASH, UUID
from processing.extraction.validation import MAX_BYTES, ExtractionError, array, day, decode, require, shape, text
from processing.matching.intervals import KST, instant_ns, midnight
from .dataset import _id, _label

STUDY_ROOT = REPO / 'data/private/evaluation/user-studies'
CATEGORIES = ('customer_guidance', 'delivery', 'event_preparation')
SNAPSHOT_FIELDS = ('schema_version snapshot_id created_at data_kind mode rules_version dictionary_version area_id '
    'timezone window_days radius_m area case_id anchor_date reference_instant knowledge_cutoff history_fidelity '
    'point_ids points revision_ids event_public_payloads sources document_count event_count collection_range last_check_min last_check_max')


def _check(condition, code='STUDY_PROTOCOL_INVALID'):
    require(condition, kind='input', code=code)


def stamp_ns(value):
    try:
        stamp(value, '$')
        return instant_ns(value)
    except (ExtractionError, ValueError, TypeError, OverflowError):
        _check(False, 'STUDY_TIME_INVALID')


def day_kst(ns):
    _check(type(ns) is int, 'STUDY_TIME_INVALID')
    try:
        return datetime.fromtimestamp(ns // 1_000_000_000, timezone.utc).astimezone(KST).date().isoformat()
    except (ValueError, OverflowError, OSError):
        _check(False, 'STUDY_TIME_INVALID')


def duration_ns(value, *, positive=True):
    _check(type(value) in (int, Decimal), 'STUDY_DURATION_INVALID')
    if type(value) is Decimal:
        _check(value.is_finite() and value.adjusted() <= 308, 'STUDY_DURATION_INVALID')
    _check(value > 0 if positive else value >= 0, 'STUDY_DURATION_INVALID')
    if not value:
        return 0
    if type(value) is int:
        return value * 1_000_000_000
    digits, exponent = value.as_tuple().digits, value.as_tuple().exponent
    if exponent < -9:
        fraction = -exponent - 9
        # 거대한 음수 지수를 정수 비율로 전개하기 전에 나노초 미만 값을 거부한다.
        _check(fraction <= len(digits) and not any(digits[-fraction:]), 'STUDY_DURATION_INVALID')
    numerator, denominator = value.as_integer_ratio()
    numerator *= 1_000_000_000
    _check(numerator % denominator == 0, 'STUDY_DURATION_INVALID')
    return numerator // denominator


def _pack_root(root):
    resolved = _root(root, create=False)
    _check(resolved.is_dir() and not resolved.is_symlink(), 'STUDY_PATH_INVALID')
    _check(stat.S_IMODE(resolved.stat().st_mode) & 0o077 == 0, 'STUDY_PATH_INVALID')
    return resolved


def _path(root, value):
    """입력과 출력 모두 canonical 상대 파일 경로와 기존 ancestors를 검사한다."""
    root = _pack_root(root)
    text(value, kind='input')
    path = PurePosixPath(value)
    _check('\x00' not in value and '\\' not in value and not path.is_absolute()
           and path.as_posix() == value and bool(path.parts) and all(part not in ('.', '..') for part in path.parts),
           'STUDY_PATH_INVALID')
    target = root
    for index, part in enumerate(path.parts):
        target /= part
        try:
            mode = target.lstat().st_mode
        except FileNotFoundError:
            break
        _check(not stat.S_ISLNK(mode) and (stat.S_ISREG(mode) if index == len(path.parts) - 1 else stat.S_ISDIR(mode)),
               'STUDY_PATH_INVALID')
    return root / path


def _artifact(value, root):
    shape(value, 'path sha256 size', kind='input')
    text(value['sha256'], kind='input', pattern=HASH)
    _check(type(value['size']) is int and value['size'] >= 0, 'STUDY_ARTIFACT_INVALID')
    path = _path(root, value['path'])
    expected = dict(sha256=value['sha256'], size=value['size'])
    _check(_fingerprint(path) == expected, 'STUDY_ARTIFACT_INVALID')
    return dict(path=path, **expected)


def _version(value, limit=MAX_BYTES):
    try:
        return _label(value, limit)
    except ExtractionError:
        _check(False)


def _uuid_set(value):
    values = array(value, '$', 'input')
    for identity in values:
        _id(identity)
    _check(len(values) == len(set(values)))
    return set(values)


def _url(value):
    text(value, kind='input')
    parsed = urlsplit(value)
    _check(parsed.scheme == 'https' and bool(parsed.hostname) and parsed.username is None and parsed.password is None
           and not any(character.isspace() or ord(character) < 32 or ord(character) == 127 for character in value)
           and (parsed.port is None or 1 <= parsed.port <= 65535))


def check_retention(prepared, *, evaluated_at=None):
    if evaluated_at is None:
        evaluated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    _check(stamp_ns(evaluated_at) < prepared['deadline_ns'], 'STUDY_RETENTION_EXPIRED')


def _snapshot(content, protocol, sources, frozen_ns):
    value = decode(content, 'input')
    shape(value, SNAPSHOT_FIELDS, kind='input')
    versions = protocol['versions']
    _check(value['schema_version'] == 'snapshot-v1' and value['data_kind'] == protocol['data_kind']
           and all(value[key] == versions[key] for key in ('snapshot_id', 'rules_version', 'dictionary_version')))
    _check(stamp_ns(value['created_at']) <= frozen_ns)
    actual_sources = {}
    for source in array(value['sources'], '$.sources', 'input'):
        _check(type(source) is dict)
        version = _id(source['document_version_id'])
        _check(version not in actual_sources and version in sources)
        _check(all(source[key] == sources[version][key]
                   for key in ('document_id', 'document_version_id', 'official_url', 'text_sha256')))
        actual_sources[version] = source
    _check(actual_sources.keys() == sources.keys())
    revisions = _uuid_set(value['revision_ids'])
    events, ordered_revisions, used = set(), [], set()
    for event in array(value['event_public_payloads'], '$.event_public_payloads', 'input'):
        _check(type(event) is dict)
        identity, revision = _id(event['event_id']), _id(event['revision_id'])
        _check(identity not in events and revision not in ordered_revisions)
        events.add(identity); ordered_revisions.append(revision)
        event_sources = _uuid_set(event['source_version_ids'])
        _check(bool(event_sources) and event_sources <= sources.keys())
        used.update(event_sources)
    _check(used == sources.keys() and revisions == set(ordered_revisions) and value['revision_ids'] == ordered_revisions)
    _check(type(value['document_count']) is int and value['document_count'] == len({source['document_id'] for source in sources.values()})
           and type(value['event_count']) is int and value['event_count'] == len(events))
    return events


def validate_protocol(content, root=STUDY_ROOT, *, evaluated_at=None):
    """동의·보존 선언과 같은 자료 집합만 검사하며 공개 승인·원문 진실성은 인증하지 않는다."""
    try:
        root = _pack_root(root)
        value = decode(content, 'input')
        shape(value, 'schema_version study_id protocol_version phase data_kind declared_frozen_at pilot_review privacy source_set task_sets versions time_limit_seconds', kind='input')
        _check(value['schema_version'] == 'user-study-protocol-v1' and value['phase'] in ('pilot', 'main')
               and value['data_kind'] in ('synthetic', 'real'))
        _id(value['study_id']); _version(value['protocol_version'], 100)
        if evaluated_at is None:
            evaluated_at = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        evaluated_ns, frozen_ns = stamp_ns(evaluated_at), stamp_ns(value['declared_frozen_at'])
        _check(frozen_ns <= evaluated_ns)
        privacy = value['privacy']
        shape(privacy, 'consent_version photo_consent_version access_owner retention_deadline post_study_processing confirmed_at', kind='input')
        _version(privacy['consent_version']); _label(privacy['access_owner'], MAX_BYTES)
        if privacy['photo_consent_version'] is not None:
            _version(privacy['photo_consent_version'])
        text(privacy['post_study_processing'], kind='input')
        _check(stamp_ns(privacy['confirmed_at']) <= frozen_ns)
        retention_day = day(privacy['retention_deadline'], '$.retention_deadline', 'input')
        # 최대 KST 날짜의 다음 자정도 UTC에서는 9999년 안에 표현할 수 있다.
        deadline = (midnight(retention_day).astimezone(timezone.utc) + timedelta(days=1) if retention_day == date.max
                    else midnight(retention_day + timedelta(days=1)))
        deadline_ns = int(deadline.timestamp()) * 1_000_000_000
        prepared = dict(protocol=value, root=root, evaluated_at=evaluated_at, evaluated_ns=evaluated_ns,
                        deadline_ns=deadline_ns, protocol_sha256=hashlib.sha256(content).hexdigest())
        check_retention(prepared, evaluated_at=evaluated_at)
        pilot = value['pilot_review']
        if value['phase'] == 'pilot':
            _check(pilot is None)
        else:
            shape(pilot, 'completed_at reviewer excluded_participant_ids note', kind='input')
            _label(pilot['reviewer'], MAX_BYTES); text(pilot['note'], kind='input')
            _check(stamp_ns(pilot['completed_at']) <= frozen_ns and bool(_uuid_set(pilot['excluded_participant_ids'])))
        versions = value['versions']
        shape(versions, 'app_version snapshot_id snapshot_checksum rules_version dictionary_version', kind='input')
        for key in ('app_version', 'dictionary_version'):
            _version(versions[key])
        _id(versions['snapshot_id']); text(versions['snapshot_checksum'], kind='input', pattern=HASH)
        _check(versions['rules_version'] == 'rules-v1')
        prepared['time_limit_ns'] = duration_ns(value['time_limit_seconds'])
        source_set = value['source_set']
        shape(source_set, 'documents board_document_version_ids prototype_document_version_ids location_reference_artifact snapshot_artifact', kind='input')
        sources = {}
        for source in array(source_set['documents'], '$.documents', 'input'):
            shape(source, 'document_id document_version_id official_url text_sha256 artifact', kind='input')
            _id(source['document_id']); version = _id(source['document_version_id'])
            _check(version not in sources); _url(source['official_url'])
            text(source['text_sha256'], kind='input', pattern=HASH)
            _artifact(source['artifact'], root)
            sources[version] = source
        _check(_uuid_set(source_set['board_document_version_ids']) == sources.keys()
               and _uuid_set(source_set['prototype_document_version_ids']) == sources.keys())
        _artifact(source_set['location_reference_artifact'], root)
        snapshot = _artifact(source_set['snapshot_artifact'], root)
        _check(snapshot['sha256'] == versions['snapshot_checksum'])
        snapshot_bytes = _read_checked(snapshot['path'], dict(sha256=snapshot['sha256'], size=snapshot['size']))
        events = _snapshot(snapshot_bytes, value, sources, frozen_ns)
        tasks, task_sets = {}, {}
        for task_set in array(value['task_sets'], '$.task_sets', 'input'):
            shape(task_set, 'set_id version items', kind='input')
            name = task_set['set_id']; _check(type(name) is str and name in ('A', 'B') and name not in task_sets)
            _version(task_set['version'])
            items = array(task_set['items'], '$.items', 'input'); _check(len(items) == 3)
            categories, identities = set(), set()
            for task in items:
                shape(task, 'task_id category prompt expected_event_ids answer_basis_note', kind='input')
                identity = _id(task['task_id']); _check(identity not in tasks)
                _check(type(task['category']) is str and task['category'] in CATEGORIES and task['category'] not in categories)
                text(task['prompt'], kind='input'); text(task['answer_basis_note'], kind='input')
                _check(_uuid_set(task['expected_event_ids']) <= events)
                tasks[identity] = task; identities.add(identity); categories.add(task['category'])
            task_sets[name] = identities
        _check(set(task_sets) == {'A', 'B'})
        prepared.update(sources=sources, events=events, tasks=tasks, task_sets=task_sets)
        return prepared
    except ExtractionError:
        raise
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        _check(False)
