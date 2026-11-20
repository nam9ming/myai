import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from processing.tests.test_human_reviews import ReviewFixture


class HumanReviewCliTest(ReviewFixture):
    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'processing.evaluation', *map(str, args)],
            cwd=Path(__file__).resolve().parents[2], capture_output=True)

    def prepare_review(self):
        self.review_path.write_bytes(self.encoded_review())
        return ['--input', self.review_path, '--run-root', self.run_root]

    def test_actual_check_freeze_verify_and_reuse_are_safe(self):
        args = self.prepare_review()
        checked = self.cli('check-review', *args)
        self.assertEqual((checked.returncode, checked.stderr), (0, b''))
        result = json.loads(checked.stdout)
        self.assertEqual(result['status'], 'declared_reviewed')
        self.assertEqual(result['review_duration_ns'], 600_000_000_000)
        frozen = self.cli('freeze-review', *args, '--root', self.review_root)
        self.assertEqual((frozen.returncode, frozen.stderr), (0, b''))
        receipt = json.loads(frozen.stdout)
        self.assertEqual(receipt['summary'], result)
        verified = self.cli('verify-review', receipt['review_ref'], '--root', self.review_root)
        self.assertEqual((verified.returncode, verified.stderr, verified.stdout), (0, b'', frozen.stdout))
        for current, _, _ in os.walk(self.run_root): Path(current).chmod(0o700)
        shutil.rmtree(self.run_root); self.input.unlink()
        reused = self.cli('freeze-review', *args, '--root', self.review_root)
        self.assertEqual((reused.returncode, reused.stdout, reused.stderr), (0, frozen.stdout, b''))
        for output in (checked, frozen, verified, reused):
            self.assertNotIn(b'PRIVATE_', output.stdout + output.stderr)
            self.assertNotIn(str(self.work).encode(), output.stdout + output.stderr)
            self.assertNotIn('합성 검토'.encode(), output.stdout + output.stderr)

    def test_actual_argument_and_malformed_input_errors_are_input2(self):
        for args in [('check-review',), ('verify-review', '../PRIVATE_BAD'),
                     ('freeze-review', '--input', 'x', '--PRIVATE_EXTRA')]:
            with self.subTest(args=args):
                result = self.cli(*args)
                self.assertEqual((result.returncode, result.stdout), (2, b''))
                self.assertNotIn(b'PRIVATE_', result.stderr)
        args = self.prepare_review(); self.review_path.write_bytes(b'PRIVATE_INVALID_JSON')
        result = self.cli('check-review', *args)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (2, b'', b'JSON_INVALID\n'))
        self.assertFalse(self.review_root.exists())

    def test_actual_conflict_and_corruption_are_archive3(self):
        args = self.prepare_review()
        result = self.cli('freeze-review', *args, '--root', self.review_root)
        self.assertEqual(result.returncode, 0)
        reference = json.loads(result.stdout)['review_ref']
        self.review_path.write_bytes(self.encoded_review(self.changed()))
        conflict = self.cli('freeze-review', *args, '--root', self.review_root)
        self.assertEqual((conflict.returncode, conflict.stdout, conflict.stderr), (3, b'', b'HUMAN_REVIEW_CONFLICT\n'))
        (self.review_root / reference / 'output.json').chmod(0o600)
        corrupt = self.cli('verify-review', reference, '--root', self.review_root)
        self.assertEqual((corrupt.returncode, corrupt.stdout, corrupt.stderr), (3, b'', b'HUMAN_REVIEW_INTEGRITY\n'))

    def test_actual_missing_input_is_safe_io5(self):
        result = self.cli('check-review', '--input', self.work / 'PRIVATE_MISSING')
        self.assertEqual((result.returncode, result.stdout, result.stderr), (5, b'', b'DATASET_IO_FAILED\n'))

    def test_actual_fractional_identity_is_archive3(self):
        args = self.prepare_review()
        frozen = self.cli('freeze-review', *args, '--root', self.review_root)
        self.assertEqual(frozen.returncode, 0)
        reference = json.loads(frozen.stdout)['review_ref']
        path = self.review_root / reference / 'identity.json'
        value = json.loads(path.read_bytes()); value['recorded_at'] = 1.5
        self.rewrite(path, json.dumps(value).encode())
        result = self.cli('verify-review', reference, '--root', self.review_root)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (3, b'', b'HUMAN_REVIEW_INTEGRITY\n'))

    def test_legacy_evaluation_command_still_scores_original_ai(self):
        control = self.work / 'legacy-control'; control.write_text(json.dumps(self.control))
        result = self.cli('check-evaluation', '--input', control, '--gold-root', self.gold_root,
                          '--run-root', self.run_root, '--initial-root', self.initial_root)
        self.assertEqual((result.returncode, result.stderr), (0, b''))
        self.assertEqual(json.loads(result.stdout)['views']['final_auto']['correct_fields'], 8)
