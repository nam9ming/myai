"""공식 목록에서 게시물을 찾아 포털 원본과 비공개로 보관한다."""

import argparse
from datetime import UTC, date, datetime
import hashlib
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import PORTAL_MAX_BYTES, SOURCE_PAGES, decode_input, parse_detail, parse_portal, preview, read_raw
from .capture import CAPTURE_ROOT, bundle_directory, validate_name, write_new, write_receipt
from .event_listing import parse_event_listing
from .library_listing import parse_library_listing
from .official_web import (
    DETAIL_MAX_BYTES, OFFICIAL_ORIGIN, SourceHTTPError, detail_url, fetch_detail, fetch_listing, listing_request,
)

BATCH_ROOT = CAPTURE_ROOT.with_name("collection-batches")
LIST_MAX_BYTES = 2 * 1024 * 1024
STOP_STATUSES = {401, 403, 429, 503}


def save_web(directory: int, name: str, raw: bytes) -> dict:
    fetched_at = datetime.now(UTC).isoformat()
    write_new(directory, name, raw)
    return {"file": name, "sha256": hashlib.sha256(raw).hexdigest(), "fetched_at": fetched_at}


def discover(directory: int, category: str, begin: date | None, end: date | None,
             max_pages: int, max_items: int) -> tuple[list[dict], list[str], str, int | None]:
    pages = []
    ids = []
    seen = set()
    expected_total = None
    parse = parse_event_listing if category == "culture" else parse_library_listing
    extension = "json" if category == "culture" else "html"
    for page in range(1, max_pages + 1):
        if page > 1:
            sleep(0.5)
        method, path, _ = listing_request(category, page, begin, end)
        entry = {"page": page, "method": method, "source_url": OFFICIAL_ORIGIN + path}
        pages.append(entry)
        try:
            raw = fetch_listing(category, page, begin, end, limit=LIST_MAX_BYTES)
        except ValueError as error:
            entry.update(status="fetch_failed", error=str(error))
            stop = error.status if isinstance(error, SourceHTTPError) and error.status in STOP_STATUSES else None
            return pages, ids, "failed", stop
        entry.update(save_web(directory, f"list-{page}.{extension}", raw))
        try:
            total, found = parse(raw, page=page)
            if expected_total is not None and total != expected_total:
                raise ValueError("목록을 순회하는 중 공식 사이트의 전체 건수 또는 페이지 수가 달라졌습니다.")
            if seen.intersection(found):
                raise ValueError("공식 목록의 페이지 사이에 같은 게시물 번호가 있습니다.")
            if category == "culture" and (len(ids) + len(found) > total or (not found and len(ids) < total)):
                raise ValueError("행사 목록의 실제 건수와 전체 건수가 맞지 않습니다.")
        except ValueError as error:
            entry.update(status="parse_failed", error=str(error))
            return pages, ids, "failed", None
        entry.update(status="parsed", reported_total=total, web_ids=found)
        expected_total = total
        seen.update(found)
        ids.extend(found)
        done = len(ids) == total if category == "culture" else page >= total
        if len(ids) > max_items or (len(ids) == max_items and not done):
            return pages, ids[:max_items], "item_limit", None
        if done:
            return pages, ids, "complete", None
    return pages, ids, "page_limit", None


def capture_detail(directory: int, category: str, web_id: str, records: list[dict], portal_sha: str) -> tuple[dict, int | None]:
    item = {"web_id": web_id, "source_url": detail_url(category, web_id)}
    try:
        raw = fetch_detail(category, web_id, limit=DETAIL_MAX_BYTES)
    except ValueError as error:
        item.update(status="fetch_failed", error=str(error))
        stop = error.status if isinstance(error, SourceHTTPError) and error.status in STOP_STATUSES else None
        return item, stop
    extension = "json" if category == "culture" else "html"
    item.update(save_web(directory, f"detail-{web_id}.{extension}", raw))
    try:
        text, web_sha = decode_input(raw, "공식 웹 상세")
        parsed = parse_detail(category, text, web_id)
        comparison = preview(category, records, parsed, portal_sha, web_sha)
    except ValueError as error:
        item.update(status="parse_failed", error=str(error))
        return item, None
    parsed_file = f"parsed-{web_id}.json"
    write_receipt(directory, parsed_file, {"web": comparison["web"], "relationship": comparison["relationship"]})
    item.update(status="parsed", parsed_file=parsed_file)
    return item, None


def capture_batch(category: str, portal_file: Path, name: str, root: Path, *,
                  begin: date | None = None, end: date | None = None, max_pages: int = 3, max_items: int = 20) -> dict:
    validate_name(name)
    listing_request(category, 1, begin, end)
    if type(max_pages) is not int or not 1 <= max_pages <= 20 or type(max_items) is not int or not 1 <= max_items <= 80:
        raise ValueError("요청 한도는 페이지 1~20장, 게시물 1~80건입니다.")
    portal_raw = read_raw(portal_file, PORTAL_MAX_BYTES, "포털 CSV")
    portal_text, portal_sha = decode_input(portal_raw, "포털 CSV", portal_csv=True)
    records = parse_portal(category, portal_text)
    with bundle_directory(root, name) as directory:
        write_new(directory, "portal.csv", portal_raw)
        pages, ids, discovery, stop = discover(directory, category, begin, end, max_pages, max_items)
        items = []
        for web_id in ids:
            if stop is None:
                sleep(0.5)
                item, stop = capture_detail(directory, category, web_id, records, portal_sha)
            else:
                item = {"web_id": web_id, "source_url": detail_url(category, web_id), "status": "not_attempted"}
            items.append(item)
        parsed_count = sum(item["status"] == "parsed" for item in items)
        status = "complete" if discovery == "complete" and parsed_count == len(items) else "partial"
        summary = {"batch_id": name, "status": status, "discovery_status": discovery,
                   "selected": len(items), "parsed": parsed_count}
        write_receipt(directory, "batch.json", {
            **summary,
            "schema_version": "citizen-source-batch-v1",
            "category": category,
            "period": [begin.isoformat(), end.isoformat()] if begin is not None and end is not None else None,
            "max_pages": max_pages,
            "max_items": max_items,
            "stop_http_status": stop,
            "portal": {"file": "portal.csv", "catalog_url": SOURCE_PAGES[category][0],
                       "sha256": portal_sha, "records": records},
            "pages": pages,
            "items": items,
        })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=SOURCE_PAGES)
    parser.add_argument("--portal-csv", required=True, type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--begin", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    try:
        summary = capture_batch(args.category, args.portal_csv, args.name, BATCH_ROOT,
                                begin=args.begin, end=args.end, max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"묶음 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("묶음 수집 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
