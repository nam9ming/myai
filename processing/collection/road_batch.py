"""안성시 도로 공사현황 목록과 상세를 비공개 묶음으로 보관한다."""

import argparse
import json
from pathlib import Path
import sys
from time import sleep

from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT
from .official_web import (
    DETAIL_MAX_BYTES, OFFICIAL_ORIGIN, ROAD_STATES, fetch_road_detail, fetch_road_listing, road_detail_url,
    road_listing_path, road_state,
)
from .road_works import PARSER_VERSION, parse_road_detail, parse_road_listing
from .web_batch import WebSource, capture_web_batch

ROAD_SECTION = "collection-road-works"
ROAD_ROOT = CAPTURE_ROOT.with_name(ROAD_SECTION)
BATCH_SCHEMA = "citizen-road-works-batch-v1"
RECORD_SCHEMA = "citizen-road-work-v1"


def road_source(state: str) -> WebSource:
    road_state(state)
    return WebSource(
        label="도로 공사현황",
        item_label="공사",
        listing_method="GET",
        listing_url=lambda page: OFFICIAL_ORIGIN + road_listing_path(state, page),
        fetch_listing=lambda page: fetch_road_listing(state, page, limit=LIST_MAX_BYTES),
        parse_listing=lambda raw, page: (*parse_road_listing(raw, state=state, page=page), None),
        detail_url=lambda project_id: road_detail_url(state, project_id),
        fetch_detail=lambda project_id: fetch_road_detail(state, project_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, project_id: parse_road_detail(text, state=state, project_id=project_id),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=lambda: sleep(0.5),
    )


def capture_road_batch(state: str, name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                       max_items: int = 20) -> dict:
    return capture_web_batch(road_source(state), name, root, {"schema_version": BATCH_SCHEMA, "state": state},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


class _Arguments(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: 입력 오류: {message}\n")


def main() -> int:
    parser = _Arguments(description=__doc__)
    parser.add_argument("state", choices=ROAD_STATES)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    try:
        summary = capture_road_batch(args.state, args.name, ROAD_ROOT, start_page=args.start_page,
                                     max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"도로 공사현황 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("도로 공사현황 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
