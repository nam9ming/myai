import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from unittest.mock import patch

from processing.evaluation import study
from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_study_protocol import StudyProtocolFixture, STUDY_AT, uid


class UserStudyFixture(StudyProtocolFixture):
    def setUp(self):
        super().setUp()
        self.protocol_path = self.work / 'protocol.json'
        self.records_path = self.work / 'records.json'
        self.protocol_path.write_bytes(self.protocol_bytes())
        person = self.person()
        self.records = dict(schema_version='user-study-records-v1', study_id=self.protocol['study_id'],
            protocol_sha256=hashlib.sha256(self.protocol_bytes()).hexdigest(), records_version='synthetic-records-v1',
            recruitment=[dict(participant_id=person['participant_id'], status='consented')], participants=[person], evidence=[])

    def person(self, sequence=1, *, participant_id=None, participant_type='merchant', role='user', board=100, prototype=80):
        person = dict(participant_id=participant_id or uid(2000 + sequence), participant_type=participant_type,
            participation_role=role, consent=dict(version=self.protocol['privacy']['consent_version'], consented_at='2026-11-03T00:45:00Z'),
            photo_consent=None, assignment_sequence=sequence if role == 'user' else None, sessions=[],
            interview=dict(convenience=4, usefulness=5, continued_use=None),
            observations=dict(needs_check_understood=True, distance_distinction_understood=False, source_access_succeeded=None),
            feedback=dict(satisfied='PRIVATE_FEEDBACK', required_changes='PRIVATE_CHANGES'))
        if role == 'expert': return person
        order = ((('board', 'A'), ('prototype', 'B')), (('prototype', 'A'), ('board', 'B')),
                 (('board', 'B'), ('prototype', 'A')), (('prototype', 'B'), ('board', 'A')))[(sequence - 1) % 4]
        sets = {value['set_id']: value for value in self.protocol['task_sets']}
        start = datetime(2026, 11, 3, sequence, tzinfo=timezone.utc)
        for index, (method, name) in enumerate(order):
            session = dict(method=method, task_set=name, task_set_version=sets[name]['version'],
                device_browser='synthetic-pc-browser-v1', network='synthetic-network', instruction_seconds=30,
                timing_includes_loading=True, source_check=dict(checked_at='2026-11-03T00:30:00Z', originals_changed=False), records=[])
            duration = board if method == 'board' else prototype
            for task_index, task in enumerate(sets[name]['items']):
                begin = start + timedelta(minutes=10 * index, seconds=task_index * 120)
                session['records'].append(dict(task_id=task['task_id'], started_at=begin.isoformat().replace('+00:00', 'Z'),
                    ended_at=(begin + timedelta(seconds=duration)).isoformat().replace('+00:00', 'Z'), elapsed_seconds=duration,
                    outcome='correct', date_correct=True, place_correct=True, target_correct=True, exceptions_correct=True,
                    reported_event_ids=copy.deepcopy(task['expected_event_ids']), missed_event_ids=[], false_positive_ids=[],
                    out_of_scope_ids=[], assistance_notes=None, answer_feedback_given=False, operation_taken_over=False))
            person['sessions'].append(session)
        return person

    def add_person(self, sequence, **kwargs):
        person = self.person(sequence, **kwargs)
        self.records['participants'].append(person)
        self.records['recruitment'].append(dict(participant_id=person['participant_id'], status='consented'))
        return person

    def write_records(self, value=None):
        self.records_path.write_bytes(_json(self.records if value is None else value))
        self.protocol_path.write_bytes(self.protocol_bytes())
        return self.records_path

    def study(self, value=None, protocol=None, at=STUDY_AT):
        prepared = self.prepare(protocol, at)
        selected = copy.deepcopy(self.records if value is None else value)
        if protocol is not None: selected['protocol_sha256'] = prepared['protocol_sha256']
        return study.evaluate_study(_json(selected), prepared)

    def invalid(self, value, code=None):
        with self.assertRaises(ExtractionError) as caught: self.study(value)
        if code: self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_', str(caught.exception))

    def not_started(self, record, outcome='not_started'):
        record.update({key: None for key in ('started_at', 'ended_at', 'elapsed_seconds', 'date_correct', 'place_correct',
            'target_correct', 'exceptions_correct', 'reported_event_ids', 'missed_event_ids', 'false_positive_ids', 'out_of_scope_ids')})
        record['outcome'] = outcome

    def fictional_real(self):
        self.protocol['data_kind'] = self.snapshot['data_kind'] = 'real'
        self.save_snapshot()
        self.records['protocol_sha256'] = hashlib.sha256(self.protocol_bytes()).hexdigest()


