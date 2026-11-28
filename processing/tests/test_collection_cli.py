import contextlib
import importlib
import io
import unittest
from unittest.mock import patch


# 각 수집 명령의 잘못된 인자와 인자 해석 뒤에 불리는 작업 함수. 종료 2는 원본·실패 기록을 남긴 부분 결과에만 쓴다.
CASES = {
    "processing.collection": (["collection", "unknown"], ["read_input", "compare_sources"]),
    "processing.collection.capture": (["capture", "living", "--web-id"], ["capture"]),
    "processing.collection.batch": (["batch", "living", "--max-pages", "x"], ["capture_batch"]),
    "processing.collection.portal": (["portal", "unknown"], ["collect_portal"]),
    "processing.collection.odcloud": (["odcloud", "road-construction"], ["collect_odcloud"]),
    "processing.collection.media": (["media", "inspect", "--board", "other", "--web-id", "1", "--name", "x"],
                                    ["inspect_notice", "store_media"]),
    "processing.collection.d03": (["d03", "--name"], ["prepare"]),
    "processing.collection.road_batch": (["road_batch", "closed", "--name", "x"], ["capture_road_batch"]),
    "processing.collection.board_batch": (["board_batch", "library", "--name", "x"], ["capture_board_batch"]),
    "processing.collection.welfare_batch": (["welfare_batch", "--name", "x", "--max-pages", "x"], ["collect_welfare"]),
    "processing.collection.edu_course_batch": (["edu_course_batch", "--name", "x", "--max-items", "x"],
                                               ["capture_course_batch"]),
    "processing.collection.library_program_batch": (["library_program_batch", "--name", "x", "--start-page", "x"],
                                                    ["capture_program_batch"]),
    "processing.collection.gosi_batch": (["gosi_batch", "fetch", "--name", "x"], ["capture_gosi_batch", "read_gosi_batch"]),
    "processing.collection.youth_batch": (["youth_batch", "capture", "--name", "x", "--max-pages", "x"],
                                          ["capture_youth_batch", "read_youth_batch"]),
    "processing.collection.arthall_batch": (["arthall_batch", "capture", "--year", "x", "--month", "1", "--name", "x"],
                                            ["capture_arthall_batch", "read_arthall_batch"]),
}


class CollectionCliTest(unittest.TestCase):
    def test_argument_errors_exit_one_without_requests(self):
        for module_name, (argv, workers) in CASES.items():
            module = importlib.import_module(module_name if module_name != "processing.collection"
                                             else "processing.collection.__main__")
            with (self.subTest(module=module_name), patch("sys.argv", argv),
                  contextlib.ExitStack() as stack, contextlib.redirect_stderr(io.StringIO()) as error):
                for worker in workers:
                    stack.enter_context(patch.object(module, worker, side_effect=AssertionError("요청 금지")))
                with self.assertRaises(SystemExit) as caught:
                    module.main()
                self.assertEqual(caught.exception.code, 1)
                self.assertIn("입력 오류", error.getvalue())

    def test_help_still_exits_zero(self):
        from processing.collection import batch
        with patch("sys.argv", ["batch", "--help"]), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                batch.main()
        self.assertEqual(caught.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
