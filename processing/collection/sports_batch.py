"""안성시 직영 공공체육시설 예약 누리집 공지를 비공개 묶음으로 보관하고 다시 대조한다. D03 연결은 후속 작업이다."""

import hashlib
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES, save_web
from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name,
    write_receipt,
)
from .cli import CollectionArguments
from .official_web import DETAIL_MAX_BYTES
from .sports_notices import (
    LISTING_URL, PARSER_VERSION, ROBOTS_MAX_BYTES, ROBOTS_URL, allowed, detail_url, fetch_detail, fetch_listing,
    fetch_robots, parse_detail, parse_listing, robots_rules,
)
from .web_batch import WebSource, _stop, capture_detail, check_limits

SPORTS_SECTION = "collection-sports-notices"
SPORTS_ROOT = CAPTURE_ROOT.with_name(SPORTS_SECTION)
BATCH_SCHEMA = "citizen-sports-notice-batch-v1"
RECORD_SCHEMA = "citizen-sports-notice-v1"
BOARD = "notice"
_ITEM_STATUSES = ("parsed", "parse_failed", "fetch_failed", "not_attempted")
_ROBOTS_BLOCKED = "robots.txt가 이 상세 주소를 허용하지 않습니다."


def _pause() -> None:
    sleep(1.5)


SOURCE = WebSource(
    label="체육시설 공지",
    item_label="공지",
    listing_method="GET",
    listing_url=lambda _page: LISTING_URL,
    fetch_listing=lambda _page: fetch_listing(limit=LIST_MAX_BYTES),
    parse_listing=None,  # 전체 페이지 수 표시 형식을 몰라 web_batch.discover로 순회하지 않는다.
    detail_url=detail_url,
    fetch_detail=lambda seq: fetch_detail(seq, limit=DETAIL_MAX_BYTES),
    parse_detail=lambda text, seq: parse_detail(text, seq=seq),
    record_schema=RECORD_SCHEMA,
    parser_version=PARSER_VERSION,
    pause=_pause,
)


def _robots(directory: int) -> tuple[dict, object]:
    """robots.txt를 HTTP 200으로 받아 목록 주소를 허용할 때만 규칙을 돌려준다. 4xx도 판단 불가로 멈춘다."""
    entry = {"source_url": ROBOTS_URL}
    try:
        raw = fetch_robots()
    except ValueError as error:
        entry.update(status="fetch_failed", error=str(error))
        return entry, None
    entry.update(save_web(directory, "robots.txt", raw))
    try:
        rules = robots_rules(raw)
    except ValueError as error:
        entry.update(status="parse_failed", error=str(error))
        return entry, None
    entry["status"] = "allowed" if allowed(rules, LISTING_URL) else "disallowed"
    return entry, rules if entry["status"] == "allowed" else None


def _listing(directory: int, max_items: int) -> tuple[list[dict], list[str], str, int | None]:
    entry = {"page": 1, "method": "GET", "source_url": LISTING_URL}
    try:
        raw = fetch_listing(limit=LIST_MAX_BYTES)
    except ValueError as error:
        entry.update(status="fetch_failed", error=str(error))
        return [entry], [], "failed", _stop(error)
    entry.update(save_web(directory, "list-1.html", raw))
    try:
        ids = parse_listing(raw)
    except ValueError as error:
        entry.update(status="parse_failed", error=str(error))
        return [entry], [], "failed", None
    entry.update(status="parsed", web_ids=ids)
    if len(ids) > max_items:
        return [entry], ids[:max_items], "item_limit", None
    return [entry], ids, "first_page_only", None


def capture_sports_batch(name: str, root: Path, *, max_items: int = 20) -> dict:
    """목록 1쪽과 그 상세만 받는다. 원본을 먼저 쓰고 `batch.json`을 마지막에 쓴다."""
    check_limits(name, 1, 1, max_items)
    with bundle_directory(root, name) as directory:
        robots, rules = _robots(directory)
        pages, ids, discovery, stop = [], [], "robots_not_allowed", None
        if rules is not None:
            _pause()
            pages, ids, discovery, stop = _listing(directory, max_items)
        items = []
        for seq in ids:
            if stop is not None:
                item = {"web_id": seq, "source_url": detail_url(seq), "status": "not_attempted"}
            elif not allowed(rules, detail_url(seq)):
                item = {"web_id": seq, "source_url": detail_url(seq), "status": "not_attempted", "error": _ROBOTS_BLOCKED}
            else:
                _pause()
                item, stop = capture_detail(directory, SOURCE, seq)
            items.append(item)
        parsed = sum(item["status"] == "parsed" for item in items)
        status = "complete" if discovery == "first_page_only" and parsed == len(items) else "partial"
        summary = {"batch_id": name, "status": status, "discovery_status": discovery,
                   "selected": len(items), "parsed": parsed}
        write_receipt(directory, "batch.json", {
            **summary, "schema_version": BATCH_SCHEMA, "board": BOARD, "max_items": max_items,
            "stop_http_status": stop, "robots": robots, "pages": pages, "items": items,
        })
    return summary


