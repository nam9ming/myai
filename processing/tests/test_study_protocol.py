import copy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from processing.extraction.validation import ExtractionError
from support import payload

try:
    protocol_module = importlib.import_module('processing.evaluation.study_protocol')
except ModuleNotFoundError:
    protocol_module = None

STUDY_AT = '2026-11-04T03:00:00Z'


def uid(number):
    return f'40000000-0000-4000-8000-{number:012d}'


class StudyProtocolFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='myai-study-protocol-')
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name).resolve()
        self.work.chmod(0o700)
        p = payload()
        self.source = copy.deepcopy(p['source_versions'][0])
        first = copy.deepcopy(p['events'][0]); first.update(event_id=uid(101), revision_id=uid(201))
        second = copy.deepcopy(first); second.update(event_id=uid(102), revision_id=uid(202))
        points = [dict(point_id=p['point']['point_id'] if i == 0 else uid(300 + i), area_id=uid(10),
            label=f'합성 지점 {i}', longitude=127.27, latitude=37.01, version=1,
            dictionary_version=p['context']['dictionary_version'], verification_status='verified',
            active=True, is_test_reference=True) for i in range(5)]
        self.snapshot = dict(schema_version='snapshot-v1', snapshot_id=p['snapshot_id'], created_at='2026-11-02T23:00:00Z',
            data_kind='synthetic', mode='current', rules_version='rules-v1', dictionary_version=p['context']['dictionary_version'],
            area_id=uid(10), timezone='Asia/Seoul', window_days=14, radius_m=500,
            area=dict(area_id=uid(10), name='합성 구역', description='실제 참여·현장 자료가 아닌 시험'),
            case_id=None, anchor_date=None, reference_instant=None, knowledge_cutoff=None, history_fidelity=None,
            point_ids=[point['point_id'] for point in points], points=points,
            revision_ids=[first['revision_id'], second['revision_id']], event_public_payloads=[first, second],
            sources=[self.source], document_count=1, event_count=2,
            collection_range={'from': '2026-11-02', 'to': '2026-11-02'},
            last_check_min=self.source['last_verified_at'], last_check_max=self.source['last_verified_at'])
        source_artifact = self.artifact('materials/source.txt', b'SYNTHETIC source asset, not the declared D03 cleaned text\n')
        location_artifact = self.artifact('materials/location.txt', '합성 공통 위치 참고\n'.encode())
        snapshot_artifact = self.artifact('materials/snapshot.json', self.raw(self.snapshot))
        document = {key: self.source[key] for key in ('document_id', 'document_version_id', 'official_url', 'text_sha256')}
        document['artifact'] = source_artifact
        task_sets = []
        for offset, name in enumerate(('A', 'B')):
            items = [dict(task_id=uid(1000 + offset * 10 + i), category=category, prompt='합성 비교 과제',
                expected_event_ids=expected, answer_basis_note='합성 수동 정답·난이도 검토 선언')
                for i, (category, expected) in enumerate(zip(('customer_guidance', 'delivery', 'event_preparation'),
                    ([uid(101)], [uid(101), uid(102)], [])))]
            task_sets.append(dict(set_id=name, version=f'tasks-{name}-v1', items=items))
        self.protocol = dict(schema_version='user-study-protocol-v1', study_id=uid(1), protocol_version='synthetic-study-v1',
            phase='main', data_kind='synthetic', declared_frozen_at='2026-11-03T00:00:00Z',
            pilot_review=dict(completed_at='2026-11-02T22:00:00Z', reviewer='합성 파일럿 검토자',
                excluded_participant_ids=[uid(900)], note='실제 파일럿 아님'),
            privacy=dict(consent_version='synthetic-consent-v1', photo_consent_version='synthetic-photo-v1',
                access_owner='합성 접근 담당자', retention_deadline='9999-12-31',
                post_study_processing='합성 운영 선언; 실제 정책 아님', confirmed_at='2026-11-02T21:00:00Z'),
            source_set=dict(documents=[document], board_document_version_ids=[self.source['document_version_id']],
                prototype_document_version_ids=[self.source['document_version_id']],
                location_reference_artifact=location_artifact, snapshot_artifact=snapshot_artifact),
            task_sets=task_sets,
            versions=dict(app_version='synthetic-app-v1', snapshot_id=self.snapshot['snapshot_id'],
                snapshot_checksum=snapshot_artifact['sha256'], rules_version='rules-v1',
                dictionary_version=self.snapshot['dictionary_version']), time_limit_seconds=300)

    def raw(self, value):
        return (json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n').encode()

    def artifact(self, name, content):
        path = self.work / name; path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(content); path.chmod(0o600)
        return dict(path=name, sha256=hashlib.sha256(content).hexdigest(), size=len(content))

    def save_snapshot(self):
        artifact = self.artifact('materials/snapshot.json', self.raw(self.snapshot))
        self.protocol['source_set']['snapshot_artifact'] = artifact
        self.protocol['versions']['snapshot_checksum'] = artifact['sha256']

    def protocol_bytes(self):
        return self.raw(self.protocol)

    def prepare(self, protocol=None, at=STUDY_AT):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        return protocol_module.validate_protocol(self.protocol_bytes() if protocol is None else self.raw(protocol), self.work, evaluated_at=at)


class StudyProtocolTest(StudyProtocolFixture):
    def invalid(self, protocol=None, at=STUDY_AT):
        with self.assertRaises(ExtractionError): self.prepare(protocol, at)

    def test_prepares_same_materials_and_all_tasks_without_mutating_raw_protocol(self):
        before = copy.deepcopy(self.protocol); raw = self.protocol_bytes(); prepared = self.prepare()
        self.assertEqual(self.protocol, before)
        self.assertEqual(prepared['protocol'], before)
        self.assertEqual(prepared['protocol_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(prepared['events'], {uid(101), uid(102)})
        self.assertEqual(prepared['sources'].keys(), {self.source['document_version_id']})
        self.assertEqual({key: len(value) for key, value in prepared['task_sets'].items()}, {'A': 3, 'B': 3})
        self.assertEqual(len(prepared['tasks']), 6)
        self.assertEqual(prepared['time_limit_ns'], 300_000_000_000)
        self.assertEqual(set(prepared), {'protocol', 'root', 'evaluated_at', 'evaluated_ns', 'deadline_ns',
            'protocol_sha256', 'time_limit_ns', 'sources', 'events', 'tasks', 'task_sets'})

    def test_exact_schema_keys_ids_versions_and_explicit_privacy_are_required(self):
        changes = [('study_id', 'bad'), ('protocol_version', ' '), ('protocol_version', 'v' * 101),
                   ('phase', 'other'), ('data_kind', 'other'), ('schema_version', 'other')]
        for key, value in changes:
            with self.subTest(key=key, value=value):
                protocol = copy.deepcopy(self.protocol); protocol[key] = value; self.invalid(protocol)
        for parent in ('', 'privacy', 'source_set', 'versions', 'pilot_review'):
            with self.subTest(parent=parent):
                protocol = copy.deepcopy(self.protocol); node = protocol[parent] if parent else protocol
                node['PRIVATE_VALUE'] = 'unexpected'; self.invalid(protocol)
        for key in self.protocol['privacy']:
            with self.subTest(key=key):
                protocol = copy.deepcopy(self.protocol); protocol['privacy'][key] = None
                if key == 'photo_consent_version': self.prepare(protocol)
                else: self.invalid(protocol)

    def test_pilot_main_review_ids_and_freeze_time_are_declared_not_invented(self):
        protocol = copy.deepcopy(self.protocol); protocol['phase'] = 'pilot'; protocol['pilot_review'] = None
        self.assertEqual(self.prepare(protocol)['protocol']['phase'], 'pilot')
        for change in [None, dict(self.protocol['pilot_review'], excluded_participant_ids=[]),
                       dict(self.protocol['pilot_review'], excluded_participant_ids=[uid(900), uid(900)]),
                       dict(self.protocol['pilot_review'], completed_at='2026-11-03T00:00:00.000000001Z')]:
            protocol = copy.deepcopy(self.protocol); protocol['pilot_review'] = change; self.invalid(protocol)
        self.protocol['declared_frozen_at'] = '2026-11-04T03:00:00.000000001Z'; self.invalid()

    def test_only_protocol_version_has_hard_label_length_cap(self):
        for path in (('privacy', 'consent_version'), ('privacy', 'photo_consent_version'),
                     ('privacy', 'access_owner'), ('pilot_review', 'reviewer'), ('versions', 'app_version')):
            with self.subTest(path=path):
                protocol = copy.deepcopy(self.protocol); protocol[path[0]][path[1]] = '합성' * 100
                self.prepare(protocol)
        protocol = copy.deepcopy(self.protocol)
        for task_set in protocol['task_sets']: task_set['version'] = 'v' * 150
        self.prepare(protocol)
        self.protocol['versions']['dictionary_version'] = 'v' * 150
        self.snapshot['dictionary_version'] = 'v' * 150; self.save_snapshot()
        self.prepare()

    def test_labels_reject_controls_but_free_notes_keep_newlines(self):
        for path in (('privacy', 'consent_version'), ('privacy', 'access_owner'), ('pilot_review', 'reviewer'),
                     ('versions', 'app_version')):
            with self.subTest(path=path):
                protocol = copy.deepcopy(self.protocol); protocol[path[0]][path[1]] = '합성\nlabel'; self.invalid(protocol)
        self.protocol['pilot_review']['note'] = '합성\n선언'
        self.protocol['privacy']['post_study_processing'] = '합성\n운영 처리 선언'
        self.assertEqual(self.prepare()['protocol']['privacy']['post_study_processing'], '합성\n운영 처리 선언')

    def test_retention_includes_entire_kst_day_but_not_next_midnight(self):
        self.protocol['privacy']['retention_deadline'] = '2026-12-31'
        self.prepare(at='2026-12-31T14:59:59.999999999Z')
        self.invalid(at='2026-12-31T15:00:00Z')
        self.protocol['privacy']['retention_deadline'] = '2026-02-30'; self.invalid()

    def test_maximum_calendar_retention_day_does_not_require_year_10000(self):
        self.protocol['privacy']['retention_deadline'] = '9999-12-31'
        prepared = self.prepare()
        self.assertEqual(prepared['deadline_ns'], protocol_module.stamp_ns('9999-12-31T15:00:00Z'))
        self.prepare(at='9999-12-31T14:59:59.999999999Z')
        self.invalid(at='9999-12-31T15:00:00Z')

    def test_expiration_is_checked_before_material_files_are_read(self):
        self.protocol['privacy']['retention_deadline'] = '2026-12-31'
        (self.work / 'materials/snapshot.json').unlink()
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        with self.assertRaises(ExtractionError) as caught:
            self.prepare(at='2026-12-31T15:00:00Z')
        self.assertEqual(caught.exception.code, 'STUDY_RETENTION_EXPIRED')

    def test_synthetic_fixture_survives_future_clock_but_explicit_expiry_is_enforced(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        class FutureClock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2027, 1, 1, tzinfo=timezone.utc)
        with patch.object(protocol_module, 'datetime', FutureClock):
            prepared = protocol_module.validate_protocol(self.protocol_bytes(), self.work)
            self.assertEqual(prepared['evaluated_at'], '2027-01-01T00:00:00Z')
            expired = copy.deepcopy(self.protocol); expired['privacy']['retention_deadline'] = '2026-12-31'
            with self.assertRaises(ExtractionError) as caught:
                protocol_module.validate_protocol(self.raw(expired), self.work)
            self.assertEqual(caught.exception.code, 'STUDY_RETENTION_EXPIRED')

    def test_nanosecond_duration_rejects_rounding_bool_and_nonfinite_values(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        for value, expected in [(1, 1_000_000_000), (Decimal('0.000000001'), 1),
                                (Decimal('12345678901234567890.123456789'), 12345678901234567890123456789)]:
            self.assertEqual(protocol_module.duration_ns(value), expected)
        self.assertEqual(protocol_module.duration_ns(0, positive=False), 0)
        for value in (True, '1', 1.0, 0, -1, Decimal('0.0000000001'), Decimal('NaN'), Decimal('Infinity'), Decimal('1e-999999999')):
            with self.subTest(value=value), self.assertRaises(ExtractionError): protocol_module.duration_ns(value)
        for value in (True, 0, -1, '300'):
            protocol = copy.deepcopy(self.protocol); protocol['time_limit_seconds'] = value; self.invalid(protocol)

    def test_stamp_and_kst_day_preserve_nine_fractional_digits(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        a = protocol_module.stamp_ns('2026-11-03T14:59:59.999999999Z')
        b = protocol_module.stamp_ns('2026-11-03T15:00:00Z')
        self.assertEqual(b - a, 1)
        self.assertEqual(protocol_module.day_kst(a), '2026-11-03')
        self.assertEqual(protocol_module.day_kst(b), '2026-11-04')
        for value in ('2026-11-03T15:00:00.0000000001Z', '2026-11-03T15:00:00+00:00', '2026-02-30T00:00:00Z'):
            with self.subTest(value=value), self.assertRaises(ExtractionError): protocol_module.stamp_ns(value)

    def test_document_coverage_duplicates_https_and_identity_are_checked(self):
        for field in ('board_document_version_ids', 'prototype_document_version_ids'):
            for versions in ([], [self.source['document_version_id']] * 2, [uid(999)]):
                protocol = copy.deepcopy(self.protocol); protocol['source_set'][field] = versions; self.invalid(protocol)
        for key, value in [('document_id', uid(999)), ('document_version_id', uid(998)),
                           ('official_url', 'http://example.org/synthetic-notice'), ('text_sha256', '0' * 64)]:
            protocol = copy.deepcopy(self.protocol); protocol['source_set']['documents'][0][key] = value; self.invalid(protocol)
        self.protocol['source_set']['documents'].append(copy.deepcopy(self.protocol['source_set']['documents'][0])); self.invalid()

    def test_same_document_multiple_versions_count_once_and_all_versions_are_bound(self):
        source = copy.deepcopy(self.source); source['document_version_id'] = uid(50)
        self.snapshot['sources'].append(source)
        self.snapshot['event_public_payloads'][1]['source_version_ids'] = [uid(50)]
        document = copy.deepcopy(self.protocol['source_set']['documents'][0]); document['document_version_id'] = uid(50)
        self.protocol['source_set']['documents'].append(document)
        for key in ('board_document_version_ids', 'prototype_document_version_ids'):
            self.protocol['source_set'][key].append(uid(50))
        self.save_snapshot()
        prepared = self.prepare(); self.assertEqual(len(prepared['sources']), 2)
        self.snapshot['document_count'] = 2; self.save_snapshot(); self.invalid()

    def test_snapshot_selected_keys_identity_counts_and_source_edges_are_checked(self):
        for action in ('extra', 'version', 'created', 'source_extra', 'source_unused', 'source_duplicate',
                       'event_duplicate', 'revision_duplicate', 'revision_mismatch', 'event_count', 'document_count', 'event_source'):
            with self.subTest(action=action):
                snapshot = copy.deepcopy(self.snapshot)
                if action == 'extra': self.snapshot['PRIVATE_VALUE'] = 1
                elif action == 'version': self.snapshot['dictionary_version'] = 'other'
                elif action == 'created': self.snapshot['created_at'] = '2026-11-03T00:00:00.000000001Z'
                elif action == 'source_extra': self.snapshot['sources'][0]['official_url'] = 'https://example.org/other'
                elif action == 'source_unused': self.snapshot['sources'].append(dict(self.source, document_version_id=uid(999)))
                elif action == 'source_duplicate': self.snapshot['sources'].append(copy.deepcopy(self.source))
                elif action == 'event_duplicate': self.snapshot['event_public_payloads'][1]['event_id'] = uid(101)
                elif action == 'revision_duplicate': self.snapshot['revision_ids'][1] = self.snapshot['revision_ids'][0]
                elif action == 'revision_mismatch': self.snapshot['event_public_payloads'][1]['revision_id'] = uid(999)
                elif action == 'event_count': self.snapshot['event_count'] = True
                elif action == 'document_count': self.snapshot['document_count'] = 2
                else: self.snapshot['event_public_payloads'][0]['source_version_ids'] = [uid(999)]
                self.save_snapshot(); self.invalid(); self.snapshot = snapshot
        self.save_snapshot()

    def test_task_sets_have_unique_ids_categories_and_known_expected_events(self):
        for action in ('set', 'version', 'count', 'category', 'duplicate_task', 'unknown_event', 'duplicate_expected', 'extra'):
            with self.subTest(action=action):
                protocol = copy.deepcopy(self.protocol); task_set = protocol['task_sets'][0]
                if action == 'set': task_set['set_id'] = 'C'
                elif action == 'version': task_set['version'] = ' '
                elif action == 'count': task_set['items'].pop()
                elif action == 'category': task_set['items'][1]['category'] = task_set['items'][0]['category']
                elif action == 'duplicate_task': protocol['task_sets'][1]['items'][0]['task_id'] = task_set['items'][0]['task_id']
                elif action == 'unknown_event': task_set['items'][0]['expected_event_ids'] = [uid(999)]
                elif action == 'duplicate_expected': task_set['items'][0]['expected_event_ids'] *= 2
                else: task_set['items'][0]['PRIVATE_VALUE'] = 'unexpected'
                self.invalid(protocol)

    def test_artifact_hash_size_and_full_large_file_are_checked_without_copying(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        artifact = self.artifact('materials/large.bin', b'x' * (8 * 1024 * 1024 + 123))
        result = protocol_module._artifact(artifact, self.work)
        self.assertEqual((result['size'], result['sha256']), (artifact['size'], artifact['sha256']))
        self.assertEqual(result['path'], self.work / artifact['path'])
        for change in (dict(size=True), dict(size=-1), dict(size=artifact['size'] - 1), dict(sha256='0' * 64), dict(extra=1)):
            with self.subTest(change=change), self.assertRaises(ExtractionError):
                protocol_module._artifact(dict(artifact, **change), self.work)
        (self.work / self.protocol['source_set']['documents'][0]['artifact']['path']).write_bytes(b'changed')
        self.invalid()

    def test_canonical_paths_ancestor_symlinks_and_private_root_are_required(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        for name in ('', '.', '../escape', '/tmp/escape', 'materials//source.txt', 'materials/../source.txt',
                     'materials/./source.txt', 'materials\\source.txt', 'materials/source.txt/', 'nul\x00path'):
            with self.subTest(name=name), self.assertRaises(ExtractionError): protocol_module._path(self.work, name)
        self.assertEqual(protocol_module._path(self.work, 'reports/new/result.json'), self.work / 'reports/new/result.json')
        (self.work / 'linked').symlink_to(self.work / 'materials', target_is_directory=True)
        with self.assertRaises(ExtractionError): protocol_module._path(self.work, 'linked/source.txt')
        (self.work / 'file-link').symlink_to(self.work / 'materials/source.txt')
        with self.assertRaises(ExtractionError): protocol_module._path(self.work, 'file-link')
        self.work.chmod(0o750)
        try: self.invalid()
        finally: self.work.chmod(0o700)

    def test_root_leaf_symlink_is_rejected(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        (self.work / 'alias').symlink_to(self.work / 'materials', target_is_directory=True)
        with self.assertRaises(ExtractionError):
            protocol_module.validate_protocol(self.protocol_bytes(), self.work / 'alias', evaluated_at=STUDY_AT)

    def test_external_parent_alias_uses_existing_root_policy_and_resolves_normal_leaf(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        with tempfile.TemporaryDirectory(prefix='myai-study-root-alias-') as temporary:
            parent = Path(temporary).resolve() / 'parent-alias'
            parent.symlink_to(self.work.parent, target_is_directory=True)
            prepared = protocol_module.validate_protocol(self.protocol_bytes(), parent / self.work.name, evaluated_at=STUDY_AT)
        self.assertEqual(prepared['root'], self.work)

    def test_strict_json_duplicate_unicode_size_and_decimal_protocol_are_preserved(self):
        self.assertIsNotNone(protocol_module, 'study_protocol API is missing')
        for raw in (b'{"x":1,"x":2}', b'"\\ud800"', b'{"x":NaN}', b'[' * 102 + b'0' + b']' * 102,
                    b' ' * (8 * 1024 * 1024 + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(ExtractionError):
                protocol_module.validate_protocol(raw, self.work, evaluated_at=STUDY_AT)
        raw = self.protocol_bytes().replace(b'"time_limit_seconds":300', b'"time_limit_seconds":300.000000001')
        prepared = protocol_module.validate_protocol(raw, self.work, evaluated_at=STUDY_AT)
        self.assertEqual(prepared['protocol']['time_limit_seconds'], Decimal('300.000000001'))
        self.assertEqual(prepared['time_limit_ns'], 300_000_000_001)


if __name__ == '__main__':
    unittest.main()
