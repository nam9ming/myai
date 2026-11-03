import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from processing.evaluation import gold
from processing.evaluation.storage import freeze_dataset, verify_dataset
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import manifest, uid, REPO


class GoldTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.work = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.dataset_root = self.work/'datasets'
        self.input = self.work/'PRIVATE_INPUT.json'
        self.input.write_bytes((REPO/'contracts/examples/ai-input.json').read_bytes())
        self.source = json.loads(self.input.read_bytes())
        m = manifest(); m['documents']=m['documents'][:1]; m['split_assignments']=m['split_assignments'][:1]
        m['documents'][0]['versions']=[dict(document_version_id=self.source['document_version_id'],
            input_sha256=hashlib.sha256(self.input.read_bytes()).hexdigest())]
        m['events']=m['events'][:1]; m['events'][0]['document_ids']=[m['documents'][0]['document_id']]
        m['events'][0]['suspected_duplicate_ids']=[]; m['relations']=[]
        self.manifest=m
        path=self.work/'manifest.json'; path.write_text(json.dumps(m))
        receipt=freeze_dataset(path,self.dataset_root)
        # 기존 예제는 사람이 만든 합성 사실이며 실제 모델 결과/실제 금표가 아니다.
        output=json.loads((REPO/'contracts/examples/ai-extraction.json').read_bytes())
        self.value=dict(schema_version='dataset-gold-v1',gold_version='synthetic-gold-v1',
            dataset_ref=receipt['dataset_ref'],manifest_sha256=receipt['manifest_sha256'],
            instructions=dict(version='synthetic-instructions-v1',normalization_version='gold-exact-v1',
                text='PRIVATE_RULES: 합성 원문을 독립적으로 판독하는 시험',synonyms=[]),
            authorship=dict(author='PRIVATE_AUTHOR',reviewer='PRIVATE_REVIEWER',
                authored_at='2026-11-03T00:00:00Z',reviewed_at='2026-11-03T01:00:00Z',
                independent_source_reading=True,cross_reviewed=True,no_unresolved_disagreements=True),
            documents=[dict(document_version_id=self.source['document_version_id'],input_path=str(self.input),
                output=output,anchors=[dict(slot_id='item1',event_id=m['events'][0]['event_id'],evidence_ids=['e1'])])],
            adjudications=[])

    def cleanup(self):
        for current,_,_ in os.walk(self.work):Path(current).chmod(0o700)
        self.temp.cleanup()

    def check(self,value=None):
        return gold.check_gold(json.dumps(value or self.value).encode(),self.dataset_root)

    def invalid(self,value,code=None):
        with self.assertRaises(ExtractionError) as caught:self.check(value)
        if code:self.assertEqual(caught.exception.code,code)
        self.assertNotIn('PRIVATE_',str(caught.exception))

    def test_summary_is_safe_and_does_not_certify_humans(self):
        result=self.check()
        self.assertEqual(result['counts'],dict(documents=1,document_versions=1,slots=1,adjudications=0))
        self.assertEqual(result['data_kind'],'synthetic')
        self.assertEqual(result['review_status'],'declared_cross_reviewed')
        self.assertEqual(result['gold_sha256'],hashlib.sha256(json.dumps(self.value).encode()).hexdigest())
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertNotIn(str(self.work),json.dumps(result))

    def test_independence_and_resolution_declarations_are_required(self):
        for field in ('independent_source_reading','cross_reviewed','no_unresolved_disagreements'):
            for bad in (False,1,None):
                value=copy.deepcopy(self.value);value['authorship'][field]=bad
                with self.subTest(field=field,bad=bad):self.invalid(value)

    def test_author_and_reviewer_must_differ_after_normalization(self):
        value=copy.deepcopy(self.value);value['authorship']['reviewer']=' private_author '
        self.invalid(value)
        value['authorship'].update(author='가',reviewer='가');self.invalid(value)

    def test_malformed_fractional_output_is_an_input_error(self):
        value=copy.deepcopy(self.value)
        value['documents'][0]['output']['evidence'][0]['start_char']=1.5
        self.invalid(value)

    def test_review_time_cannot_precede_authorship(self):
        value=copy.deepcopy(self.value);value['authorship']['reviewed_at']='2026-11-02T23:59:59.999999999Z'
        self.invalid(value)

    def test_all_versions_are_required_once(self):
        for mode in ('missing','duplicate','unknown'):
            value=copy.deepcopy(self.value)
            if mode=='missing':value['documents']=[]
            elif mode=='duplicate':value['documents'].append(copy.deepcopy(value['documents'][0]))
            else:value['documents'][0]['document_version_id']=uid(999)
            with self.subTest(mode=mode):self.invalid(value)

    def test_actual_input_bytes_are_pinned(self):
        self.input.write_bytes(self.input.read_bytes()+b'\n');self.invalid(self.value,'GOLD_SOURCE_MISMATCH')

    def test_anchors_cover_slots_and_reference_registered_events_and_evidence(self):
        for mode in ('missing','duplicate','slot','event','evidence','empty'):
            value=copy.deepcopy(self.value);a=value['documents'][0]['anchors']
            if mode=='missing':a.clear()
            elif mode=='duplicate':a.append(copy.deepcopy(a[0]))
            elif mode=='slot':a[0]['slot_id']='other'
            elif mode=='event':a[0]['event_id']=uid(999)
            elif mode=='evidence':a[0]['evidence_ids']=['missing']
            else:a[0]['evidence_ids']=[]
            with self.subTest(mode=mode):self.invalid(value)

    def test_wrong_evidence_quote_is_not_accepted_as_gold(self):
        value=copy.deepcopy(self.value);value['documents'][0]['output']['evidence'][0]['quote']='PRIVATE_WRONG'
        self.invalid(value,'EVIDENCE_MISMATCH')

    def test_empty_document_is_explicit_and_not_a_missing_version(self):
        value=copy.deepcopy(self.value);doc=value['documents'][0]
        doc['output'].update(items=[],evidence=[],warnings=['NO_EVENT_FOUND']);doc['anchors']=[]
        self.assertEqual(self.check(value)['counts']['slots'],0)

    def test_unknown_and_explicit_empty_values_remain_distinct(self):
        value=copy.deepcopy(self.value);item=value['documents'][0]['output']['items'][0]
        item['exceptions']=dict(value=None,knowledge='not_stated',evidence_ids=[],reason='원문 미기재')
        self.assertEqual(self.check(value)['counts']['slots'],1)
        item['exceptions']=dict(value=[],knowledge='known',evidence_ids=['e1'],reason=None)
        self.assertEqual(self.check(value)['counts']['slots'],1)

    def adjudication(self):
        return dict(document_version_id=self.source['document_version_id'],slot_id='item1',field='exceptions',
            disagreement='PRIVATE_DISAGREEMENT',resolution='PRIVATE_RESOLUTION',reason='PRIVATE_REASON',
            evidence_ids=['e1'],adjudicated_by='PRIVATE_ADJUDICATOR',adjudicated_at='2026-11-03T00:30:00.123456789Z')

    def test_adjudications_bind_slot_evidence_field_and_review_window(self):
        value=copy.deepcopy(self.value);value['adjudications']=[self.adjudication()]
        self.assertEqual(self.check(value)['counts']['adjudications'],1)
        for field,bad in (('slot_id','missing'),('field','title'),('evidence_ids',[]),
                          ('adjudicated_at','2026-11-03T01:00:00.000000001Z')):
            changed=copy.deepcopy(value);changed['adjudications'][0][field]=bad
            with self.subTest(field=field):self.invalid(changed)
        value['adjudications'].append(self.adjudication());self.invalid(value)

    def test_synonyms_are_fixed_and_cannot_conflict_after_whitespace_nfc(self):
        value=copy.deepcopy(self.value)
        value['instructions']['synonyms']=[dict(field='locations',canonical='가상 도로',variants=['가상 연결도로'])]
        self.assertEqual(self.check(value)['counts']['slots'],1)
        value['instructions']['synonyms'].append(dict(field='locations',canonical='다른 곳',variants=[' 가상   연결도로 ']))
        self.invalid(value)

    def test_manifest_reread_is_compared_and_json_is_strict(self):
        path=self.dataset_root/self.value['dataset_ref']/'manifest.json'
        def changed(ref,root):
            result=verify_dataset(ref,root);path.chmod(0o600);path.write_bytes(path.read_bytes()+b'\n');path.chmod(0o400)
            return result
        with patch('processing.evaluation.gold.verify_dataset',side_effect=changed):self.invalid(self.value,'GOLD_DATASET_MISMATCH')
        value=copy.deepcopy(self.value);value['extra']='PRIVATE';self.invalid(value)
