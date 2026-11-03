import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

from processing.evaluation import evaluation_storage as storage
from processing.extraction.archive import _fingerprint
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import REPO, uid
from processing.tests.test_evaluation_records import EvaluationFixture, LaterGoldClock


class EvaluationStorageTest(EvaluationFixture):
    def write_control(self,value=None,name='selection.json'):
        path=self.work/name;path.write_text(json.dumps(value or self.control));return path

    def freeze(self,value=None,hour=5,root=None):
        class EvalClock(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2020,1,1,hour,tzinfo=timezone.utc)
        class FreezeClock(datetime):
            @classmethod
            def now(cls,tz=None):return cls(2020,1,1,hour,30,tzinfo=timezone.utc)
        path=self.write_control(value)
        with patch('processing.evaluation.records.datetime',EvalClock),patch('processing.extraction.archive.datetime',FreezeClock):
            return storage.freeze_evaluation(path,root or self.initial_root,self.gold_root,self.run_root,self.initial_root)

    def snapshot(self,directory):
        return {str(p.relative_to(directory)):(_fingerprint(p),p.stat().st_mode & 0o777)
                for p in directory.rglob('*') if p.is_file()}

    def test_freeze_exact_bytes_reuse_and_verify_without_original_sources(self):
        receipt=self.freeze();ref=receipt['evaluation_ref'];directory=self.initial_root/ref
        before=self.snapshot(directory)
        self.assertEqual((directory/'selection.json').read_bytes(),self.write_control().read_bytes())
        self.assertTrue(all(mode==0o400 for _,mode in before.values()))
        self.assertTrue(all(p.stat().st_mode & 0o777==0o500 for p in [directory,*directory.rglob('*')] if p.is_dir()))
        self.assertIn(f"runs/{self.selected['snapshot_ref']}/attempt-1.response",before)
        for folder in (self.gold_root,self.run_root,self.dataset_root):folder.rename(folder.with_name(folder.name+'-gone'))
        self.input.unlink();self.gold_control.unlink()
        self.assertEqual(storage.verify_evaluation(ref,self.initial_root),receipt)
        self.assertEqual(self.freeze(),receipt)
        self.assertEqual(self.snapshot(directory),before)
        self.assertNotIn('PRIVATE_',json.dumps(receipt));self.assertNotIn(str(self.work),json.dumps(receipt))

    def test_same_id_different_bytes_conflict_preserves_existing(self):
        receipt=self.freeze();before=self.snapshot(self.initial_root/receipt['evaluation_ref'])
        value=copy.deepcopy(self.control);value['review']['exposure_note']='PRIVATE_CHANGED'
        with self.assertRaises(ExtractionError) as caught:self.freeze(value)
        self.assertEqual(caught.exception.code,'EVALUATION_CONFLICT')
        self.assertEqual(self.snapshot(self.initial_root/receipt['evaluation_ref']),before)

    def test_native_concurrent_same_and_conflicting_selections(self):
        original=self.write_control(name='one.json')
        changed=copy.deepcopy(self.control);changed['review']['exposure_note']='different'
        other=self.write_control(changed,'two.json')
        for paths,name,success in (([original]*4,'same',4),([original,other],'conflict',1)):
            root=self.work/name
            def run(path):
                try:return storage.freeze_evaluation(path,root,self.gold_root,self.run_root,self.initial_root)
                except ExtractionError as error:return error.code
            with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,paths))
            self.assertEqual(sum(type(r) is dict for r in results),success)
            if success==1:self.assertIn('EVALUATION_CONFLICT',results)
            self.assertEqual(len(list(root.iterdir())),1)

    def test_retest_copies_initial_and_gold_correction_without_changing_original(self):
        self.value['gold_version']='synthetic-wrong-gold'
        self.value['documents'][0]['output']['items'][0]['occurrences'][0]['time_end']['value']='15:00'
        self.gold_receipt=self.make_gold();self.control.update(gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        for key in ('first_annotation','final_annotation'):
            self.control['documents'][0][key]['generation_reviews']=[dict(local_item_id='item1',field='time_end',unsupported=False,reason='합성 gold 오류')]
        initial=self.freeze();before=self.snapshot(self.initial_root/initial['evaluation_ref'])
        self.value['gold_version']='synthetic-corrected-gold';self.value['documents'][0]['output']=copy.deepcopy(self.good_output)
        self.gold_receipt=self.make_gold(LaterGoldClock)
        value=copy.deepcopy(self.control);value.update(extraction_eval_id=uid(602),phase='retest',initial_ref=initial['evaluation_ref'],
            gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        value['review'].update(reviewed_at='2020-01-01T06:00:00Z',exposure_status='exposed')
        receipt=self.freeze(value,hour=7);summary=receipt['summary']
        self.assertTrue(summary['gold_changed']);self.assertEqual(summary['initial_comparison']['final_auto_delta_percent'],12.5)
        self.assertFalse(summary['generalization_claim']);self.assertFalse(summary['m02']['eligible_as_declared'])
        self.assertEqual(self.snapshot(self.initial_root/initial['evaluation_ref']),before)
        original=self.initial_root/initial['evaluation_ref'];original.chmod(0o700)
        moved=original.rename(self.work/'initial-gone');moved.chmod(0o500)
        self.gold_root.rename(self.work/'gold-gone');self.run_root.rename(self.work/'runs-gone')
        self.assertEqual(storage.verify_evaluation(receipt['evaluation_ref'],self.initial_root),receipt)

    def test_policy_retest_requires_new_run_after_initial_and_initial_only_reference(self):
        initial=self.freeze();value=copy.deepcopy(self.control)
        value.update(extraction_eval_id=uid(603),phase='retest',initial_ref=initial['evaluation_ref'])
        value['review'].update(reviewed_at='2020-01-01T07:00:00Z',exposure_status='exposed',semantic_feedback_used=True)
        value['policy']['prompt_version']='prompt-v1'
        value['documents'][0].update(self.make_run(uid(508),started='2020-01-01T06:00:00Z',prompt_version='prompt-v1'))
        retest=self.freeze(value,hour=8)
        self.assertTrue(retest['summary']['policy_changed'])
        early=copy.deepcopy(value);early['extraction_eval_id']=uid(604)
        early['documents'][0].update(self.make_run(uid(509),prompt_version='prompt-v1'))
        with self.assertRaises(ExtractionError) as caught:self.freeze(early,hour=8)
        self.assertEqual(caught.exception.code,'EVALUATION_RETEST_RUN_TIME_INVALID')
        value.update(extraction_eval_id=uid(605),initial_ref=retest['evaluation_ref'])
        with self.assertRaises(ExtractionError) as caught:self.freeze(value,hour=9)
        self.assertEqual(caught.exception.code,'EVALUATION_INITIAL_REQUIRED')

    def test_extra_missing_symlink_permissions_and_tampered_results_are_rejected(self):
        receipt=self.freeze();ref=receipt['evaluation_ref'];original=self.initial_root/ref
        for case in ('extra','empty-dir','missing','file-mode','dir-mode','symlink','result','identity-path'):
            root=self.work/f'corrupt-{case}';folder=root/ref;shutil.copytree(original,folder);folder.chmod(0o700)
            if case=='extra':(folder/'extra').write_text('x');(folder/'extra').chmod(0o400)
            elif case=='empty-dir':(folder/'extra').mkdir(mode=0o500)
            elif case=='missing':(folder/'result.json').unlink()
            elif case=='file-mode':(folder/'result.json').chmod(0o600)
            elif case=='dir-mode':(folder/'gold').chmod(0o700)
            elif case=='symlink':
                target=folder/'result.json';target.unlink();target.symlink_to(original/'result.json')
            elif case=='result':
                target=folder/'result.json';target.chmod(0o600);target.write_bytes(b'{}');target.chmod(0o400)
            else:
                target=folder/'identity.json';identity=json.loads(target.read_bytes())
                identity['artifacts']['../PRIVATE_OUTSIDE']={'sha256':'0'*64,'size':0}
                target.chmod(0o600);target.write_text(json.dumps(identity));target.chmod(0o400)
            folder.chmod(0o500)
            with self.subTest(case=case),self.assertRaises(ExtractionError) as caught:storage.verify_evaluation(ref,root)
            self.assertEqual(caught.exception.code,'EVALUATION_INTEGRITY')

    def test_install_failure_cleans_only_own_staging(self):
        self.initial_root.mkdir();unrelated=self.initial_root/'.unrelated';unrelated.mkdir();(unrelated/'keep').write_text('keep')
        with patch.object(storage,'_rename_exclusive',side_effect=OSError(errno.EIO,'synthetic')):
            with self.assertRaises(OSError):self.freeze()
        self.assertEqual(list(self.initial_root.iterdir()),[unrelated])
        self.assertEqual((unrelated/'keep').read_text(),'keep')

    def test_concurrent_partial_destination_is_never_replaced(self):
        ref=hashlib.sha256(self.control['extraction_eval_id'].encode()).hexdigest()
        def collide(source,destination):
            destination.mkdir(mode=0o500);raise FileExistsError(errno.EEXIST,'synthetic')
        with patch.object(storage,'_rename_exclusive',side_effect=collide):
            with self.assertRaises(ExtractionError):self.freeze()
        self.assertEqual(list((self.initial_root/ref).iterdir()),[])
        self.assertEqual(len(list(self.initial_root.iterdir())),1)

    def test_source_change_during_copy_is_not_installed(self):
        copy_file=storage._copy
        def corrupt(source,destination,expected):
            if destination.name=='input.json':
                source.chmod(0o600);source.write_bytes(source.read_bytes()+b'\n');source.chmod(0o400)
            return copy_file(source,destination,expected)
        with patch.object(storage,'_copy',side_effect=corrupt):
            with self.assertRaises(ExtractionError):self.freeze()
        self.assertEqual(list(self.initial_root.iterdir()),[])

    def test_full_oversized_failed_response_and_first_attempt_are_retained(self):
        from processing.extraction.api import run_api
        from processing.extraction.archive import freeze_run
        from processing.extraction.validation import MAX_BYTES
        from processing.tests.test_extraction_api import KEY
        raw=b'x'*(MAX_BYTES+1)
        with patch.dict(os.environ,OPENAI_API_KEY=KEY),patch('processing.extraction.api._exchange',return_value=(401,raw,'API_RESPONSE_LIMIT',False)):
            run_api(self.input,'fixture-nfc-v1',self.run_root,uid(510),model='gpt-6.1-sol')
        packet=freeze_run(uid(510),self.run_root);folder=self.run_root/packet['snapshot_ref']
        self.control['documents'][0].update(run_id=uid(510),snapshot_ref=packet['snapshot_ref'],
            receipt_sha256=hashlib.sha256((folder/'receipt.json').read_bytes()).hexdigest())
        empty=dict(schema_version='score-links-v1',item_links=[],generation_reviews=[])
        self.control['documents'][0].update(first_annotation=empty,final_annotation=empty)
        self.control['review']['reviewed_at']=datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        receipt=storage.freeze_evaluation(self.write_control(),self.initial_root,self.gold_root,self.run_root)
        target=self.initial_root/receipt['evaluation_ref']/f"runs/{packet['snapshot_ref']}/attempt-1.response"
        self.assertEqual(target.read_bytes(),raw)
        self.assertEqual(receipt['summary']['views']['final_auto']['known_fields'],8)
        self.assertEqual(receipt['summary']['views']['final_auto']['document_failures'],1)

    def test_rehashed_result_is_recomputed_instead_of_trusting_reported_scores(self):
        from processing.extraction.archive import _json
        receipt=self.freeze();folder=self.initial_root/receipt['evaluation_ref']
        result=json.loads((folder/'result.json').read_bytes());result['summary']['views']['final_auto']['correct_fields']=999
        path=folder/'result.json';path.chmod(0o600);path.write_bytes(_json(result));path.chmod(0o400)
        identity=json.loads((folder/'identity.json').read_bytes());identity['artifacts']['result.json']=_fingerprint(path)
        path=folder/'identity.json';path.chmod(0o600);path.write_bytes(_json(identity));path.chmod(0o400)
        receipt['artifacts']=identity['artifacts'];receipt['summary']=result['summary']
        path=folder/'receipt.json';path.chmod(0o600);path.write_bytes(_json(receipt));path.chmod(0o400)
        with self.assertRaises(ExtractionError) as caught:storage.verify_evaluation(receipt['evaluation_ref'],self.initial_root)
        self.assertEqual(caught.exception.code,'EVALUATION_INTEGRITY')

    def test_retest_cannot_change_normalization_instructions(self):
        initial=self.freeze();self.value['gold_version']='different-guidelines'
        self.value['instructions']['text']='다른 정규화 지침';self.gold_receipt=self.make_gold(LaterGoldClock)
        value=copy.deepcopy(self.control);value.update(extraction_eval_id=uid(606),phase='retest',initial_ref=initial['evaluation_ref'],
            gold_ref=self.gold_receipt['gold_ref'],gold_receipt_sha256=self.gold_receipt_hash())
        value['review']['reviewed_at']='2020-01-01T06:00:00Z'
        with self.assertRaises(ExtractionError) as caught:self.freeze(value,hour=7)
        self.assertEqual(caught.exception.code,'EVALUATION_COHORT_MISMATCH')

    def test_real_cli_summary_and_exit_codes(self):
        path=self.write_control()
        def cli(*args):return subprocess.run([sys.executable,'-m','processing.evaluation',*map(str,args)],cwd=REPO,capture_output=True)
        arguments=['--input',path,'--gold-root',self.gold_root,'--run-root',self.run_root,'--initial-root',self.initial_root]
        checked=cli('check-evaluation',*arguments)
        self.assertEqual(checked.returncode,0,checked.stderr);summary=json.loads(checked.stdout)
        self.assertEqual(summary['views']['final_auto']['correct_fields'],8)
        frozen=cli('freeze-evaluation',*arguments,'--root',self.initial_root)
        self.assertEqual(frozen.returncode,0,frozen.stderr);receipt=json.loads(frozen.stdout)
        verified=cli('verify-evaluation',receipt['evaluation_ref'],'--root',self.initial_root)
        self.assertEqual(verified.returncode,0,verified.stderr)
        for result in (checked,frozen,verified):
            self.assertNotIn(b'PRIVATE_',result.stdout+result.stderr);self.assertNotIn(os.fsencode(self.work),result.stdout+result.stderr)
        invalid=self.work/'invalid';invalid.write_bytes(b'{"PRIVATE_":1}')
        self.assertEqual(cli('check-evaluation','--input',invalid).returncode,2)
        self.assertEqual(cli('verify-evaluation','0'*64,'--root',self.initial_root).returncode,3)
        self.assertEqual(cli('check-evaluation','--input',self.work/'PRIVATE_MISSING').returncode,5)
