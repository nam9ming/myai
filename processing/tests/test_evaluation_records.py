import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from unittest.mock import patch

from processing.evaluation import records
from processing.evaluation.gold_storage import freeze_gold
from processing.evaluation.storage import freeze_dataset
from processing.extraction.api import run_api
from processing.extraction.archive import freeze_run, import_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_extraction_api import KEY, response
from processing.tests.test_extraction_prompt_metadata import metadata
from processing.tests.test_gold import GoldFixture

EVALUATED_AT='2020-01-01T05:00:00Z'


class DatasetClock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2020,1,1,0,30,tzinfo=timezone.utc)


class GoldClock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2020,1,1,2,tzinfo=timezone.utc)


class LaterGoldClock(datetime):
    @classmethod
    def now(cls,tz=None):return cls(2020,1,1,4,tzinfo=timezone.utc)


class EvaluationFixture(GoldFixture):
    def setUp(self):
        super().setUp()
        # 전송·시각·역할은 모두 합성이다. 실제 독립 gold/API 실행 실적으로 세지 않는다.
        self.source.update(published_date='2019-12-31',document_version_id=uid(101));self.input.write_text(json.dumps(self.source))
        self.manifest['dataset_version']='synthetic-evaluation-cohort-v1'
        self.manifest['documents'][0]['versions'][0]['input_sha256']=hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.manifest['documents'][0]['versions'][0]['document_version_id']=self.source['document_version_id']
        for entry in self.manifest['split_assignments']:entry['assigned_at']='2020-01-01T00:00:00Z'
        self.manifest['grouping_review'].update(reviewed_by=None,reviewed_at=None)
        path=self.work/'evaluation-manifest.json';path.write_text(json.dumps(self.manifest))
        with patch('processing.extraction.archive.datetime',DatasetClock):dataset=freeze_dataset(path,self.dataset_root)
        self.value.update(dataset_ref=dataset['dataset_ref'],manifest_sha256=dataset['manifest_sha256'])
        self.value['documents'][0]['document_version_id']=self.source['document_version_id']
        self.value['documents'][0]['output']['document_version_id']=self.source['document_version_id']
        self.value['authorship'].update(authored_at='2020-01-01T00:00:00Z',reviewed_at='2020-01-01T01:00:00Z')
        self.gold_root=self.work/'gold';self.run_root=self.work/'runs';self.initial_root=self.work/'evaluations'
        self.gold_control=self.work/'gold-control.json';self.good_output=copy.deepcopy(self.value['documents'][0]['output'])
        self.gold_receipt=self.make_gold()
        self.selected=self.make_run(uid(501))
        annotation=self.annotations(self.good_output)
        self.control=dict(schema_version='extraction-evaluation-v1',extraction_eval_id=uid(601),
            gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash(),method='ai_auto',
            phase='initial',initial_ref=None,
            review=dict(reviewed_by='synthetic-evaluator',reviewed_at='2020-01-01T04:30:00Z',
                semantic_feedback_used=False,exposure_status='unknown',exposure_note='합성 자료 노출 판정 없음'),
            policy=dict(provider='openai',model_label='gpt-6.1-sol',prompt_version='prompt-v2',
                        schema_version='extract-schema-v1',retry_policy_version='api-structure-retry-v1'),
            documents=[dict(document_version_id=self.source['document_version_id'],**self.selected,
                            first_annotation=copy.deepcopy(annotation),final_annotation=copy.deepcopy(annotation))])

    def annotations(self,output):
        return dict(schema_version='score-links-v1',item_links=[dict(slot_id=i['local_item_id'],
            local_item_id=i['local_item_id'],kind='match',occurrence_links=[dict(gold_occurrence_id=o['local_occurrence_id'],
                local_occurrence_id=o['local_occurrence_id']) for o in i['occurrences']]) for i in output['items']],generation_reviews=[])

    def make_gold(self,clock=GoldClock):
        self.gold_control.write_text(json.dumps(self.value))
        with patch('processing.extraction.archive.datetime',clock):
            return freeze_gold(self.gold_control,self.gold_root,self.dataset_root)

    def gold_receipt_hash(self):
        return hashlib.sha256((self.gold_root/self.gold_receipt['gold_ref']/'receipt.json').read_bytes()).hexdigest()

    def make_run(self,run_id,retry=False,failed=False,started='2020-01-01T03:00:00Z',prompt_version='prompt-v2',recorded=None):
        class RunClock(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.fromisoformat(recorded or started)
        created=int(datetime.fromisoformat(started).timestamp())
        replies=[(200,response(json.dumps(self.good_output),created_at=created),None,True)]
        if retry:replies.insert(0,(200,response('not-json',created_at=created),None,True))
        if failed:replies=[(401,b'{}',None,True)]
        with patch.dict(os.environ,OPENAI_API_KEY=KEY),patch('processing.extraction.api._exchange',side_effect=replies),\
             patch('processing.extraction.api._now',return_value=started),patch('processing.extraction.api.time.sleep'),\
             patch('processing.extraction.api.API_PROMPT_VERSION',prompt_version),patch('processing.extraction.archive.datetime',RunClock):
            run_api(self.input,'fixture-nfc-v1',self.run_root,run_id,model='gpt-6.1-sol')
        packet=freeze_run(run_id,self.run_root)
        return dict(run_id=run_id,snapshot_ref=packet['snapshot_ref'],receipt_sha256=hashlib.sha256(
            (self.run_root/packet['snapshot_ref']/'receipt.json').read_bytes()).hexdigest())

    def evaluate(self,control=None):
        return records.evaluate_record(json.dumps(control or self.control).encode(),self.gold_root,self.run_root,
                                       self.initial_root,evaluated_at=EVALUATED_AT)

    def invalid_record(self,control,code=None):
        with self.assertRaises(ExtractionError) as caught:self.evaluate(control)
        if code:self.assertEqual(caught.exception.code,code)
        self.assertNotIn('PRIVATE_',str(caught.exception))


class EvaluationRecordTest(EvaluationFixture):
    def test_declared_real_cohort_gate_uses_holdout_and_preserves_distribution(self):
        # real 선언의 분기만 시험한다. 40개 입력/역할/응답 모두 가상이며 실제 평가가 아니다.
        manifest=copy.deepcopy(self.manifest);manifest.update(dataset_version='fictional-real-declaration-gate',data_kind='real',
            documents=[],events=[],split_assignments=[])
        manifest['grouping_review'].update(reviewed_by='fictional-group-reviewer',reviewed_at='2020-01-01T00:00:00Z')
        gold_docs=[];inputs=[]
        for i in range(40):
            version,doc,event,group=uid(1000+i),uid(2000+i),uid(3000+i),uid(4000+i)
            source=copy.deepcopy(self.source);source.update(data_kind='real',document_version_id=version,title=f'가상 선언 시험 {i}')
            path=self.work/f'fictional-{i}.json';path.write_text(json.dumps(source));inputs.append(path)
            document=copy.deepcopy(self.manifest['documents'][0]);document.update(document_id=doc,
                official_url=f'https://example.test/fictional/{i}',exposure_status='development' if i<20 else 'unexposed',
                versions=[dict(document_version_id=version,input_sha256=hashlib.sha256(path.read_bytes()).hexdigest())])
            manifest['documents'].append(document)
            manifest['events'].append(dict(event_id=event,document_ids=[doc],split_group_id=group,suspected_duplicate_ids=[]))
            assignment=copy.deepcopy(self.manifest['split_assignments'][0]);assignment.update(document_id=doc,split_group_id=group,
                split='dev' if i<20 else 'holdout');manifest['split_assignments'].append(assignment)
            answer=copy.deepcopy(self.value['documents'][0]);answer.update(document_version_id=version,input_path=str(path))
            answer['output']['document_version_id']=version;answer['anchors'][0]['event_id']=event;gold_docs.append(answer)
        path=self.work/'fictional-real-manifest.json';path.write_text(json.dumps(manifest))
        with patch('processing.extraction.archive.datetime',DatasetClock):dataset=freeze_dataset(path,self.dataset_root)
        self.value.update(gold_version='fictional-real-gold',dataset_ref=dataset['dataset_ref'],manifest_sha256=dataset['manifest_sha256'],
            documents=gold_docs)
        self.gold_receipt=self.make_gold();self.control.update(gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash(),documents=[])
        self.control['review']['exposure_status']='none_declared'
        for i,(path,answer) in enumerate(zip(inputs,gold_docs)):
            self.input=path;self.good_output=answer['output']
            annotation=self.annotations(self.good_output)
            self.control['documents'].append(dict(document_version_id=answer['document_version_id'],**self.make_run(uid(5000+i)),
                first_annotation=annotation,final_annotation=annotation))
        summary=self.evaluate()['result']['summary']
        self.assertEqual(summary['views']['final_auto']['known_fields'],320)
        self.assertEqual(summary['splits']['holdout']['final_auto']['known_fields'],160)
        self.assertTrue(summary['m02']['eligible_as_declared']);self.assertEqual(summary['m02']['accuracy_percent'],100)
        self.assertTrue(summary['m02']['meets_90_percent']);self.assertFalse(summary['generalization_claim'])
        self.assertEqual(summary['cohort_distribution']['holdout']['types']['construction'],20)
        self.control['review']['exposure_status']='exposed'
        self.assertIsNone(self.evaluate()['result']['summary']['m02']['accuracy_percent'])

    def test_binds_real_archive_bytes_and_reports_primary_final_view(self):
        packet=self.evaluate();summary=packet['result']['summary']
        self.assertEqual(summary['primary_view'],'final_auto')
        self.assertEqual(summary['views']['final_auto']['correct_fields'],8)
        self.assertEqual(summary['views']['first_raw']['correct_fields'],8)
        self.assertFalse(summary['m02']['eligible_as_declared'])
        self.assertIsNone(summary['m02']['accuracy_percent'])
        self.assertNotIn(str(self.work),json.dumps(summary));self.assertNotIn('PRIVATE_',json.dumps(summary))
        self.assertTrue(packet['sources'])

    def test_first_schema_failure_and_final_success_are_both_scored(self):
        self.control['documents'][0].update(self.make_run(uid(502),retry=True))
        self.control['documents'][0]['first_annotation']=dict(schema_version='score-links-v1',item_links=[],generation_reviews=[])
        summary=self.evaluate()['result']['summary']
        self.assertEqual((summary['views']['first_raw']['correct_fields'],summary['views']['first_raw']['known_fields']),(0,8))
        self.assertEqual(summary['views']['first_raw']['document_failures'],1)
        self.assertEqual((summary['views']['final_auto']['correct_fields'],summary['views']['final_auto']['known_fields']),(8,8))
        self.assertEqual(summary['views']['final_auto']['document_failures'],0)

    def test_failed_api_run_is_not_removed_from_known_field_denominator(self):
        self.control['documents'][0].update(self.make_run(uid(503),failed=True))
        empty=dict(schema_version='score-links-v1',item_links=[],generation_reviews=[])
        self.control['documents'][0].update(first_annotation=empty,final_annotation=empty)
        summary=self.evaluate()['result']['summary']['views']['final_auto']
        self.assertEqual((summary['correct_fields'],summary['known_fields'],summary['document_failures']),(0,8,1))
        self.assertIsNone(summary['generation_rate_percent'])

    def test_receipt_policy_versions_and_coverage_must_match(self):
        for kind in ('gold-hash','run-hash','policy','version','duplicate'):
            value=copy.deepcopy(self.control)
            if kind=='gold-hash':value['gold_receipt_sha256']='0'*64
            elif kind=='run-hash':value['documents'][0]['receipt_sha256']='0'*64
            elif kind=='policy':value['policy']['model_label']='PRIVATE_OTHER_MODEL'
            elif kind=='version':value['documents'][0]['document_version_id']=uid(999)
            else:value['documents'].append(copy.deepcopy(value['documents'][0]))
            with self.subTest(kind=kind):self.invalid_record(value)

    def test_manual_import_is_not_ai_automatic_execution(self):
        meta=metadata();meta.update(run_id=uid(504),document_version_id=self.source['document_version_id'])
        path=self.work/'manual-meta';path.write_text(json.dumps(meta))
        prompt=self.work/'prompt';prompt.write_bytes(b'synthetic manual prompt')
        output=self.work/'manual-output';output.write_text(json.dumps(self.good_output))
        import_run(self.input,path,[(prompt,output)],self.run_root)
        packet=freeze_run(meta['run_id'],self.run_root)
        self.control['documents'][0].update(run_id=meta['run_id'],snapshot_ref=packet['snapshot_ref'],
            receipt_sha256=hashlib.sha256((self.run_root/packet['snapshot_ref']/'receipt.json').read_bytes()).hexdigest())
        self.invalid_record(self.control,'EVALUATION_AUTO_REQUIRES_API')

    def test_initial_requires_gold_frozen_before_first_run(self):
        self.value['gold_version']='synthetic-late-gold';self.gold_receipt=self.make_gold(LaterGoldClock)
        self.control.update(gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        self.invalid_record(self.control,'EVALUATION_GOLD_AFTER_RUN')

    def test_review_and_phase_history_cannot_claim_future_or_semantic_retry_as_initial(self):
        for kind in ('future','before-run','feedback','missing-initial','self-initial'):
            value=copy.deepcopy(self.control)
            if kind=='future':value['review']['reviewed_at']='2020-01-01T06:00:00Z'
            elif kind=='before-run':value['review']['reviewed_at']='2020-01-01T02:30:00Z'
            elif kind=='feedback':value['review'].update(semantic_feedback_used=True,exposure_status='exposed')
            elif kind=='missing-initial':value.update(phase='retest')
            else:value.update(phase='retest',initial_ref=hashlib.sha256(value['extraction_eval_id'].encode()).hexdigest())
            with self.subTest(kind=kind):self.invalid_record(value)

    def test_one_attempt_has_one_consistent_set_of_annotations(self):
        self.control['documents'][0]['first_annotation']['item_links'][0]['kind']='additional'
        self.control['documents'][0]['first_annotation']['item_links'][0].update(slot_id=None,occurrence_links=[])
        self.invalid_record(self.control,'EVALUATION_SINGLE_ATTEMPT_ANNOTATIONS')

    def test_archive_recorded_after_evaluation_cannot_be_used_retroactively(self):
        self.control['documents'][0].update(self.make_run(uid(507),recorded='2020-01-01T06:00:00Z'))
        self.invalid_record(self.control,'EVALUATION_RUN_ARCHIVE_TIME_INVALID')

    def test_retest_gold_correction_preserves_initial_and_is_not_generalization(self):
        self.value['gold_version']='synthetic-wrong-gold'
        self.value['documents'][0]['output']['items'][0]['occurrences'][0]['time_end']['value']='15:00'
        self.gold_receipt=self.make_gold();self.control.update(gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        for key in ('first_annotation','final_annotation'):
            self.control['documents'][0][key]['generation_reviews']=[dict(local_item_id='item1',field='time_end',unsupported=False,reason='의도적 합성 금표 오류: 원문은16시')]
        original=self.evaluate()['result'];before=json.dumps(original,sort_keys=True)
        self.value['gold_version']='synthetic-corrected-gold';self.value['documents'][0]['output']=copy.deepcopy(self.good_output)
        self.gold_receipt=self.make_gold(LaterGoldClock)
        value=copy.deepcopy(self.control);value.update(extraction_eval_id=uid(602),phase='retest',initial_ref=original['evaluation_ref'],
            gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        value['review'].update(reviewed_at='2020-01-01T06:00:00Z',exposure_status='exposed',exposure_note='합성 금표 수정')
        parsed=records._header(json.dumps(value).encode())
        gold,runs,_=records._load_sources(parsed,self.gold_root,self.run_root)
        initial=dict(result=original,receipt=dict(evaluation_ref=original['evaluation_ref'],frozen_at='2020-01-01T05:30:00Z'))
        result=records._compute(parsed,gold,runs,initial,'2020-01-01T07:00:00Z',hashlib.sha256(json.dumps(value).encode()).hexdigest())
        self.assertTrue(result['summary']['gold_changed'])
        self.assertFalse(result['summary']['generalization_claim'])
        self.assertEqual(result['summary']['initial_comparison']['final_auto_delta_percent'],12.5)
        self.assertEqual(before,json.dumps(original,sort_keys=True))
