import copy
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import study_export as export
from processing.evaluation import __main__ as cli
from processing.evaluation import study_protocol
from processing.extraction.archive import _json
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import REPO
from processing.tests.test_user_study import UserStudyFixture


class UserStudyExportTest(UserStudyFixture):
    def file_fingerprints(self):
        return {p.relative_to(self.work).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.work.rglob('*') if p.is_file() and not p.is_symlink()}

    def output(self, packet=None, name='reports/result.json', format='json'):
        return export.export_study(self.study() if packet is None else packet, self.prepare(), name, format)

    def test_private_json_is_exact_reusable_and_original_inputs_are_unchanged(self):
        self.write_records(); before = self.file_fingerprints(); packet = self.study()
        receipt = self.output(packet); path = self.work / 'reports/result.json'
        self.assertEqual(path.read_bytes(), _json(packet['result']))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(set(receipt), set('protocol_version status format output_sha256 output_size summary'.split()))
        self.assertEqual(receipt['output_sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(receipt['output_size'], path.stat().st_size)
        self.assertEqual(receipt, self.output(packet))
        path.chmod(0o400); self.assertEqual(receipt, self.output(packet))
        self.assertEqual(path.stat().st_mode & 0o777, 0o400)
        for name, digest in before.items(): self.assertEqual(hashlib.sha256((self.work / name).read_bytes()).hexdigest(), digest)
        self.assertNotIn('PRIVATE_', json.dumps(receipt)); self.assertNotIn(str(self.work), json.dumps(receipt))
        self.assertNotIn(self.records['participants'][0]['participant_id'], json.dumps(receipt))

    def test_csv_keeps_all_participant_and_task_rows_without_free_narratives(self):
        self.add_person(2, participant_type='expert', role='expert')
        packet = self.study(); receipt = self.output(packet, 'reports/result.csv', 'csv')
        path = self.work / 'reports/result.csv'; rows = list(csv.DictReader(io.StringIO(path.read_text())))
        self.assertEqual(receipt['format'], 'csv')
        self.assertEqual(sum(r['row_kind'] == 'participant' for r in rows), 2)
        self.assertEqual(sum(r['row_kind'] == 'task' for r in rows), 6)
        self.assertEqual({r['participant_id'] for r in rows}, {p['participant_id'] for p in self.records['participants']})
        self.assertEqual({r['records_sha256'] for r in rows}, {packet['result']['records_sha256']})
        self.assertEqual({r['retention_deadline'] for r in rows}, {self.protocol['privacy']['retention_deadline']})
        tasks = [r for r in rows if r['row_kind'] == 'task']
        self.assertEqual({r['outcome'] for r in tasks}, {'correct'})
        self.assertTrue(all(int(r['elapsed_ns']) > 0 for r in tasks))
        self.assertNotIn('PRIVATE_FEEDBACK', path.read_text()); self.assertNotIn('PRIVATE_CHANGES', path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_csv_escapes_formula_versions_and_json_keeps_original(self):
        self.protocol['protocol_version'] = '  =PRIVATE_FORMULA()'
        self.records['protocol_sha256'] = hashlib.sha256(self.protocol_bytes()).hexdigest()
        packet = self.study(); self.output(packet, 'formula.csv', 'csv')
        rows = list(csv.DictReader(io.StringIO((self.work / 'formula.csv').read_text())))
        self.assertTrue(all(r['protocol_version'] == "'  =PRIVATE_FORMULA()" for r in rows))
        self.output(packet, 'formula.json')
        self.assertEqual(json.loads((self.work / 'formula.json').read_text())['protocol_version'], '  =PRIVATE_FORMULA()')

    def test_csv_preserves_unknown_condition_reasons_without_dropping_correct_tasks(self):
        self.records['participants'][0]['sessions'][0]['records'][0]['answer_feedback_given'] = None
        self.output(self.study(), 'unknown.csv', 'csv')
        rows = list(csv.DictReader(io.StringIO((self.work / 'unknown.csv').read_text())))
        person = next(row for row in rows if row['row_kind'] == 'participant')
        self.assertIn('ASSISTANCE_STATUS_UNKNOWN', json.loads(person['deviations']))
        self.assertEqual(person['eligible_pair'], 'false')
        tasks = [row for row in rows if row['row_kind'] == 'task']
        self.assertEqual(len(tasks), 6); self.assertTrue(all(row['outcome'] == 'correct' for row in tasks))

    def test_other_bytes_and_widened_permissions_do_not_replace_first_output(self):
        packet = self.study(); self.output(packet); path = self.work / 'reports/result.json'; raw = path.read_bytes()
        other = copy.deepcopy(self.records); other['participants'][0]['feedback']['satisfied'] = 'PRIVATE_OTHER'
        with self.assertRaises(ExtractionError) as caught: self.output(self.study(other))
        self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'STUDY_EXPORT_CONFLICT'))
        self.assertEqual(path.read_bytes(), raw)
        path.chmod(0o644)
        with self.assertRaises(ExtractionError) as caught: self.output(packet)
        self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'STUDY_EXPORT_INTEGRITY'))
        self.assertEqual(path.read_bytes(), raw)

    def test_unsafe_paths_are_rejected_without_writing_outside_the_pack(self):
        packet = self.study(); outside = self.work.parent / ('outside-' + self.work.name)
        outside.mkdir(mode=0o700); self.addCleanup(lambda: __import__('shutil').rmtree(outside))
        (self.work / 'link').symlink_to(outside, target_is_directory=True)
        (self.work / 'target').write_bytes(b'keep'); (self.work / 'alias').symlink_to(self.work / 'target')
        for name in ('../escape.json', '/tmp/PRIVATE_ESCAPE.json', './bad.json', 'link/out.json', 'alias', 'target/child.json'):
            with self.subTest(name=name), self.assertRaises(ExtractionError): self.output(packet, name)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual((self.work / 'target').read_bytes(), b'keep')

    def test_concurrent_same_and_different_reports_are_exclusive(self):
        packet = self.study(); other = copy.deepcopy(self.records)
        other['participants'][0]['feedback']['required_changes'] = 'PRIVATE_OTHER'
        changed = self.study(other)
        for packets, name, successes in (([packet] * 3, 'same.json', 3), ([packet, changed], 'different.json', 1)):
            def run(value):
                try: return self.output(value, name)
                except ExtractionError as error: return error.code
            with ThreadPoolExecutor(max_workers=3) as pool: results = list(pool.map(run, packets))
            self.assertEqual(sum(isinstance(r, dict) for r in results), successes)
            if successes == 1: self.assertIn('STUDY_EXPORT_CONFLICT', results)
        self.assertFalse(any(p.name.endswith('.tmp') for p in self.work.rglob('*')))

    def test_current_retention_is_rechecked_before_creating_output(self):
        packet = self.study(); real = export.check_retention
        expired_at = self.protocol['privacy']['retention_deadline'] + 'T15:00:00Z'
        with patch.object(export, 'check_retention', side_effect=lambda p: real(p, evaluated_at=expired_at)):
            with self.assertRaises(ExtractionError) as caught: self.output(packet)
        self.assertEqual(caught.exception.code, 'STUDY_RETENTION_EXPIRED')
        self.assertFalse((self.work / 'reports').exists())

    def test_io_failures_and_result_budget_do_not_leave_partial_reports(self):
        packet = self.study(); before = self.file_fingerprints()
        with patch.object(export, '_write', side_effect=OSError(errno.EIO, 'PRIVATE_IO')):
            with self.assertRaises(OSError): self.output(packet)
        self.assertFalse((self.work / 'reports/result.json').exists())
        for kind in ('json', 'csv'):
            with patch.object(export, 'MAX_BYTES', 32), self.assertRaises(ExtractionError):
                self.output(packet, 'limited.' + kind, kind)
        self.assertFalse((self.work / 'limited.json').exists()); self.assertFalse((self.work / 'limited.csv').exists())
        for name, digest in before.items(): self.assertEqual(hashlib.sha256((self.work / name).read_bytes()).hexdigest(), digest)

    def test_every_new_nested_export_directory_is_owner_only_under_open_umask(self):
        packet = self.study(); previous = os.umask(0)
        try: self.output(packet, 'deep/nested/result.json')
        finally: os.umask(previous)
        self.assertEqual((self.work / 'deep').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.work / 'deep/nested').stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.work / 'deep/nested/result.json').stat().st_mode & 0o777, 0o600)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', '-m', 'processing.evaluation', *map(str, args)],
                              cwd=REPO, capture_output=True, timeout=30)

    def test_actual_cli_check_json_csv_and_error_codes_are_safe(self):
        self.write_records(); common = ['--root', self.work, '--protocol', 'protocol.json', '--input', 'records.json']
        checked = self.run_cli('check-study', *common)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)['protocol_version'], 'user-study-summary-v1')
        results = [checked]
        for kind in ('json', 'csv'):
            result = self.run_cli('export-study', *common, '--output', 'PRIVATE_REPORT.' + kind, '--format', kind)
            self.assertEqual(result.returncode, 0, result.stderr); results.append(result)
        for result in results:
            self.assertEqual(result.stderr, b''); self.assertEqual(result.stdout.count(b'\n'), 1)
            self.assertNotIn(b'PRIVATE_', result.stdout); self.assertNotIn(str(self.work).encode(), result.stdout)
            self.assertNotIn(self.records['participants'][0]['participant_id'].encode(), result.stdout)
        target = self.work / 'PRIVATE_REPORT.json'; target.write_bytes(b'PRIVATE_CORRUPTION')
        conflict = self.run_cli('export-study', *common, '--output', target.name, '--format', 'json')
        missing = self.run_cli('check-study', '--root', self.work, '--protocol', 'missing.json', '--input', 'records.json')
        invalid = self.run_cli('check-study')
        for result, status in ((conflict, 3), (missing, 5), (invalid, 2)):
            self.assertEqual(result.returncode, status, result.stderr); self.assertEqual(result.stdout, b'')
            self.assertNotIn(b'PRIVATE_', result.stderr); self.assertNotIn(str(self.work).encode(), result.stderr)

    def test_expired_protocol_blocks_records_read_and_safe_internal_failure(self):
        original_deadline = self.protocol['privacy']['retention_deadline']
        self.protocol['privacy']['retention_deadline'] = '2026-11-03'
        self.protocol_path.write_bytes(self.protocol_bytes())
        result = self.run_cli('check-study', '--root', self.work, '--protocol', 'protocol.json', '--input', 'PRIVATE_MISSING.json')
        self.assertEqual(result.returncode, 2, result.stderr); self.assertEqual(result.stderr, b'STUDY_RETENTION_EXPIRED\n')
        self.assertEqual(result.stdout, b'')
        self.protocol['privacy']['retention_deadline'] = original_deadline; self.write_records()
        with patch.object(sys, 'argv', ['evaluation', 'check-study', '--root', str(self.work), '--protocol', 'protocol.json', '--input', 'records.json']), \
                patch.object(cli, 'evaluate_study', side_effect=RuntimeError('PRIVATE_VALUE')), \
                patch.object(sys, 'stdout', io.StringIO()) as stdout, patch.object(sys, 'stderr', io.StringIO()) as stderr:
            self.assertEqual(cli.main(), 1)
            self.assertEqual(stdout.getvalue(), ''); self.assertEqual(stderr.getvalue(), 'DATASET_INTERNAL_FAILED\n')

    def test_actual_json_cli_retry_reuses_the_original_evaluation_time(self):
        self.write_records()
        args = ['export-study', '--root', self.work, '--protocol', 'protocol.json', '--input', 'records.json',
                '--output', 'retry.json', '--format', 'json']
        first = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stderr)
        raw = (self.work / 'retry.json').read_bytes()
        second = self.run_cli(*args)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout), json.loads(first.stdout))
        self.assertEqual((self.work / 'retry.json').read_bytes(), raw)

    def test_cli_rechecks_current_retention_before_reading_records(self):
        self.protocol['privacy']['retention_deadline'] = '2026-11-04'
        self.records['protocol_sha256'] = hashlib.sha256(self.protocol_bytes()).hexdigest(); self.write_records()
        real_validate = cli.validate_protocol
        for command in ('check-study', 'export-study'):
            args = ['evaluation', command, '--root', str(self.work), '--protocol', 'protocol.json', '--input', 'records.json']
            if command == 'export-study': args += ['--output', 'expired.json', '--format', 'json']
            with self.subTest(command=command), patch.object(study_protocol, 'datetime', wraps=datetime) as clock:
                clock.now.return_value = datetime(2026, 11, 4, 14, 59, 59, tzinfo=timezone.utc)
                def validated(*args, **kwargs):
                    prepared = real_validate(*args, **kwargs)
                    clock.now.return_value = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
                    return prepared
                with patch.object(cli, 'validate_protocol', side_effect=validated), patch.object(cli, '_read', wraps=cli._read) as reader, \
                        patch.object(sys, 'argv', args), patch.object(sys, 'stdout', io.StringIO()) as stdout, \
                        patch.object(sys, 'stderr', io.StringIO()) as stderr:
                    self.assertEqual(cli.main(), 2)
                    self.assertEqual([call.args[0].name for call in reader.call_args_list], ['protocol.json'])
                    self.assertEqual(stdout.getvalue(), ''); self.assertEqual(stderr.getvalue(), 'STUDY_RETENTION_EXPIRED\n')
            self.assertFalse((self.work / 'expired.json').exists())

    def test_check_does_not_emit_summary_if_retention_expires_during_analysis(self):
        self.protocol['privacy']['retention_deadline'] = '2026-11-04'
        self.records['protocol_sha256'] = hashlib.sha256(self.protocol_bytes()).hexdigest(); self.write_records()
        real_evaluate = cli.evaluate_study
        with patch.object(study_protocol, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 4, 14, 59, 59, tzinfo=timezone.utc)
            def evaluated(*args):
                packet = real_evaluate(*args)
                clock.now.return_value = datetime(2026, 11, 4, 15, tzinfo=timezone.utc)
                return packet
            with patch.object(cli, 'evaluate_study', side_effect=evaluated), \
                    patch.object(sys, 'argv', ['evaluation', 'check-study', '--root', str(self.work), '--protocol', 'protocol.json', '--input', 'records.json']), \
                    patch.object(sys, 'stdout', io.StringIO()) as stdout, patch.object(sys, 'stderr', io.StringIO()) as stderr:
                self.assertEqual(cli.main(), 2)
                self.assertEqual(stdout.getvalue(), ''); self.assertEqual(stderr.getvalue(), 'STUDY_RETENTION_EXPIRED\n')

    def test_reuse_recomputes_stored_report_and_rejects_forged_time_or_metrics(self):
        packet = self.study()
        for case in ('future', 'metrics'):
            name = case + '.json'; self.output(packet, name)
            path = self.work / name; value = json.loads(path.read_bytes())
            if case == 'future': value['evaluated_at'] = '2099-01-01T00:00:00Z'
            else: value['summary']['primary']['median_reduction_percent'] = 999
            path.write_bytes(_json(value)); original = path.read_bytes()
            with self.subTest(case=case), self.assertRaises(ExtractionError) as caught: self.output(packet, name)
            self.assertEqual(caught.exception.code, 'STUDY_EXPORT_INTEGRITY')
            self.assertEqual(path.read_bytes(), original)

    def test_empty_report_cannot_be_backdated_before_the_fixed_protocol(self):
        empty = copy.deepcopy(self.records); empty.update(recruitment=[], participants=[])
        packet = self.study(empty); self.output(packet, 'empty.json')
        path = self.work / 'empty.json'; value = json.loads(path.read_bytes())
        value['evaluated_at'] = '2026-11-02T12:00:00Z'; path.write_bytes(_json(value))
        with self.assertRaises(ExtractionError) as caught: self.output(packet, 'empty.json')
        self.assertEqual(caught.exception.code, 'STUDY_EXPORT_INTEGRITY')

    def test_concurrent_same_inputs_with_distinct_analysis_times_reuse_one_report(self):
        now = datetime.now(timezone.utc)
        times = [(now - timedelta(seconds=seconds)).isoformat().replace('+00:00', 'Z') for seconds in (1, 0)]
        packets = [(self.study(at=at), self.prepare(at=at)) for at in times]
        def run(pair): return export.export_study(pair[0], pair[1], 'clock-race.json', 'json')
        with ThreadPoolExecutor(max_workers=2) as pool: receipts = list(pool.map(run, packets))
        self.assertEqual(receipts[0], receipts[1])
        self.assertFalse(any(p.name.endswith('.tmp') for p in self.work.rglob('*')))
