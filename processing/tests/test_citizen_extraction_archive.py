import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.evaluation import reviews
from processing.extraction.archive import freeze_run, import_run, prepare, verify_run, verify_sealed_run
from processing.extraction.validation import ExtractionError, MAX_BYTES
from processing.tests.test_extraction_prompt_metadata import metadata

ROOT = Path(__file__).resolve().parents[2]


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2020, 1, 1, tzinfo=timezone.utc)


class CitizenExtractionArchiveTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / 'runs'
        self.source = self.work / 'input.json'
        self.source.write_bytes((ROOT / 'contracts/examples/citizen-ai-input.json').read_bytes())
        self.body = metadata()
        self.body.update(document_version_id=json.loads(self.source.read_bytes())['document_version_id'],
                         schema_version='extract-citizen-v1', prompt_version='manual-template-label')
        self.meta = self.work / 'metadata.json'
        self.meta.write_text(json.dumps(self.body), encoding='utf-8')
        self.prompt = self.work / 'actual-prompt.bin'
        self.prompt.write_bytes(b'actual supplied synthetic prompt\r\n')
        self.output = self.work / 'actual-output.bin'
        self.good = (ROOT / 'contracts/examples/citizen-ai-extraction.json').read_bytes()
        self.output.write_bytes(self.good)
        self.run_id = self.body['run_id']

    def record(self, pairs=None):
        with patch('processing.extraction.archive.datetime', FixedClock):
            return import_run(self.source, self.meta, pairs or [(self.prompt, self.output)], self.root)

    def frozen(self):
        packet = freeze_run(self.run_id, self.root)
        return packet, self.root / packet['snapshot_ref']

    def review(self, before):
        after = json.loads(self.good)
        after['items'][0]['title']['value'] = '시민 배움 안내'
        packet, folder = self.frozen()
        return dict(schema_version='human-review-v1', review_id='38000000-0000-4000-8000-000000000001',
            source=dict(run_id=self.run_id, snapshot_ref=packet['snapshot_ref'],
                        receipt_sha256=hashlib.sha256((folder / 'receipt.json').read_bytes()).hexdigest()),
            review=dict(reviewed_by='synthetic-review-declaration', started_at='2020-01-01T01:00:00Z',
                        finished_at='2020-01-01T01:10:00Z', basis='source_only', note='합성 선언, 실제 사람 아님'),
            output=after, changes=[dict(field_path='output', before=before, after=copy.deepcopy(after),
                reason='합성 제목 축약', evidence_ids=['e1'], reviewer='synthetic-review-declaration',
                time='2020-01-01T01:10:00Z')])

    def test_original_fields_prompt_label_and_sealed_replay_survive_source_removal(self):
        receipt = self.record()
        self.assertEqual(receipt['status'], 'validated')
        self.assertEqual(receipt['execution_mode'], 'manual_import')
        self.assertTrue(receipt['review_required'])
        self.assertEqual(self.record(), receipt)
        packet, folder = self.frozen()
        originals = {name: (folder / name).read_bytes() for name in [*receipt['artifacts'], 'identity.json', 'receipt.json']}
        self.assertEqual(originals['attempt-1.output'], self.good)
        self.assertEqual(originals['attempt-1.prompt'], self.prompt.read_bytes())
        self.assertEqual(json.loads(originals['metadata.json']), self.body)
        for name in originals:
            self.assertEqual((folder / name).stat().st_mode & 0o777, 0o400)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o500)
        for path in (self.source, self.meta, self.prompt, self.output):
            path.unlink()
        shutil.rmtree(self.root / self.run_id)
        self.assertEqual(verify_sealed_run(self.run_id, folder.parent)['receipt'], receipt)
        self.assertEqual(freeze_run(self.run_id, folder.parent)['receipt'], packet['receipt'])
        self.assertEqual({name: (folder / name).read_bytes() for name in originals}, originals)

    def test_all_three_attempts_keep_invalid_utf8_large_failure_and_final_facts(self):
        invalid = self.work / 'invalid.bin'; invalid.write_bytes(b'\xff\x00synthetic')
        large = self.work / 'large.bin'; large.write_bytes(b'x' * (MAX_BYTES + 1))
        self.body['attempts'] = 3; self.meta.write_text(json.dumps(self.body))
        receipt = self.record([(self.prompt, invalid), (self.prompt, large), (self.prompt, self.output)])
        self.assertEqual([a['status'] for a in receipt['attempts']], ['failed', 'failed', 'validated'])
        _, folder = self.frozen()
        for index, original in enumerate((invalid, large, self.output), 1):
            self.assertEqual((folder / f'attempt-{index}.output').read_bytes(), original.read_bytes())
        self.assertEqual(verify_sealed_run(self.run_id, folder.parent)['receipt'], receipt)

    def test_last_failed_output_stays_failed_and_exact_original_is_sealed(self):
        self.output.write_bytes(b'\xff\x00unparseable synthetic output')
        receipt = self.record()
        self.assertEqual(receipt['status'], 'failed')
        _, folder = self.frozen()
        self.assertEqual((folder / 'attempt-1.output').read_bytes(), self.output.read_bytes())
        self.assertEqual(verify_sealed_run(self.run_id, folder.parent)['receipt'], receipt)

    def test_unknown_prepare_version_rejects_before_writing_any_root(self):
        with self.assertRaises(ExtractionError) as caught:
            prepare(self.source, self.root, 'extract-citizen-unknown')
        self.assertEqual(caught.exception.code, 'EXTRACTION_SCHEMA_UNSUPPORTED')
        self.assertFalse(self.root.exists())

    def test_manual_metadata_cannot_enter_api_or_v2_mode(self):
        self.body.update(execution_mode='api', provider='openai', model_label='synthetic-model')
        self.body['unavailable_reasons'].pop('model_label')
        self.meta.write_text(json.dumps(self.body))
        with self.assertRaises(ExtractionError) as caught:
            self.record()
        self.assertEqual((caught.exception.kind, caught.exception.path), ('input', '$.execution_mode'))
        self.assertFalse(self.root.exists())

    def test_metadata_family_selects_parser_and_preserves_mismatched_output_as_failure(self):
        body = json.loads(self.good); body['schema_version'] = 'extract-schema-v1'
        self.output.write_text(json.dumps(body))
        receipt = self.record()
        self.assertEqual(receipt['status'], 'failed')
        self.assertEqual(receipt['attempts'][0]['error_path'], '$.schema_version')
        self.assertEqual((self.root / self.run_id / 'attempt-1.output').read_bytes(), self.output.read_bytes())

    def test_changed_prompt_cannot_replace_existing_run_or_sealed_image(self):
        receipt = self.record(); _, folder = self.frozen()
        before = (folder / 'attempt-1.prompt').read_bytes()
        self.prompt.write_bytes(b'different supplied prompt')
        with self.assertRaises(ExtractionError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, 'ARCHIVE_CONFLICT')
        self.assertEqual((folder / 'attempt-1.prompt').read_bytes(), before)
        self.assertEqual(verify_run(self.run_id, folder.parent), receipt)

    def test_actual_review_cli_accepts_citizen_parent_without_old_schema_projection(self):
        self.record(); value = self.review(json.loads(self.good))
        path = self.work / 'review.json'; path.write_text(json.dumps(value, ensure_ascii=False))
        result = subprocess.run([sys.executable, '-B', '-m', 'processing.evaluation', 'check-review',
            '--input', str(path), '--run-root', str(self.root)], cwd=ROOT,
            env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        summary = json.loads(result.stdout)
        self.assertEqual(summary['status'], 'declared_reviewed')
        self.assertEqual(summary['review_duration_ns'], 600_000_000_000)
        self.assertEqual(summary['human_verification'], 'declared_only')

    def test_human_revision_keeps_all_facts_changes_and_parent_without_original_paths(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                self.root = self.work / ('failed' if failed else 'successful')
                self.output.write_bytes(b'\xffsynthetic' if failed else self.good)
                self.record(); value = self.review(None if failed else json.loads(self.good))
                path = self.work / 'review.json'; raw = json.dumps(value, ensure_ascii=False).encode(); path.write_bytes(raw)
                review_root = self.work / ('failed-reviews' if failed else 'reviews')
                receipt = reviews.freeze_review(path, review_root, self.root)
                folder = review_root / receipt['review_ref']
                self.assertEqual((folder / 'review.json').read_bytes(), raw)
                self.assertEqual(json.loads((folder / 'output.json').read_bytes()), value['output'])
                self.assertEqual(receipt['summary']['source_status'], 'failed' if failed else 'validated')
                self.assertEqual(receipt['summary']['change_count'], 1)
                packet, parent = self.frozen()
                saved_parent = folder / 'source' / packet['snapshot_ref']
                for item in parent.iterdir():
                    self.assertEqual((saved_parent / item.name).read_bytes(), item.read_bytes())
                for current, _, _ in os.walk(self.root):
                    Path(current).chmod(0o700)
                shutil.rmtree(self.root)
                path.unlink()
                self.assertEqual(reviews.verify_review(receipt['review_ref'], review_root), receipt)

    def test_review_rejects_cross_family_and_missing_change_audit(self):
        self.record(); value = self.review(json.loads(self.good))
        for alteration in ('family', 'changes'):
            with self.subTest(alteration=alteration):
                changed = copy.deepcopy(value)
                if alteration == 'family':
                    changed['output']['schema_version'] = 'extract-schema-v1'
                    expected = 'HUMAN_REVIEW_OUTPUT_INVALID'
                else:
                    changed['changes'] = []
                    expected = 'HUMAN_REVIEW_CHANGE_MISSING'
                with self.assertRaises(ExtractionError) as caught:
                    reviews.check_review(json.dumps(changed).encode(), self.root)
                self.assertEqual(caught.exception.code, expected)


if __name__ == '__main__':
    unittest.main()
