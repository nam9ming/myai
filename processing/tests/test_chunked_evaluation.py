import copy
import hashlib
import json
import os
from contextlib import nullcontext
from datetime import datetime
from unittest.mock import patch

from processing.evaluation.storage import freeze_dataset
from processing.extraction.api import run_api
from processing.extraction.archive import freeze_run
from processing.tests.test_dataset import uid
from processing.tests.test_evaluation_records import DatasetClock, EvaluationFixture
from processing.tests.test_extraction_api import KEY, response


class ChunkedEvaluationTest(EvaluationFixture):
    def prepare_chunked(self, *, retry=False, failed=False, large_receipt=False):
        if large_receipt:
            self.source['title'] = 'T' * 131072
            self.source['blocks'].extend(dict(block_id=f'long-{i}', page=None, text='x')
                                         for i in range(51000 - len(self.source['blocks'])))
        else:
            self.source['blocks'].extend(dict(block_id=f'long-{i}', page=None, text='x' * 48000) for i in range(3))
        self.input.write_text(json.dumps(self.source))
        self.manifest['dataset_version'] = 'synthetic-chunk-evaluation-v1'
        self.manifest['documents'][0]['versions'][0]['input_sha256'] = hashlib.sha256(self.input.read_bytes()).hexdigest()
        manifest = self.work / 'chunk-manifest.json'; manifest.write_text(json.dumps(self.manifest))
        with patch('processing.extraction.archive.datetime', DatasetClock):
            dataset = freeze_dataset(manifest, self.dataset_root)
        self.value.update(gold_version='synthetic-chunk-gold-v1', dataset_ref=dataset['dataset_ref'],
                          manifest_sha256=dataset['manifest_sha256'])
        self.gold_receipt = self.make_gold()
        self.control.update(gold_ref=self.gold_receipt['gold_ref'], gold_receipt_sha256=self.gold_receipt_hash())
        calls = []
        def partial(value):
            if isinstance(value, dict):
                if value.get('knowledge') == 'not_stated':
                    value.update(knowledge='ambiguous', reason='partial synthetic context')
                for child in value.values(): partial(child)
            elif isinstance(value, list):
                for child in value: partial(child)
        def exchange(request, key):
            calls.append(request)
            if failed: return 401, b'{}', None, True
            if retry and len(calls) == 1: return 200, response('{'), None, True
            chunk = json.loads(json.loads(request)['input'])['chunk']
            if chunk['core_start'] == 0:
                output = copy.deepcopy(self.good_output); partial(output)
                output['warnings'].append('CHUNK_CONTEXT_PARTIAL')
            else:
                output = dict(schema_version='extract-schema-v1', document_version_id=self.source['document_version_id'],
                              items=[], evidence=[], warnings=['CHUNK_CONTEXT_PARTIAL', 'NO_EVENT_FOUND'])
            return 200, response(json.dumps(output)), None, True
        at = '2020-01-01T03:00:00Z'
        class RunClock(datetime):
            @classmethod
            def now(cls, tz=None): return datetime.fromisoformat(at)
        run_id = uid(502)
        planner = nullcontext()
        if large_receipt:
            from processing.extraction.chunk_archive import plan_chunks
            plan = plan_chunks(self.source, 'gpt-6.1-sol', hashlib.sha256(self.input.read_bytes()).hexdigest())
            planner = patch('processing.extraction.chunk_archive.plan_chunks', return_value=plan)
        with patch.dict(os.environ, OPENAI_API_KEY=KEY), patch('processing.extraction.api._exchange', side_effect=exchange), \
                patch('processing.extraction.api._now', return_value=at), patch('processing.extraction.api.time.sleep'), \
                patch('processing.extraction.archive.datetime', RunClock), planner:
            receipt = run_api(self.input, 'fixture-nfc-v1', self.run_root, run_id, model='gpt-6.1-sol')
            frozen = freeze_run(run_id, self.run_root)
        folder = self.run_root / frozen['snapshot_ref']
        self.control['documents'][0].update(run_id=run_id, snapshot_ref=frozen['snapshot_ref'],
            receipt_sha256=hashlib.sha256((folder / 'receipt.json').read_bytes()).hexdigest())
        self.control['policy'].update(prompt_version='prompt-v2-or-v3', retry_policy_version='api-document-cycle-v1')
        empty = dict(schema_version='score-links-v1', item_links=[], generation_reviews=[])
        annotation = copy.deepcopy(empty)
        if receipt['status'] == 'validated':
            final = json.loads((folder / f"attempt-{len(receipt['attempts'])}.output").read_bytes())
            gold, item = self.good_output['items'][0], final['items'][0]
            annotation['item_links'] = [dict(slot_id=gold['local_item_id'], local_item_id=item['local_item_id'], kind='match',
                occurrence_links=[dict(gold_occurrence_id=g['local_occurrence_id'], local_occurrence_id=a['local_occurrence_id'])
                    for g, a in zip(gold['occurrences'], item['occurrences'], strict=True)])]
        self.control['documents'][0].update(first_annotation=empty if retry or failed else copy.deepcopy(annotation),
                                            final_annotation=annotation)
        return receipt

    def test_new_policy_accepts_existing_small_v1_run(self):
        self.control['policy'].update(prompt_version='prompt-v2-or-v3', retry_policy_version='api-document-cycle-v1')
        self.assertEqual(self.evaluate()['result']['summary']['views']['final_auto']['correct_fields'], 8)

    def test_chunked_first_failed_cycle_and_final_whole_document_are_scored(self):
        receipt = self.prepare_chunked(retry=True)
        self.assertGreater(receipt['total_calls'], len(receipt['attempts']))
        views = self.evaluate()['result']['summary']['views']
        self.assertEqual((views['first_raw']['correct_fields'], views['first_raw']['known_fields'], views['first_raw']['document_failures']), (0, 8, 1))
        self.assertEqual((views['final_auto']['correct_fields'], views['final_auto']['known_fields'], views['final_auto']['document_failures']), (8, 8, 0))

    def test_permanent_chunk_failure_stays_in_whole_document_denominator(self):
        self.prepare_chunked(failed=True)
        final = self.evaluate()['result']['summary']['views']['final_auto']
        self.assertEqual((final['correct_fields'], final['known_fields'], final['document_failures']), (0, 8, 1))

    def test_legacy_policy_does_not_accept_chunked_receipt(self):
        self.prepare_chunked()
        self.control['policy'].update(prompt_version='prompt-v3', retry_policy_version='api-structure-retry-v1')
        self.invalid_record(self.control, 'EVALUATION_POLICY_MISMATCH')

    def test_large_failed_receipt_preserves_bindings_and_evaluation_denominators(self):
        from processing.evaluation.bindings import check_bindings
        receipt = self.prepare_chunked(large_receipt=True)
        selected = self.control['documents'][0]
        folder = self.run_root / selected['snapshot_ref']
        self.assertGreater((folder / 'receipt.json').stat().st_size, 8 * 1024 * 1024)
        self.assertEqual((receipt['status'], receipt['total_calls']), ('failed', 0))
        plan = json.loads((folder / 'chunk-plan.json').read_bytes())
        binding = dict(schema_version='dataset-bindings-v1', dataset_ref=self.value['dataset_ref'],
            manifest_sha256=self.value['manifest_sha256'], bindings=[dict(
                document_version_id=self.source['document_version_id'], input_path=str(self.input),
                runs=[{key: selected[key] for key in ('run_id', 'snapshot_ref', 'receipt_sha256')}])])
        with patch('processing.extraction.chunk_archive.plan_chunks', return_value=plan):
            self.assertEqual(check_bindings(json.dumps(binding).encode(), self.dataset_root, self.run_root)
                             ['counts']['failed_runs'], 1)
            final = self.evaluate()['result']['summary']['views']['final_auto']
        self.assertEqual((final['correct_fields'], final['known_fields'], final['document_failures']), (0, 8, 1))