def _raw(directory: int, entry: object, filename: str, url: str, limit: int) -> bytes:
    if not isinstance(entry, dict) or entry.get("file") != filename or entry.get("source_url") != url:
        raise ValueError("체육시설 공지 수집 기록의 파일 이름 또는 원문 주소가 맞지 않습니다.")
    capture_timestamp(entry.get("fetched_at"))
    raw = read_capture_file(directory, filename, limit)
    if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("체육시설 공지 원본 해시가 수집 기록과 다릅니다.")
    return raw


def read_sports_batch(private_root: Path, name: str) -> dict[str, dict]:
    """robots.txt·목록·상세 원본의 해시와 파싱 결과를 현재 파서로 다시 대조한다. 파일은 바꾸지 않는다."""
    validate_name(name)
    relative = Path(SPORTS_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        items, pages, limit = receipt.get("items"), receipt.get("pages"), receipt.get("max_items")
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or receipt.get("board") != BOARD or receipt.get("status") not in ("complete", "partial")
                or not isinstance(items, list) or not isinstance(pages, list)
                or type(limit) is not int or not 1 <= limit <= 80):
            raise ValueError("체육시설 공지 수집 기록의 규격·이름·상태가 맞지 않습니다.")
        parsed_rows = [row for row in items if isinstance(row, dict) and row.get("status") == "parsed"]
        if ((receipt.get("selected"), receipt.get("parsed")) != (len(items), len(parsed_rows))
                or (receipt["status"] == "complete" and len(parsed_rows) != len(items))):
            raise ValueError("체육시설 공지 수집 기록의 게시물 건수가 맞지 않습니다.")
        if not items:
            return {}
        robots = receipt.get("robots")
        rules = robots_rules(_raw(directory, robots, "robots.txt", ROBOTS_URL, ROBOTS_MAX_BYTES))
        if (robots.get("status") != "allowed" or not allowed(rules, LISTING_URL) or len(pages) != 1
                or not isinstance(pages[0], dict) or pages[0].get("status") != "parsed"):
            raise ValueError("체육시설 공지 수집 기록의 robots.txt 또는 목록 기록이 맞지 않습니다.")
        listed = parse_listing(_raw(directory, pages[0], "list-1.html", LISTING_URL, LIST_MAX_BYTES))
        if (pages[0].get("web_ids") != listed or not all(isinstance(row, dict) for row in items)
                or [row.get("web_id") for row in items] != listed[:limit]
                or any(row.get("status") not in _ITEM_STATUSES or row.get("source_url") != detail_url(row["web_id"])
                       for row in items)):
            raise ValueError("체육시설 공지 수집 기록의 공지 번호·상태가 목록 원본과 다릅니다.")
        assets = {}
        for row in parsed_rows:
            seq = row["web_id"]
            url = detail_url(seq)
            if not allowed(rules, url) or row.get("parsed_file") != f"parsed-{seq}.json":
                raise ValueError("체육시설 공지 수집 기록의 상세 기록이 맞지 않습니다.")
            filename = f"detail-{seq}.html"
            text, digest = decode_input(_raw(directory, row, filename, url, DETAIL_MAX_BYTES), "체육시설 공지 상세")
            stored = read_receipt(directory, row["parsed_file"])
            if stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            record = parse_detail(text, seq=seq)
            if stored != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": digest, "record": record}:
                raise ValueError("체육시설 공지 파싱 결과가 원본과 다릅니다.")
            assets[seq] = {"raw_asset_path": (relative / filename).as_posix(), "raw_sha256": digest,
                           "official_url": url, "collected_at": row["fetched_at"], "record": record}
        return assets


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--verify", action="store_true", help="새로 요청하지 않고 보관한 묶음을 다시 대조한다.")
    args = parser.parse_args()
    if args.verify:
        try:
            assets = read_sports_batch(SPORTS_ROOT.parent, args.name)
        except ValueError as error:
            print(f"체육시설 공지 재검증 실패: {error}", file=sys.stderr)
            return 1
        print(json.dumps({"batch_id": args.name, "verified": list(assets)}, ensure_ascii=False))
        return 0
    try:
        summary = capture_sports_batch(args.name, SPORTS_ROOT, max_items=args.max_items)
    except ValueError as error:
        print(f"체육시설 공지 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("체육시설 공지 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
