"""고정 G4 시민 review를 명시 D06 사실 인계로 연결하는 공개 합성 시험."""

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import errno
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

from processing.evaluation import handoff_storage, human_handoff, reviews
from processing.extraction import archive, draft
from processing.extraction.validation import ExtractionError, MAX_BYTES


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/citizen-g4'
MANIFEST_SHA256 = 'd747977a82af2aa43a1ea635d5068589441d56e803112578ae953745420f2979'
PROJECT_AT = '2026-11-18T03:00:00Z'
FROZEN_AT = '2026-11-18T03:01:00Z'
HANDOFF_ID = '40000000-0000-4000-8000-000000000001'
SPLIT_ID = '40000000-0000-4000-8000-000000000002'
OFFLINE_CLI = '''import runpy, socket, sys
from datetime import datetime
from unittest.mock import patch
def forbidden(*args, **kwargs):
    raise AssertionError("citizen handoff verification must stay offline")
socket.socket = forbidden
socket.getaddrinfo = forbidden
class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls.fromisoformat("2026-11-18T03:01:00Z")
with patch("processing.evaluation.human_handoff.datetime", Clock), patch("processing.extraction.archive.datetime", Clock):
    runpy.run_module(sys.argv.pop(1), run_name="__main__")
'''


def fixed_clock(value):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            result = datetime.fromisoformat(value)
            return result if tz is None else result.astimezone(tz)
    return Clock


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def materialize_g4(work):
    raw = (FIXTURE / 'manifest.json').read_bytes()
    assert digest(raw) == MANIFEST_SHA256
    manifest = json.loads(raw)
    assert digest((FIXTURE / 'verification.json').read_bytes()) == manifest['verification']['sha256']
    base = work / 'g4'
    shutil.copytree(FIXTURE / 'original', base)
    for relative, expected in manifest['entries'].items():
        path = base / relative
        if expected['type'] == 'file':
            content = path.read_bytes()
            assert digest(content) == expected['sha256'] and len(content) == expected['size']
        path.chmod(int(expected['mode'], 8))
    return base, manifest


def selection_for(base, manifest, case='review_success'):
    selected = manifest['cases']['review_failed_parent' if case == 'review_failed' else case]
    return dict(schema_version='citizen-human-handoff-v1', handoff_id=HANDOFF_ID,
        review_ref=selected['review_ref'], review_receipt_sha256=selected['receipt_sha256'],
        source=json.loads((base / 'setup/source-import.json').read_bytes()), split_group_id=SPLIT_ID)


def offline_cli(args):
    return subprocess.run([sys.executable, '-B', '-c', OFFLINE_CLI, *args], cwd=ROOT,
        env={'PATH': os.defpath, 'PYTHONDONTWRITEBYTECODE': '1'}, capture_output=True, timeout=30)


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_mode & 0o777, digest(p.read_bytes()))
            for p in root.rglob('*') if p.is_file()}


def empty_review(work, base, manifest):
    value = json.loads((base / 'setup/review_success.json').read_bytes())
    previous = copy.deepcopy(value['output'])
    value['review_id'] = '40000000-0000-4000-8000-000000000019'
    value['output'].update(items=[], warnings=['NO_EVENT_FOUND'])
    value['changes'] = [dict(field_path='output', before=previous, after=copy.deepcopy(value['output']),
        reason='합성 빈 사건 선언', evidence_ids=['e1'], reviewer=value['review']['reviewed_by'],
        time=value['review']['finished_at'])]
    path = work / 'empty-review.json'; path.write_bytes(archive._json(value))
    review_root = work / 'empty-reviews'
    with patch('processing.evaluation.reviews.datetime', fixed_clock('2026-11-18T01:15:00Z')), \
         patch('processing.extraction.archive.datetime', fixed_clock('2026-11-18T01:15:00Z')):
        result = reviews.freeze_review(path, review_root, base / 'runs')
    selection = selection_for(base, manifest)
    selection.update(review_ref=result['review_ref'],
                     review_receipt_sha256=digest((review_root / result['review_ref'] / 'receipt.json').read_bytes()))
    return selection, review_root


