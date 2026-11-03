from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from processing.extraction.archive import import_run, freeze_run, verify_run
from processing.extraction.validation import ExtractionError, MAX_BYTES

REPO = Path(__file__).resolve().parents[2]
RUN = '20000000-0000-4000-8000-000000000001'
KEY = 'TEST_ONLY_OPENAI_KEY'


def response(output=None, **changes):
    value = dict(id='resp_synthetic', object='response', created_at=1793664000,
                 status='completed', error=None, incomplete_details=None, model='gpt-6.1-sol',
                 output=[dict(id='msg_synthetic', type='message', status='completed', role='assistant',
                              content=[dict(type='output_text', text=output if output is not None else
                                            (REPO / 'contracts/examples/ai-extraction.json').read_text(),
                                            annotations=[], logprobs=[])])],
                 usage=dict(input_tokens=17, output_tokens=31, total_tokens=48,
                            input_tokens_details=dict(cached_tokens=0),
                            output_tokens_details=dict(reasoning_tokens=0)))
    value.update(changes)
    return json.dumps(value, ensure_ascii=False).encode()


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name).resolve()
        self.root = self.work / 'archive'
        self.input = self.work / 'input.json'
        self.input.write_bytes((REPO / 'contracts/examples/ai-input.json').read_bytes())
        self.env = patch.dict(os.environ, OPENAI_API_KEY=KEY, OPENAI_MODEL='gpt-6.1-sol')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        if self.root.exists():
            for current, dirs, files in os.walk(self.root):
                Path(current).chmod(0o700)
                for name in dirs:
                    (Path(current) / name).chmod(0o700)
        self.temp.cleanup()

    def run_api(self, replies, **kwargs):
        from processing.extraction.api import run_api
        with patch('processing.extraction.api._exchange', side_effect=replies) as network:
            result = run_api(self.input, 'fixture-nfc-v1', self.root, RUN, **kwargs)
        return result, network.call_count

    def test_cli_run_requires_key_without_echoing_any_path(self):
        env = os.environ.copy(); env.pop('OPENAI_API_KEY', None)
        result = subprocess.run([sys.executable, '-m', 'processing.extraction', 'run', '--input', str(self.input),
                                 '--preprocessing-version', 'fixture-nfc-v1', '--root', str(self.root)],
                                cwd=REPO, env=env, capture_output=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b'')
        self.assertEqual(result.stderr, b'OPENAI_API_KEY_MISSING\n')
        self.assertFalse(self.root.exists())

    def test_success_preserves_wire_bytes_and_measured_metadata_then_freezes(self):
        raw = response()
        result, calls = self.run_api([(200, raw, None, True)])
        self.assertEqual(calls, 1)
        self.assertEqual((result['status'], result['execution_mode']), ('validated', 'api'))
        self.assertTrue(result['review_required'])
        folder = self.root / RUN
        self.assertEqual((folder / 'attempt-1.response').read_bytes(), raw)
        request = json.loads((folder / 'attempt-1.prompt').read_bytes())
        self.assertEqual(request['model'], 'gpt-6.1-sol')
        self.assertIs(request['store'], False)
        self.assertEqual(set(request), {'model', 'input', 'instructions', 'max_output_tokens', 'store'})
        self.assertEqual(json.loads(request['input'])['source']['blocks'], json.loads(self.input.read_bytes())['blocks'])
        self.assertNotIn('data_kind', json.loads(request['input'])['source'])
        self.assertEqual((folder / 'attempt-1.output').read_bytes(),
                         json.loads(raw)['output'][0]['content'][0]['text'].encode())
        metadata = json.loads((folder / 'metadata.json').read_bytes())
        self.assertEqual((metadata['provider'], metadata['model_label']), ('openai', 'gpt-6.1-sol'))
        self.assertEqual((metadata['usage_in'], metadata['usage_out']), (17, 31))
        self.assertIsNone(metadata['cost']); self.assertIsNone(metadata['model_version'])
        self.assertEqual(result, verify_run(RUN, self.root))
        self.assertEqual(freeze_run(RUN, self.root)['receipt'], result)
        for file in folder.iterdir():
            self.assertNotIn(KEY.encode(), file.read_bytes())
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(str(self.work), json.dumps(result))

    def test_schema_retry_keeps_original_input_and_only_error_path_feedback(self):
        result, calls = self.run_api([(200, response('not json'), None, True), (200, response(), None, True)])
        self.assertEqual((calls, result['status']), (2, 'validated'))
        self.assertEqual([a['failure_kind'] for a in result['attempts']], ['schema', None])
        folder = self.root / RUN
        a, b = [json.loads((folder / f'attempt-{i}.prompt').read_bytes()) for i in (1, 2)]
        self.assertEqual(a['input'], b['input'])
        self.assertNotIn('not json', b['instructions'])
        self.assertIn('$', b['instructions'])
        metadata = json.loads((folder / 'metadata.json').read_bytes())
        self.assertEqual((metadata['usage_in'], metadata['usage_out']), (34, 62))

    def test_schema_failures_stop_after_three_preserved_attempts(self):
        result, calls = self.run_api([(200, response('{}'), None, True)] * 3)
        self.assertEqual((calls, result['status']), (3, 'failed'))
        self.assertEqual(len(result['attempts']), 3)
        self.assertTrue(all(a['retryable'] for a in result['attempts']))
        self.assertEqual(result, verify_run(RUN, self.root))
        self.assertEqual(len(result['artifacts']), 14)

    def test_escaped_surrogate_response_retries_and_finishes_failed_receipt(self):
        for number, (value, code) in enumerate((('\ud800', 'API_RESPONSE_INVALID'),
                                               ('{"bad":"\\ud800"}', 'JSON_INVALID'))):
            self.root = self.work / f'surrogate-{number}'
            packet = json.loads(response())
            packet['output'][0]['content'][0]['text'] = value
            raw = json.dumps(packet).encode()
            result, calls = self.run_api([(200, raw, None, True)] * 3)
            self.assertEqual((calls, result['status']), (3, 'failed'))
            self.assertTrue(all(a['error_code'] == code for a in result['attempts']))
            self.assertEqual(result, verify_run(RUN, self.root))
            self.assertEqual((self.root / RUN / 'attempt-3.response').read_bytes(), raw)

    def test_content_filter_stops_but_token_limit_can_retry(self):
        blocked = response(status='incomplete', incomplete_details=dict(reason='content_filter'))
        result, calls = self.run_api([(200, blocked, None, True)] * 3)
        self.assertEqual((calls, result['status']), (1, 'failed'))
        self.assertEqual(result['attempts'][0]['failure_kind'], 'review')
        self.assertFalse(result['attempts'][0]['retryable'])
        self.root = self.work / 'token-limit'
        limited = response(status='incomplete', incomplete_details=dict(reason='max_output_tokens'))
        result, calls = self.run_api([(200, limited, None, True), (200, response(), None, True)])
        self.assertEqual((calls, result['status']), (2, 'validated'))

    def test_api_retryable_failure_cannot_be_finalized_before_policy_is_exhausted(self):
        self.run_api([(200, response('{}'), None, True)] * 3)
        folder = self.root / RUN
        for count in (1, 2):
            metadata = json.loads((folder / 'metadata.json').read_bytes())
            exchange = json.loads((folder / f'attempt-{count}.exchange').read_bytes())
            metadata.update(attempts=count, finished_at=exchange['finished_at'], usage_in=17 * count, usage_out=31 * count)
            file = self.work / f'partial-{count}.json'; file.write_text(json.dumps(metadata))
            pairs = [(folder / f'attempt-{i}.prompt', folder / f'attempt-{i}.output') for i in range(1, count + 1)]
            extra = [(folder / f'attempt-{i}.response', folder / f'attempt-{i}.exchange') for i in range(1, count + 1)]
            with self.subTest(count=count), self.assertRaises(ExtractionError):
                import_run(folder / 'input.json', file, pairs, self.work / f'partial-root-{count}', extra)

    def test_evidence_failure_is_not_retried_or_repaired(self):
        output = json.loads((REPO / 'contracts/examples/ai-extraction.json').read_bytes())
        output['evidence'][0]['quote'] = 'PRIVATE_BAD_QUOTE'
        result, calls = self.run_api([(200, response(json.dumps(output)), None, True)])
        self.assertEqual((calls, result['status']), (1, 'failed'))
        self.assertEqual(result['attempts'][0]['failure_kind'], 'review')
        self.assertFalse(result['attempts'][0]['retryable'])
        self.assertNotIn('PRIVATE_BAD_QUOTE', json.dumps(result))

    def test_transport_retries_but_authentication_redirect_and_refusal_stop(self):
        for status in (401, 403, 400, 302):
            self.root = self.work / str(status)
            result, calls = self.run_api([(status, b'PRIVATE_PROVIDER_ERROR', None, True)])
            self.assertEqual((calls, result['status']), (1, 'failed'))
            self.assertFalse(result['attempts'][0]['retryable'])
            self.assertNotIn('PRIVATE_PROVIDER_ERROR', json.dumps(result))
        self.root = self.work / 'retry'
        result, calls = self.run_api([(429, b'PRIVATE_LIMIT', None, True), (None, b'', 'API_TIMEOUT', False),
                                      (200, response(), None, True)])
        self.assertEqual((calls, result['status']), (3, 'validated'))
        metadata = json.loads((self.root / RUN / 'metadata.json').read_bytes())
        self.assertIsNone(metadata['usage_in']); self.assertIsNone(metadata['usage_out'])
        self.root = self.work / 'refusal'
        packet = json.loads(response())
        packet['output'] = [dict(type='message', role='assistant', status='completed',
                                 content=[dict(type='refusal', refusal='PRIVATE_REFUSAL')])]
        raw = json.dumps(packet).encode()
        result, calls = self.run_api([(200, raw, None, True)])
        self.assertEqual((calls, result['attempts'][0]['failure_kind']), (1, 'review'))

    def test_transient_retry_is_paced(self):
        start = time.monotonic()
        result, calls = self.run_api([(429, b'limit', None, True), (200, response(), None, True)])
        self.assertEqual((calls, result['status']), (2, 'validated'))
        self.assertGreaterEqual(time.monotonic() - start, 0.9)

    def test_existing_run_reuses_without_key_or_network_and_rejects_mismatch(self):
        from processing.extraction.api import run_api
        result, _ = self.run_api([(200, response(), None, True)])
        with patch.dict(os.environ, {}, clear=True), patch('processing.extraction.api._exchange', side_effect=AssertionError('network')):
            self.assertEqual(run_api(self.input, 'fixture-nfc-v1', self.root, RUN), result)
            with self.assertRaises(ExtractionError):
                run_api(self.input, 'other-preprocessing', self.root, RUN)
            with self.assertRaises(ExtractionError):
                run_api(self.input, 'fixture-nfc-v1', self.root, RUN, 'other-model')

    def test_incomplete_run_is_not_reissued(self):
        from processing.extraction.api import run_api
        (self.root / RUN).mkdir(parents=True)
        with patch('processing.extraction.api._exchange', side_effect=AssertionError('network')):
            with self.assertRaises(ExtractionError):
                run_api(self.input, 'fixture-nfc-v1', self.root, RUN)

    def test_output_and_metadata_cannot_disagree_with_preserved_response(self):
        for changed in ('output', 'metadata', 'prompt'):
            with self.subTest(changed=changed):
                self.root = self.work / changed
                self.run_api([(200, response(), None, True)])
                folder = self.root / RUN
                if changed == 'output':
                    (folder / 'attempt-1.output').write_bytes(b'{}')
                elif changed == 'metadata':
                    path = folder / 'metadata.json'; value = json.loads(path.read_bytes())
                    value['usage_in'] = 999; path.write_bytes(json.dumps(value).encode())
                else:
                    path = folder / 'attempt-1.prompt'; value = json.loads(path.read_bytes())
                    value['store'] = True; path.write_bytes(json.dumps(value).encode())
                with self.assertRaises(ExtractionError):
                    import_run(folder / 'input.json', folder / 'metadata.json',
                               [(folder / 'attempt-1.prompt', folder / 'attempt-1.output')], self.work / ('forged-' + changed),
                               [(folder / 'attempt-1.response', folder / 'attempt-1.exchange')])

    def test_invalid_key_header_stops_before_creating_a_run_or_network(self):
        from processing.extraction.api import run_api
        for key in ('BAD KEY', 'BAD\r\nHEADER', 'é'):
            with self.subTest(key=key), patch.dict(os.environ, OPENAI_API_KEY=key), \
                    patch('processing.extraction.api._exchange', side_effect=AssertionError('network')):
                with self.assertRaises(ExtractionError) as caught:
                    run_api(self.input, 'fixture-nfc-v1', self.root, RUN)
                self.assertEqual(caught.exception.code, 'OPENAI_API_KEY_INVALID')
                self.assertFalse(self.root.exists())

    def test_large_escaped_prompt_is_preserved_and_verified(self):
        document = json.loads(self.input.read_bytes())
        document['blocks'][0]['text'] = '"\\' * 1800000
        self.input.write_bytes(json.dumps(document, ensure_ascii=False).encode())
        output = dict(schema_version='extract-schema-v1', document_version_id=document['document_version_id'],
                      items=[], evidence=[], warnings=['NO_EVENT_FOUND'])
        result, calls = self.run_api([(200, response(json.dumps(output)), None, True)])
        self.assertEqual((calls, result['status']), (1, 'validated'))
        self.assertGreater((self.root / RUN / 'attempt-1.prompt').stat().st_size, MAX_BYTES)
        self.assertEqual(verify_run(RUN, self.root), result)

    def server(self, body, *, prefix=None, delay=0, extra_length=0, slow_header=False, slow_chunk=False, slow_dns=False):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'

            def log_message(self, *args):
                pass

            def do_POST(self):
                data = self.rfile.read(int(self.headers['Content-Length']))
                requests.append((self.path, self.headers['Authorization'], data))
                if slow_header or slow_chunk:
                    try:
                        if slow_header:
                            self.wfile.write(b'HTTP/1.1 200 OK\r\nX-Slow: '); self.wfile.flush()
                            for _ in range(25):
                                self.wfile.write(b'x'); self.wfile.flush(); time.sleep(0.04)
                            self.wfile.write(b'\r\nContent-Length: 2\r\n\r\n{}'); self.wfile.flush()
                        else:
                            self.wfile.write(b'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n4;slow=')
                            self.wfile.flush()
                            for _ in range(25):
                                self.wfile.write(b'x'); self.wfile.flush(); time.sleep(0.04)
                            self.wfile.write(b'\r\ndata\r\n0\r\n\r\n'); self.wfile.flush()
                    except OSError:
                        pass
                    self.close_connection = True
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(body) + extra_length))
                self.send_header('Connection', 'close')
                self.end_headers()
                try:
                    self.wfile.write(body if prefix is None else prefix); self.wfile.flush()
                    if delay:
                        time.sleep(delay)
                        self.wfile.write(body[len(prefix):]); self.wfile.flush()
                except OSError:
                    pass
                self.close_connection = True

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        popen = subprocess.Popen
        script = f'''
import http.client
import socket, time
resolve = socket.getaddrinfo
def dns(*args, **kwargs):
    if {slow_dns!r}:
        time.sleep(2)
    return resolve(*args, **kwargs)
socket.getaddrinfo = dns
def connection(host, timeout):
    assert host == 'api.openai.com'
    return http.client.HTTPConnection('127.0.0.1', {server.server_port}, timeout=timeout)
http.client.HTTPSConnection = connection
from processing.extraction.transport import main
raise SystemExit(main())
'''
        processes = []

        def start(command, **kwargs):
            self.assertEqual(command[1:], ['-m', 'processing.extraction.transport'])
            process = popen([command[0], '-c', script], **kwargs)
            processes.append(process)
            return process

        self.addCleanup(lambda: self.assertTrue(all(p.poll() is not None for p in processes)))
        return patch('processing.extraction.api.subprocess.Popen', side_effect=start), requests

    def test_deadline_kills_slow_dns_before_any_late_request(self):
        from processing.extraction.api import _exchange
        network, requests = self.server(b'{}', slow_dns=True)
        with network, patch('processing.extraction.api.REQUEST_TIMEOUT', 0.25):
            start = time.monotonic()
            result = _exchange(b'{}', KEY)
            elapsed = time.monotonic() - start
        self.assertEqual(result, (None, b'', 'API_TIMEOUT', False))
        self.assertLess(elapsed, 0.8)
        self.assertEqual(requests, [])

    def test_slow_headers_and_chunk_framing_cannot_extend_deadline(self):
        from processing.extraction.api import _exchange
        for options in ({'slow_header': True}, {'slow_chunk': True}):
            with self.subTest(options=options):
                network, _ = self.server(b'', **options)
                with network, patch('processing.extraction.api.REQUEST_TIMEOUT', 0.25):
                    start = time.monotonic()
                    status, raw, error, complete = _exchange(b'{}', KEY)
                    elapsed = time.monotonic() - start
                self.assertEqual((error, complete), ('API_TIMEOUT', False))
                self.assertLess(elapsed, 0.8)

    def test_partial_permanent_http_responses_do_not_retry(self):
        for status in (400, 401, 403, 302):
            self.root = self.work / ('partial-' + str(status))
            result, calls = self.run_api([(status, b'PRIVATE_PARTIAL', 'API_TRANSPORT_ERROR', False)] * 3)
            self.assertEqual((calls, result['status']), (1, 'failed'))
            self.assertFalse(result['attempts'][0]['retryable'])
            self.assertEqual(result['attempts'][0]['error_code'], 'API_HTTP_' + str(status))

    def test_actual_http_request_and_response_are_archived(self):
        from processing.extraction.api import run_api
        network, requests = self.server(response())
        with network:
            result = run_api(self.input, 'fixture-nfc-v1', self.root, RUN)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0][:2], ('/v1/responses', 'Bearer ' + KEY))
        self.assertEqual(requests[0][2], (self.root / RUN / 'attempt-1.prompt').read_bytes())

    def test_actual_http_truncated_content_is_not_marked_complete(self):
        from processing.extraction.api import _exchange
        network, _ = self.server(response(), extra_length=100)
        with network:
            status, raw, error, complete = _exchange(b'{}', KEY)
        self.assertEqual((status, raw), (200, response()))
        self.assertEqual(error, 'API_TRANSPORT_ERROR')
        self.assertFalse(complete)

    def test_actual_http_timeout_preserves_partial_body_and_deadline(self):
        from processing.extraction.api import _exchange
        network, _ = self.server(b'{"status":"completed"}', prefix=b'{"', delay=1)
        with network, patch('processing.extraction.api.REQUEST_TIMEOUT', 0.5):
            start = time.monotonic()
            status, raw, error, complete = _exchange(b'{}', KEY)
            elapsed = time.monotonic() - start
        self.assertEqual((status, raw, error, complete), (200, b'{"', 'API_TIMEOUT', False))
        self.assertLess(elapsed, 2)

    def test_actual_http_oversize_retains_only_marked_prefix(self):
        from processing.extraction.api import _exchange
        network, _ = self.server(b'x' * (MAX_BYTES + 1000))
        with network:
            status, raw, error, complete = _exchange(b'{}', KEY)
        self.assertEqual((status, len(raw), error, complete), (200, MAX_BYTES + 1, 'API_RESPONSE_LIMIT', False))

    def test_concurrent_same_id_does_not_duplicate_paid_call(self):
        from processing.extraction.api import run_api
        entered, release = threading.Event(), threading.Event()

        def exchange(request, key):
            entered.set()
            self.assertTrue(release.wait(3))
            return 200, response(), None, True

        with patch('processing.extraction.api._exchange', side_effect=exchange) as network, ThreadPoolExecutor(1) as pool:
            first = pool.submit(run_api, self.input, 'fixture-nfc-v1', self.root, RUN)
            try:
                self.assertTrue(entered.wait(1))
                with self.assertRaises(ExtractionError):
                    run_api(self.input, 'fixture-nfc-v1', self.root, RUN)
            finally:
                release.set()
            self.assertEqual(first.result(3)['status'], 'validated')
        self.assertEqual(network.call_count, 1)


if __name__ == '__main__':
    unittest.main()
