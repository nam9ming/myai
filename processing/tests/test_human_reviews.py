import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
from unittest.mock import patch

from processing.evaluation import reviews
from processing.extraction.archive import freeze_run, import_run, verify_run
from processing.extraction.prompt import render_prompt
from processing.extraction.validation import ExtractionError, parse_input
from processing.tests.test_dataset import uid
from processing.tests.test_evaluation_records import EvaluationFixture
from processing.tests.test_extraction_prompt_metadata import metadata

AT = '2020-01-01T05:00:00Z'


class ReviewFixture(EvaluationFixture):
    def setUp(self):
        super().setUp()
        self.review = dict(schema_version='human-review-v1', review_id=uid(900), source=copy.deepcopy(self.selected),
            review=dict(reviewed_by='PRIVATE_HUMAN_DECLARATION', started_at='2020-01-01T04:00:00Z',
                        finished_at='2020-01-01T04:10:00Z', basis='source_only', note='합성 검토 선언; 실제 사람 아님'),
            output=copy.deepcopy(self.good_output), changes=[])
        self.review_path = self.work / 'PRIVATE_REVIEW.json'
        self.review_root = self.work / 'reviews'

    def encoded_review(self, value=None):
        return json.dumps(self.review if value is None else value, ensure_ascii=False).encode()

    def check_review(self, value=None):
        return reviews.check_review(self.encoded_review(value), self.run_root, checked_at=AT)

    def freeze_review(self, value=None):
        self.review_path.write_bytes(self.encoded_review(value))
        return reviews.freeze_review(self.review_path, self.review_root, self.run_root)

    def change(self, value, path='output.items', before=None, after=None):
        value['changes'].append(dict(field_path=path,
            before=copy.deepcopy(self.good_output['items'] if before is None else before),
            after=copy.deepcopy(value['output']['items'] if after is None else after), reason='합성 원문 대조 수정',
            evidence_ids=['e1'], reviewer=value['review']['reviewed_by'], time=value['review']['finished_at']))

    def changed(self):
        value = copy.deepcopy(self.review)
        value['output']['items'][0]['title']['value'] = '합성 수정 제목'
        self.change(value)
        return value

    def invalid_review(self, value):
        with self.assertRaises(ExtractionError) as caught:
            self.check_review(value)
        self.assertEqual(caught.exception.kind, 'input')
        self.assertNotIn('PRIVATE_', str(caught.exception))

    def image(self, receipt):
        return self.review_root / receipt['review_ref']

    def rewrite(self, path, content):
        path.chmod(0o600)
        path.write_bytes(content)
        path.chmod(0o400)


