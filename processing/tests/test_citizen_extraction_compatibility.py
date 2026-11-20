"""시민 family 추가 전 고정한 공개 legacy 원본 bytes와 현재 동작을 대조한다."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

from processing.extraction.api import request_bytes
from processing.extraction.archive import _json
from processing.extraction.metadata import parse_metadata
from processing.extraction.prompt import render_prompt
from processing.extraction.schema import input_schema, output_schema
from processing.extraction.validation import parse_input, parse_output


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/citizen-legacy'
ARCHIVE_MANIFEST_SHA256 = '0cdb9589b6f1acc66075cec2a2651e23546a3dbb8747e127ff17349b67eab77f'
PROMPT_MANIFEST_SHA256 = 'a58fa2d587a69ce08dbd08c0c757264ab99136c27b6dcbdfa8a4860e90553ad1'
CLI_VERIFICATION_SHA256 = 'f2fe83b08929f1a18aa301f1636de0873974d21a92a7ef0099cf3a9725f5b0d2'
OFFLINE_CLI = '''import runpy, socket, sys
def forbidden(*args, **kwargs):
    raise AssertionError("legacy verification must stay offline")
socket.socket = forbidden
socket.getaddrinfo = forbidden
runpy.run_module(sys.argv.pop(1), run_name="__main__")
'''


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshot(root):
    result = {}
    for path in [root, *sorted(root.rglob('*'))]:
        info = path.lstat()
        result[path.relative_to(root).as_posix()] = (
            stat.S_IMODE(info.st_mode), digest(path.read_bytes()) if stat.S_ISREG(info.st_mode) else None)
    return result


class CitizenLegacyCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        pinned = [('archive-manifest.json', ARCHIVE_MANIFEST_SHA256),
                  ('prompt-manifest.json', PROMPT_MANIFEST_SHA256),
                  ('cli-verification.json', CLI_VERIFICATION_SHA256)]
        values = []
        for name, expected in pinned:
            raw = (FIXTURE / name).read_bytes()
            if digest(raw) != expected:
                raise AssertionError('fixed legacy manifest changed: ' + name)
            values.append(json.loads(raw))
        cls.manifest, cls.prompts, cli = values
        cls.cli = {case['case']: case for case in cli['commands']}

    def test_portable_fixture_is_exact_original_subset_without_source_code_hash_gate(self):
        prefixes = [self.manifest['cases'][name]['archive'] + '/'
                    for name in ('manual_failure', 'api_chunk', 'human_handoff')]
        expected = {name: metadata for name, metadata in self.manifest['files'].items()
                    if any(name.startswith(prefix) for prefix in prefixes)}
        actual = {path.relative_to(FIXTURE / 'archives').as_posix(): path
                  for path in (FIXTURE / 'archives').rglob('*') if path.is_file()}
        self.assertEqual(set(actual), set(expected))
        self.assertEqual(len(actual), 39)
        for name, path in actual.items():
            raw = path.read_bytes()
            self.assertEqual((digest(raw), len(raw)), (expected[name]['sha256'], expected[name]['size']), name)
        self.assertEqual(len(self.prompts['files']), 13)
        self.assertEqual({path.name for path in (FIXTURE / 'prompts').iterdir()}, set(self.prompts['files']))
        for name, expected in self.prompts['files'].items():
            raw = (FIXTURE / 'prompts' / name).read_bytes()
            self.assertEqual(dict(sha256=digest(raw), size=len(raw)), expected, name)

    def test_legacy_public_input_output_and_schemas_match_saved_bytes(self):
        inputs = FIXTURE / 'prompts'
        for fixture, contract in [('input.json', 'ai-input.json'), ('output.json', 'ai-extraction.json')]:
            self.assertEqual((ROOT / 'contracts/examples' / contract).read_bytes(), (inputs / fixture).read_bytes())
        document = parse_input((inputs / 'input.json').read_bytes())
        self.assertEqual(parse_output((inputs / 'output.json').read_bytes(), document),
                         json.loads((inputs / 'output.json').read_bytes()))
        for name, build in [('input-schema.json', input_schema), ('output-schema.json', output_schema)]:
            self.assertEqual(_json(build()), (inputs / name).read_bytes())

    def test_all_legacy_prompt_request_and_feedback_versions_match_saved_bytes(self):
        document = parse_input((FIXTURE / 'prompts/input.json').read_bytes())
        for version in ('prompt-v1', 'prompt-v2', 'prompt-v3'):
            chunk = self.prompts['chunk'] if version == 'prompt-v3' else None
            for name, actual in [(version + '.json', render_prompt(document, version, chunk)),
                                 (version + '-request.json', request_bytes(document, 'synthetic-baseline-model',
                                                                           prompt_version=version, chunk=chunk)),
                                 (version + '-feedback-request.json', request_bytes(document, 'synthetic-baseline-model',
                                                '$.items', prompt_version=version, chunk=chunk))]:
                with self.subTest(artifact=name):
                    self.assertEqual(digest(actual), self.prompts['files'][name]['sha256'])
                    self.assertEqual(actual, (FIXTURE / 'prompts' / name).read_bytes())

    def replay(self, case_name):
        fixture_before = snapshot(FIXTURE)
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary).resolve() / 'archives'
            shutil.copytree(FIXTURE / 'archives', copied)
            for current, _, files in os.walk(copied, topdown=False):
                folder = Path(current)
                for name in files: (folder / name).chmod(0o400)
                folder.chmod(0o500)
            try:
                handoff = copied / self.manifest['cases']['human_handoff']['archive']
                review = handoff / 'review' / Path(self.manifest['cases']['human_review']['archive']).name
                success = review / 'source' / self.manifest['cases']['manual_success']['registration']['snapshot_ref']
                folders = dict(human_handoff=handoff, human_review=review, manual_success=success,
                               manual_failure=copied / self.manifest['cases']['manual_failure']['archive'],
                               api_chunk=copied / self.manifest['cases']['api_chunk']['archive'])
                folder = folders[case_name]
                case = self.manifest['cases'][case_name]
                receipt_bytes = (folder / 'receipt.json').read_bytes()
                self.assertEqual(digest(receipt_bytes), case['receipt_sha256'])
                receipt = json.loads(receipt_bytes)
                if case_name.startswith('manual_') or case_name == 'api_chunk':
                    args = ['processing.extraction', 'verify-sealed', case['run_id'], '--root', str(folder.parent)]
                    metadata_bytes = (folder / 'metadata.json').read_bytes()
                    metadata = json.loads(metadata_bytes)
                    document = parse_input((folder / 'input.json').read_bytes())
                    self.assertEqual(parse_metadata(metadata_bytes, document, len(receipt['attempts'])), metadata)
                    if case_name.startswith('manual_'):
                        self.assertEqual(metadata['execution_mode'], 'manual_import')
                        self.assertEqual(metadata['prompt_version'], 'prompt-v1')
                        self.assertIsNone(metadata['model_label'])
                else:
                    args = ['processing.evaluation', 'verify-review' if case_name == 'human_review' else 'verify-handoff',
                            folder.name, '--root', str(folder.parent)]
                before = snapshot(copied)
                process = subprocess.run([sys.executable, '-B', '-c', OFFLINE_CLI, *args], cwd=ROOT,
                    env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, timeout=30)
                original = self.cli[case_name]
                self.assertEqual(process.returncode, original['expected_exit'], process.stderr)
                self.assertEqual(digest(process.stdout), original['stdout_sha256'])
                self.assertEqual(digest(process.stderr), original['stderr_sha256'])
                packet = json.loads(process.stdout)
                self.assertEqual(packet['receipt'] if args[0] == 'processing.extraction' else packet, receipt)
                self.assertEqual(snapshot(copied), before)
            finally:
                for current, _, _ in os.walk(copied): Path(current).chmod(0o700)
        self.assertEqual(snapshot(FIXTURE), fixture_before)

    def test_legacy_manual_success_sealed_cli_receipt_and_original_bytes(self):
        self.replay('manual_success')

    def test_legacy_manual_non_utf8_failure_keeps_failed_receipt_and_entire_bytes(self):
        self.replay('manual_failure')

    def test_legacy_api_v2_chunk_archive_verifies_offline_without_regenerating_outputs(self):
        self.replay('api_chunk')

    def test_legacy_human_review_declared_changes_and_parent_bytes_are_preserved(self):
        self.replay('human_review')

    def test_legacy_handoff_projection_and_full_parent_archive_are_preserved(self):
        self.replay('human_handoff')


if __name__ == '__main__':
    unittest.main()
