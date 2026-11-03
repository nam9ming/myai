import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from processing.evaluation import bindings
from processing.evaluation.storage import freeze_dataset, verify_dataset
from processing.extraction.archive import freeze_run, import_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import manifest, uid
from processing.tests.test_extraction_prompt_metadata import ROOT, metadata


class DatasetBindingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.dataset_root, self.run_root = self.work/'datasets', self.work/'runs'
        self.input = self.work/'PRIVATE_SOURCE.json'
        self.input.write_bytes((ROOT/'contracts/examples/ai-input.json').read_bytes())
        self.version = metadata()['document_version_id']
        self.value = manifest()
        self.value['documents'] = self.value['documents'][:1]
        self.value['documents'][0]['versions'] = [dict(document_version_id=self.version,
            input_sha256=hashlib.sha256(self.input.read_bytes()).hexdigest())]
        self.value['events'] = []; self.value['relations'] = []
        self.value['split_assignments'] = self.value['split_assignments'][:1]
        self.first = self.make_run(uid(90), failed=True)
        self.last = self.make_run(uid(91))
        self.packet = dict(schema_version='dataset-bindings-v1', dataset_ref='', manifest_sha256='',
                           bindings=[dict(document_version_id=self.version, input_path=str(self.input),
                                          runs=[self.first, self.last])])
        self.dataset()

    def cleanup(self):
        for current, _, _ in os.walk(self.work): Path(current).chmod(0o700)
        self.temp.cleanup()

    def dataset(self):
        p = self.work/'manifest.json'; p.write_text(json.dumps(self.value))
        receipt = freeze_dataset(p, self.dataset_root)
        self.packet.update(dataset_ref=receipt['dataset_ref'], manifest_sha256=receipt['manifest_sha256'])

    def make_run(self, run_id, failed=False, version=None, retry=False):
        version = version or self.version
        meta = metadata(); meta.update(run_id=run_id, document_version_id=version, attempts=2 if retry else 1)
        p = self.work/'metadata.json'; p.write_text(json.dumps(meta))
        prompt = self.work/'prompt'; prompt.write_bytes(b'PRIVATE_PROMPT')
        output = self.work/'output'
        raw = json.loads((ROOT/'contracts/examples/ai-extraction.json').read_bytes())
        raw['document_version_id'] = version
        output.write_bytes(b'PRIVATE_BAD_OUTPUT' if failed else json.dumps(raw).encode())
        pairs = [(prompt, output)]
        if retry:
            bad = self.work/'bad'; bad.write_bytes(b'PRIVATE_BAD_OUTPUT')
            pairs.insert(0, (prompt, bad))
        import_run(self.input, p, pairs, self.run_root)
        frozen = freeze_run(run_id, self.run_root)
        path = self.run_root/frozen['snapshot_ref']/'receipt.json'
        return dict(run_id=run_id, snapshot_ref=frozen['snapshot_ref'],
                    receipt_sha256=hashlib.sha256(path.read_bytes()).hexdigest())

    def check(self, packet=None):
        return bindings.check_bindings(json.dumps(packet or self.packet).encode(), self.dataset_root, self.run_root)

    def invalid(self, packet, code=None):
        with self.assertRaises(ExtractionError) as caught: self.check(packet)
        if code: self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_', str(caught.exception))

    def test_binds_all_inputs_and_retains_failed_runs_without_writes(self):
        before = {str(p): (p.read_bytes(), p.stat().st_mode) for root in (self.dataset_root,self.run_root)
                  for p in root.rglob('*') if p.is_file()}
        result = self.check()
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['counts'], dict(documents=1, document_versions=1, runs=2,
                                               validated_runs=1, failed_runs=1))
        self.assertEqual([r['status'] for r in result['runs']], ['failed','validated'])
        self.assertEqual([r['first_status'] for r in result['runs']], ['failed','validated'])
        self.assertEqual(result['bindings_sha256'], hashlib.sha256(json.dumps(self.packet).encode()).hexdigest())
        for private in ('PRIVATE_', str(self.work), 'prompt-v1', 'example.org'):
            self.assertNotIn(private, json.dumps(result))
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mode) for root in (self.dataset_root,self.run_root)
                                for p in root.rglob('*') if p.is_file()})

    def test_original_input_bytes_must_match_manifest_and_run(self):
        self.input.write_bytes(self.input.read_bytes()+b'\n')
        self.invalid(self.packet, 'BINDING_SOURCE_MISMATCH')

    def test_manifest_hash_is_pinned(self):
        p = copy.deepcopy(self.packet); p['manifest_sha256'] = '0'*64
        self.invalid(p, 'BINDING_DATASET_MISMATCH')

    def test_run_must_match_current_input_even_when_manifest_matches(self):
        self.input.write_bytes(self.input.read_bytes()+b'\n')
        self.value['dataset_version'] = 'different-input-bytes'
        self.value['documents'][0]['versions'][0]['input_sha256'] = hashlib.sha256(self.input.read_bytes()).hexdigest()
        self.dataset()
        self.invalid(self.packet, 'BINDING_SOURCE_MISMATCH')

    def test_data_kind_and_actual_version_id_must_match(self):
        for mode in ('kind','version'):
            with self.subTest(mode=mode):
                packet = copy.deepcopy(self.packet)
                self.value['dataset_version'] = mode
                if mode == 'kind': self.value['data_kind'] = 'real'
                else:
                    self.value['data_kind'] = 'synthetic'
                    self.value['documents'][0]['versions'][0]['document_version_id'] = uid(99)
                    packet['bindings'][0]['document_version_id'] = uid(99)
                self.dataset()
                packet.update(dataset_ref=self.packet['dataset_ref'],manifest_sha256=self.packet['manifest_sha256'])
                self.invalid(packet, 'BINDING_SOURCE_MISMATCH')

    def test_missing_duplicate_and_unknown_versions_are_rejected(self):
        for mode in ('missing','duplicate','unknown'):
            p = copy.deepcopy(self.packet)
            if mode == 'missing': p['bindings'] = []
            elif mode == 'duplicate': p['bindings'].append(copy.deepcopy(p['bindings'][0]))
            else: p['bindings'][0]['document_version_id'] = uid(99)
            with self.subTest(mode=mode): self.invalid(p)

    def test_run_ids_cannot_be_counted_twice(self):
        p = copy.deepcopy(self.packet); p['bindings'][0]['runs'].append(copy.deepcopy(self.first))
        self.invalid(p)

    def test_no_run_and_wrong_receipt_are_rejected(self):
        for mode in ('empty','hash'):
            p = copy.deepcopy(self.packet)
            if mode == 'empty': p['bindings'][0]['runs'] = []
            else: p['bindings'][0]['runs'][0]['receipt_sha256'] = '0'*64
            with self.subTest(mode=mode): self.invalid(p)

    def test_snapshot_reference_cannot_escape_or_name_another_run(self):
        for ref in ('../'+self.first['snapshot_ref'], '/'+self.first['snapshot_ref'],
                    'registered/../'+self.first['run_id'], self.last['snapshot_ref'],
                    self.first['snapshot_ref']+'/extra'):
            p = copy.deepcopy(self.packet); p['bindings'][0]['runs'][0]['snapshot_ref'] = ref
            with self.subTest(ref=ref): self.invalid(p)

    def test_mutable_or_permission_expanded_run_is_rejected(self):
        p = copy.deepcopy(self.packet); p['bindings'][0]['runs'][0]['snapshot_ref'] = self.first['run_id']
        self.invalid(p, 'BINDING_REQUIRES_FROZEN')
        folder = self.run_root/self.first['snapshot_ref']
        for path, mode, restore in ((folder,0o555,0o500), (folder/'receipt.json',0o444,0o400)):
            path.chmod(mode)
            with self.subTest(path=path): self.invalid(self.packet, 'BINDING_REQUIRES_FROZEN')
            path.chmod(restore)
        self.assertEqual(self.check()['counts']['runs'], 2)

    def test_tampered_failed_output_is_still_rejected(self):
        path = self.run_root/self.first['snapshot_ref']/'attempt-1.output'
        path.chmod(0o600); path.write_bytes(b'PRIVATE_CHANGED'); path.chmod(0o400)
        self.invalid(self.packet, 'ARCHIVE_INTEGRITY')

    def test_input_symlink_and_snapshot_parent_symlink_are_rejected(self):
        link = self.work/'link'; link.symlink_to(self.input)
        p = copy.deepcopy(self.packet); p['bindings'][0]['input_path'] = str(link)
        with self.assertRaises((ExtractionError,OSError)): self.check(p)
        registered = self.run_root/'registered'; other = self.run_root/'elsewhere'
        registered.rename(other); registered.symlink_to(other, target_is_directory=True)
        with self.assertRaises((ExtractionError,OSError)): self.check()

    def test_changed_manifest_after_verification_is_rejected(self):
        path = self.dataset_root/self.packet['dataset_ref']/'manifest.json'
        def changed(ref, root):
            result = verify_dataset(ref, root)
            path.chmod(0o600); path.write_bytes(path.read_bytes()+b'\n'); path.chmod(0o400)
            return result
        with patch('processing.evaluation.bindings.verify_dataset', side_effect=changed):
            self.invalid(self.packet, 'BINDING_DATASET_MISMATCH')

    def test_retry_preserves_first_failure_and_final_status(self):
        selected = self.make_run(uid(92), retry=True)
        self.packet['bindings'][0]['runs'] = [selected]
        result = self.check()['runs'][0]
        self.assertEqual((result['attempt_count'],result['first_status'],result['status']), (2,'failed','validated'))
        self.assertEqual(result['execution_mode'], 'manual_import')

    def test_multiple_versions_do_not_increase_document_count(self):
        original = self.input
        self.input = self.work/'second-input.json'
        data = json.loads(original.read_bytes()); data['document_version_id'] = uid(98)
        self.input.write_text(json.dumps(data))
        run = self.make_run(uid(93), version=uid(98))
        self.value['documents'][0]['versions'].append(dict(document_version_id=uid(98),
            input_sha256=hashlib.sha256(self.input.read_bytes()).hexdigest()))
        self.value['dataset_version'] = 'two-versions'
        self.dataset()
        self.packet['bindings'].append(dict(document_version_id=uid(98),input_path=str(self.input),runs=[run]))
        self.assertEqual(self.check()['counts'], dict(documents=1,document_versions=2,runs=3,
                                                     validated_runs=2,failed_runs=1))

    def test_json_duplicates_and_extra_keys_are_rejected(self):
        p = copy.deepcopy(self.packet); p['PRIVATE_EXTRA'] = 'PRIVATE_VALUE'; self.invalid(p)
        content = json.dumps(self.packet).replace('"schema_version":', '"schema_version":"duplicate","schema_version":')
        with self.assertRaises(ExtractionError): bindings.check_bindings(content.encode(),self.dataset_root,self.run_root)
