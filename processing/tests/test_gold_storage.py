from concurrent.futures import ThreadPoolExecutor
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from processing.evaluation.gold_storage import freeze_gold, verify_gold
from processing.extraction.validation import ExtractionError
from processing.tests.test_gold import GoldFixture, REPO


class GoldStorageTest(GoldFixture):
    def setUp(self):
        super().setUp()
        self.root=self.work/'gold'
        self.control=self.work/'PRIVATE_GOLD.json';self.control.write_text(json.dumps(self.value))

    def freeze(self):return freeze_gold(self.control,self.root,self.dataset_root)

    def cli(self,*args):
        return subprocess.run([sys.executable,'-m','processing.evaluation',*args],cwd=REPO,capture_output=True)

    def test_preserves_all_bytes_and_verifies_without_original_paths(self):
        result=self.freeze();folder=self.root/result['gold_ref']
        self.assertEqual((folder/'gold.json').read_bytes(),self.control.read_bytes())
        self.assertEqual((folder/f"input-{self.source['document_version_id']}.json").read_bytes(),self.input.read_bytes())
        self.assertEqual(folder.stat().st_mode&0o777,0o500)
        self.assertEqual(len(list(folder.iterdir())),5)
        for p in folder.iterdir():self.assertEqual(p.stat().st_mode&0o777,0o400)
        self.assertEqual(self.freeze(),result)
        self.input.unlink();self.control.unlink();self.dataset_root.rename(self.work/'gone-datasets')
        self.assertEqual(verify_gold(result['gold_ref'],self.root),result)
        self.assertNotIn('PRIVATE_',json.dumps(result));self.assertNotIn(str(self.work),json.dumps(result))

    def test_same_version_different_bytes_conflict_and_new_version_is_separate(self):
        first=self.freeze();folder=self.root/first['gold_ref'];before={p.name:p.read_bytes() for p in folder.iterdir()}
        self.control.write_bytes(self.control.read_bytes()+b'\n')
        with self.assertRaises(ExtractionError) as caught:self.freeze()
        self.assertEqual(caught.exception.code,'GOLD_CONFLICT')
        self.assertEqual(before,{p.name:p.read_bytes() for p in folder.iterdir()})
        self.value['gold_version']='../../PRIVATE_NEW';self.control.write_text(json.dumps(self.value))
        second=self.freeze();self.assertNotEqual(second['gold_ref'],first['gold_ref'])
        self.assertNotIn('PRIVATE_',json.dumps(second))

    def test_concurrent_same_and_conflicting_input_have_complete_winner(self):
        with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:self.freeze(),range(6)))
        self.assertTrue(all(r==results[0] for r in results))
        self.assertEqual(len(list(self.root.iterdir())),1)
        self.root=self.work/'conflict-root'
        other=self.work/'other';other.write_bytes(self.control.read_bytes()+b'\n')
        def execute(path):
            try:return freeze_gold(path,self.root,self.dataset_root)
            except ExtractionError as e:return e.code
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,[self.control,other]))
        self.assertEqual(sum(type(r) is dict for r in results),1);self.assertIn('GOLD_CONFLICT',results)
        winner=next(r for r in results if type(r) is dict)
        self.assertEqual(verify_gold(winner['gold_ref'],self.root),winner)

    def test_future_review_cannot_be_frozen(self):
        self.value['authorship']['reviewed_at']='9999-01-01T00:00:00Z';self.control.write_text(json.dumps(self.value))
        with self.assertRaises(ExtractionError):self.freeze()
        self.assertFalse(self.root.exists())

    def test_expanded_permissions_and_tampered_inputs_are_rejected(self):
        result=self.freeze();folder=self.root/result['gold_ref'];path=folder/f"input-{self.source['document_version_id']}.json"
        for target,expanded,original in ((folder,0o555,0o500),(path,0o444,0o400)):
            target.chmod(expanded)
            with self.assertRaises(ExtractionError):verify_gold(result['gold_ref'],self.root)
            target.chmod(original)
        path.chmod(0o600);path.write_bytes(path.read_bytes()+b'\n');path.chmod(0o400)
        with self.assertRaises(ExtractionError):verify_gold(result['gold_ref'],self.root)

    def test_extra_missing_and_symlink_artifacts_are_rejected(self):
        result=self.freeze();folder=self.root/result['gold_ref'];extra=folder/'extra'
        folder.chmod(0o700);extra.write_text('PRIVATE');folder.chmod(0o500)
        with self.assertRaises(ExtractionError):verify_gold(result['gold_ref'],self.root)
        folder.chmod(0o700);extra.unlink();(folder/'gold.json').unlink();folder.chmod(0o500)
        with self.assertRaises(ExtractionError):verify_gold(result['gold_ref'],self.root)
        folder.chmod(0o700);(folder/'gold.json').symlink_to(self.control);folder.chmod(0o500)
        with self.assertRaises(ExtractionError):verify_gold(result['gold_ref'],self.root)

    def test_existing_incomplete_or_empty_destination_is_not_replaced(self):
        ref=self.check()['gold_ref'];folder=self.root/ref;folder.mkdir(parents=True)
        with self.assertRaises(ExtractionError):self.freeze()
        self.assertEqual(list(folder.iterdir()),[])

    def test_install_failure_cleans_only_owned_staging(self):
        self.root.mkdir();sentinel=self.root/'operator-note';sentinel.write_text('KEEP')
        with patch('processing.evaluation.gold_storage._rename_exclusive',side_effect=PermissionError(errno.EACCES,'PRIVATE')):
            with self.assertRaises(OSError):self.freeze()
        self.assertEqual([p.name for p in self.root.iterdir()],['operator-note'])
        self.assertEqual(sentinel.read_text(),'KEEP')

    def test_corrupt_staging_never_becomes_a_final_gold_version(self):
        from processing.evaluation.gold_storage import _write
        def corrupt(path,content):
            _write(path,content)
            if path.name=='gold.json':path.write_bytes(content+b'\n')
        with patch('processing.evaluation.gold_storage._write',side_effect=corrupt):
            with self.assertRaises(ExtractionError):self.freeze()
        self.assertEqual(list(self.root.iterdir()),[])

    def test_cli_check_freeze_verify_and_safe_error_exits(self):
        check=self.cli('check-gold','--input',str(self.control),'--dataset-root',str(self.dataset_root))
        self.assertEqual(check.returncode,0,check.stderr)
        result=self.cli('freeze-gold','--input',str(self.control),'--dataset-root',str(self.dataset_root),'--root',str(self.root))
        self.assertEqual(result.returncode,0,result.stderr)
        ref=json.loads(result.stdout)['gold_ref']
        verified=self.cli('verify-gold',ref,'--root',str(self.root))
        self.assertEqual(verified.returncode,0,verified.stderr)
        for response in (check,result,verified):
            self.assertEqual(len(response.stdout.splitlines()),1);self.assertEqual(response.stderr,b'')
            self.assertNotIn(b'PRIVATE_',response.stdout)
        path=self.root/ref/'gold.json';path.chmod(0o600)
        bad=self.cli('verify-gold',ref,'--root',str(self.root))
        self.assertEqual((bad.returncode,bad.stdout,bad.stderr),(3,b'',b'GOLD_INTEGRITY\n'))
        missing=self.cli('check-gold','--input',str(self.work/'PRIVATE_MISSING'))
        self.assertEqual((missing.returncode,missing.stdout,missing.stderr),(5,b'',b'DATASET_IO_FAILED\n'))
        self.value['authorship']['cross_reviewed']=False;self.control.write_text(json.dumps(self.value))
        invalid=self.cli('check-gold','--input',str(self.control),'--dataset-root',str(self.dataset_root))
        self.assertEqual(invalid.returncode,2);self.assertEqual(invalid.stdout,b'')
        self.assertNotIn(b'PRIVATE_',invalid.stderr)
