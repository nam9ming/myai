import copy
from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import patch

from processing.evaluation import records
from processing.evaluation.scoring import score_document
from processing.evaluation.storage import freeze_dataset
from processing.extraction.rule_runs import run_rules
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_evaluation_records import DatasetClock, EVALUATED_AT, EvaluationFixture
from processing.tests.test_rules import encoded, profile


class RuleEvaluationFixture(EvaluationFixture):
    def setUp(self):
        super().setUp()
        self.ai_control = copy.deepcopy(self.control)
        self.rule_root = self.work / 'rule-runs'
        self.profile_path = self.work / 'PRIVATE_PROFILE.json'
        self.profile = profile(); self.profile_path.write_bytes(encoded(self.profile))
        self.control.update(method='rules', policy=self.rule_policy())
        self.selected_rules = self.make_rules(uid(701))
        self.control['documents'][0].update(self.selected_rules)

    def rule_policy(self):
        return dict(rule_version='rule-extract-v1', profile_version=self.profile['profile_version'],
            profile_sha256=hashlib.sha256(self.profile_path.read_bytes()).hexdigest(), schema_version='extract-schema-v1',
            retry_policy_version='rules-single-pass-v1', profile_reviewed_by='PRIVATE_SYNTHETIC_PROFILE_REVIEWER',
            profile_locked_at='2020-01-01T01:30:00Z', profile_basis='development_only')

    def make_rules(self, run_id, started='2020-01-01T03:00:00Z', root=None, preprocessing='fixture-nfc-v1'):
        class RunClock(datetime):
            @classmethod
            def now(cls, tz=None): return datetime.fromisoformat(started)
        root = root or self.rule_root
        with patch('processing.extraction.rule_runs.datetime', RunClock), patch('processing.extraction.archive.datetime', RunClock):
            receipt = run_rules(self.input, self.profile_path, preprocessing, root, run_id)
        output = json.loads((root / run_id / 'output.json').read_bytes())
        links = []
        # 단일 사건/일정의 합성 수동 대응이다. 실제 자료의 최적 대응을 자동 선택하지 않는다.
        if receipt['status'] != 'failed' and output['items']:
            answer, item = self.good_output['items'][0], output['items'][0]
            links = [dict(slot_id=answer['local_item_id'], local_item_id=item['local_item_id'], kind='match',
                occurrence_links=[dict(gold_occurrence_id=answer['occurrences'][0]['local_occurrence_id'],
                                       local_occurrence_id=item['occurrences'][0]['local_occurrence_id'])])]
        annotation = dict(schema_version='score-links-v1', item_links=links, generation_reviews=[])
        return dict(run_id=run_id, snapshot_ref=run_id,
            receipt_sha256=hashlib.sha256((root / run_id / 'receipt.json').read_bytes()).hexdigest(),
            first_annotation=copy.deepcopy(annotation), final_annotation=copy.deepcopy(annotation))

    def evaluate(self, control=None, run_root=None):
        return records.evaluate_record(encoded(self.control if control is None else control), self.gold_root,
            self.rule_root if run_root is None else run_root, self.initial_root, evaluated_at=EVALUATED_AT)

    def replace_source_with_overflow(self):
        self.source['document_version_id'] = uid(111)
        extra = [f'합성 추가 조건{i}' for i in range(257)]
        body = self.source['blocks'][0]['text'] + '\n' + '\n'.join('예외: ' + entry for entry in extra)
        self.source['blocks'][0]['text'] = body; self.input.write_bytes(encoded(self.source))
        self.manifest['dataset_version'] = 'synthetic-rule-failure-cohort'
        self.manifest['documents'][0]['versions'] = [dict(document_version_id=uid(111),
            input_sha256=hashlib.sha256(self.input.read_bytes()).hexdigest())]
        path = self.work / 'rule-failure-manifest.json'; path.write_bytes(encoded(self.manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock): dataset = freeze_dataset(path, self.dataset_root)
        self.value.update(gold_version='synthetic-rule-failure-gold', dataset_ref=dataset['dataset_ref'],
                          manifest_sha256=dataset['manifest_sha256'])
        document = self.value['documents'][0]; document['document_version_id'] = uid(111)
        output = document['output']; output['document_version_id'] = uid(111)
        digest = hashlib.sha256(body.encode()).hexdigest()
        for evidence in output['evidence']: evidence['text_sha256'] = digest
        output['evidence'].append(dict(evidence_id='extra', block_id='b1', quote=body,
            start_char=0, end_char=len(body), text_sha256=digest))
        output['items'][0]['exceptions']['value'].extend(extra)
        output['items'][0]['exceptions']['evidence_ids'].append('extra')
        self.good_output = copy.deepcopy(output); self.gold_receipt = self.make_gold()
        self.control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        self.control['documents'][0].update(document_version_id=uid(111), **self.make_rules(uid(703)))


class RuleEvaluationTest(RuleEvaluationFixture):
    def test_rule_source_uses_same_scorer_and_keeps_original_receipt(self):
        folder = self.rule_root / self.selected_rules['run_id']
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        packet = self.evaluate(); result = packet['result']; summary = result['summary']
        direct = score_document(self.input.read_bytes(), encoded(self.good_output), before['output.json'],
            encoded(self.control['documents'][0]['final_annotation']), self.value['instructions'])
        self.assertEqual(summary['method'], 'rules')
        for view in ('first_raw', 'final_auto'):
            self.assertEqual(result['documents'][0][view]['summary'], direct['summary'])
            self.assertEqual(summary['views'][view]['known_fields'], 8)
            self.assertLess(summary['views'][view]['correct_fields'], 8)
        self.assertEqual(result['documents'][0]['attempt_count'], 1)
        self.assertEqual(json.loads(before['receipt.json'])['attempts'], 1)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, before)
        self.assertEqual(len([name for name in packet['sources'] if name.startswith('runs/')]), 6)
        self.assertIn('M02_REQUIRES_AI_AUTO', summary['m02']['warnings'])
        self.assertIsNone(summary['m02']['accuracy_percent'])
        self.assertNotIn('PRIVATE_', json.dumps(summary)); self.assertNotIn(str(self.work), json.dumps(summary))

    def test_failed_rules_keep_known_denominator_and_actual_error_code(self):
        self.replace_source_with_overflow()
        result = self.evaluate()['result']; view = result['summary']['views']['final_auto']
        self.assertEqual((view['correct_fields'], view['known_fields'], view['document_failures']), (0, 8, 1))
        self.assertIsNone(view['generation_rate_percent'])
        self.assertEqual(result['documents'][0]['first_raw']['source_error_code'], 'RULE_OUTPUT_LIMIT')
        self.assertEqual(result['documents'][0]['final_auto']['source_attempt'], 1)

    def test_strict_rule_policy_and_api_policy_are_not_interchangeable(self):
        for field, value in (('profile_sha256', '0'*64), ('profile_version', 'other'), ('rule_version', 'future'),
                             ('schema_version', 'future'), ('retry_policy_version', 'api-structure-retry-v1'),
                             ('provider', 'openai'), ('profile_reviewed_by', ''), ('profile_locked_at', None)):
            changed = copy.deepcopy(self.control); changed['policy'][field] = value
            with self.subTest(field=field): self.invalid_record(changed)
        changed = copy.deepcopy(self.control); del changed['policy']['profile_basis']; self.invalid_record(changed)

    def test_rules_cannot_use_registered_api_reference_or_claim_ai_method(self):
        changed = copy.deepcopy(self.control); changed['documents'][0]['snapshot_ref'] = self.selected['snapshot_ref']
        self.invalid_record(changed)
        changed = copy.deepcopy(self.ai_control); changed['documents'][0].update(self.selected_rules)
        with self.assertRaises(ExtractionError) as caught: self.evaluate(changed)
        self.assertEqual(caught.exception.kind, 'archive')

    def test_profile_lock_must_precede_selected_run_and_initial_requires_dev_basis(self):
        for locked_at in ('2020-01-01T03:00:00Z', '2020-01-01T04:00:00Z'):
            changed = copy.deepcopy(self.control); changed['policy']['profile_locked_at'] = locked_at
            with self.subTest(locked_at=locked_at): self.invalid_record(changed, 'EVALUATION_PROFILE_LOCK_TIME_INVALID')
        for basis in ('unknown', 'holdout_feedback', 'unsupported'):
            changed = copy.deepcopy(self.control); changed['policy']['profile_basis'] = basis
            with self.subTest(basis=basis): self.invalid_record(changed)

    def test_holdout_profile_feedback_requires_explicit_semantic_exposure_declaration(self):
        changed = copy.deepcopy(self.control); changed.update(phase='retest', initial_ref='a'*64)
        changed['policy']['profile_basis'] = 'holdout_feedback'
        with self.assertRaises(ExtractionError): records._header(encoded(changed))
        changed['review'].update(semantic_feedback_used=True, exposure_status='exposed')
        self.assertEqual(records._header(encoded(changed))['policy']['profile_basis'], 'holdout_feedback')

    def test_one_rule_attempt_requires_identical_annotations(self):
        changed = copy.deepcopy(self.control); changed['documents'][0]['first_annotation']['generation_reviews'] = [
            dict(local_item_id='rule-item-1', field='types', unsupported=True, reason='합성 불일치')]
        self.invalid_record(changed, 'EVALUATION_SINGLE_ATTEMPT_ANNOTATIONS')

    def test_changed_source_bytes_or_receipt_are_not_silently_selected(self):
        changed = copy.deepcopy(self.control); changed['documents'][0]['receipt_sha256'] = '0'*64
        self.invalid_record(changed, 'EVALUATION_RUN_MISMATCH')
        self.input.write_bytes(self.input.read_bytes() + b' ')
        changed = copy.deepcopy(self.control); changed['documents'][0].update(self.make_rules(uid(704)))
        self.invalid_record(changed, 'EVALUATION_SOURCE_MISMATCH')

    def test_default_root_uses_method_without_changing_explicit_source_root(self):
        with patch.object(records, 'RULE_ROOT', self.rule_root, create=True):
            packet = records.evaluate_record(encoded(self.control), self.gold_root,
                initial_root=self.initial_root, evaluated_at=EVALUATED_AT)
        self.assertEqual(packet['result']['summary'], self.evaluate()['result']['summary'])

    def test_rules_are_not_ai_m02_even_for_complete_declared_real_holdout(self):
        # 40건 모두 가상 자료를 real로 선언한 분기 시험이다. 실제 gold/성능 실적이 아니다.
        manifest = copy.deepcopy(self.manifest)
        manifest.update(dataset_version='fictional-rule-real-cohort', data_kind='real', documents=[], events=[], split_assignments=[])
        manifest['grouping_review'].update(reviewed_by='fictional-group-reviewer', reviewed_at='2020-01-01T00:00:00Z')
        answers, inputs = [], []
        for i in range(40):
            version, doc, event, group = uid(1000+i), uid(2000+i), uid(3000+i), uid(4000+i)
            source = copy.deepcopy(self.source); source.update(data_kind='real', document_version_id=version)
            path = self.work/f'fictional-rules-{i}.json'; path.write_bytes(encoded(source)); inputs.append(path)
            document = copy.deepcopy(self.manifest['documents'][0]); document.update(document_id=doc,
                official_url=f'https://example.test/fictional-rules/{i}', exposure_status='development' if i<20 else 'unexposed',
                versions=[dict(document_version_id=version, input_sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
            manifest['documents'].append(document)
            manifest['events'].append(dict(event_id=event, document_ids=[doc], split_group_id=group, suspected_duplicate_ids=[]))
            assignment = copy.deepcopy(self.manifest['split_assignments'][0]); assignment.update(document_id=doc,
                split_group_id=group, split='dev' if i<20 else 'holdout'); manifest['split_assignments'].append(assignment)
            answer = copy.deepcopy(self.value['documents'][0]); answer.update(document_version_id=version, input_path=str(path))
            answer['output']['document_version_id'] = version; answer['anchors'][0]['event_id'] = event; answers.append(answer)
        path = self.work/'fictional-rule-real-manifest.json'; path.write_bytes(encoded(manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock): dataset = freeze_dataset(path, self.dataset_root)
        self.value.update(gold_version='fictional-rule-real-gold', dataset_ref=dataset['dataset_ref'],
            manifest_sha256=dataset['manifest_sha256'], documents=answers)
        self.gold_receipt = self.make_gold(); self.profile['data_kind'] = 'real'; self.profile_path.write_bytes(encoded(self.profile))
        self.control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash(),
                            policy=self.rule_policy(), documents=[])
        self.control['review']['exposure_status'] = 'none_declared'
        for i, (path, answer) in enumerate(zip(inputs, answers)):
            self.input = path; self.good_output = answer['output']
            self.control['documents'].append(dict(document_version_id=answer['document_version_id'], **self.make_rules(uid(8000+i))))
        summary = self.evaluate()['result']['summary']
        self.assertEqual(summary['views']['final_auto']['known_fields'], 320)
        self.assertEqual(summary['splits']['holdout']['final_auto']['known_fields'], 160)
        self.assertIsNotNone(summary['splits']['holdout']['final_auto']['accuracy_percent'])
        self.assertEqual(summary['m02']['warnings'], ['M02_REQUIRES_AI_AUTO'])
        self.assertFalse(summary['m02']['eligible_as_declared']); self.assertIsNone(summary['m02']['accuracy_percent'])
