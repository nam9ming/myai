"""안성시 도로 공사현황 목록과 상세를 비공개 묶음으로 보관한다."""

import argparse
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES, STOP_STATUSES, save_web
from .capture import CAPTURE_ROOT, bundle_directory, validate_name, write_receipt
from .official_web import (
    DETAIL_MAX_BYTES, OFFICIAL_ORIGIN, ROAD_STATES, SourceHTTPError, fetch_road_detail, fetch_road_listing,
    road_detail_url, road_listing_path, road_state,
)
from .road_works import PARSER_VERSION, parse_road_detail, parse_road_listing

ROAD_SECTION = "collection-road-works"
ROAD_ROOT = CAPTURE_ROOT.with_name(ROAD_SECTION)
BATCH_SCHEMA = "citizen-road-works-batch-v1"
RECORD_SCHEMA = "citizen-road-work-v1"


def _stop(error: ValueError) -> int | None:
    return error.status if isinstance(error, SourceHTTPError) and error.status in STOP_STATUSES else None


def discover(directory: int, state: str, start_page: int, max_pages: int,
             max_items: int) -> tuple[list[dict], list[str], str, int | None]:
    pages, ids = [], []
    expected_total = None
    for page in range(start_page, start_page + max_pages):
        if page > start_page:
            sleep(0.5)
        entry = {"page": page, "method": "GET", "source_url": OFFICIAL_ORIGIN + road_listing_path(state, page)}
        pages.append(entry)
        try:
            raw = fetch_road_listing(state, page, limit=LIST_MAX_BYTES)
        except ValueError as error:
            entry.update(status="fetch_failed", error=str(error))
            return pages, ids, "failed", _stop(error)
        entry.update(save_web(directory, f"list-{page}.html", raw))
        try:
            total, found = parse_road_listing(raw, state=state, page=page)
            if expected_total is not None and total != expected_total:
                raise ValueError("목록을 순회하는 중 공식 사이트의 전체 페이지 수가 달라졌습니다.")
            if set(ids).intersection(found):
                raise ValueError("공식 목록의 페이지 사이에 같은 공사 번호가 있습니다.")
        except ValueError as error:
            entry.update(status="parse_failed", error=str(error))
            return pages, ids, "failed", None
        entry.update(status="parsed", reported_pages=total, web_ids=found)
        expected_total = total
        ids.extend(found)
        done = page >= total
        if len(ids) > max_items or (len(ids) == max_items and not done):
            return pages, ids[:max_items], "item_limit", None
        if done:
            return pages, ids, "complete" if start_page == 1 else "end_reached", None
    return pages, ids, "page_limit", None


def capture_detail(directory: int, state: str, project_id: str) -> tuple[dict, int | None]:
    item = {"web_id": project_id, "source_url": road_detail_url(state, project_id)}
    try:
        raw = fetch_road_detail(state, project_id, limit=DETAIL_MAX_BYTES)
    except ValueError as error:
        item.update(status="fetch_failed", error=str(error))
        return item, _stop(error)
    item.update(save_web(directory, f"detail-{project_id}.html", raw))
    try:
        text, digest = decode_input(raw, "도로 공사현황 상세")
        record = parse_road_detail(text, state=state, project_id=project_id)
    except ValueError as error:
        item.update(status="parse_failed", error=str(error))
        return item, None
    parsed_file = f"parsed-{project_id}.json"
    write_receipt(directory, parsed_file, {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                                           "sha256": digest, "record": record})
    item.update(status="parsed", parsed_file=parsed_file)
    return item, None


def capture_road_batch(state: str, name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                       max_items: int = 20) -> dict:
    road_state(state)
    validate_name(name)
    if type(max_pages) is not int or not 1 <= max_pages <= 20 or type(max_items) is not int or not 1 <= max_items <= 80:
        raise ValueError("요청 한도는 페이지 1~20장, 게시물 1~80건입니다.")
    if type(start_page) is not int or not 1 <= start_page <= 10000:
        raise ValueError("시작 페이지는 1~10000 사이의 정수여야 합니다.")
    with bundle_directory(root, name) as directory:
        pages, ids, discovery, stop = discover(directory, state, start_page, max_pages, max_items)
        items = []
        for project_id in ids:
            if stop is None:
                sleep(0.5)
                item, stop = capture_detail(directory, state, project_id)
            else:
                item = {"web_id": project_id, "source_url": road_detail_url(state, project_id),
                        "status": "not_attempted"}
            items.append(item)
        parsed_count = sum(item["status"] == "parsed" for item in items)
        status = "complete" if discovery == "complete" and parsed_count == len(items) else "partial"
        summary = {"batch_id": name, "status": status, "discovery_status": discovery,
                   "selected": len(items), "parsed": parsed_count}
        write_receipt(directory, "batch.json", {
            **summary,
            "schema_version": BATCH_SCHEMA,
            "state": state,
            "start_page": start_page,
            "max_pages": max_pages,
            "max_items": max_items,
            "stop_http_status": stop,
            "pages": pages,
            "items": items,
        })
    return summary


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
