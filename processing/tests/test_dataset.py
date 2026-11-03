import copy
import hashlib
import json
from pathlib import Path
import unittest

from processing.evaluation.dataset import validate_manifest
from processing.extraction.validation import ExtractionError, MAX_BYTES

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / 'processing/examples/dataset-manifest.json'


def uid(number):
    return f'40000000-0000-4000-8000-{number:012x}'


def manifest():
    return json.loads(FIXTURE.read_bytes())


class DatasetTest(unittest.TestCase):
    def check(self, value):
        return validate_manifest(json.dumps(value, ensure_ascii=False).encode())

    def invalid(self, value, code=None):
        with self.assertRaises(ExtractionError) as caught:
            self.check(value)
        if code:
            self.assertEqual(caught.exception.code, code)
        self.assertNotIn('PRIVATE_SECRET', str(caught.exception))

    def test_counts_documents_once_and_reports_fixed_targets(self):
        raw = FIXTURE.read_bytes(); report = validate_manifest(raw)
        self.assertEqual(report['manifest_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(report['data_kind'], 'synthetic')
        self.assertEqual(report['counts'], dict(documents=4, document_versions=5, events=3, groups=2))
        self.assertEqual(report['splits']['dev']['documents'], 3)
        self.assertEqual(report['splits']['holdout']['document_versions'], 1)
        self.assertEqual(report['targets'], dict(documents=40, dev=20, holdout=20, data_kind='real'))
        self.assertEqual(report['shortfall'], dict(documents=36, dev=17, holdout=19))
        self.assertEqual(report['holdout_status'], 'unexposed_as_declared')
        self.assertEqual(report['splits']['dev']['types']['construction'], 2)
        self.assertEqual(report['splits']['dev']['features']['multiple_times'], 1)
        self.assertNotIn('example.org', json.dumps(report))

    def test_shared_document_component_cannot_cross_splits(self):
        value = manifest(); value['split_assignments'][2]['split'] = 'holdout'
        self.invalid(value, 'DATASET_SPLIT_LEAK')

    def test_component_and_declared_groups_must_correspond(self):
        for mutate in ('split_component', 'merge_disconnected', 'event_group'):
            value = manifest()
            if mutate == 'split_component':
                value['split_assignments'][2]['split_group_id'] = uid(33)
            elif mutate == 'merge_disconnected':
                value['split_assignments'][3]['split_group_id'] = uid(31)
                value['events'][2]['split_group_id'] = uid(31)
            else:
                value['events'][0]['split_group_id'] = uid(33)
            with self.subTest(mutate=mutate):
                self.invalid(value, 'DATASET_GROUP_INVALID')

    def test_reviewed_relations_join_otherwise_disconnected_documents(self):
        for kind in ('corrects', 'cancels', 'reposts', 'duplicates'):
            value = manifest(); edge = copy.deepcopy(value['relations'][0])
            edge.update(from_document_id=uid(4), to_document_id=uid(3), type=kind)
            value['relations'].append(edge)
            with self.subTest(kind=kind):
                self.invalid(value, 'DATASET_SPLIT_LEAK')

    def test_documents_without_events_still_require_one_assignment(self):
        value = manifest(); value['events'].pop()
        self.assertEqual(self.check(value)['counts']['documents'], 4)
        for assignments in (value['split_assignments'][:-1], value['split_assignments'] * 2):
            broken = copy.deepcopy(value); broken['split_assignments'] = assignments
            self.invalid(broken)

    def test_document_and_version_identity_are_unique(self):
        for mutate in ('document', 'version', 'same_document_version', 'url_fragment'):
            value = manifest()
            if mutate == 'document':
                value['documents'].append(copy.deepcopy(value['documents'][0]))
            elif mutate == 'version':
                value['documents'][1]['versions'][0]['document_version_id'] = uid(11)
            elif mutate == 'same_document_version':
                value['documents'][0]['versions'] *= 2
            else:
                value['documents'][3]['official_url'] = value['documents'][0]['official_url'] + '#section'
            with self.subTest(mutate=mutate):
                self.invalid(value)

    def test_references_and_relationship_cycles_fail_closed(self):
        for mutate in ('event_ref', 'relation_ref', 'self_relation', 'cycle', 'duplicate_edge', 'duplicate_doc_ref', 'suspect'):
            value = manifest()
            if mutate == 'event_ref': value['events'][0]['document_ids'][0] = uid(99)
            elif mutate == 'relation_ref': value['relations'][0]['to_document_id'] = uid(99)
            elif mutate == 'self_relation': value['relations'][0]['to_document_id'] = uid(2)
            elif mutate == 'cycle':
                edge = copy.deepcopy(value['relations'][0]); edge.update(from_document_id=uid(1), to_document_id=uid(2))
                value['relations'].append(edge)
            elif mutate == 'duplicate_edge': value['relations'] *= 2
            elif mutate == 'duplicate_doc_ref': value['events'][0]['document_ids'] *= 2
            else: value['events'][0]['suspected_duplicate_ids'] = [uid(99)]
            with self.subTest(mutate=mutate): self.invalid(value)

    def test_suspected_duplicates_warn_without_automatic_merge(self):
        value = manifest(); value['events'][1]['suspected_duplicate_ids'] = [uid(23)]
        report = self.check(value)
        self.assertEqual(report['counts']['groups'], 2)
        self.assertEqual(report['holdout_status'], 'review_required')
        self.assertIn('SUSPECTED_DUPLICATE_CROSSES_SPLIT', report['holdout_warnings'])
        value['events'][1]['suspected_duplicate_ids'] = [uid(21)]
        self.assertNotIn('SUSPECTED_DUPLICATE_CROSSES_SPLIT', self.check(value)['holdout_warnings'])

    def test_holdout_exposure_and_group_review_are_not_blindness_proof(self):
        for status, warning in (('development', 'HOLDOUT_DEVELOPMENT_EXPOSURE'), ('unknown', 'HOLDOUT_EXPOSURE_UNKNOWN')):
            value = manifest(); value['documents'][3]['exposure_status'] = status
            report = self.check(value)
            self.assertEqual(report['holdout_status'], 'review_required')
            self.assertIn(warning, report['holdout_warnings'])
        value = manifest(); value['grouping_review'].update(reviewed_by=None, reviewed_at=None)
        self.assertIn('GROUPING_UNREVIEWED', self.check(value)['holdout_warnings'])

    def test_dev_only_dataset_reports_absent_holdout_and_shortfall(self):
        value = manifest()
        for assignment in value['split_assignments']: assignment['split'] = 'dev'
        report = self.check(value)
        self.assertEqual(report['holdout_status'], 'absent')
        self.assertEqual(report['shortfall'], dict(documents=36, dev=16, holdout=20))

    def test_group_review_older_than_a_relation_requires_review(self):
        value = manifest(); value['grouping_review']['reviewed_at'] = '2026-11-02T00:00:00Z'
        report = self.check(value)
        self.assertEqual(report['holdout_status'], 'review_required')
        self.assertIn('GROUPING_REVIEW_OUTDATED', report['holdout_warnings'])

    def test_unknown_values_empty_lists_bad_times_and_urls_rejected(self):
        for mutate in ('version', 'kind', 'docs', 'versions', 'types', 'tag', 'exposure', 'time', 'partial_review', 'url', 'auth_url'):
            value = manifest()
            if mutate == 'version': value['schema_version'] = 'other'
            elif mutate == 'kind': value['data_kind'] = 'other'
            elif mutate == 'docs': value['documents'] = []
            elif mutate == 'versions': value['documents'][0]['versions'] = []
            elif mutate == 'types': value['documents'][0]['types'] = ['other']
            elif mutate == 'tag': value['documents'][0]['feature_tags'] = ['other']
            elif mutate == 'exposure': value['documents'][0]['exposure_status'] = 'blind'
            elif mutate == 'time': value['split_assignments'][0]['assigned_at'] = '2026-02-30T00:00:00Z'
            elif mutate == 'partial_review': value['grouping_review']['reviewed_at'] = None
            elif mutate == 'url': value['documents'][0]['official_url'] = 'file:///PRIVATE_SECRET'
            else: value['documents'][0]['official_url'] = 'https://user:PRIVATE_SECRET@example.org/a'
            with self.subTest(mutate=mutate): self.invalid(value)

    def test_extra_gold_conditions_and_raw_values_never_echoed(self):
        for key in ('gold_items', 'conditions', 'PRIVATE_SECRET'):
            value = manifest(); value[key] = 'PRIVATE_SECRET'
            self.invalid(value)
        value = manifest(); value['documents'][0]['types'] = []
        self.assertEqual(self.check(value)['splits']['dev']['types']['unknown'], 1)

    def test_json_boundary_size_unicode_duplicate_keys_and_depth(self):
        for raw in (b'{}', b'\xff', b'{"x":1,"x":2}', b'{"x":"\\ud800"}', b'[' * 102 + b']' * 102, b' ' * (MAX_BYTES + 1)):
            with self.subTest(size=len(raw)), self.assertRaises(ExtractionError): validate_manifest(raw)

    def test_thousand_document_correction_chain_has_no_recursion_dependency(self):
        value = manifest(); template = value['documents'][0]
        value['documents'] = [dict(template, document_id=uid(1000+i), official_url=f'https://example.org/long/{i}',
                                   versions=[dict(document_version_id=uid(3000+i), input_sha256='a'*64)]) for i in range(1000)]
        value['events'] = [dict(value['events'][0], document_ids=[uid(1000+i) for i in range(1000)])]
        value['relations'] = [dict(value['relations'][0], from_document_id=uid(1000+i), to_document_id=uid(999+i)) for i in range(1,1000)]
        value['split_assignments'] = [dict(value['split_assignments'][0], document_id=uid(1000+i)) for i in range(1000)]
        report = self.check(value)
        self.assertEqual(report['counts'], dict(documents=1000, document_versions=1000, events=1, groups=1))


if __name__ == '__main__':
    unittest.main()
