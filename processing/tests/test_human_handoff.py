import copy
from datetime import datetime, timezone
import hashlib
import json
from unittest.mock import patch

from processing.evaluation import human_handoff as handoff
from processing.extraction import draft
from processing.extraction.archive import _json, freeze_run, import_run
from processing.extraction.prompt import render_prompt
from processing.extraction.validation import ExtractionError, parse_input
from processing.tests.test_dataset import REPO, uid
from processing.tests import test_extraction_draft
from processing.tests.test_extraction_draft import AREA, SPLIT
from processing.tests.test_extraction_prompt_metadata import metadata
from processing.tests.test_human_evaluation import HumanEvaluationFixture

AT = '2020-01-01T05:00:00Z'


class HumanHandoffFixture(HumanEvaluationFixture):
    def setUp(self):
        super().setUp()
        source = json.loads((REPO / 'backend/examples/source-import.json').read_bytes())
        doc = source['documents'][0]
        doc.update(document_version_id=self.source['document_version_id'], title=self.source['title'],
            published_date=self.source['published_date'], block_index=copy.deepcopy(self.source['blocks']),
            preprocessing_version='fixture-nfc-v1')
        doc['cleaned_text'] = '\n'.join(block['text'] for block in self.source['blocks'])
        doc['text_sha256'] = hashlib.sha256(doc['cleaned_text'].encode()).hexdigest()
        selected = self.control['documents'][0]
        self.request = dict(schema_version='human-handoff-v1', handoff_id=uid(980),
            review_ref=selected['review_ref'], review_receipt_sha256=selected['receipt_sha256'], source=source,
            area_id=AREA, split_group_id=SPLIT, dictionary_version='test-dictionary-v1')

    def project(self, value=None, *, at=AT, root=None):
        return handoff.project_handoff(_json(self.request if value is None else value),
            self.human_root if root is None else root, projected_at=at)

    def use_review(self, selected):
        self.request.update(review_ref=selected['review_ref'], review_receipt_sha256=selected['receipt_sha256'])

    def invalid(self, value, code=None):
        with self.assertRaises(ExtractionError) as caught: self.project(value)
        if code: self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_', str(caught.exception))


