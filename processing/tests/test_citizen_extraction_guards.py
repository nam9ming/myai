import copy
import hashlib
import json
from unittest.mock import patch

from processing.extraction.archive import freeze_run, import_run
from processing.extraction.validation import ExtractionError
from processing.tests.test_dataset import uid
from processing.tests.test_evaluation_records import DatasetClock
from processing.tests.test_extraction_prompt_metadata import metadata
from processing.tests.test_human_handoff import HumanHandoffFixture


class CitizenEvaluationGuardsTest(HumanHandoffFixture):
    def citizen_parent(self, failed=False):
        body = metadata()
        body.update(run_id=uid(977 if failed else 976), document_version_id=self.source['document_version_id'],
                    schema_version='extract-citizen-v1')
        meta = self.work / 'citizen-metadata.json'; meta.write_text(json.dumps(body))
        prompt = self.work / 'citizen-prompt'; prompt.write_bytes(b'actual synthetic prompt')
        output = dict(schema_version='extract-citizen-v1', document_version_id=body['document_version_id'],
                      items=[], evidence=[], warnings=['NO_EVENT_FOUND'])
        raw = self.work / 'citizen-output'; raw.write_bytes(b'\xffsynthetic' if failed else json.dumps(output).encode())
        with patch('processing.extraction.archive.datetime', DatasetClock):
            import_run(self.input, meta, [(prompt, raw)], self.run_root)
        packet = freeze_run(body['run_id'], self.run_root)
        return dict(run_id=body['run_id'], snapshot_ref=packet['snapshot_ref'],
            receipt_sha256=hashlib.sha256((self.run_root / packet['snapshot_ref'] / 'receipt.json').read_bytes()).hexdigest()), output

    def citizen_review(self):
        parent, output = self.citizen_parent()
        self.good_output = output
        return self.make_human(uid(978), source=parent, output=output)

    def test_direct_citizen_success_and_failure_never_reach_eight_field_scorer(self):
        for failed in (False, True):
            with self.subTest(failed=failed):
                selected, _ = self.citizen_parent(failed)
                control = copy.deepcopy(self.ai_control)
                control['documents'][0].update(selected)
                with patch('processing.evaluation.records.score_document', side_effect=AssertionError('legacy scorer reached')):
                    with self.assertRaises(ExtractionError) as caught:
                        self.evaluate(control, run_root=self.run_root)
                self.assertEqual(caught.exception.code, 'EVALUATION_SCHEMA_UNSUPPORTED')

    def test_citizen_human_review_never_reaches_eight_field_scorer(self):
        selected = self.citizen_review()
        control = copy.deepcopy(self.control)
        control['documents'][0].update(selected)
        with patch('processing.evaluation.records.score_document', side_effect=AssertionError('legacy scorer reached')):
            with self.assertRaises(ExtractionError) as caught:
                self.evaluate(control)
        self.assertEqual(caught.exception.code, 'EVALUATION_SCHEMA_UNSUPPORTED')

    def test_citizen_human_review_never_enters_legacy_handoff_projection(self):
        self.use_review(self.citizen_review())
        with self.assertRaises(ExtractionError) as caught:
            self.project()
        self.assertEqual(caught.exception.code, 'HANDOFF_SCHEMA_UNSUPPORTED')
