import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

from processing.matching.protocol import run, ProtocolError, MAX_BYTES
from support import payload, ROOT


def raw(p):
    return json.dumps(p, ensure_ascii=False).encode('utf-8')


class ProtocolTest(unittest.TestCase):
    def test_echo_and_raw_input_hash(self):
        p = payload()
        content = raw(p) + b'\n'
        result = run(content)
        self.assertEqual('calc-v1', result['protocol_version'])
        self.assertEqual(p['snapshot_id'], result['snapshot_id'])
        self.assertEqual(p['request_id'], result['request_id'])
        self.assertEqual('rules-v1', result['rules_version'])
        self.assertEqual(hashlib.sha256(content).hexdigest(), result['input_sha256'])
        self.assertEqual(result, run(content))

    def test_exceptions_may_be_reviewed_text_not_only_list(self):
        p = payload()
        p['events'][0]['exceptions'] = dict(value='보행자 제외', knowledge='known', evidence_ids=['body-quote'], reason=None)
        self.assertEqual('보행자 제외', run(raw(p))['data']['items'][0]['exceptions'])

    def test_explicit_multiday_uses_datetime_not_same_day_clock_duration(self):
        p = payload()
        occ = p['events'][0]['occurrences'][0]
        occ.update(date_end='2026-11-05', time_start='22:00', time_end='02:00', end_day_offset=0)
        self.assertEqual(540.0, run(raw(p))['data']['items'][0]['time_overlap_minutes'])
        occ.update(time_start='10:00', time_end='10:00')
        self.assertEqual(1080.0, run(raw(p))['data']['items'][0]['time_overlap_minutes'])
        occ['recurrence_dates'] = ['2026-11-03', '2026-11-05']
        with self.assertRaises(ProtocolError):
            run(raw(p))

    def test_explicit_partial_end_bounds_exclude_before_business_or_window(self):
        for changes, reason in [
            (dict(date_start='2026-11-02', date_end='2026-11-03', time_start=None, time_end='02:00', end_day_offset=None), 'TIME_NO_OVERLAP'),
            (dict(date_start='2026-11-01', date_end='2026-11-02', time_start='22:00', time_end=None, end_day_offset=1), 'WINDOW_OUTSIDE'),
        ]:
            with self.subTest(changes=changes):
                p = payload()
                p['events'][0]['occurrences'][0].update(changes | dict(precision='unknown', knowledge='not_stated'))
                p['query']['selection'] = 'needs_check'
                result = run(raw(p))
                self.assertEqual(0, sum(result['data']['counts'].values()))
                self.assertIn(reason, result['diagnostics'][0]['reason_codes'])

    def test_overlap_amplification_stops_during_calculation(self):
        p = payload()
        original = p['events'][0]
        from support import event_copy
        p['events'] = []
        for i in range(1000):
            e = event_copy(original, i + 100)
            occ = e['occurrences'][0]
            occ['time_start'] = (datetime(2026, 11, 3, 9) + timedelta(seconds=i)).strftime('%H:%M:%S')
            occ['time_end'] = (datetime(2026, 11, 3, 17) + timedelta(seconds=i)).strftime('%H:%M:%S')
            p['events'].append(e)
        content = raw(p)
        self.assertLess(len(content), MAX_BYTES)
        with self.assertRaisesRegex(ValueError, 'CALCULATION_OUTPUT_TOO_LARGE'):
            run(content)
        proc = self.cli(content)
        self.assertEqual(3, proc.returncode)
        self.assertEqual(b'', proc.stdout)
        self.assertEqual(b'CALCULATION_OUTPUT_TOO_LARGE\n', proc.stderr)

    def test_unknown_overnight_offset_keeps_possible_next_day_hours(self):
        p = payload()
        p['events'][0]['occurrences'][0].update(time_start='22:00', time_end='02:00', end_day_offset=None,
                                               precision='unknown', knowledge='ambiguous')
        for hours in p['query']['weekly_hours'].values():
            hours.update(state='closed', intervals=[])
        p['query']['weekly_hours']['wednesday'].update(state='open', intervals=[dict(start='00:00', end='03:00', end_day_offset=0)])
        p['query']['selection'] = 'needs_check'
        self.assertEqual(1, run(raw(p))['data']['counts']['needs_check'])

    def test_shared_large_source_is_bounded_while_projecting_selected_items(self):
        from support import event_copy
        p = payload()
        p['source_versions'][0]['title'] = '공유 출처 ' * 20_000
        original = p['events'][0]
        p['events'] = [event_copy(original, i + 100) for i in range(100)]
        content = raw(p)
        self.assertLess(len(content), MAX_BYTES)
        with self.assertRaisesRegex(ValueError, 'CALCULATION_OUTPUT_TOO_LARGE'):
            run(content)
        proc = self.cli(content)
        self.assertEqual(3, proc.returncode)
        self.assertEqual(b'', proc.stdout)
        self.assertEqual(b'CALCULATION_OUTPUT_TOO_LARGE\n', proc.stderr)
        # 반환하지 않는 상태의 카드는 투영 한도 때문에 정상 조회를 막지 않는다.
        p['query']['selection'] = 'needs_check'
        result = run(raw(p))
        self.assertEqual([], result['data']['items'])
        self.assertEqual(100, result['data']['counts']['candidate'])

    def test_projection_agrees_with_actual_java_fact_response(self):
        p = payload()
        expected = json.loads((ROOT / 'contracts/examples/event-facts-response.json').read_text())['data']['event']
        p['events'][0]['revision_id'] = expected['revision_id']
        actual = run(raw(p))['data']['items'][0]
        self.assertEqual({k: v for k, v in expected.items() if k != 'history'},
                         {k: actual[k] for k in expected if k != 'history'})

    def test_missing_timezone_runtime_fails_without_traceback_or_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            proc = subprocess.run([sys.executable, '-S', '-m', 'processing.matching'], input=raw(payload()),
                                  cwd=ROOT, capture_output=True, timeout=10,
                                  env=os.environ | {'PYTHONTZPATH': folder})
        self.assertEqual(1, proc.returncode)
        self.assertEqual(b'', proc.stdout)
        self.assertEqual(b'CALCULATION_FAILED\n', proc.stderr)

    def test_cli_single_json_and_utf8(self):
        p = payload()
        proc = self.cli(raw(p))
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertEqual(b'', proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual('합성 공지 😀', result['data']['items'][0]['title'])
        self.assertEqual(hashlib.sha256(raw(p)).hexdigest(), result['input_sha256'])

    def test_cli_failure_never_returns_zero_items_as_success(self):
        for content in [b'{}', b'not json', b'\xff', b'{} {}', b'{"a":1,"a":2}', b'NaN']:
            with self.subTest(content=content):
                proc = self.cli(content)
                self.assertEqual(2, proc.returncode)
                self.assertEqual(b'', proc.stdout)
                self.assertEqual(b'CALCULATION_INPUT_INVALID\n', proc.stderr)

    def test_size_and_depth_limits(self):
        for content in [b' ' * (MAX_BYTES + 1), b'[' * 101 + b'0' + b']' * 101]:
            proc = self.cli(content)
            self.assertEqual(2, proc.returncode)
            self.assertEqual(b'', proc.stdout)

    def test_output_limit_is_nonzero_with_no_partial_json(self):
        p = payload()
        for field in ('applicability', 'exceptions'):
            value = 'x' * 2_200_000
            p['events'][0][field] = dict(value=value if field == 'applicability' else [value],
                                        knowledge='known', evidence_ids=['body-quote'], reason=None)
        proc = self.cli(raw(p))
        self.assertEqual(3, proc.returncode)
        self.assertEqual(b'', proc.stdout)
        self.assertEqual(b'CALCULATION_OUTPUT_TOO_LARGE\n', proc.stderr)

    def test_invalid_context_and_query_fail_closed(self):
        changes = [
            ('protocol_version', 'calc-v2'), ('snapshot_checksum', 'broken'),
            ('context.rules_version', 'unimplemented'), ('context.data_kind', 'imaginary'),
            ('context.window_days', True), ('context.window_days', 15), ('context.radius_m', 501),
            ('context.anchor_date', '2026-11-04'), ('context.server_now', '2026-11-03T11:00:00'),
            ('context.server_now', '2026-11-03T11:00:00+09:00'),
            ('context.history_fidelity', 'verified_snapshot'), ('context.case_id', '00000000-0000-0000-0000-000000000001'),
            ('point.latitude', 91), ('point.longitude', float('inf')), ('point.latitude', True),
            ('query.point_id', '00000000-0000-0000-0000-000000000001'),
            ('query.snapshot_id', '00000000-0000-0000-0000-000000000001'), ('query.mode', 'replay'),
            ('query.selection', 'excluded'), ('query.sort', 'random'), ('query.types', ['event', 'event']),
            ('query.weekly_hours.monday.full_day', 1),
            ('query.weekly_hours.monday.intervals.0.end', '09:00'),
            ('query.weekly_hours.monday.intervals.0.end_day_offset', 1),
            ('query.weekly_hours.monday.intervals.0.start', '09:00:01'),
            ('events.0.title', '\ud800'), ('events.0.area_membership', 'outside'),
            ('events.0.source_version_ids', []), ('events.0.lifecycle', 'invented'),
            ('events.0.occurrences.0.location_ids', ['00000000-0000-0000-0000-000000000001']),
            ('events.0.occurrences.0.time_end', '09:00'),
            ('events.0.occurrences.0.recurrence_dates', ['2026-11-02']),
            ('events.0.occurrences.0.end_day_offset', True),
            ('events.0.locations.0.geometry.coordinates', [0, 100]),
            ('events.0.applicability.knowledge', 'maybe'), ('events.0.exceptions.value', []),
            ('events.0.evidence.0.end_char', 8), ('events.0.evidence.0.text_sha256', '0'*64),
            ('source_versions.0.official_url', 'javascript:alert(1)'),
            ('source_versions.0.official_url', 'https://private:password@example.org/notice'),
            ('source_versions.0.last_verified_at', None),
            ('source_versions.0.check_result', 'unreachable'),
            ('source_versions.0.collected_at', '2027-01-01T00:00:00Z'),
        ]
        for path, value in changes:
            with self.subTest(path=path, value=str(value)[:70]):
                p = payload()
                node = p
                parts = path.split('.')
                for part in parts[:-1]:
                    node = node[int(part)] if isinstance(node, list) else node[part]
                key = int(parts[-1]) if isinstance(node, list) else parts[-1]
                node[key] = value
                with self.assertRaises(ProtocolError):
                    run(json.dumps(p).encode())

    def test_unknown_private_fields_and_duplicate_ids_rejected(self):
        mutations = [
            lambda p: p.update(secret='never print'),
            lambda p: p['events'][0].update(reviewer_id='private-reviewer'),
            lambda p: p['events'].append(copy.deepcopy(p['events'][0])),
            lambda p: p['source_versions'].append(copy.deepcopy(p['source_versions'][0])),
            lambda p: p['events'][0]['occurrences'].append(copy.deepcopy(p['events'][0]['occurrences'][0])),
        ]
        for mutation in mutations:
            p = payload()
            mutation(p)
            proc = self.cli(raw(p))
            self.assertEqual(2, proc.returncode)
            self.assertEqual(b'', proc.stdout)
            self.assertNotIn(b'private-reviewer', proc.stderr)

    def test_replay_rejects_future_source_or_check_and_context_mismatch(self):
        p = payload()
        case = '40000000-0000-4000-8000-000000000001'
        p['context'].update(mode='replay', case_id=case, server_now='2026-12-03T02:00:00Z',
                            reference_instant='2026-11-03T02:00:00Z', knowledge_cutoff='2026-11-03T01:00:00Z',
                            history_fidelity='verified_snapshot')
        p['query'].update(mode='replay', case_id=case)
        self.assertEqual(1, run(raw(p))['data']['counts']['candidate'])
        for key in ('collected_at', 'last_verified_at', 'latest_check_attempt_at'):
            q = copy.deepcopy(p)
            q['source_versions'][0][key] = '2026-11-03T02:00:00Z'
            with self.assertRaises(ProtocolError):
                run(raw(q))
        p['context']['knowledge_cutoff'] = '2026-11-04T00:00:00Z'
        with self.assertRaises(ProtocolError):
            run(raw(p))

    @staticmethod
    def cli(content):
        return subprocess.run([sys.executable, '-m', 'processing.matching'], input=content,
                              cwd=ROOT, capture_output=True, timeout=10)
