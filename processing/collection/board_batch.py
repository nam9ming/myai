"""안성시청 공지 게시판의 목록과 상세를 비공개 묶음으로 보관한다."""

import argparse
import json
from pathlib import Path
import sys
from time import sleep

from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT
from .libraries import BOARD_PARSER_VERSION, parse_board_notice
from .library_listing import parse_board_listing
from .official_web import (
    BOARDS, DETAIL_MAX_BYTES, OFFICIAL_ORIGIN, board, board_detail_url, board_listing_path, fetch_board_detail,
    fetch_board_listing,
)
from .web_batch import WebSource, capture_web_batch

BOARD_SECTION = "collection-boards"
BOARD_ROOT = CAPTURE_ROOT.with_name(BOARD_SECTION)
BATCH_SCHEMA = "citizen-board-batch-v1"
RECORD_SCHEMA = "citizen-board-notice-v1"


def board_source(name: str) -> WebSource:
    _, _, label, _ = board(name)
    return WebSource(
        label=label,
        item_label="게시물",
        listing_method="POST",
        listing_url=lambda _page: OFFICIAL_ORIGIN + board_listing_path(name),
        fetch_listing=lambda page: fetch_board_listing(name, page, limit=LIST_MAX_BYTES),
        parse_listing=lambda raw, page: parse_board_listing(raw, board=name, page=page),
        detail_url=lambda notice_id: board_detail_url(name, notice_id),
        fetch_detail=lambda notice_id: fetch_board_detail(name, notice_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, notice_id: parse_board_notice(text, board=name, notice_id=notice_id),
        record_schema=RECORD_SCHEMA,
        parser_version=BOARD_PARSER_VERSION,
        pause=lambda: sleep(0.5),
    )


def capture_board_batch(name: str, batch_name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                        max_items: int = 20) -> dict:
    return capture_web_batch(board_source(name), batch_name, root, {"schema_version": BATCH_SCHEMA, "board": name},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: 입력 오류: {message}\n")


def main() -> int:
    parser = _Arguments(description=__doc__)
    parser.add_argument("board", choices=BOARDS)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    try:
        summary = capture_board_batch(args.board, args.name, BOARD_ROOT, start_page=args.start_page,
                                      max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"공지 게시판 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("공지 게시판 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
