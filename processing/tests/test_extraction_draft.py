from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from processing.extraction.archive import import_run
from processing.extraction.draft import draft_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_extraction_prompt_metadata import metadata

REPO = Path(__file__).resolve().parents[2]
AREA = '10000000-0000-4000-8000-000000000005'
SPLIT = '10000000-0000-4000-8000-000000000006'


class DraftTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.work = Path(temporary.name).resolve()
        self.root = self.work / 'archive'
        self.input = self.work / 'input.json'
        self.input.write_bytes((REPO / 'contracts/examples/ai-input.json').read_bytes())
        self.output = json.loads((REPO / 'contracts/examples/ai-extraction.json').read_bytes())
        self.meta = self.work / 'metadata.json'
        self.meta.write_text(json.dumps(metadata()), encoding='utf-8')
        self.prompt = self.work / 'prompt.txt'
        self.prompt.write_bytes(b'PRIVATE_VALUE synthetic prompt')
        self.id = metadata()['run_id']
        doc = json.loads((REPO / 'backend/examples/source-import.json').read_bytes())
        source = doc['documents'][0]
        ai = json.loads(self.input.read_bytes())
        source.update(document_version_id=ai['document_version_id'], title=ai['title'],
                      published_date=ai['published_date'], block_index=ai['blocks'],
                      preprocessing_version=metadata()['preprocessing_version'])
        source['cleaned_text'] = '\n'.join(b['text'] for b in ai['blocks'])
        source['text_sha256'] = hashlib.sha256(source['cleaned_text'].encode()).hexdigest()
        self.source_body = doc
        self.source = self.work / 'source.json'
        self.target = self.work / 'private' / 'draft.json'

    def register(self, raw=None):
        self.source.write_text(json.dumps(self.source_body, ensure_ascii=False), encoding='utf-8')
        out = self.work / 'output.json'
        out.write_bytes(json.dumps(self.output, ensure_ascii=False).encode() if raw is None else raw)
        return import_run(self.input, self.meta, [(self.prompt, out)], self.root)

    def draft(self, target=None):
        return draft_run(self.id, self.source, target or self.target, AREA, SPLIT, 'test-dictionary-v1', self.root)

    @staticmethod
    def unknown(reason='원문 미기재', knowledge='not_stated'):
        return dict(value=None, knowledge=knowledge, evidence_ids=[], reason=reason)

    def test_exact_projection_ids_hashes_private_reuse_and_original_preservation(self):
        receipt = self.register()
        before = {name: (self.root / self.id / name).read_bytes() for name in receipt['artifacts']}
        result = self.draft()
        content = self.target.read_bytes()
        batch = json.loads(content)
        event = batch['events'][0]; revision = event['revision']
        self.assertEqual(batch['schema_version'], 'ai-draft-import-v1')
        self.assertEqual(batch['documents'], self.source_body['documents'])
        self.assertEqual((revision['origin'], revision['review_status'], revision['publication_intent']),
                         ('ai_draft', 'draft', 'hidden'))
        self.assertIsNone(revision['reviewer_id']); self.assertIsNone(revision['reviewed_at'])
        self.assertEqual(revision['human_overrides'], [])
        self.assertEqual(revision['originating_run_ids'], [self.id])
        self.assertEqual(revision['title'], self.output['items'][0]['title']['value'])
        self.assertEqual(revision['lifecycle'], 'uncertain')
        self.assertEqual(event['area_membership'], 'uncertain')
        self.assertEqual(revision['occurrences'][0]['precision'], 'exact_time')
        location = revision['locations'][0]
        self.assertIsNone(location['geometry']); self.assertIsNone(location['checked_by'])
        self.assertEqual(location['coverage'], 'unknown')
        evidence = batch['evidence'][0]
        self.assertEqual(evidence['text_sha256'], batch['documents'][0]['text_sha256'])
        self.assertEqual(revision['applicability']['evidence_ids'], [evidence['evidence_id']])
        self.assertEqual(revision['occurrences'][0]['location_ids'], [location['location_id']])
        self.assertEqual(result['output_sha256'], hashlib.sha256(content).hexdigest())
        self.assertTrue(result['review_required'])
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(result, self.draft())
        self.assertEqual(self.target.read_bytes(), content)
        self.assertEqual(before, {name: (self.root / self.id / name).read_bytes() for name in receipt['artifacts']})
        self.assertNotIn('PRIVATE_VALUE', json.dumps(result))
        self.assertNotIn(str(self.work), json.dumps(result))

    def test_unknown_title_types_time_and_unbound_location_are_not_invented(self):
        item = self.output['items'][0]
        item['title'] = self.unknown(); item['types'] = self.unknown(knowledge='ambiguous')
        occurrence = item['occurrences'][0]
        occurrence['location_refs'] = []
        occurrence['time_end'] = self.unknown('종료 시각 미기재')
        self.output['warnings'].append('LOCATION_BINDING_UNKNOWN')
        self.register(); self.draft()
        revision = json.loads(self.target.read_bytes())['events'][0]['revision']
        self.assertIsNone(revision['title']); self.assertEqual(revision['types'], [])
        occ = revision['occurrences'][0]
        self.assertEqual(occ['precision'], 'unknown')
        self.assertEqual(occ['time_start'], '10:00'); self.assertIsNone(occ['time_end'])
        self.assertIn('종료 시각 미기재', occ['normalization_note'])
        self.assertEqual(len(revision['locations']), 2)
        self.assertEqual(occ['location_ids'], [revision['locations'][1]['location_id']])
        self.assertEqual(revision['locations'][1]['kind'], 'unknown')

    def test_recurrence_requires_review_and_seconds_are_preserved(self):
        occurrence = self.output['items'][0]['occurrences'][0]
        occurrence['recurrence_text'] = dict(value='매주 토요일', knowledge='known', evidence_ids=['e1'], reason=None)
        occurrence['time_start']['value'] = '10:00:30'
        self.register(); self.draft()
        occ = json.loads(self.target.read_bytes())['events'][0]['revision']['occurrences'][0]
        self.assertEqual(occ['precision'], 'unknown')
        self.assertIsNone(occ['recurrence_dates'])
        self.assertEqual(occ['time_start'], '10:00:30')
        self.assertIn('매주 토요일', occ['normalization_note'])

    def test_ambiguous_recurrence_is_not_normalized_to_a_continuous_interval(self):
        self.output['items'][0]['occurrences'][0]['recurrence_text'] = self.unknown('반복 관계 불명확', 'ambiguous')
        self.register(); self.draft()
        occ = json.loads(self.target.read_bytes())['events'][0]['revision']['occurrences'][0]
        self.assertEqual(occ['precision'], 'unknown')

    def test_all_temporal_fields_not_stated_remain_not_stated(self):
        occurrence = self.output['items'][0]['occurrences'][0]
        for key in list(occurrence):
            if key not in ('local_occurrence_id', 'location_refs'):
                occurrence[key] = self.unknown()
        self.register(); self.draft()
        occ = json.loads(self.target.read_bytes())['events'][0]['revision']['occurrences'][0]
        self.assertEqual((occ['precision'], occ['knowledge']), ('unknown', 'not_stated'))

    def test_multiblock_document_hash_differs_from_quoted_block_hash(self):
        ai = json.loads(self.input.read_bytes())
        ai['blocks'].insert(0, dict(block_id='heading', page=None, text='합성 제목 😀'))
        self.input.write_text(json.dumps(ai, ensure_ascii=False), encoding='utf-8')
        doc = self.source_body['documents'][0]
        doc['block_index'] = ai['blocks']
        doc['cleaned_text'] = '\n'.join(b['text'] for b in ai['blocks'])
        doc['text_sha256'] = hashlib.sha256(doc['cleaned_text'].encode()).hexdigest()
        self.register(); self.draft()
        entry = json.loads(self.target.read_bytes())['evidence'][0]
        self.assertNotEqual(entry['text_sha256'], self.output['evidence'][0]['text_sha256'])
        self.assertEqual(entry['text_sha256'], doc['text_sha256'])
        self.assertEqual(entry['quote'], self.output['evidence'][0]['quote'])

    def test_public_output_path_is_rejected_without_creating_a_file(self):
        self.register()
        with self.assertRaises(ExtractionError):
            self.draft(REPO / 'data/public/d05-draft-must-not-exist.json')
        self.assertFalse((REPO / 'data/public/d05-draft-must-not-exist.json').exists())

    def test_no_event_found_does_not_create_fake_event(self):
        self.output.update(items=[], evidence=[], warnings=['NO_EVENT_FOUND'])
        self.register(); result = self.draft()
        batch = json.loads(self.target.read_bytes())
        self.assertEqual(batch['events'], []); self.assertEqual(batch['evidence'], [])
        self.assertEqual(result['event_ids'], [])
        self.assertTrue(result['review_required'])

    def test_date_only_all_day_and_conflicting_partial_time_keep_their_meaning(self):
        original = copy.deepcopy(self.output)
        for mode, precision in [('date_only', 'date_only'), ('all_day', 'explicit_all_day'),
                                ('conflict', 'unknown'), ('dateless', 'unknown')]:
            with self.subTest(mode=mode):
                self.root = self.work / mode
                self.output = copy.deepcopy(original)
                occ = self.output['items'][0]['occurrences'][0]
                if mode in ('date_only', 'all_day'):
                    for key in ('time_start', 'time_end', 'end_day_offset', 'all_day'):
                        occ[key] = self.unknown()
                if mode in ('all_day', 'conflict'):
                    occ['all_day'] = dict(value=True, knowledge='known', evidence_ids=['e1'], reason=None)
                if mode == 'dateless':
                    occ['date_start'] = self.unknown(); occ['date_end'] = self.unknown()
                    occ['time_start']['value'] = '12:00'; occ['time_end']['value'] = '10:00'
                self.register()
                target = self.work / 'private' / (mode + '.json')
                self.draft(target)
                result = json.loads(target.read_bytes())['events'][0]['revision']['occurrences'][0]
                self.assertEqual(result['precision'], precision)
                self.assertEqual(result['time_start'], occ['time_start']['value'])
                self.assertEqual(result['time_end'], occ['time_end']['value'])

    def test_original_change_after_freeze_does_not_change_the_draft(self):
        from processing.extraction import draft
        self.register()
        freeze = draft.freeze_run
        def changed(*args):
            packet = freeze(*args)
            (self.root / self.id / 'attempt-1.output').write_bytes(b'PRIVATE_VALUE changed original')
            return packet
        with patch.object(draft, 'freeze_run', side_effect=changed):
            self.draft()
        title = json.loads(self.target.read_bytes())['events'][0]['revision']['title']
        self.assertEqual(title, self.output['items'][0]['title']['value'])

    def test_changed_snapshot_is_rejected_before_any_draft_is_written(self):
        from processing.extraction import draft
        self.register()
        freeze = draft.freeze_run
        def changed(*args):
            packet = freeze(*args)
            path = self.root / packet['snapshot_ref'] / 'attempt-1.output'
            path.chmod(0o600); path.write_bytes(b'PRIVATE_VALUE changed snapshot')
            return packet
        with patch.object(draft, 'freeze_run', side_effect=changed), self.assertRaises(ExtractionError):
            self.draft()
        self.assertFalse(self.target.exists())

    def test_output_limit_preserves_source_and_does_not_install_a_partial_file(self):
        from processing.extraction.validation import MAX_BYTES
        size = len(json.dumps(self.source_body, ensure_ascii=False).encode())
        self.source_body['documents'][0]['use_note'] = 'x' * (MAX_BYTES - size - 100)
        self.register()
        original = self.source.read_bytes()
        with self.assertRaises(ExtractionError) as error:
            self.draft()
        self.assertEqual(error.exception.code, 'DRAFT_OUTPUT_TOO_LARGE')
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(self.target.exists())

    def test_read_only_output_parent_fails_without_partial_file(self):
        self.register()
        self.target.parent.mkdir(mode=0o500)
        try:
            with self.assertRaises(OSError): self.draft()
            self.assertFalse(self.target.exists())
            self.assertEqual(list(self.target.parent.iterdir()), [])
        finally:
            self.target.parent.chmod(0o700)

    def test_failed_source_mismatch_and_conflicting_file_are_preserved(self):
        self.register(raw=b'PRIVATE_VALUE invalid JSON')
        with self.assertRaises(ExtractionError): self.draft()
        self.assertFalse(self.target.exists())

    def test_source_projection_or_preprocessing_mismatch_is_rejected(self):
        self.register()
        original = copy.deepcopy(self.source_body)
        for key in ('title', 'preprocessing_version', 'text_sha256'):
            self.source_body = copy.deepcopy(original)
            self.source_body['documents'][0][key] = 'PRIVATE_VALUE wrong'
            self.source.write_text(json.dumps(self.source_body), encoding='utf-8')
            with self.subTest(key=key), self.assertRaises(ExtractionError): self.draft()
            self.assertFalse(self.target.exists())

    def test_concurrent_reuse_conflict_and_safe_cli(self):
        self.register()
        with ThreadPoolExecutor(max_workers=4) as workers:
            results = list(workers.map(lambda _: self.draft(), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        content = self.target.read_bytes()
        self.target.write_bytes(b'PRIVATE_VALUE existing')
        with self.assertRaises(ExtractionError): self.draft()
        self.assertEqual(self.target.read_bytes(), b'PRIVATE_VALUE existing')
        self.target.write_bytes(content)
        args = [sys.executable, '-m', 'processing.extraction', 'draft', self.id, '--root', str(self.root),
                '--source', str(self.source), '--output', str(self.target), '--area-id', AREA,
                '--split-group-id', SPLIT, '--dictionary-version', 'test-dictionary-v1']
        process = subprocess.run(args, cwd=REPO, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout), results[0])
        self.assertEqual(process.stderr, b'')
        process = subprocess.run(args[:-1] + [''], cwd=REPO, capture_output=True, timeout=15)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, b'')
        self.assertNotIn(b'PRIVATE_VALUE', process.stderr)
        self.assertNotIn(str(self.work).encode(), process.stderr)