class UserStudyTest(UserStudyFixture):
    def test_six_tasks_preserve_normalized_details_and_private_safe_summary(self):
        packet = self.study(); result, summary = packet['result'], packet['summary']
        self.assertEqual(set(result), set('schema_version study_id protocol_version records_version protocol_sha256 records_sha256 evaluated_at phase data_kind privacy versions summary participants'.split()))
        self.assertEqual(set(summary), set('protocol_version data_kind phase recruitment participants m04 methods primary interviews observations evidence warnings generalization_claim'.split()))
        self.assertEqual(summary['protocol_version'], 'user-study-summary-v1')
        analysis = result['participants'][0]['analysis']
        self.assertEqual(set(analysis), set('started finished_all all_correct eligible_pair exclusion_reasons board_ns prototype_ns reduction_percent deviations'.split()))
        self.assertEqual((analysis['board_ns'], analysis['prototype_ns'], analysis['reduction_percent']), (300_000_000_000, 240_000_000_000, 20.0))
        self.assertTrue(analysis['eligible_pair'])
        self.assertEqual(summary['primary']['eligible_pairs'], 1)
        self.assertIsNone(summary['primary']['meets_20_percent_as_declared'])
        self.assertIsNone(summary['primary']['improvement_supported_as_declared'])
        self.assertEqual(summary['methods']['board']['assigned_tasks'], 3)
        self.assertEqual(summary['methods']['board']['missed_incidence']['expected'], 3)
        self.assertEqual(summary['methods']['board']['missed_incidence']['rate_percent'], 0.0)
        for session in result['participants'][0]['sessions']:
            self.assertEqual(session['instruction_ns'], 30_000_000_000)
            self.assertNotIn('instruction_seconds', session)
            for record in session['records']:
                self.assertNotIn('elapsed_seconds', record); self.assertIn('elapsed_ns', record); self.assertIn('expected_event_ids', record)
        self.assertEqual(result['privacy'], self.protocol['privacy']); self.assertEqual(result['versions'], self.protocol['versions'])
        raw = json.dumps(summary)
        for private in ('PRIVATE_', self.records['participants'][0]['participant_id'], str(self.work), 'consented_at', 'feedback'):
            self.assertNotIn(private, raw)
        self.assertFalse(summary['generalization_claim'])

    def test_declared_real_main_one_eligible_pair_can_meet_twenty_without_three_pair_gate(self):
        self.fictional_real(); summary = self.study()['summary']
        self.assertTrue(summary['primary']['meets_20_percent_as_declared'])
        self.assertTrue(summary['primary']['improvement_supported_as_declared'])
        self.assertIs(summary['m04']['meets_minimum_3_as_declared'], False)
        self.assertIs(summary['m04']['meets_target_6_as_declared'], False)

    def test_four_cycle_assignments_and_participant_types_are_separate(self):
        for sequence in range(2, 7): self.add_person(sequence, participant_type='resident' if sequence == 2 else 'merchant')
        self.add_person(7, participant_type='expert', role='expert')
        self.fictional_real(); result = self.study(); summary = result['summary']
        self.assertEqual((summary['participants']['users'], summary['participants']['experts'], summary['m04']['started_users']), (6, 1, 6))
        self.assertTrue(summary['m04']['meets_target_6_as_declared'])
        self.assertEqual(summary['m04']['merchant_started_users'], 5)
        self.assertEqual(summary['primary']['eligible_pairs'], 6)
        self.assertEqual(summary['participants']['by_type']['resident']['users'], 1)
        self.assertEqual(summary['interviews']['expert']['convenience']['answered'], 1)

    def test_wrong_assignment_version_duplicate_sequence_role_and_pilot_ids_are_rejected(self):
        changes = [lambda v: v['participants'][0].update(assignment_sequence=True),
            lambda v: v['participants'][0].update(participant_type='expert'),
            lambda v: v['participants'][0]['sessions'][0].update(task_set='B'),
            lambda v: v['participants'][0]['sessions'][0].update(task_set_version='wrong'),
            lambda v: v['participants'][0].update(participant_id=uid(900))]
        for change in changes:
            value = copy.deepcopy(self.records); change(value)
            if value['participants'][0]['participant_id'] == uid(900): value['recruitment'][0]['participant_id'] = uid(900)
            with self.subTest(change=change): self.invalid(value)
        self.add_person(1, participant_id=uid(2999)); self.invalid(self.records)

    def test_recruitment_no_details_and_withdrawal_denominators_are_preserved(self):
        self.fictional_real()
        for number, status in enumerate(('invited', 'declined', 'no_show', 'withdrawn')):
            self.records['recruitment'].append(dict(participant_id=uid(3000 + number), status=status))
        summary = self.study()['summary']
        self.assertEqual(summary['recruitment']['total'], 5)
        self.assertEqual(summary['recruitment']['missing_participant_details'], 2)
        self.assertIsNone(summary['primary']['improvement_supported_as_declared'])
        self.assertIs(summary['primary']['comparison_conditions_confirmed'], False)
        value = copy.deepcopy(self.records); value['recruitment'][-1]['status'] = 'consented'; self.invalid(value)
        value = copy.deepcopy(self.records); value['recruitment'][0]['status'] = 'declined'; self.invalid(value)

    def test_not_started_and_unknown_missing_do_not_become_zero_or_disappear(self):
        value = copy.deepcopy(self.records)
        self.not_started(value['participants'][0]['sessions'][1]['records'][1])
        result = self.study(value); metric = result['summary']['methods']['prototype']
        self.assertEqual((metric['assigned_tasks'], metric['started_tasks'], metric['not_started_tasks']), (3, 2, 1))
        self.assertEqual(metric['missed_incidence']['expected'], 3)
        self.assertEqual(metric['missed_incidence']['unknown'], 2)
        self.assertIsNone(metric['missed_incidence']['rate_percent'])
        self.assertEqual(metric['missed_incidence']['upper_bound_percent'], 200 / 3)
        self.assertFalse(result['result']['participants'][0]['analysis']['eligible_pair'])

    def test_deviations_remain_in_details_and_exclude_pair(self):
        mutations = [lambda p: p['sessions'][1].update(device_browser='other-browser'),
            lambda p: p['sessions'][1].update(network='other-network'),
            lambda p: p['sessions'][1].update(instruction_seconds=31),
            lambda p: p['sessions'][1].update(timing_includes_loading=False),
            lambda p: p['sessions'][1].update(source_check=None),
            lambda p: p['sessions'][1]['source_check'].update(originals_changed=True),
            lambda p: p['sessions'][1]['source_check'].update(checked_at='2026-11-02T14:30:00Z'),
            lambda p: p['sessions'][1]['records'][0].update(answer_feedback_given=True),
            lambda p: p['sessions'][1]['records'][0].update(operation_taken_over=True)]
        for mutate in mutations:
            value = copy.deepcopy(self.records); mutate(value['participants'][0])
            with self.subTest(mutate=mutate):
                packet = self.study(value); analysis = packet['result']['participants'][0]['analysis']
                self.assertFalse(analysis['eligible_pair']); self.assertTrue(analysis['deviations'])
                self.assertEqual(packet['summary']['methods']['prototype']['assigned_tasks'], 3)

    def test_elapsed_and_clock_boundaries_are_exact_and_timeout_limit_is_inclusive(self):
        for key, bad in (('elapsed_seconds', True), ('elapsed_seconds', 99), ('started_at', None),
                         ('ended_at', '2026-11-04T04:00:00Z'), ('date_correct', 1)):
            value = copy.deepcopy(self.records); value['participants'][0]['sessions'][0]['records'][0][key] = bad
            with self.subTest(key=key, bad=bad): self.invalid(value)
        value = copy.deepcopy(self.records); r = value['participants'][0]['sessions'][0]['records'][2]
        r.update(ended_at='2026-11-03T01:09:00Z', elapsed_seconds=300)
        self.invalid(value)
        r['outcome'] = 'timeout'
        self.assertEqual(self.study(value)['summary']['methods']['board']['outcomes']['timeout'], 1)

    def test_consents_task_coverage_overlap_and_order_are_strict(self):
        mutations = [lambda p: p['consent'].update(version='wrong'), lambda p: p.update(consent=None),
            lambda p: p['consent'].update(consented_at='2026-11-03T02:00:00Z'),
            lambda p: p['sessions'][0]['records'].pop(),
            lambda p: p['sessions'][0]['records'].append(copy.deepcopy(p['sessions'][0]['records'][0])),
            lambda p: p['sessions'].reverse(),
            lambda p: p['sessions'][0]['records'][1].update(started_at='2026-11-03T01:01:00Z', ended_at='2026-11-03T01:02:40Z')]
        for mutate in mutations:
            value = copy.deepcopy(self.records); mutate(value['participants'][0])
            with self.subTest(mutate=mutate): self.invalid(value)

    def test_reported_sets_are_recomputed_outside_events_are_separate(self):
        value = copy.deepcopy(self.records); r = value['participants'][0]['sessions'][0]['records'][0]
        r['reported_event_ids'].append(uid(9999)); r['out_of_scope_ids'] = [uid(9999)]
        self.assertTrue(self.study(value)['result']['participants'][0]['analysis']['eligible_pair'])
        r['out_of_scope_ids'] = []; self.invalid(value)
        value = copy.deepcopy(self.records); r = value['participants'][0]['sessions'][0]['records'][0]
        r.update(reported_event_ids=None, missed_event_ids=[uid(101)], outcome='incorrect', target_correct=False)
        self.assertEqual(self.study(value)['summary']['methods']['board']['missed_incidence']['missed'], 1)
        r['outcome'] = 'correct'; self.invalid(value)
        value = copy.deepcopy(self.records); value['participants'][0]['sessions'][0]['records'][0]['outcome'] = 'incorrect'; self.invalid(value)

    def test_pilot_experts_zero_pairs_and_survey_unknowns_remain_separate(self):
        protocol = copy.deepcopy(self.protocol); protocol.update(phase='pilot', pilot_review=None)
        summary = self.study(protocol=protocol)['summary']
        self.assertIsNone(summary['m04']['meets_target_6_as_declared'])
        self.assertIsNone(summary['primary']['meets_20_percent_as_declared'])
        expert = self.person(2, participant_type='expert', role='expert')
        value = copy.deepcopy(self.records); value['participants'] = [expert]; value['recruitment'][0]['participant_id'] = expert['participant_id']
        summary = self.study(value)['summary']
        self.assertEqual(summary['primary']['eligible_pairs'], 0); self.assertIsNone(summary['primary']['median_reduction_percent'])
        self.assertEqual(summary['interviews']['expert']['continued_use']['unknown'], 1)
        self.assertEqual(summary['observations']['expert']['source_access_succeeded']['unknown'], 1)

    def test_protocol_identity_extra_keys_types_and_raw_bytes_sha_are_strict(self):
        for mutate in [lambda v: v.update(study_id=uid(9)), lambda v: v.update(protocol_sha256='0' * 64),
                       lambda v: v.update(records_version=' '), lambda v: v.update(extra=True),
                       lambda v: v['participants'][0].update(real_name='PRIVATE_REAL_NAME')]:
            value = copy.deepcopy(self.records); mutate(value)
            with self.subTest(mutate=mutate): self.invalid(value)
        self.assertEqual(self.study()['result']['records_sha256'], hashlib.sha256(_json(self.records)).hexdigest())

    def test_evidence_requires_photo_consent_and_checked_whole_artifact(self):
        value = copy.deepcopy(self.records)
        value['evidence'] = [dict(evidence_id=uid(4000), artifact=self.artifact('evidence/synthetic.txt', b'not actual photo'),
            kind='deidentified_photo', participant_id=value['participants'][0]['participant_id'], captured_at='2026-11-03T02:00:00Z',
            issue_ids=['PRIVATE_ISSUE'], change_refs=['PRIVATE_CHANGE'], note='합성 증빙; 실제 사진 아님')]
        self.invalid(value)
        value['participants'][0]['photo_consent'] = dict(version=self.protocol['privacy']['photo_consent_version'], consented_at='2026-11-03T00:45:00Z')
        self.assertEqual(self.study(value)['summary']['evidence']['verified_artifacts'], 1)
        (self.work / 'evidence/synthetic.txt').write_bytes(b'changed'); self.invalid(value)

    def test_input_and_incremental_output_limits_are_checked(self):
        with self.assertRaises(ExtractionError): study.evaluate_study(b' ' * (8 * 1024 * 1024 + 1), self.prepare())
        with patch.object(study, 'MAX_BYTES', 1000), self.assertRaises(ExtractionError) as caught: self.study()
        self.assertEqual(caught.exception.code, 'STUDY_RESULT_TOO_LARGE')

    def test_long_valid_labels_have_only_global_limit_and_environment_controls_are_rejected(self):
        value = copy.deepcopy(self.records); value['records_version'] = 'r' * 200
        for session in value['participants'][0]['sessions']:
            session.update(device_browser='b' * 200, network='n' * 200)
        self.assertTrue(self.study(value)['result']['participants'][0]['analysis']['eligible_pair'])

    def test_environment_labels_reject_control_characters(self):
        value = copy.deepcopy(self.records)
        value['participants'][0]['sessions'][0]['device_browser'] = 'browser\nPRIVATE_LINE'
        self.invalid(value)

    def test_malformed_unhashable_participant_identity_is_an_input_error(self):
        for bad in ([], {}, ['PRIVATE_ID']):
            value = copy.deepcopy(self.records); value['participants'][0]['participant_id'] = bad
            with self.subTest(bad=bad): self.invalid(value)

    def decimal_bytes(self, value):
        from decimal import Decimal
        def encode(item):
            if type(item) is Decimal: return str(item)
            if type(item) is dict: return '{' + ','.join(json.dumps(key) + ':' + encode(entry) for key, entry in item.items()) + '}'
            if type(item) is list: return '[' + ','.join(encode(entry) for entry in item) + ']'
            return json.dumps(item, ensure_ascii=False)
        return encode(value).encode()

    def nanosecond_records(self, board_ns, prototype_ns):
        from decimal import Decimal
        value = copy.deepcopy(self.records)
        for session in value['participants'][0]['sessions']:
            total = board_ns if session['method'] == 'board' else prototype_ns
            quotient, remainder = divmod(total, 3)
            for index, record in enumerate(session['records']):
                ns = quotient + int(index < remainder)
                start = datetime.fromisoformat(record['started_at'])
                end = start + timedelta(seconds=ns // 1_000_000_000)
                record['ended_at'] = end.strftime('%Y-%m-%dT%H:%M:%S') + (f'.{ns % 1_000_000_000:09d}' if ns % 1_000_000_000 else '') + 'Z'
                record['elapsed_seconds'] = Decimal(ns).scaleb(-9)
                session['instruction_seconds'] = Decimal('30.000000001')
        return value

    def test_exact_nanoseconds_survive_normalization_and_twenty_percent_near_boundary(self):
        self.fictional_real()
        for prototype_ns, meets in ((2_400_000_000, True), (2_400_000_001, False), (2_399_999_999, True)):
            value = self.nanosecond_records(3_000_000_000, prototype_ns); raw = self.decimal_bytes(value)
            with self.subTest(prototype_ns=prototype_ns):
                packet = study.evaluate_study(raw, self.prepare()); person = packet['result']['participants'][0]
                self.assertEqual(person['analysis']['board_ns'], 3_000_000_000)
                self.assertEqual(person['analysis']['prototype_ns'], prototype_ns)
                self.assertEqual(person['sessions'][0]['instruction_ns'], 30_000_000_001)
                self.assertEqual(packet['summary']['primary']['meets_20_percent_as_declared'], meets)
                self.assertEqual(packet['result']['records_sha256'], hashlib.sha256(raw).hexdigest())
                _json(packet['result'])
        from decimal import Decimal
        value = self.nanosecond_records(3_000_000_000, 2_400_000_000)
        value['participants'][0]['sessions'][0]['records'][0]['elapsed_seconds'] = Decimal('1.0000000001')
        with self.assertRaises(ExtractionError): study.evaluate_study(self.decimal_bytes(value), self.prepare())

    def test_negative_and_even_fraction_medians_keep_every_eligible_pair(self):
        self.add_person(2, prototype=120)
        packet = self.study(); self.assertEqual(packet['summary']['primary']['median_reduction_percent'], 0.0)
        self.assertEqual([p['analysis']['reduction_percent'] for p in packet['result']['participants']], [20.0, -20.0])
        self.add_person(3, prototype=110)
        self.assertEqual(self.study()['summary']['primary']['median_reduction_percent'], -10.0)

    def test_known_accuracy_worsening_blocks_time_success(self):
        self.fictional_real(); person = self.add_person(2)
        row = next(s for s in person['sessions'] if s['method'] == 'prototype')['records'][0]
        row.update(outcome='incorrect', target_correct=False)
        packet = self.study(); primary = packet['summary']['primary']
        self.assertTrue(primary['meets_20_percent_as_declared'])
        self.assertIs(primary['improvement_supported_as_declared'], False)
        self.assertEqual(packet['summary']['primary']['eligible_pairs'], 1)

    def test_known_omission_worsening_blocks_success_with_equal_completion_accuracy(self):
        self.fictional_real(); person = self.add_person(2)
        board = next(s for s in person['sessions'] if s['method'] == 'board')['records'][0]
        prototype = next(s for s in person['sessions'] if s['method'] == 'prototype')['records'][0]
        board.update(outcome='incorrect', date_correct=False)
        prototype.update(outcome='incorrect', target_correct=False, reported_event_ids=[], missed_event_ids=[uid(101)])
        packet = self.study(); methods = packet['summary']['methods']
        self.assertEqual(methods['board']['accuracy_percent'], methods['prototype']['accuracy_percent'])
        self.assertIs(packet['summary']['primary']['improvement_supported_as_declared'], False)

    def test_unknown_correctness_and_missed_fields_make_improvement_unconfirmed(self):
        self.fictional_real(); person = self.add_person(2)
        for session in person['sessions']:
            row = session['records'][0]
            row.update(outcome='incorrect', date_correct=None, reported_event_ids=None, missed_event_ids=None)
        packet = self.study(); primary = packet['summary']['primary']
        self.assertTrue(primary['meets_20_percent_as_declared'])
        self.assertIsNone(primary['improvement_supported_as_declared'])
        self.assertIs(primary['comparison_conditions_confirmed'], False)
        for method in ('board', 'prototype'):
            self.assertEqual(packet['summary']['methods'][method]['correctness']['date_correct']['unknown'], 1)
            self.assertIsNone(packet['summary']['methods'][method]['missed_incidence']['rate_percent'])

    def test_complete_zero_expected_rates_remain_na_and_one_zero_method_is_not_comparable(self):
        self.fictional_real(); protocol = copy.deepcopy(self.protocol); value = copy.deepcopy(self.records)
        for task_set in protocol['task_sets']:
            for task in task_set['items']: task['expected_event_ids'] = []
        for session in value['participants'][0]['sessions']:
            for row in session['records']: row['reported_event_ids'] = []
        summary = self.study(value, protocol)['summary']
        self.assertTrue(summary['primary']['comparison_conditions_confirmed'])
        self.assertTrue(summary['primary']['improvement_supported_as_declared'])
        self.assertIsNone(summary['methods']['board']['missed_incidence']['rate_percent'])
        protocol['task_sets'][1] = copy.deepcopy(self.protocol['task_sets'][1])
        value['participants'][0]['sessions'][1]['records'] = copy.deepcopy(self.records['participants'][0]['sessions'][1]['records'])
        summary = self.study(value, protocol)['summary']
        self.assertIs(summary['primary']['comparison_conditions_confirmed'], False)
        self.assertIsNone(summary['primary']['improvement_supported_as_declared'])

    def test_sequence_gaps_and_cross_participant_concurrency_are_preserved(self):
        person = self.add_person(3)
        # 다른 사람의 동시 수행은 허용한다. 개인 내부의 여섯 구간은 겹치지 않는다.
        for session, original in zip(person['sessions'], self.records['participants'][0]['sessions']):
            for row, prior in zip(session['records'], original['records']):
                row.update(started_at=prior['started_at'], ended_at=prior['ended_at'])
        summary = self.study()['summary']
        self.assertEqual(summary['participants']['assignment']['missing_slots'], 1)
        self.assertIn('ASSIGNMENT_SEQUENCE_GAPS', summary['warnings'])
        self.assertEqual(summary['primary']['eligible_pairs'], 2)

    def test_non_started_technical_failure_and_withdrawal_keep_null_times(self):
        value = copy.deepcopy(self.records)
        for session in value['participants'][0]['sessions']:
            for index, row in enumerate(session['records']): self.not_started(row, 'technical_failure' if index % 2 else 'withdrawn')
        summary = self.study(value)['summary']
        self.assertEqual(summary['m04']['started_users'], 0)
        self.assertEqual(summary['methods']['board']['assigned_tasks'], 3)
        self.assertEqual(summary['methods']['board']['missed_incidence']['unknown'], 3)
        self.assertIsNone(summary['primary']['median_reduction_percent'])
        row = value['participants'][0]['sessions'][0]['records'][0]; row['elapsed_seconds'] = 0
        self.invalid(value)

    def test_duplicate_evidence_references_do_not_inflate_verified_artifact_count(self):
        artifact = self.artifact('evidence/shared.txt', b'synthetic evidence')
        self.records['evidence'] = [dict(evidence_id=uid(4100 + index), artifact=copy.deepcopy(artifact),
            kind='screen_capture', participant_id=None, captured_at='2026-11-03T02:00:00Z',
            issue_ids=[], change_refs=[], note='합성 증빙') for index in range(2)]
        evidence = self.study()['summary']['evidence']
        self.assertEqual((evidence['records'], evidence['verified_artifacts']), (2, 1))
        self.assertFalse(evidence['meets_2_artifacts_as_declared'])

    def test_source_drift_after_prepare_and_expiration_before_records_decode_are_rejected(self):
        self.protocol['privacy']['retention_deadline'] = '2026-12-31'
        self.records['protocol_sha256'] = hashlib.sha256(self.protocol_bytes()).hexdigest()
        prepared = self.prepare()
        source = self.work / self.protocol['source_set']['documents'][0]['artifact']['path']
        source.write_bytes(b'changed after prepare')
        with self.assertRaises(ExtractionError): study.evaluate_study(_json(self.records), prepared)
        prepared['evaluated_at'] = '2026-12-31T15:00:00Z'
        with self.assertRaises(ExtractionError) as caught: study.evaluate_study(b'not-json', prepared)
        self.assertEqual(caught.exception.code, 'STUDY_RETENTION_EXPIRED')

    def test_copied_evidence_keeps_records_without_inflating_artifact_target(self):
        self.records['evidence'] = [dict(evidence_id=uid(4200 + index),
            artifact=self.artifact(f'evidence/copy-{index}.txt', b'one synthetic capture'),
            kind='screen_capture', participant_id=None, captured_at='2026-11-03T02:00:00Z',
            issue_ids=[], change_refs=[], note='같은 합성 증빙의 복사본') for index in range(2)]
        summary = self.study()['summary']; evidence = summary['evidence']
        self.assertEqual((evidence['records'], evidence['verified_artifacts']), (2, 1))
        self.assertFalse(evidence['meets_2_artifacts_as_declared'])
        self.assertIn('EVIDENCE_TARGET_SHORTFALL', summary['warnings'])

    def test_started_failure_preserves_actual_time_and_nullable_fp_outside_counts(self):
        value = copy.deepcopy(self.records); row = value['participants'][0]['sessions'][0]['records'][0]
        row.update(outcome='technical_failure', ended_at='2026-11-03T01:00:42Z', elapsed_seconds=42,
            date_correct=None, place_correct=None, target_correct=None, exceptions_correct=None,
            reported_event_ids=None, missed_event_ids=None, false_positive_ids=None, out_of_scope_ids=None)
        packet = self.study(value); participant = packet['result']['participants'][0]; method = packet['summary']['methods']['board']
        self.assertEqual(participant['analysis']['board_ns'], 242_000_000_000)
        self.assertIsNone(participant['analysis']['reduction_percent'])
        self.assertEqual(participant['sessions'][0]['records'][0]['elapsed_ns'], 42_000_000_000)
        self.assertEqual((method['started_tasks'], method['outcomes']['technical_failure'], method['exact_correct']), (3, 1, 2))
        self.assertEqual((method['false_positive_unknown_tasks'], method['out_of_scope_unknown_tasks']), (1, 1))

    def test_strict_json_rejects_duplicate_keys_invalid_unicode_and_depth(self):
        prepared = self.prepare(); raw = _json(self.records)
        cases = [b'\xff', b'{}{}', raw.replace(b'"schema_version":', b'"schema_version":"duplicate","schema_version":', 1),
                 raw.replace(b'PRIVATE_FEEDBACK', b'\\ud800'), b'[' * 101 + b'0' + b']' * 101]
        for content in cases:
            with self.subTest(content=content[:32]), self.assertRaises(ExtractionError): study.evaluate_study(content, prepared)

    def test_empty_recruitment_and_zero_users_are_explicit_na(self):
        value = copy.deepcopy(self.records); value.update(recruitment=[], participants=[])
        summary = self.study(value)['summary']
        self.assertEqual(summary['m04']['started_users'], 0)
        self.assertEqual(summary['primary']['eligible_pairs'], 0)
        self.assertIsNone(summary['primary']['median_reduction_percent'])
        self.assertIsNone(summary['methods']['board']['accuracy_percent'])
        self.assertIsNone(summary['methods']['board']['missed_incidence']['rate_percent'])

    def test_photo_consent_time_future_source_check_and_expert_sessions_are_rejected(self):
        changes = [lambda p: p.update(photo_consent=dict(version='wrong', consented_at='2026-11-03T00:45:00Z')),
            lambda p: p['sessions'][0]['source_check'].update(checked_at='2026-11-04T04:00:00Z'),
            lambda p: p.update(participation_role='expert', participant_type='expert')]
        for change in changes:
            value = copy.deepcopy(self.records); change(value['participants'][0])
            with self.subTest(change=change): self.invalid(value)

    def test_timeout_over_limit_retains_original_time_without_capping(self):
        value = copy.deepcopy(self.records); row = value['participants'][0]['sessions'][0]['records'][2]
        row.update(outcome='timeout', ended_at='2026-11-03T01:09:01Z', elapsed_seconds=301)
        packet = self.study(value)
        self.assertEqual(packet['result']['participants'][0]['sessions'][0]['records'][2]['elapsed_ns'], 301_000_000_000)
        self.assertEqual(packet['summary']['methods']['board']['outcomes']['timeout'], 1)

    def test_started_no_show_or_withdrawn_details_are_kept_but_global_comparison_unconfirmed(self):
        self.fictional_real(); self.add_person(2)
        for status in ('no_show', 'withdrawn'):
            value = copy.deepcopy(self.records); value['recruitment'][1]['status'] = status
            with self.subTest(status=status):
                packet = self.study(value); primary = packet['summary']['primary']
                self.assertEqual(len(packet['result']['participants']), 2)
                self.assertEqual(packet['summary']['m04']['started_users'], 2)
                self.assertEqual(primary['eligible_pairs'], 1)
                self.assertTrue(primary['meets_20_percent_as_declared'])
                self.assertIs(primary['comparison_conditions_confirmed'], False)
                self.assertIsNone(primary['improvement_supported_as_declared'])
                self.assertIn('RECRUITMENT_NOT_CONSENTED', packet['result']['participants'][1]['analysis']['exclusion_reasons'])

    def test_known_failed_time_target_is_false_even_when_cohort_conditions_unconfirmed(self):
        self.fictional_real()
        for record in self.records['participants'][0]['sessions'][1]['records']:
            record['elapsed_seconds'] = 100
            start = datetime.fromisoformat(record['started_at'])
            record['ended_at'] = (start + timedelta(seconds=100)).isoformat().replace('+00:00', 'Z')
        self.records['recruitment'].append(dict(participant_id=uid(5000), status='withdrawn'))
        primary = self.study()['summary']['primary']
        self.assertIs(primary['comparison_conditions_confirmed'], False)
        self.assertIs(primary['meets_20_percent_as_declared'], False)
        self.assertIs(primary['improvement_supported_as_declared'], False)

    def test_ephemeral_records_content_preserves_exact_original_wire_bytes_and_sha(self):
        value = self.nanosecond_records(3_000_000_000, 2_400_000_001)
        raw = self.decimal_bytes(value) + b'\n  '
        packet = study.evaluate_study(raw, self.prepare())
        self.assertIs(type(packet['records_content']), bytes)
        self.assertEqual(packet['records_content'], raw)
        self.assertEqual(hashlib.sha256(packet['records_content']).hexdigest(), packet['result']['records_sha256'])
        self.assertNotIn('records_content', packet['result'])
        self.assertNotIn('records_content', packet['summary'])
        self.assertEqual(packet['result']['participants'][0]['analysis']['prototype_ns'], 2_400_000_001)

    def test_partial_three_and_six_person_cycles_warn_without_excluding_pairs(self):
        self.fictional_real()
        self.add_person(2); self.add_person(3)
        summary = self.study()['summary']
        self.assertEqual(summary['participants']['assignment']['cycle_counts'], {'1': 1, '2': 1, '3': 1, '4': 0})
        self.assertIn('ASSIGNMENT_CYCLE_IMBALANCE', summary['warnings'])
        self.assertEqual(summary['primary']['eligible_pairs'], 3)
        self.assertIs(summary['m04']['meets_minimum_3_as_declared'], True)
        self.assertIs(summary['primary']['improvement_supported_as_declared'], True)
        for sequence in range(4, 7): self.add_person(sequence)
        summary = self.study()['summary']
        self.assertEqual(summary['participants']['assignment']['cycle_counts'], {'1': 2, '2': 2, '3': 1, '4': 1})
        self.assertIn('ASSIGNMENT_CYCLE_IMBALANCE', summary['warnings'])
        self.assertEqual(summary['primary']['eligible_pairs'], 6)
        self.assertIs(summary['m04']['meets_target_6_as_declared'], True)
        self.assertIs(summary['primary']['improvement_supported_as_declared'], True)

    def unknown_operations(self, participant):
        for session in participant['sessions']:
            session.update(instruction_seconds=None, timing_includes_loading=None)
            session['source_check']['originals_changed'] = None
            for row in session['records']:
                row.update(answer_feedback_given=None, operation_taken_over=None)

    def test_unknown_operational_conditions_keep_all_correct_answers_without_invented_values(self):
        self.fictional_real(); self.unknown_operations(self.records['participants'][0])
        packet = self.study(); person = packet['result']['participants'][0]; analysis = person['analysis']
        self.assertTrue(analysis['all_correct']); self.assertTrue(analysis['finished_all'])
        self.assertIs(analysis['eligible_pair'], False)
        self.assertEqual(set(analysis['deviations']), {'INSTRUCTION_TIME_UNKNOWN', 'LOADING_TIME_UNKNOWN',
            'ASSISTANCE_STATUS_UNKNOWN', 'ORIGINAL_CHANGE_STATUS_UNKNOWN'})
        for session in person['sessions']:
            self.assertIsNone(session['instruction_ns']); self.assertIsNone(session['timing_includes_loading'])
            self.assertIsNone(session['source_check']['originals_changed'])
            for row in session['records']:
                self.assertIsNone(row['answer_feedback_given']); self.assertIsNone(row['operation_taken_over'])
        primary = packet['summary']['primary']
        self.assertEqual(primary['eligible_pairs'], 0)
        self.assertIs(primary['comparison_conditions_confirmed'], False)
        self.assertIsNone(primary['improvement_supported_as_declared'])
        for method in ('board', 'prototype'):
            self.assertEqual((packet['summary']['methods'][method]['started_tasks'], packet['summary']['methods'][method]['exact_correct']), (3, 3))

    def test_unknown_operational_user_keeps_other_valid_time_pair_but_whole_improvement_unknown(self):
        self.fictional_real(); participant = self.add_person(2); self.unknown_operations(participant)
        primary = self.study()['summary']['primary']
        self.assertEqual(primary['eligible_pairs'], 1)
        self.assertEqual(primary['median_reduction_percent'], 20.0)
        self.assertIs(primary['meets_20_percent_as_declared'], True)
        self.assertIs(primary['comparison_conditions_confirmed'], False)
        self.assertIsNone(primary['improvement_supported_as_declared'])
        changes = [lambda p, bad: p['sessions'][0].update(instruction_seconds=bad),
            lambda p, bad: p['sessions'][0].update(timing_includes_loading=bad),
            lambda p, bad: p['sessions'][0]['source_check'].update(originals_changed=bad),
            lambda p, bad: p['sessions'][0]['records'][0].update(answer_feedback_given=bad),
            lambda p, bad: p['sessions'][0]['records'][0].update(operation_taken_over=bad)]
        for change in changes:
            for bad in (1, 'unknown'):
                if bad == 1 and change is changes[0]: continue
                value = copy.deepcopy(self.records); change(value['participants'][0], bad)
                with self.subTest(change=change, bad=bad): self.invalid(value)
        value = copy.deepcopy(self.records); value['participants'][0]['sessions'][0]['instruction_seconds'] = True
        self.invalid(value)
