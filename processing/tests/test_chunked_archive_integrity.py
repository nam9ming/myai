from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
import threading
import unittest
from unittest.mock import patch

from processing.extraction import archive
from processing.extraction.api import run_api
from processing.extraction.validation import ExtractionError
import processing.tests.test_chunked_extraction as fixtures


def fingerprint(content):
    return dict(size=len(content), sha256=hashlib.sha256(content).hexdigest())


class ChunkedArchiveIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ChunkedApiTest()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.folder = self.fixture.root / fixtures.RUN

    def completed(self):
        receipt, _ = self.fixture.run_chunked()
        self.assertEqual(receipt['status'], 'validated')
        return receipt

    def read_json(self, name):
        return json.loads((self.folder / name).read_bytes())

    def write_json(self, name, value):
        (self.folder / name).write_bytes(archive._json(value))

    def state(self, folder=None):
        return {path.name: (path.read_bytes(), path.stat().st_mode, path.stat().st_ino)
                for path in (folder or self.folder).iterdir()}

    def restore(self, state):
        for path in self.folder.iterdir():
            path.unlink()
        for name, (content, _, _) in state.items():
            (self.folder / name).write_bytes(content)

    def rehash(self):
        identity = self.read_json('identity.json')
        receipt = self.read_json('receipt.json')
        identity['artifacts'] = {name: fingerprint((self.folder / name).read_bytes())
                                 for name in identity['artifacts']}
        receipt['artifacts'] = copy.deepcopy(identity['artifacts'])
        for name, field in [('input.json', 'input_sha256'), ('metadata.json', 'metadata_sha256'),
                            ('chunk-plan.json', 'chunk_plan_sha256')]:
            receipt[field] = identity['artifacts'][name]['sha256']
        self.write_json('identity.json', identity)
        self.write_json('receipt.json', receipt)

    def rejects_without_writes(self):
        before = self.state()
        with patch('processing.extraction.api._exchange') as network:
            with self.assertRaises(ExtractionError) as caught:
                archive.verify_run(fixtures.RUN, self.fixture.root)
        self.assertEqual(caught.exception.code, 'ARCHIVE_INTEGRITY')
        network.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_noncanonical_v2_identity_is_rejected_without_changing_v1_rules(self):
        self.completed()
        original = (self.folder / 'identity.json').read_bytes()
        reordered = dict(reversed(list(json.loads(original).items())))
        for changed in (b' ' + original, json.dumps(json.loads(original), indent=2).encode(),
                        (json.dumps(reordered, ensure_ascii=False, separators=(',', ':')) + '\n').encode()):
            with self.subTest(prefix=changed[:1]):
                (self.folder / 'identity.json').write_bytes(changed)
                self.rejects_without_writes()
        (self.folder / 'identity.json').write_bytes(original)
        self.assertEqual(archive.verify_run(fixtures.RUN, self.fixture.root)['status'], 'validated')
        from processing.tests.test_extraction_archive import ArchiveTest
        legacy = ArchiveTest(); legacy.setUp(); self.addCleanup(legacy.doCleanups)
        receipt = legacy.run_import()
        path = legacy.root / legacy.run_id / 'identity.json'
        changed = b' ' + path.read_bytes(); path.write_bytes(changed)
        self.assertEqual(archive.verify_run(legacy.run_id, legacy.root), receipt)
        self.assertEqual(path.read_bytes(), changed)

    def test_large_derived_cycle_manifest_is_checked_in_full(self):
        from processing.extraction.chunk_archive import _cycle
        folder = self.fixture.root / fixtures.RUN
        folder.mkdir(parents=True)
        plan = dict(status='requires_review', chunks=[dict(chunk_id=f'chunk-{i:06d}') for i in range(1, 135001)])
        with patch('processing.extraction.api._exchange') as network:
            expected, names, _, _ = _cycle(folder, {}, plan, 1, [])
            self.assertGreater((folder / 'attempt-1.prompt').stat().st_size, 8 * 1024 * 1024)
            artifacts = {name: archive._fingerprint(folder / name) for name in names}
            actual, _, _, _ = _cycle(folder, {}, plan, 1, [], artifacts=artifacts)
            self.assertEqual(actual, expected)
            with (folder / 'attempt-1.prompt').open('ab') as stream:
                stream.write(b' ')
            artifacts['attempt-1.prompt'] = archive._fingerprint(folder / 'attempt-1.prompt')
            with self.assertRaises(ExtractionError):
                _cycle(folder, {}, plan, 1, [], artifacts=artifacts)
        network.assert_not_called()

    def test_recomputed_plan_rejects_jointly_rehashed_requests_responses_and_outputs(self):
        self.completed()
        plan = self.read_json('chunk-plan.json')
        chunk = plan['chunks'][0]
        prefix = 'attempt-1-' + chunk['chunk_id']
        request = self.read_json(prefix + '.prompt')
        prompt = json.loads(request['input'])
        prompt['source']['blocks'][0]['text'] = '다른 가상 원문'
        request['input'] = archive._json(prompt).decode()
        self.write_json(prefix + '.prompt', request)
        chunk.update(request_sha256=fingerprint((self.folder / (prefix + '.prompt')).read_bytes())['sha256'],
                     request_bytes=(self.folder / (prefix + '.prompt')).stat().st_size)
        self.write_json('chunk-plan.json', plan)
        plan_hash = fingerprint((self.folder / 'chunk-plan.json').read_bytes())['sha256']
        manifest = self.read_json('attempt-1.prompt')
        manifest['chunk_plan_sha256'] = plan_hash
        self.write_json('attempt-1.prompt', manifest)
        output = self.read_json(prefix + '.output')
        output['warnings'].append('FORGED_SYNTHETIC_RESULT')
        self.write_json(prefix + '.output', output)
        packet = self.read_json(prefix + '.response')
        packet['output'][0]['content'][0]['text'] = archive._json(output).decode()
        self.write_json(prefix + '.response', packet)
        combined = self.read_json('attempt-1.output')
        combined['warnings'].append('FORGED_SYNTHETIC_RESULT')
        self.write_json('attempt-1.output', combined)
        self.rehash()
        self.rejects_without_writes()

    def test_wire_and_derived_results_are_recomputed_after_fingerprint_replacement(self):
        self.completed()
        original = self.state()
        prefix = 'attempt-1-' + self.read_json('chunk-plan.json')['chunks'][0]['chunk_id']
        for target in ('request', 'response', 'chunk-output', 'document-output', 'receipt'):
            with self.subTest(target=target):
                self.restore(original)
                if target == 'request':
                    value = self.read_json(prefix + '.prompt'); value['store'] = True
                    self.write_json(prefix + '.prompt', value)
                elif target == 'response':
                    value = self.read_json(prefix + '.response'); value['status'] = 'incomplete'
                    self.write_json(prefix + '.response', value)
                elif target in ('chunk-output', 'document-output'):
                    name = prefix + '.output' if target == 'chunk-output' else 'attempt-1.output'
                    value = self.read_json(name); value['warnings'].append('FORGED_SYNTHETIC_RESULT')
                    self.write_json(name, value)
                else:
                    value = self.read_json('receipt.json'); value['total_calls'] += 1
                    self.write_json('receipt.json', value)
                self.rehash()
                self.rejects_without_writes()

    def test_artifact_set_rejects_extra_missing_and_traversal_names(self):
        self.completed()
        original = self.state()
        for mutation in ('extra-file', 'missing-file', 'extra-declared', 'traversal-name', 'absolute-name'):
            with self.subTest(mutation=mutation):
                self.restore(original)
                if mutation == 'extra-file':
                    (self.folder / 'unexpected.response').write_bytes(b'synthetic extra artifact')
                elif mutation == 'missing-file':
                    (self.folder / 'attempt-1.output').unlink()
                else:
                    name = {'extra-declared': 'unexpected.response', 'traversal-name': '../escape.response',
                            'absolute-name': str(self.fixture.work / 'escape.response')}[mutation]
                    for control in ('identity.json', 'receipt.json'):
                        value = self.read_json(control)
                        value['artifacts'][name] = fingerprint(b'synthetic extra artifact')
                        self.write_json(control, value)
                self.rejects_without_writes()

    def test_three_retryable_cycles_preserve_every_call_and_unknown_usage(self):
        received = []

        def failure(request, key):
            packet = fixtures.response('{', usage=None) if not received else fixtures.response('{')
            received.append(packet)
            return 200, packet, None, True

        receipt, network = self.fixture.run_chunked(failure)
        count = len(self.read_json('chunk-plan.json')['chunks'])
        self.assertEqual((receipt['status'], len(receipt['attempts']), receipt['total_calls'], network.call_count),
                         ('failed', 3, count * 3, count * 3))
        metadata = self.read_json('metadata.json')
        self.assertEqual((metadata['attempts'], metadata['usage_in'], metadata['usage_out']), (3, None, None))
        for number, attempt in enumerate(receipt['attempts'], 1):
            self.assertEqual((attempt['status'], attempt['retryable']), ('failed', True))
            self.assertEqual((self.folder / f'attempt-{number}.output').read_bytes(), b'')
            self.assertEqual(len(attempt['chunks']), count)
            self.assertTrue(all(chunk['attempted'] for chunk in attempt['chunks']))
            for offset, chunk in enumerate(attempt['chunks']):
                prefix = f"attempt-{number}-{chunk['chunk_id']}"
                self.assertEqual((self.folder / (prefix + '.output')).read_bytes(), b'{')
                self.assertEqual((self.folder / (prefix + '.response')).read_bytes(), received[(number - 1) * count + offset])
        with patch('processing.extraction.api._exchange') as offline:
            self.assertEqual(archive.verify_run(fixtures.RUN, self.fixture.root), receipt)
        offline.assert_not_called()

    def test_interrupted_cycle_same_id_never_resends_or_rewrites_partial_files(self):
        original_write = archive._write
        outputs = 0

        def interrupted(destination, content):
            nonlocal outputs
            if '-chunk-' in destination.name and destination.name.endswith('.output'):
                outputs += 1
                if outputs == 2:
                    raise OSError('가상 프로세스 중단')
            return original_write(destination, content)

        with patch('processing.extraction.archive._write', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.fixture.run_chunked()
        before = self.state()
        self.assertFalse((self.folder / 'receipt.json').exists())
        self.assertEqual(len([name for name in before if name.endswith('.response')]), 2)
        with patch('processing.extraction.api._exchange') as network:
            with self.assertRaises(ExtractionError) as caught:
                run_api(self.fixture.input, 'fixture-nfc-v1', self.fixture.root, fixtures.RUN, model='gpt-6.1-sol')
        self.assertEqual(caught.exception.code, 'ARCHIVE_INCOMPLETE')
        network.assert_not_called()
        self.assertEqual(self.state(), before)

    def test_concurrent_same_id_only_owner_sends_one_document_cycle(self):
        started, release = threading.Event(), threading.Event()

        def blocked(request, key):
            started.set()
            if not release.wait(10):
                raise AssertionError('가상 동시 실행 대기 초과')
            return self.fixture.success(request, key)

        with patch('processing.extraction.api._exchange', side_effect=blocked) as network:
            with ThreadPoolExecutor(max_workers=1) as executor:
                owner = executor.submit(run_api, self.fixture.input, 'fixture-nfc-v1', self.fixture.root,
                                        fixtures.RUN, 'gpt-6.1-sol')
                try:
                    self.assertTrue(started.wait(10))
                    with self.assertRaises(ExtractionError) as caught:
                        run_api(self.fixture.input, 'fixture-nfc-v1', self.fixture.root, fixtures.RUN,
                                model='gpt-6.1-sol')
                    self.assertEqual(caught.exception.code, 'ARCHIVE_INCOMPLETE')
                finally:
                    release.set()
                receipt = owner.result(timeout=10)
        count = len(self.read_json('chunk-plan.json')['chunks'])
        self.assertEqual((receipt['status'], receipt['total_calls'], network.call_count), ('validated', count, count))
        self.assertEqual(archive.verify_run(fixtures.RUN, self.fixture.root), receipt)

    def test_verify_freeze_sealed_and_reuse_are_offline_and_preserve_originals(self):
        receipt = self.completed()
        original, input_bytes = self.state(), self.fixture.input.read_bytes()
        with patch.dict(os.environ, {}, clear=True), patch('processing.extraction.api._exchange') as network:
            self.assertEqual(archive.verify_run(fixtures.RUN, self.fixture.root), receipt)
            frozen = archive.freeze_run(fixtures.RUN, self.fixture.root)
            sealed = self.fixture.root / frozen['snapshot_ref']
            sealed_before = self.state(sealed)
            self.assertEqual(archive.verify_sealed_run(fixtures.RUN, sealed.parent)['receipt'], receipt)
            self.assertEqual(archive.freeze_run(fixtures.RUN, self.fixture.root), frozen)
            self.assertEqual(run_api(self.fixture.input, 'fixture-nfc-v1', self.fixture.root, fixtures.RUN,
                                     model='gpt-6.1-sol'), receipt)
            self.assertEqual(run_api(self.fixture.input, 'fixture-nfc-v1', sealed.parent, fixtures.RUN,
                                     model='gpt-6.1-sol'), receipt)
            self.assertEqual(self.state(sealed), sealed_before)
        network.assert_not_called()
        self.assertEqual(self.fixture.input.read_bytes(), input_bytes)
        self.assertEqual(self.state(), original)


if __name__ == '__main__':
    unittest.main()