def create_citizen_handoff_fixture(work, *, case='review_success'):
    """Java 시험도 사용하는 공개 합성 fixture. 호출자가 work의 생성·정리를 소유한다."""
    work = Path(work).resolve(); work.mkdir(parents=True, exist_ok=True)
    base, manifest = materialize_g4(work)
    selection, review_root = (empty_review(work, base, manifest) if case == 'empty' else
                             (selection_for(base, manifest, case), base / 'reviews'))
    path = work / 'selection.json'; path.write_bytes(archive._json(selection))
    root = work / 'handoffs'
    with patch('processing.evaluation.human_handoff.datetime', fixed_clock(PROJECT_AT)), \
         patch('processing.extraction.archive.datetime', fixed_clock(FROZEN_AT)):
        receipt = handoff_storage.freeze_handoff(path, root, review_root)
    folder = root / receipt['handoff_ref']
    return dict(handoff_root=str(root), handoff_ref=receipt['handoff_ref'],
        receipt_sha256=digest((folder / 'receipt.json').read_bytes()), source_root=str(base / 'setup'),
        source_file=str(base / 'setup/source-import.json'), run_root=str(base / 'runs'), review_root=str(review_root),
        receipt=receipt, projection=json.loads((folder / 'projection.json').read_bytes()))


class CitizenHandoffTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.work = Path(self.temporary.name).resolve()
        self.addCleanup(self.cleanup)
        self.base, self.manifest = materialize_g4(self.work)
        self.review_root = self.base / 'reviews'
        self.handoff_root = self.work / 'handoffs'
        self.request = selection_for(self.base, self.manifest)

    def cleanup(self):
        for current, _, _ in os.walk(self.work): Path(current).chmod(0o700)
        self.temporary.cleanup()

    def write_request(self, value=None):
        path = self.work / 'selection.json'
        path.write_bytes(archive._json(self.request if value is None else value))
        return path

    def project(self, value=None):
        return human_handoff.project_handoff(archive._json(self.request if value is None else value),
                                            self.review_root, projected_at=PROJECT_AT)

    def freeze(self, value=None):
        with patch('processing.evaluation.human_handoff.datetime', fixed_clock(PROJECT_AT)), \
             patch('processing.extraction.archive.datetime', fixed_clock(FROZEN_AT)):
            return handoff_storage.freeze_handoff(self.write_request(value), self.handoff_root, self.review_root)

    def test_actual_check_handoff_accepts_explicit_citizen_six_key_selection(self):
        process = offline_cli(['processing.evaluation', 'check-handoff', '--input', str(self.write_request()),
                               '--review-root', str(self.review_root)])
        self.assertEqual(process.returncode, 0, process.stderr.decode('utf-8'))
        result = json.loads(process.stdout)
        self.assertEqual(result['status'], 'projection_only')
        self.assertEqual(result['event_count'], 5)

    def test_citizen_projection_keeps_five_categories_twelve_raw_facts_and_explicit_group(self):
        before = snapshot(self.base)
        packet = self.project(); value = packet['projection']
        self.assertEqual(value['schema_version'], 'citizen-human-handoff-projection-v1')
        self.assertEqual(value['context'], dict(split_group_id=SPLIT_ID))
        original = json.loads((self.base / 'setup/review_success.json').read_bytes())['output']
        fields = ('application_period', 'occurrences', 'regions', 'locations', 'residency_requirement',
                  'target', 'eligibility', 'application_method', 'preparation', 'cost', 'recruitment', 'lifecycle')
        mapping = {old['evidence_id']: new['evidence_id'] for old, new in zip(original['evidence'], value['evidence'], strict=True)}
        for old, event in zip(original['items'], value['events'], strict=True):
            self.assertEqual(set(event), {'event_id', 'document_links', 'relations', 'suspected_duplicate_ids', 'split_group_id', 'facts'})
            self.assertEqual(event['split_group_id'], SPLIT_ID)
            facts = event['facts']
            self.assertEqual(set(facts), {'event_id', 'title', 'categories', 'source_version_ids', 'originating_run_ids', *fields})
            self.assertEqual(facts['title'], old['title']['value']); self.assertEqual(facts['categories'], old['categories']['value'])
            self.assertEqual(facts['event_id'], event['event_id'])
            for name in fields:
                self.assertEqual(facts[name], dict(old[name], evidence_ids=[mapping[key] for key in old[name]['evidence_ids']]))
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(value['documents'], self.request['source']['documents'])
        self.assertEqual((packet['summary']['status'], packet['summary']['backend_import_supported'],
                          packet['summary']['review_required']), ('projection_only', False, True))
        self.assertEqual(value['events'][0]['facts']['preparation']['value'], [])
        self.assertIsNone(value['events'][0]['facts']['cost']['value'])
        self.assertIn('😀', value['evidence'][0]['quote'])

    def test_unknown_title_and_categories_are_unresolved_without_altering_review(self):
        for case in ('review_title_unknown', 'review_category_unknown'):
            before = snapshot(self.base)
            with self.subTest(case=case), self.assertRaises(ExtractionError) as caught:
                self.project(selection_for(self.base, self.manifest, case))
            self.assertEqual((caught.exception.code, caught.exception.kind), ('HANDOFF_CITIZEN_FACTS_UNRESOLVED', 'input'))
            self.assertEqual(snapshot(self.base), before)

    def test_group_does_not_change_fact_ids_and_parent_failure_is_retained(self):
        first = self.project()['projection']
        changed = copy.deepcopy(self.request); changed['split_group_id'] = '40000000-0000-4000-8000-000000000003'
        second = self.project(changed)['projection']
        self.assertEqual([e['event_id'] for e in first['events']], [e['event_id'] for e in second['events']])
        self.assertEqual(first['evidence'], second['evidence'])
        failed = self.project(selection_for(self.base, self.manifest, 'review_failed'))['projection']
        self.assertEqual((failed['parent']['status'], failed['parent']['execution_mode']), ('failed', 'manual_import'))
        self.assertEqual(len(failed['events']), 5)

    def test_empty_review_keeps_context_unused_evidence_and_has_no_fake_events(self):
        selected, self.review_root = empty_review(self.work, self.base, self.manifest)
        packet = self.project(selected)
        self.assertEqual(packet['projection']['events'], [])
        self.assertEqual(packet['projection']['context'], dict(split_group_id=SPLIT_ID))
        self.assertEqual(len(packet['projection']['evidence']), 5)

    def test_closed_selection_source_binding_and_time_errors(self):
        for key in self.request:
            value = copy.deepcopy(self.request); del value[key]
            with self.subTest(missing=key), self.assertRaises(ExtractionError): self.project(value)
        for key in ('area_id', 'dictionary_version', 'unexpected'):
            value = copy.deepcopy(self.request); value[key] = 'forbidden'
            with self.subTest(extra=key), self.assertRaises(ExtractionError): self.project(value)
        for key, replacement in [('split_group_id', 'unknown'), ('review_receipt_sha256', '0' * 64), ('handoff_id', '../escape')]:
            value = copy.deepcopy(self.request); value[key] = replacement
            with self.subTest(key=key), self.assertRaises(ExtractionError): self.project(value)
        for key in ('title', 'document_version_id', 'preprocessing_version', 'text_sha256'):
            value = copy.deepcopy(self.request); value['source']['documents'][0][key] = 'wrong'
            with self.subTest(source=key), self.assertRaises(ExtractionError): self.project(value)
        with self.assertRaises(ExtractionError) as caught:
            human_handoff.project_handoff(archive._json(self.request), self.review_root, projected_at='2026-11-18T00:00:00Z')
        self.assertEqual(caught.exception.code, 'HANDOFF_TIME_INVALID')
        with patch.object(draft, 'MAX_BYTES', 1), self.assertRaises(ExtractionError) as caught: self.project()
        self.assertEqual(caught.exception.code, 'DRAFT_OUTPUT_TOO_LARGE')

    def test_old_request_with_citizen_parent_stays_unsupported(self):
        value = dict(self.request, schema_version='human-handoff-v1',
                     area_id='40000000-0000-4000-8000-000000000004', dictionary_version='synthetic-legacy')
        with self.assertRaises(ExtractionError) as caught: self.project(value)
        self.assertEqual(caught.exception.code, 'HANDOFF_SCHEMA_UNSUPPORTED')

    def test_citizen_request_never_accepts_verified_legacy_parent(self):
        old_root = Path(__file__).parent / 'fixtures/citizen-legacy/archives/handoffs'
        copied = self.work / 'legacy'; shutil.copytree(next(old_root.iterdir()), copied)
        for current, _, files in os.walk(copied, topdown=False):
            folder = Path(current)
            for name in files: (folder / name).chmod(0o400)
            folder.chmod(0o500)
        self.review_root = copied / 'review'
        review = next(self.review_root.iterdir())
        selected = dict(self.request, review_ref=review.name,
                        review_receipt_sha256=digest((review / 'receipt.json').read_bytes()))
        with self.assertRaises(ExtractionError) as caught: self.project(selected)
        self.assertEqual(caught.exception.code, 'HANDOFF_SCHEMA_UNSUPPORTED')

    def test_same_parent_modified_review_keeps_event_and_evidence_ids(self):
        first = self.project()['projection']
        value = json.loads((self.base / 'setup/review_success.json').read_bytes())
        before = copy.deepcopy(value['output'])
        value['review_id'] = '40000000-0000-4000-8000-000000000025'
        value['output']['items'][0]['title']['value'] = '합성 사람 수정 제목'
        value['changes'] = [dict(field_path='output', before=before, after=copy.deepcopy(value['output']),
            reason='합성 제목 수정', evidence_ids=['e1'], reviewer=value['review']['reviewed_by'],
            time=value['review']['finished_at'])]
        path = self.work / 'changed-review.json'; path.write_bytes(archive._json(value))
        self.review_root = self.work / 'changed-reviews'
        with patch('processing.evaluation.reviews.datetime', fixed_clock('2026-11-18T01:15:00Z')), \
             patch('processing.extraction.archive.datetime', fixed_clock('2026-11-18T01:15:00Z')):
            receipt = reviews.freeze_review(path, self.review_root, self.base / 'runs')
        selected = dict(self.request, review_ref=receipt['review_ref'], review_receipt_sha256=digest(
            (self.review_root / receipt['review_ref'] / 'receipt.json').read_bytes()))
        second = self.project(selected)['projection']
        self.assertEqual([e['event_id'] for e in first['events']], [e['event_id'] for e in second['events']])
        self.assertEqual(first['evidence'], second['evidence'])
        self.assertEqual(second['events'][0]['facts']['title'], '합성 사람 수정 제목')

    def test_full_freeze_replays_without_original_roots_and_actual_cli_agrees(self):
        before = snapshot(self.base)
        result = self.freeze(); image = self.handoff_root / result['handoff_ref']
        original = snapshot(image)
        ref = self.request['review_ref']; review = self.review_root / ref
        for name, (_, checksum) in snapshot(review).items():
            self.assertEqual(original[f'review/{ref}/{name}'], (0o400, checksum))
        self.assertEqual(snapshot(self.base), before)
        self.base.rename(self.work / 'original-roots-gone')
        self.assertEqual(handoff_storage.verify_handoff(result['handoff_ref'], self.handoff_root), result)
        self.assertEqual(self.freeze(), result)
        process = offline_cli(['processing.evaluation', 'verify-handoff', result['handoff_ref'], '--root', str(self.handoff_root)])
        self.assertEqual((process.returncode, process.stderr), (0, b''))
        self.assertEqual(json.loads(process.stdout), result)
        self.assertEqual(snapshot(image), original)

    def test_actual_freeze_cli_and_summary_do_not_expose_payload_or_reviewer(self):
        result = offline_cli(['processing.evaluation', 'freeze-handoff', '--input', str(self.write_request()),
            '--root', str(self.handoff_root), '--review-root', str(self.review_root)])
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        for forbidden in (str(self.work), 'cleaned_text', 'raw_asset_path', 'SYNTHETIC_G4_DECLARATION'):
            self.assertNotIn(forbidden, result.stdout.decode())
        receipt = json.loads(result.stdout)
        self.assertEqual(handoff_storage.verify_handoff(receipt['handoff_ref'], self.handoff_root), receipt)

    def test_old_new_handoff_id_collision_preserves_existing_sealed_image(self):
        old_root = Path(__file__).parent / 'fixtures/citizen-legacy/archives/handoffs'
        old_image = next(old_root.iterdir())
        self.handoff_root.mkdir()
        image = self.handoff_root / old_image.name; shutil.copytree(old_image, image)
        for current, _, files in os.walk(image, topdown=False):
            folder = Path(current)
            for name in files: (folder / name).chmod(0o400)
            folder.chmod(0o500)
        value = copy.deepcopy(self.request)
        value['handoff_id'] = json.loads((image / 'selection.json').read_bytes())['handoff_id']
        before = snapshot(image)
        with self.assertRaises(ExtractionError) as caught: self.freeze(value)
        self.assertEqual(caught.exception.code, 'HANDOFF_CONFLICT')
        self.assertEqual(snapshot(image), before)

    def test_changed_selection_and_partial_install_never_replace_sources(self):
        result = self.freeze(); original = snapshot(self.handoff_root)
        changed = dict(self.request, split_group_id='40000000-0000-4000-8000-000000000005')
        with self.assertRaises(ExtractionError) as caught: self.freeze(changed)
        self.assertEqual(caught.exception.code, 'HANDOFF_CONFLICT')
        self.assertEqual(snapshot(self.handoff_root), original)
        self.handoff_root = self.work / 'failed-install'
        before = snapshot(self.base)
        with patch.object(handoff_storage, '_rename_exclusive', side_effect=OSError(errno.ENOSPC, 'synthetic')):
            with self.assertRaises(OSError): self.freeze()
        self.assertEqual(list(self.handoff_root.iterdir()), [])
        self.assertEqual(snapshot(self.base), before)

    def test_concurrent_identical_selection_installs_one_exact_image(self):
        path = self.write_request()
        with patch('processing.evaluation.human_handoff.datetime', fixed_clock(PROJECT_AT)), \
             patch('processing.extraction.archive.datetime', fixed_clock(FROZEN_AT)), \
             ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: handoff_storage.freeze_handoff(path, self.handoff_root, self.review_root), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(list(self.handoff_root.iterdir())), 1)

    def test_oversized_failed_parent_is_copied_whole_and_stays_failed(self):
        raw = b'\xff' + b'x' * (MAX_BYTES + 32)
        output = self.work / 'large-failed-output'; output.write_bytes(raw)
        meta = self.base / 'setup/manual_failed.metadata.json'
        run_root = self.work / 'large-runs'
        run_id = self.manifest['cases']['manual_failed']['run_id']
        with patch('processing.extraction.archive.datetime', fixed_clock('2026-11-18T00:00:00Z')):
            archive.import_run(self.base / 'setup/input.json', meta, [(self.base / 'setup/actual-prompt.bin', output)], run_root)
            parent = archive.freeze_run(run_id, run_root)
        review = json.loads((self.base / 'setup/review_failed_parent.json').read_bytes())
        review['review_id'] = '40000000-0000-4000-8000-000000000099'
        review['source'].update(snapshot_ref=parent['snapshot_ref'],
            receipt_sha256=digest((run_root / parent['snapshot_ref'] / 'receipt.json').read_bytes()))
        path = self.work / 'large-review.json'; path.write_bytes(archive._json(review))
        self.review_root = self.work / 'large-reviews'
        with patch('processing.evaluation.reviews.datetime', fixed_clock('2026-11-18T01:15:00Z')), \
             patch('processing.extraction.archive.datetime', fixed_clock('2026-11-18T01:15:00Z')):
            receipt = reviews.freeze_review(path, self.review_root, run_root)
        self.request.update(review_ref=receipt['review_ref'], review_receipt_sha256=digest(
            (self.review_root / receipt['review_ref'] / 'receipt.json').read_bytes()))
        frozen = self.freeze(); image = self.handoff_root / frozen['handoff_ref']
        nested = image / 'review' / receipt['review_ref'] / 'source' / parent['snapshot_ref'] / 'attempt-1.output'
        self.assertEqual(nested.read_bytes(), raw)
        self.assertEqual(frozen['summary']['source_status'], 'failed')
        self.assertEqual(handoff_storage.verify_handoff(frozen['handoff_ref'], self.handoff_root), frozen)

    def test_new_projection_tamper_missing_extra_symlink_and_permissions_are_rejected(self):
        result = self.freeze(); image = self.handoff_root / result['handoff_ref']
        for case in ('projection', 'missing', 'extra', 'symlink', 'mode'):
            root = self.work / ('corrupt-' + case); copied = root / image.name; shutil.copytree(image, copied)
            copied.chmod(0o700); target = copied / 'projection.json'
            if case == 'projection': target.chmod(0o600); target.write_bytes(b'{}'); target.chmod(0o400)
            elif case == 'missing': target.unlink()
            elif case == 'extra': (copied / 'extra').write_bytes(b'public synthetic'); (copied / 'extra').chmod(0o400)
            elif case == 'symlink': target.unlink(); target.symlink_to(image / 'projection.json')
            else: target.chmod(0o600)
            copied.chmod(0o500)
            before = snapshot(copied)
            with self.subTest(case=case), self.assertRaises(ExtractionError) as caught:
                handoff_storage.verify_handoff(image.name, root)
            self.assertEqual(caught.exception.code, 'HANDOFF_INTEGRITY')
            self.assertEqual(snapshot(copied), before)

    def test_g4_frozen_expected_files_modes_and_original_cli_hashes_remain_unchanged(self):
        expected_cli = json.loads((FIXTURE / 'verification.json').read_bytes())['calls'][:6]
        before = snapshot(self.base)
        for expected in expected_cli:
            case = self.manifest['cases'][expected['case']]; folder = self.base / case['archive']
            args = (['processing.extraction', 'verify-sealed', case['run_id'], '--root', str(folder.parent)]
                    if case['kind'] == 'extraction' else
                    ['processing.evaluation', 'verify-review', case['review_ref'], '--root', str(folder.parent)])
            result = offline_cli(args)
            self.assertEqual((result.returncode, digest(result.stdout), digest(result.stderr)),
                             (expected['expected_exit'], expected['stdout_sha256'], expected['stderr_sha256']))
        self.assertEqual(snapshot(self.base), before)


if __name__ == '__main__':
    unittest.main()
