import copy
from datetime import datetime, timezone
import hashlib
import json
import shutil
from unittest.mock import patch

from processing.evaluation import records, reviews
from processing.evaluation.scoring import score_document
from processing.extraction.archive import _json, freeze_run, import_run
from processing.extraction.prompt import render_prompt
from processing.extraction.validation import ExtractionError, parse_input
from processing.tests.test_dataset import uid
from processing.tests.test_extraction_prompt_metadata import metadata
from processing.tests.test_human_reviews import ReviewFixture

AT = '2020-01-01T05:00:00Z'


class HumanEvaluationFixture(ReviewFixture):
    def setUp(self):
        super().setUp()
        self.ai_control = copy.deepcopy(self.control)
        self.human_root = self.work / 'human-reviews'
        selected = self.make_human(uid(950))
        self.control.update(method='human_reviewed', policy=dict(schema_version='extract-schema-v1',
            review_schema_version='human-review-v1'), documents=[dict(document_version_id=self.source['document_version_id'],
            **selected, annotation=self.annotations(self.good_output))])

    def make_human(self, review_id, source=None, output=None, basis='source_only',
                   started='2020-01-01T04:00:00Z', finished='2020-01-01T04:10:00Z',
                   frozen='2020-01-01T04:20:00Z', failed=False, root=None):
        value = copy.deepcopy(self.review)
        value.update(review_id=review_id, source=copy.deepcopy(self.selected if source is None else source),
                     output=copy.deepcopy(self.good_output if output is None else output), changes=[])
        value['review'].update(basis=basis, started_at=started, finished_at=finished)
        if failed or value['output'] != self.good_output:
            value['changes'] = [dict(field_path='output', before=None if failed else copy.deepcopy(self.good_output),
                after=copy.deepcopy(value['output']), reason='합성 수정후 평가 준비', evidence_ids=['e1'],
                reviewer=value['review']['reviewed_by'], time=finished)]
        path = self.work / ('review-' + review_id + '.json'); path.write_bytes(_json(value))
        class FreezeClock(datetime):
            @classmethod
            def now(cls, tz=None): return datetime.fromisoformat(frozen)
        root = self.human_root if root is None else root
        with patch('processing.extraction.archive.datetime', FreezeClock):
            receipt = reviews.freeze_review(path, root, self.run_root)
        return dict(review_id=review_id, review_ref=receipt['review_ref'],
            receipt_sha256=hashlib.sha256((root / receipt['review_ref'] / 'receipt.json').read_bytes()).hexdigest())

    def evaluate(self, control=None, *, run_root=None, at=AT):
        return records.evaluate_record(_json(self.control if control is None else control), self.gold_root,
            self.human_root if run_root is None else run_root, self.initial_root, evaluated_at=at)

    def invalid_human(self, value, code=None):
        self.evaluate()
        with self.assertRaises(ExtractionError) as caught: self.evaluate(value)
        if code: self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_', str(caught.exception))