class HumanHandoffTest(HumanHandoffFixture):
    def test_d06_facts_have_real_parent_ids_and_no_invented_workflow(self):
        packet = self.project(); projection, summary = packet['projection'], packet['summary']
        event = projection['events'][0]; facts = event['facts']
        self.assertEqual(projection['schema_version'], 'human-handoff-projection-v1')
        self.assertEqual(event['event_id'], '43ec55c1-d49b-5f3f-9e6f-3d98629ef377')
        self.assertEqual(facts['event_id'], event['event_id'])
        self.assertEqual(facts['originating_run_ids'], [self.selected['run_id']])
        self.assertEqual(projection['review']['review_ref'], self.request['review_ref'])
        self.assertEqual(projection['parent'], dict(run_id=self.selected['run_id'],
            receipt_sha256=self.selected['receipt_sha256'], status='validated', execution_mode='api'))
        self.assertEqual(projection['documents'], self.request['source']['documents'])
        self.assertNotIn('revision', event); self.assertNotIn('expected_revision_no', event)
        for key in ('revision_id', 'revision_no', 'origin', 'review_status', 'publication_intent',
                    'reviewer_id', 'reviewed_at', 'human_overrides'): self.assertNotIn(key, facts)
        self.assertEqual(facts['occurrences'][0]['precision'], 'exact_time')
        self.assertTrue(facts['occurrences'][0]['normalization_note'].startswith('사람 수정 원본;'))
        self.assertEqual(event['area_membership'], 'uncertain')
        self.assertIsNone(facts['locations'][0]['geometry']); self.assertIsNone(facts['locations'][0]['checked_by'])
        self.assertEqual((summary['status'], summary['backend_import_supported'], summary['review_required']),
                         ('projection_only', False, True))
        self.assertEqual(summary['projection_sha256'], hashlib.sha256(_json(projection)).hexdigest())

    def test_corrected_output_and_full_original_change_records_are_preserved(self):
        output = copy.deepcopy(self.good_output); output['items'][0]['title']['value'] = '합성 사람 수정 제목'
        selected = self.make_human(uid(981), output=output); self.use_review(selected)
        packet = self.project(); facts = packet['projection']['events'][0]['facts']
        self.assertEqual(facts['title'], '합성 사람 수정 제목')
        self.assertEqual(json.loads((self.run_root / self.selected['snapshot_ref'] / 'attempt-1.output').read_bytes()), self.good_output)
        name = f"review/{selected['review_ref']}/review.json"
        stored = json.loads(packet['sources'][name][0].read_bytes())
        self.assertEqual(stored['changes'][0]['before'], self.good_output)
        self.assertEqual(stored['changes'][0]['after'], output)
        self.assertEqual(stored['changes'][0]['reviewer'], stored['review']['reviewed_by'])
        self.assertTrue(any(name.endswith('attempt-1.response') for name in packet['sources']))

    def test_failed_parent_stays_failed_while_corrected_facts_can_be_projected(self):
        parent = self.make_run(uid(552), failed=True)
        self.use_review(self.make_human(uid(982), source=parent, failed=True))
        packet = self.project()
        self.assertEqual(packet['projection']['parent']['status'], 'failed')
        self.assertEqual(packet['projection']['parent']['run_id'], uid(552))
        self.assertEqual(packet['projection']['events'][0]['facts']['title'], self.good_output['items'][0]['title']['value'])
        self.assertEqual(json.loads((self.run_root / parent['snapshot_ref'] / 'receipt.json').read_bytes())['status'], 'failed')
        self.assertFalse(packet['summary']['backend_import_supported'])

    def test_manual_parent_with_unknown_provider_clock_keeps_actual_mode(self):
        class SourceClock(datetime):
            @classmethod
            def now(cls, tz=None): return cls(2020, 1, 1, 3, tzinfo=timezone.utc)
        info = metadata(); info.update(run_id=uid(553), document_version_id=self.source['document_version_id'])
        meta, prompt, output = [self.work / name for name in ('manual-meta', 'manual-prompt', 'manual-output')]
        meta.write_bytes(_json(info)); prompt.write_bytes(render_prompt(parse_input(self.input.read_bytes())))
        output.write_bytes(_json(self.good_output))
        with patch('processing.extraction.archive.datetime', SourceClock): import_run(self.input, meta, [(prompt, output)], self.run_root)
        frozen = freeze_run(uid(553), self.run_root)
        parent = dict(run_id=uid(553), snapshot_ref=frozen['snapshot_ref'],
            receipt_sha256=hashlib.sha256((self.run_root / frozen['snapshot_ref'] / 'receipt.json').read_bytes()).hexdigest())
        self.use_review(self.make_human(uid(983), source=parent))
        projection = self.project()['projection']
        self.assertEqual(projection['parent']['execution_mode'], 'manual_import')
        self.assertNotIn('model', projection['events'][0]['facts'])

    def test_unknowns_duplicates_partial_time_and_unbound_location_are_not_filled(self):
        output = copy.deepcopy(self.good_output); item = output['items'][0]; occ = item['occurrences'][0]
        item['title'] = test_extraction_draft.DraftTest.unknown(); item['types'] = test_extraction_draft.DraftTest.unknown(knowledge='ambiguous')
        item['directions'] = dict(value=['상행', '상행'], knowledge='known', evidence_ids=['e1'], reason=None)
        occ['time_end'] = test_extraction_draft.DraftTest.unknown('종료 미기재'); occ['location_refs'] = []
        output['warnings'].append('LOCATION_BINDING_UNKNOWN')
        self.use_review(self.make_human(uid(984), output=output))
        projection = self.project()['projection']; facts = projection['events'][0]['facts']
        self.assertIsNone(facts['title']); self.assertEqual(facts['types'], [])
        self.assertEqual(facts['directions']['value'], ['상행', '상행'])
        self.assertEqual((facts['occurrences'][0]['time_start'], facts['occurrences'][0]['time_end'], facts['occurrences'][0]['precision']),
                         ('10:00', None, 'unknown'))
        self.assertIn('종료 미기재', facts['occurrences'][0]['normalization_note'])
        self.assertEqual(len(facts['locations']), 2)
        self.assertEqual(facts['occurrences'][0]['location_ids'], [facts['locations'][1]['location_id']])
        self.assertEqual(facts['locations'][1]['name']['reason'], '사람 수정 원본 장소 대응 미상')

    def test_empty_output_preserves_unused_evidence_and_explicit_context(self):
        output = copy.deepcopy(self.good_output); output.update(items=[], warnings=['NO_EVENT_FOUND'])
        self.use_review(self.make_human(uid(985), output=output))
        packet = self.project(); projection = packet['projection']
        self.assertEqual(projection['events'], []); self.assertGreater(len(projection['evidence']), 0)
        self.assertEqual(packet['summary']['event_count'], 0)
        self.assertEqual(projection['context'], dict(area_id=AREA, split_group_id=SPLIT, dictionary_version='test-dictionary-v1'))

    def test_explicit_seconds_recurrence_and_original_temporal_fields_are_retained(self):
        output = copy.deepcopy(self.good_output); occ = output['items'][0]['occurrences'][0]
        occ['time_start']['value'] = '10:00:30'
        occ['recurrence_text'] = dict(value='매주 토요일', knowledge='known', evidence_ids=['e1'], reason=None)
        self.use_review(self.make_human(uid(986), output=output))
        result = self.project()['projection']['events'][0]['facts']['occurrences'][0]
        self.assertEqual((result['time_start'], result['precision'], result['recurrence_dates']), ('10:00:30', 'unknown', None))
        self.assertIn('매주 토요일', result['normalization_note'])

    def test_strict_header_review_receipt_context_and_source_identity(self):
        for case in ('schema', 'id', 'extra', 'ref', 'receipt', 'area', 'split', 'dictionary', 'version',
                     'title', 'blocks', 'kind', 'preprocessing', 'text-hash', 'decimal'):
            value = copy.deepcopy(self.request); doc = value['source']['documents'][0]
            if case == 'schema': value['schema_version'] = 'future'
            elif case == 'id': value['handoff_id'] = '../outside'
            elif case == 'extra': value['PRIVATE_EXTRA'] = True
            elif case == 'ref': value['review_ref'] = '0' * 64
            elif case == 'receipt': value['review_receipt_sha256'] = '0' * 64
            elif case == 'area': value['area_id'] = 'invalid'
            elif case == 'split': value['split_group_id'] = 'invalid'
            elif case == 'dictionary': value['dictionary_version'] = 'PRIVATE_\nBAD'
            elif case == 'version': doc['document_version_id'] = uid(999)
            elif case == 'title': doc['title'] += 'changed'
            elif case == 'blocks': doc['block_index'][0]['text'] += 'changed'
            elif case == 'kind': value['source']['data_kind'] = 'real'
            elif case == 'preprocessing': doc['preprocessing_version'] = 'other'
            elif case == 'text-hash': doc['text_sha256'] = '0' * 64
            else: doc['version_no'] = 1.5
            with self.subTest(case=case): self.invalid(value)

    def test_time_before_review_freeze_and_tampered_images_are_rejected(self):
        with self.assertRaises(ExtractionError) as caught: self.project(at='2020-01-01T04:19:59.999999999Z')
        self.assertEqual(caught.exception.code, 'HANDOFF_TIME_INVALID')
        path = self.human_root / self.request['review_ref'] / 'output.json'
        path.chmod(0o600); path.write_bytes(path.read_bytes() + b' '); path.chmod(0o400)
        with self.assertRaises(ExtractionError) as caught: self.project()
        self.assertEqual(caught.exception.kind, 'archive')

    def test_same_parent_different_review_and_context_are_distinct_without_new_fact_ids(self):
        first = self.project()['projection']
        self.use_review(self.make_human(uid(987)))
        second = self.project()['projection']
        self.assertNotEqual(first['review'], second['review']); self.assertEqual(first['events'], second['events'])
        self.request['area_id'] = uid(988)
        third = self.project()['projection']
        self.assertEqual(third['events'][0]['event_id'], first['events'][0]['event_id'])
        self.assertEqual(third['context']['area_id'], uid(988)); self.assertNotEqual(first['events'], third['events'])

    def test_summary_privacy_size_limit_and_read_only_source_images(self):
        before = {str(p.relative_to(self.human_root)): p.read_bytes() for p in self.human_root.rglob('*') if p.is_file()}
        packet = self.project(); text = json.dumps(packet['summary'])
        for private in ('PRIVATE_', str(self.work), 'reviewed_by', 'cleaned_text', 'raw_asset_path'): self.assertNotIn(private, text)
        self.assertEqual({str(p.relative_to(self.human_root)): p.read_bytes() for p in self.human_root.rglob('*') if p.is_file()}, before)
        with patch.object(draft, 'MAX_BYTES', 1):
            with self.assertRaises(ExtractionError) as caught: self.project()
        self.assertEqual(caught.exception.code, 'DRAFT_OUTPUT_TOO_LARGE')