class HumanReviewTest(ReviewFixture):
    def test_unchanged_review_preserves_states_and_declared_duration_safely(self):
        result = self.check_review()
        self.assertEqual(result['status'], 'declared_reviewed')
        self.assertEqual(result['review_duration_ns'], 600_000_000_000)
        self.assertEqual(result['change_count'], 0)
        self.assertEqual(result['source_status'], 'validated')
        self.assertEqual(result['data_kind'], 'synthetic')
        self.assertEqual(result['human_verification'], 'declared_only')
        self.assertNotIn('PRIVATE_', json.dumps(result))
        self.assertNotIn(str(self.work), json.dumps(result))
        self.assertNotIn('합성 검토', json.dumps(result, ensure_ascii=False))
        receipt = self.freeze_review()
        output = json.loads((self.image(receipt) / 'output.json').read_bytes())
        self.assertEqual(output, self.good_output)
        self.assertEqual(output['items'][0]['locations'][0]['address']['knowledge'], 'not_stated')

    def test_real_change_requires_exact_audit_and_preserves_original_parent(self):
        folder = self.run_root / self.selected['snapshot_ref']
        original = {p.name: p.read_bytes() for p in folder.iterdir()}
        value = self.changed()
        receipt = self.freeze_review(value)
        image = self.image(receipt)
        self.assertEqual(json.loads((image / 'output.json').read_bytes())['items'][0]['title']['value'], '합성 수정 제목')
        self.assertEqual(receipt['summary']['change_count'], 1)
        self.assertEqual((image / 'review.json').read_bytes(), self.encoded_review(value))
        for name, raw in original.items():
            self.assertEqual((image / 'source' / self.selected['snapshot_ref'] / name).read_bytes(), raw)
            self.assertEqual((folder / name).read_bytes(), raw)
        self.assertEqual(verify_run(self.selected['run_id'], folder.parent)['status'], 'validated')

    def test_missing_fake_noop_duplicate_overlapping_and_invalid_path_changes_fail(self):
        for mode in ('missing', 'before', 'after', 'reviewer', 'time', 'reason', 'reference', 'duplicate', 'overlap', 'path', 'noop'):
            value = self.changed()
            change = value['changes'][0]
            if mode == 'missing': value['changes'] = []
            elif mode in ('before', 'after'): change[mode] = None
            elif mode == 'reviewer': change['reviewer'] = 'another-person'
            elif mode == 'time': change['time'] = '2020-01-01T04:09:59.999999999Z'
            elif mode == 'reason': change['reason'] = ' '
            elif mode == 'reference': change['evidence_ids'] = ['missing']
            elif mode == 'duplicate': value['changes'].append(copy.deepcopy(change))
            elif mode == 'overlap': self.change(value, 'output', self.good_output, value['output'])
            elif mode == 'path': change['field_path'] = 'output.items.0.title'
            elif mode == 'noop': value = copy.deepcopy(self.review); self.change(value)
            with self.subTest(mode=mode): self.invalid_review(value)

    def test_boolean_and_numeric_before_values_are_not_equal(self):
        value = self.changed()
        self.change(value, 'output', self.good_output, value['output'])
        value['changes'] = value['changes'][1:]
        value['changes'][0]['before']['evidence'][0]['start_char'] = False
        self.assertEqual(self.good_output['evidence'][0]['start_char'], 0)
        self.invalid_review(value)
        value['changes'][0]['before']['evidence'][0]['start_char'] = 0.0
        self.invalid_review(value)

    def test_failed_parent_requires_full_output_audit_and_keeps_failure(self):
        self.review['source'] = self.make_run(uid(902), failed=True)
        self.invalid_review(self.review)
        self.review['changes'] = [dict(field_path='output', before=None, after=copy.deepcopy(self.good_output),
            reason='합성 실패 원본을 보고 별도 판독', evidence_ids=['e1'],
            reviewer=self.review['review']['reviewed_by'], time=self.review['review']['finished_at'])]
        receipt = self.freeze_review()
        self.assertEqual(receipt['summary']['source_status'], 'failed')
        source = self.image(receipt) / 'source' / self.review['source']['snapshot_ref']
        self.assertEqual(verify_run(self.review['source']['run_id'], source.parent)['status'], 'failed')
        self.assertEqual((source / 'attempt-1.output').read_bytes(), b'')

    def test_manual_source_keeps_unknown_model_and_execution_mode(self):
        class SourceClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 3, tzinfo=timezone.utc)
        value = metadata(); value.update(run_id=uid(903), document_version_id=self.source['document_version_id'])
        meta, prompt, raw = [self.work / n for n in ('manual-meta', 'manual-prompt', 'manual-output')]
        meta.write_text(json.dumps(value)); prompt.write_bytes(render_prompt(parse_input(self.input.read_bytes())))
        raw.write_text(json.dumps(self.good_output))
        with patch('processing.extraction.archive.datetime', SourceClock):
            import_run(self.input, meta, [(prompt, raw)], self.run_root)
        packet = freeze_run(uid(903), self.run_root)
        source = self.run_root / packet['snapshot_ref']
        self.review['source'] = dict(run_id=uid(903), snapshot_ref=packet['snapshot_ref'],
            receipt_sha256=hashlib.sha256((source / 'receipt.json').read_bytes()).hexdigest())
        receipt = self.freeze_review()
        preserved = json.loads((self.image(receipt) / 'source' / packet['snapshot_ref'] / 'metadata.json').read_bytes())
        self.assertEqual(preserved['execution_mode'], 'manual_import')
        self.assertIsNone(preserved['model_label'])

    def test_schema_binding_output_evidence_and_root_escape_fail_closed(self):
        for mode in ('schema', 'id', 'extra', 'source_hash', 'source_path', 'source_id', 'doc', 'quote', 'fraction', 'basis', 'reviewer'):
            value = copy.deepcopy(self.review)
            if mode == 'schema': value['schema_version'] = 'other'
            elif mode == 'id': value['review_id'] = '../bad'
            elif mode == 'extra': value['PRIVATE_EXTRA'] = 'secret'
            elif mode == 'source_hash': value['source']['receipt_sha256'] = '0' * 64
            elif mode == 'source_path': value['source']['snapshot_ref'] = '../' + self.selected['run_id']
            elif mode == 'source_id': value['source']['run_id'] = uid(999)
            elif mode == 'doc': value['output']['document_version_id'] = uid(998)
            elif mode == 'quote': value['output']['evidence'][0]['quote'] = 'PRIVATE_WRONG_QUOTE'
            elif mode == 'fraction': value['output']['evidence'][0]['start_char'] = 0.0
            elif mode == 'basis': value['review']['basis'] = 'independence_certified'
            elif mode == 'reviewer': value['review']['reviewed_by'] = ' '
            with self.subTest(mode=mode): self.invalid_review(value)

    def test_nanosecond_duration_zero_and_all_basis_declarations_are_preserved(self):
        self.review['review'].update(started_at='2020-01-01T04:00:00.999999999Z', finished_at='2020-01-01T04:00:01.000000001Z')
        self.assertEqual(self.check_review()['review_duration_ns'], 2)
        for basis in ('source_only', 'gold_feedback', 'unknown'):
            self.review['review']['basis'] = basis
            self.assertEqual(self.check_review()['review_basis'], basis)
        self.review['review']['started_at'] = self.review['review']['finished_at']
        self.assertEqual(self.check_review()['review_duration_ns'], 0)

    def test_review_cannot_precede_source_record_or_finish_in_future(self):
        for start, finish in [('2020-01-01T02:59:59.999999999Z', '2020-01-01T04:10:00Z'),
            ('2020-01-01T04:00:00Z', '2020-01-01T03:59:59.999999999Z'),
            ('2020-01-01T04:00:00Z', '2020-01-01T05:00:00.000000001Z')]:
            value = copy.deepcopy(self.review); value['review'].update(started_at=start, finished_at=finish)
            with self.subTest(start=start, finish=finish): self.invalid_review(value)
        self.review['source'] = self.make_run(uid(904), recorded='2020-01-01T04:00:00.000001Z')
        self.invalid_review(self.review)

    def test_explicit_invalid_check_time_is_not_replaced_by_current_time(self):
        for clock in ('', False, 0):
            with self.subTest(clock=clock):
                with self.assertRaises(ExtractionError) as caught:
                    reviews.check_review(self.encoded_review(), self.run_root, checked_at=clock)
                self.assertEqual(caught.exception.kind, 'input')

    def test_review_can_remove_false_positive_events_without_creating_a_new_event(self):
        value = copy.deepcopy(self.review)
        value['output'].update(items=[], warnings=['NO_EVENT_FOUND'])
        self.change(value, 'output', self.good_output, value['output'])
        receipt = self.freeze_review(value)
        output = json.loads((self.image(receipt) / 'output.json').read_bytes())
        self.assertEqual(output['items'], [])
        self.assertEqual(output['warnings'], ['NO_EVENT_FOUND'])

    def test_image_replays_and_reuses_without_original_paths(self):
        receipt = self.freeze_review(self.changed()); image = self.image(receipt)
        before = {p.relative_to(image).as_posix(): p.read_bytes() for p in image.rglob('*') if p.is_file()}
        for current, _, _ in os.walk(self.run_root): Path(current).chmod(0o700)
        shutil.rmtree(self.run_root); self.input.unlink()
        self.assertEqual(reviews.verify_review(receipt['review_ref'], self.review_root), receipt)
        self.assertEqual(reviews.freeze_review(self.review_path, self.review_root, self.run_root), receipt)
        self.assertEqual({p.relative_to(image).as_posix(): p.read_bytes() for p in image.rglob('*') if p.is_file()}, before)
        self.assertTrue(all(p.stat().st_mode & 0o777 == (0o500 if p.is_dir() else 0o400) for p in [image, *image.rglob('*')]))

    def test_any_payload_receipt_identity_or_parent_modification_is_integrity_error(self):
        receipt = self.freeze_review(); image = self.image(receipt)
        for path in [image / 'review.json', image / 'output.json', image / 'identity.json', image / 'receipt.json',
                     image / 'source' / self.selected['snapshot_ref'] / 'attempt-1.output']:
            before = path.read_bytes(); self.rewrite(path, before + b' ')
            with self.subTest(name=path.name), self.assertRaises(ExtractionError) as caught:
                reviews.verify_review(receipt['review_ref'], self.review_root)
            self.assertEqual(caught.exception.kind, 'archive')
            self.rewrite(path, before)

    def test_wrong_modes_extra_files_and_symlinks_are_rejected(self):
        receipt = self.freeze_review(); image = self.image(receipt)
        target = image / 'output.json'
        target.chmod(0o600)
        with self.assertRaises(ExtractionError): reviews.verify_review(receipt['review_ref'], self.review_root)
        target.chmod(0o400); image.chmod(0o700); extra = image / 'extra'; extra.write_bytes(b'')
        image.chmod(0o500)
        with self.assertRaises(ExtractionError): reviews.verify_review(receipt['review_ref'], self.review_root)
        image.chmod(0o700); extra.unlink(); raw = target.read_bytes(); target.unlink()
        copied = self.work / 'copied-output'; copied.write_bytes(raw); copied.chmod(0o400)
        target.symlink_to(copied); image.chmod(0o500)
        with self.assertRaises(ExtractionError): reviews.verify_review(receipt['review_ref'], self.review_root)

    def test_fractional_identity_values_are_classified_as_archive_corruption(self):
        receipt = self.freeze_review(); identity = self.image(receipt) / 'identity.json'
        original = identity.read_bytes()
        for field in ('recorded_at', 'artifact_size'):
            value = json.loads(original)
            if field == 'recorded_at': value['recorded_at'] = 1.5
            else: value['artifacts']['review.json']['size'] = 1.5
            self.rewrite(identity, json.dumps(value).encode())
            with self.subTest(field=field):
                with self.assertRaises(Exception) as caught:
                    reviews.verify_review(receipt['review_ref'], self.review_root)
                self.assertIsInstance(caught.exception, ExtractionError)
                self.assertEqual((caught.exception.kind, caught.exception.code), ('archive', 'HUMAN_REVIEW_INTEGRITY'))
            self.rewrite(identity, original)

    def test_conflict_and_partial_destination_are_preserved(self):
        receipt = self.freeze_review(); value = self.changed()
        with self.assertRaises(ExtractionError) as caught: self.freeze_review(value)
        self.assertEqual(caught.exception.code, 'HUMAN_REVIEW_CONFLICT')
        self.assertEqual(reviews.verify_review(receipt['review_ref'], self.review_root), receipt)
        value['review_id'] = uid(905)
        image = self.review_root / hashlib.sha256(uid(905).encode()).hexdigest(); image.mkdir()
        (image / 'marker').write_bytes(b'KEEP')
        with self.assertRaises(ExtractionError): self.freeze_review(value)
        self.assertEqual((image / 'marker').read_bytes(), b'KEEP')

    def test_identical_and_conflicting_native_races_do_not_overwrite(self):
        self.review_path.write_bytes(self.encoded_review())
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: reviews.freeze_review(self.review_path, self.review_root, self.run_root), range(4)))
        self.assertTrue(all(r == results[0] for r in results))
        other_root = self.work / 'race'
        other = self.work / 'other-review'; other.write_bytes(self.encoded_review(self.changed()))
        def run(path):
            try: return reviews.freeze_review(path, other_root, self.run_root)
            except ExtractionError as error: return error.code
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(run, [self.review_path, other]))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertIn('HUMAN_REVIEW_CONFLICT', results)
        self.assertEqual(len(list(other_root.iterdir())), 1)

    def test_failed_install_and_source_change_leave_no_partial_image(self):
        self.review_path.write_bytes(self.encoded_review())
        with patch.object(reviews, '_rename_exclusive', side_effect=OSError('PRIVATE_IO')):
            with self.assertRaises(OSError): reviews.freeze_review(self.review_path, self.review_root, self.run_root)
        self.assertEqual(list(self.review_root.iterdir()), [])
        source = self.run_root / self.selected['snapshot_ref'] / 'attempt-1.output'
        before = source.read_bytes(); original_copy = reviews._copy
        def mutate(origin, target, expected):
            if Path(origin) == source: self.rewrite(source, before + b' ')
            return original_copy(origin, target, expected)
        try:
            with patch.object(reviews, '_copy', side_effect=mutate):
                with self.assertRaises(ExtractionError): reviews.freeze_review(self.review_path, self.review_root, self.run_root)
            self.assertEqual(list(self.review_root.iterdir()), [])
        finally: self.rewrite(source, before)
