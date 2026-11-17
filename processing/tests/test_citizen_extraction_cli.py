import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from processing.tests.test_extraction_prompt_metadata import metadata

ROOT = Path(__file__).resolve().parents[2]


class CitizenExtractionCliTest(unittest.TestCase):
    def test_manual_import_preserves_actual_prompt_label_and_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary).resolve()
            body = metadata()
            body.update(schema_version='extract-citizen-v1', prompt_version='manual-tool-template-2026')
            meta = work / 'metadata.json'
            meta.write_text(json.dumps(body), encoding='utf-8')
            prompt = work / 'actual-prompt.bin'
            prompt.write_bytes(b'actual supplied synthetic prompt\r\n')
            output = work / 'raw-output.json'
            output.write_text(json.dumps(dict(schema_version='extract-citizen-v1',
                document_version_id=body['document_version_id'], items=[], evidence=[],
                warnings=['NO_EVENT_FOUND'])), encoding='utf-8')
            archive = work / 'archive'
            result = subprocess.run([
                sys.executable, '-B', '-m', 'processing.extraction', 'import',
                '--input', str(ROOT / 'contracts/examples/ai-input.json'),
                '--metadata', str(meta), '--attempt', str(prompt), str(output), '--root', str(archive),
            ], cwd=ROOT, env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
            packet = json.loads(result.stdout)
            self.assertEqual(packet['status'], 'validated')
            self.assertTrue(packet['review_required'])
            folder = archive / body['run_id']
            for name, source in [('metadata.json', meta), ('attempt-1.prompt', prompt), ('attempt-1.output', output)]:
                self.assertEqual((folder / name).read_bytes(), source.read_bytes())
            self.assertEqual(json.loads((folder / 'metadata.json').read_bytes())['prompt_version'],
                             'manual-tool-template-2026')

    def test_prepare_selects_citizen_schema_without_changing_legacy_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary).resolve() / 'archive'
            result = subprocess.run([
                sys.executable, '-B', '-m', 'processing.extraction', 'prepare',
                '--input', str(ROOT / 'contracts/examples/ai-input.json'),
                '--root', str(archive), '--schema-version', 'extract-citizen-v1',
            ], cwd=ROOT, env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'},
                capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8'))
            packet = json.loads(result.stdout)
            self.assertEqual(packet['status'], 'prepared')
            folder = archive / 'prepared' / 'extract-citizen-v1' / packet['input_sha256']
            prompt = json.loads((folder / 'prompt.json').read_bytes())
            self.assertEqual(prompt['prompt_version'], 'citizen-prompt-v1')
            self.assertEqual(prompt['schema']['properties']['schema_version']['const'], 'extract-citizen-v1')
            self.assertFalse((archive / 'prepared' / packet['input_sha256']).exists())


if __name__ == '__main__':
    unittest.main()