class HumanEvaluationTest(HumanEvaluationFixture):
    def test_human_view_preserves_actual_review_and_parent_without_fake_attempts(self):
        selected = self.control['documents'][0]; image = self.human_root / selected['review_ref']
        before = {p.relative_to(image).as_posix(): p.read_bytes() for p in image.rglob('*') if p.is_file()}
        packet = self.evaluate(); result = packet['result']; summary = result['summary']; doc = result['documents'][0]
        self.assertEqual(summary['primary_view'], 'human_reviewed')
        self.assertEqual(set(summary['views']), {'human_reviewed'})
        self.assertEqual(set(summary['splits']['dev']), {'human_reviewed'})
        self.assertEqual(result['review_ids'], [uid(950)])
        self.assertNotIn('run_ids', result)
        self.assertEqual((doc['review_id'], doc['source_run_id'], doc['source_execution_mode'], doc['source_status']),
                         (uid(950), self.selected['run_id'], 'api', 'validated'))
        for key in ('run_id', 'attempt_count', 'metadata_sha256', 'final_auto', 'first_raw'): self.assertNotIn(key, doc)
        self.assertNotIn('source_attempt', doc['human_reviewed'])
        self.assertEqual(summary['views']['human_reviewed']['correct_fields'], 8)
        direct = score_document(self.input.read_bytes(), _json(self.good_output), before['output.json'],
                                _json(selected['annotation']), self.value['instructions'])
        self.assertEqual(doc['human_reviewed']['summary'], direct['summary'])
        self.assertTrue(all(f['review_id'] == uid(950) and 'run_id' not in f for f in doc['human_reviewed']['field_results']))
        self.assertEqual({p.relative_to(image).as_posix(): p.read_bytes() for p in image.rglob('*') if p.is_file()}, before)
        self.assertIn(f"runs/{selected['review_ref']}/source/{self.selected['snapshot_ref']}/attempt-1.response", packet['sources'])
        self.assertNotIn('PRIVATE_', json.dumps(summary)); self.assertNotIn(str(self.work), json.dumps(summary))

    def test_declared_review_time_and_ai_only_target_remain_separate(self):
        summary = self.evaluate()['result']['summary']; time = summary['human_review_time']
        self.assertEqual(time['status'], 'declared_only')
        self.assertEqual((time['review_count'], time['total_duration_ns']), (1, 600_000_000_000))
        self.assertEqual(time['splits']['dev'], dict(review_count=1, total_duration_ns=600_000_000_000))
        self.assertEqual(time['splits']['holdout'], dict(review_count=0, total_duration_ns=0))
        self.assertIn('M02_REQUIRES_AI_AUTO', summary['m02']['warnings'])
        self.assertIsNone(summary['m02']['accuracy_percent']); self.assertFalse(summary['generalization_claim'])

    def test_failed_parent_can_be_corrected_without_changing_automatic_failure(self):
        source = self.make_run(uid(552), failed=True)
        selected = self.make_human(uid(951), source=source, failed=True)
        value = copy.deepcopy(self.control); value['documents'][0].update(selected)
        doc = self.evaluate(value)['result']['documents'][0]
        self.assertEqual(doc['source_status'], 'failed')
        self.assertEqual((doc['human_reviewed']['summary']['correct_fields'], doc['human_reviewed']['summary']['document_failed']), (8, False))
        self.assertEqual(json.loads((self.run_root / source['snapshot_ref'] / 'receipt.json').read_bytes())['status'], 'failed')

    def test_empty_review_preserves_gold_denominator_and_missing_event(self):
        output = copy.deepcopy(self.good_output); output.update(items=[], warnings=['NO_EVENT_FOUND'])
        selected = self.make_human(uid(952), output=output)
        value = copy.deepcopy(self.control); value['documents'][0].update(selected)
        value['documents'][0]['annotation'] = dict(schema_version='score-links-v1', item_links=[], generation_reviews=[])
        s = self.evaluate(value)['result']['summary']['views']['human_reviewed']
        self.assertEqual((s['correct_fields'], s['known_fields'], s['missing_events'], s['document_failures']), (0, 8, 1, 0))

    def test_strict_policy_reference_hash_coverage_and_source_kinds(self):
        for case in ('policy', 'ref', 'id', 'hash', 'version', 'duplicate', 'method', 'annotation'):
            value = copy.deepcopy(self.control); doc = value['documents'][0]
            if case == 'policy': value['policy']['provider'] = 'openai'
            elif case == 'ref': doc['review_ref'] = '0' * 64
            elif case == 'id': doc['review_id'] = uid(999)
            elif case == 'hash': doc['receipt_sha256'] = '0' * 64
            elif case == 'version': doc['document_version_id'] = uid(998)
            elif case == 'duplicate': value['documents'].append(copy.deepcopy(doc))
            elif case == 'method': value['method'] = 'ai_auto'
            else: doc['first_annotation'] = doc.pop('annotation')
            with self.subTest(case=case): self.invalid_human(value)
        selected = self.control['documents'][0]; wrong = self.work / 'wrong-review'
        shutil.copytree(self.run_root / self.selected['snapshot_ref'], wrong / selected['review_ref'])
        with self.assertRaises(ExtractionError) as caught: self.evaluate(run_root=wrong)
        self.assertEqual(caught.exception.kind, 'archive')

    def test_source_input_bytes_and_data_kind_must_match_gold(self):
        raw = self.input.read_bytes()
        try:
            for index, case in enumerate(('bytes', 'data_kind')):
                if case == 'bytes': self.input.write_bytes(raw + b' ')
                else:
                    source = json.loads(raw); source['data_kind'] = 'real'; self.input.write_bytes(_json(source))
                selected = self.make_human(uid(953 + index), source=self.make_run(uid(553 + index)))
                value = copy.deepcopy(self.control); value['documents'][0].update(selected)
                with self.subTest(case=case): self.invalid_human(value, 'EVALUATION_SOURCE_MISMATCH')
        finally: self.input.write_bytes(raw)

    def test_initial_parent_must_start_after_gold_and_review_must_finish_before_scoring(self):
        source = self.make_run(uid(555), started='2020-01-01T02:00:00Z')
        value = copy.deepcopy(self.control); value['documents'][0].update(self.make_human(uid(955), source=source))
        self.invalid_human(value, 'EVALUATION_GOLD_AFTER_PARENT')
        value = copy.deepcopy(self.control); value['review']['reviewed_at'] = '2020-01-01T04:09:59.999999999Z'
        self.invalid_human(value, 'EVALUATION_HUMAN_TIME_INVALID')
        value['review']['reviewed_at'] = '2020-01-01T04:15:00Z'
        with self.assertRaises(ExtractionError) as caught: self.evaluate(value, at='2020-01-01T04:19:59.999999999Z')
        self.assertEqual(caught.exception.code, 'EVALUATION_REVIEW_ARCHIVE_TIME_INVALID')

    def test_unknown_parent_clock_is_archived_but_not_a_controlled_evaluation(self):
        class SourceClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 3, tzinfo=timezone.utc)
        meta = metadata(); meta.update(run_id=uid(556), document_version_id=self.source['document_version_id'])
        paths = [self.work / n for n in ('manual-meta', 'manual-prompt', 'manual-output')]
        paths[0].write_bytes(_json(meta)); paths[1].write_bytes(render_prompt(parse_input(self.input.read_bytes())))
        paths[2].write_bytes(_json(self.good_output))
        with patch('processing.extraction.archive.datetime', SourceClock):
            import_run(self.input, paths[0], [(paths[1], paths[2])], self.run_root)
        frozen = freeze_run(uid(556), self.run_root); source = dict(run_id=uid(556), snapshot_ref=frozen['snapshot_ref'],
            receipt_sha256=hashlib.sha256((self.run_root / frozen['snapshot_ref'] / 'receipt.json').read_bytes()).hexdigest())
        selected = self.make_human(uid(956), source=source)
        value = copy.deepcopy(self.control); value['documents'][0].update(selected)
        self.invalid_human(value, 'EVALUATION_HUMAN_PARENT_TIME_UNKNOWN')
        self.assertEqual(reviews.verify_review(selected['review_ref'], self.human_root)['summary']['source_status'], 'validated')

    def test_initial_requires_source_only_and_feedback_requires_exposure(self):
        for index, basis in enumerate(('unknown', 'gold_feedback')):
            selected = self.make_human(uid(957 + index), basis=basis)
            value = copy.deepcopy(self.control); value['documents'][0].update(selected)
            with self.subTest(basis=basis): self.invalid_human(value)
        value.update(phase='retest', initial_ref='a' * 64)
        self.invalid_human(value, 'EVALUATION_HUMAN_FEEDBACK_CONFLICT')

    def test_nanosecond_duration_and_method_default_root(self):
        selected = self.make_human(uid(959), started='2020-01-01T04:00:00.999999999Z', finished='2020-01-01T04:00:01.000000001Z')
        value = copy.deepcopy(self.control); value['documents'][0].update(selected)
        with patch.object(records, 'REVIEW_ROOT', self.human_root, create=True):
            result = records.evaluate_record(_json(value), self.gold_root, initial_root=self.initial_root, evaluated_at=AT)['result']
        self.assertEqual(result['summary']['human_review_time']['total_duration_ns'], 2)
