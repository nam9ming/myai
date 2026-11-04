import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from processing.extraction import archive
from processing.extraction.api import run_api
from processing.extraction.validation import ExtractionError
from processing.tests.test_extraction_api import response

REPO = Path(__file__).resolve().parents[2]
RUN = '24000000-0000-4000-8000-000000000001'


class ChunkedApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.cleanup)
        self.work = Path(self.temp.name).resolve()
        self.root = self.work / 'runs'
        self.input = self.work / 'input.json'
        self.document = json.loads((REPO / 'contracts/examples/ai-input.json').read_text())
        self.document['blocks'] = [dict(block_id=f'b{i}', page=None, text='A' * 40000) for i in range(4)]
        self.input.write_bytes(archive._json(self.document))
        self.key = patch.dict(os.environ, OPENAI_API_KEY='SYNTHETIC_CHUNK_KEY', OPENAI_MODEL='gpt-6.1-sol')
        self.key.start(); self.addCleanup(self.key.stop)

    def cleanup(self):
        if self.root.exists():
            for current, directories, _ in os.walk(self.root):
                Path(current).chmod(0o700)
                for name in directories:
                    (Path(current) / name).chmod(0o700)
        self.temp.cleanup()

    def success(self, request, key):
        self.assertEqual(key, 'SYNTHETIC_CHUNK_KEY')
        body = json.loads(request)
        prompt = json.loads(body['input'])
        self.assertEqual(prompt['prompt_version'], 'prompt-v3')
        self.assertLessEqual(len(request), 131072)
        output = dict(schema_version='extract-schema-v1', document_version_id=self.document['document_version_id'],
                      items=[], evidence=[], warnings=['NO_EVENT_FOUND', 'CHUNK_CONTEXT_PARTIAL'])
        return 200, response(json.dumps(output)), None, True

    def run_chunked(self, exchange=None):
        with patch('processing.extraction.api._exchange', side_effect=exchange or self.success) as network, patch('processing.extraction.api.time.sleep'):
            result = run_api(self.input, 'fixture-nfc-v1', self.root, RUN, model='gpt-6.1-sol')
        return result, network

    def test_large_input_calls_each_chunk_and_verifies_freezes_and_reuses_without_key(self):
        original = self.input.read_bytes()
        receipt, network = self.run_chunked()
        self.assertEqual(receipt['format_version'], 'extraction-archive-v2')
        self.assertEqual(receipt['status'], 'validated')
        folder = self.root / RUN
        plan = json.loads((folder / 'chunk-plan.json').read_bytes())
        self.assertGreaterEqual(len(plan['chunks']), 2)
        self.assertEqual(network.call_count, len(plan['chunks']))
        self.assertEqual(receipt['total_calls'], network.call_count)
        self.assertEqual(len(receipt['attempts']), 1)
        metadata = json.loads((folder / 'metadata.json').read_bytes())
        self.assertEqual((metadata['attempts'], metadata['prompt_version']), (1, 'prompt-v3'))
        self.assertEqual((metadata['usage_in'], metadata['usage_out']), (17 * network.call_count, 31 * network.call_count))
        self.assertEqual(receipt['chunk_plan_sha256'], hashlib.sha256((folder / 'chunk-plan.json').read_bytes()).hexdigest())
        combined = json.loads((folder / 'attempt-1.output').read_bytes())
        self.assertEqual(combined['items'], [])
        self.assertIn('NO_EVENT_FOUND', combined['warnings'])
        self.assertIn('CHUNK_RELATIONS_REQUIRE_REVIEW', combined['warnings'])
        self.assertEqual(original, self.input.read_bytes())
        self.assertEqual(receipt, archive.verify_run(RUN, self.root))
        frozen = archive.freeze_run(RUN, self.root)
        self.assertEqual(receipt, frozen['receipt'])
        with patch.dict(os.environ, {}, clear=True), patch('processing.extraction.api._exchange') as network:
            reused = run_api(self.input, 'fixture-nfc-v1', self.root, RUN, model='gpt-6.1-sol')
        self.assertEqual(reused, receipt); network.assert_not_called()
        sealed = self.root / frozen['snapshot_ref']
        before = {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in sealed.iterdir()}
        self.assertEqual(archive.verify_sealed_run(RUN, sealed.parent)['receipt'], receipt)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in sealed.iterdir()})

    def test_schema_failure_retries_whole_cycle_and_keeps_actual_call_count(self):
        calls = []
        def exchange(request, key):
            calls.append(request)
            return (200, response('{'), None, True) if len(calls) == 1 else self.success(request, key)
        receipt, network = self.run_chunked(exchange)
        count = len(json.loads((self.root / RUN / 'chunk-plan.json').read_bytes())['chunks'])
        self.assertEqual([a['status'] for a in receipt['attempts']], ['failed', 'validated'])
        self.assertEqual(receipt['total_calls'], network.call_count)
        self.assertEqual(network.call_count, 2 * count)
        self.assertEqual((self.root / RUN / 'attempt-1.output').read_bytes(), b'')
        self.assertEqual(archive.verify_run(RUN, self.root), receipt)

    def test_permanent_failure_preserves_unattempted_chunks_and_never_returns_empty_success(self):
        receipt, network = self.run_chunked(lambda request, key: (401, b'', None, True))
        self.assertEqual((receipt['status'], receipt['total_calls'], network.call_count), ('failed', 1, 1))
        chunks = receipt['attempts'][0]['chunks']
        self.assertTrue(chunks[0]['attempted'])
        self.assertTrue(all(c['status'] == 'not_attempted' and not c['attempted'] for c in chunks[1:]))
        self.assertEqual((self.root / RUN / 'attempt-1.output').read_bytes(), b'')
        self.assertEqual(archive.verify_run(RUN, self.root), receipt)

    def test_oversized_single_block_creates_failed_archive_without_http_calls(self):
        self.document['blocks'] = [dict(block_id='huge', page=None, text='A' * 180000)]
        self.input.write_bytes(archive._json(self.document))
        receipt, network = self.run_chunked()
        network.assert_not_called()
        self.assertEqual((receipt['status'], receipt['total_calls']), ('failed', 0))
        self.assertEqual(receipt['attempts'][0]['error_code'], 'CHUNK_REQUEST_LIMIT')
        self.assertEqual(archive.verify_run(RUN, self.root), receipt)

    def test_chunked_automatic_result_requires_human_review_before_direct_draft(self):
        from processing.extraction.draft import draft_run
        self.run_chunked()
        source = json.loads((REPO / 'backend/examples/source-import.json').read_text())
        doc = source['documents'][0]
        doc.update(document_version_id=self.document['document_version_id'], title=self.document['title'],
                   published_date=self.document['published_date'], block_index=self.document['blocks'],
                   preprocessing_version='fixture-nfc-v1')
        doc['cleaned_text'] = '\n'.join(b['text'] for b in self.document['blocks'])
        doc['text_sha256'] = hashlib.sha256(doc['cleaned_text'].encode()).hexdigest()
        path = self.work / 'source.json'; path.write_bytes(archive._json(source))
        target = self.work / 'private/draft.json'
        with self.assertRaises(ExtractionError) as failure:
            draft_run(RUN, path, target, '10000000-0000-4000-8000-000000000005',
                      '10000000-0000-4000-8000-000000000006', 'fixture-dictionary-v1', self.root)
        self.assertEqual(failure.exception.code, 'CHUNK_DRAFT_REVIEW_REQUIRED')
        self.assertFalse(target.exists())

    def test_cli_verifies_successful_and_failed_v2_receipts_without_key(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                self.root = self.work / ('failed-cli' if failed else 'succeeded-cli')
                receipt, _ = self.run_chunked((lambda request, key: (401, b'', None, True)) if failed else None)
                env = {key: value for key, value in os.environ.items() if not key.upper().startswith('OPENAI_')}
                process = subprocess.run([sys.executable, '-B', '-m', 'processing.extraction', 'verify', RUN,
                    '--root', str(self.root)], cwd=REPO, env=env, capture_output=True, timeout=15)
                self.assertEqual(process.returncode, 4 if failed else 0)
                self.assertEqual(json.loads(process.stdout), receipt)
                self.assertEqual(process.stderr, b'')
                self.assertNotIn(str(self.work).encode(), process.stdout)
                self.assertNotIn(b'SYNTHETIC_CHUNK_KEY', process.stdout)

    def test_combined_output_limit_preserves_all_wire_outputs_as_failed_document(self):
        def exchange(request, key):
            chunk = json.loads(json.loads(request)['input'])['chunk']['chunk_id']
            output = dict(schema_version='extract-schema-v1', document_version_id=self.document['document_version_id'],
                          items=[], evidence=[], warnings=['NO_EVENT_FOUND', 'CHUNK_CONTEXT_PARTIAL', chunk + 'X' * 4300000])
            return 200, response(json.dumps(output)), None, True
        receipt, network = self.run_chunked(exchange)
        self.assertGreaterEqual(network.call_count, 2)
        self.assertEqual(receipt['total_calls'], network.call_count)
        self.assertEqual((receipt['status'], len(receipt['attempts'])), ('failed', 1))
        cycle = receipt['attempts'][0]
        self.assertEqual((cycle['error_code'], cycle['failure_kind'], cycle['retryable']), ('CHUNK_OUTPUT_LIMIT', 'review', False))
        self.assertTrue(all(c['status'] == 'validated' for c in cycle['chunks']))
        self.assertEqual((self.root / RUN / 'attempt-1.output').read_bytes(), b'')
        for chunk in cycle['chunks']:
            prefix = f"attempt-1-{chunk['chunk_id']}"
            self.assertGreater((self.root / RUN / (prefix + '.output')).stat().st_size, 4300000)
            self.assertGreater((self.root / RUN / (prefix + '.response')).stat().st_size, 4300000)
        self.assertEqual(archive.verify_run(RUN, self.root), receipt)

    def test_large_derived_plan_preserves_valid_input_and_failed_wire_attempt(self):
        self.document['blocks'] = [dict(block_id=str(i) + 'A' * 4400, page=None, text='x') for i in range(1800)]
        original = archive._json(self.document)
        self.assertLess(len(original), 8 * 1024 * 1024)
        self.input.write_bytes(original)
        receipt, network = self.run_chunked(lambda request, key: (401, b'{}', None, True))
        self.assertEqual((receipt['status'], receipt['total_calls'], network.call_count), ('failed', 1, 1))
        plan = self.root / RUN / 'chunk-plan.json'
        self.assertGreater(plan.stat().st_size, 8 * 1024 * 1024)
        self.assertEqual((self.root / RUN / 'input.json').read_bytes(), original)
        self.assertEqual(receipt['chunk_plan_sha256'], hashlib.sha256(plan.read_bytes()).hexdigest())
        self.assertEqual(archive.verify_run(RUN, self.root), receipt)
        self.assertEqual(archive.freeze_run(RUN, self.root)['receipt'], receipt)


if __name__ == '__main__':
    unittest.main()
