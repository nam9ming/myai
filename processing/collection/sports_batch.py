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
from .official_web import DETAIL_MAX_BYTES, SourceHTTPError
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
_ROBOTS_BLOCKED = "robots.txt가 이 상세 주소를 허용하지 않습니다."
# 이 호스트의 차단 화면은 HTTP 400이다. 공통 중단 상태(web_batch)는 두고 여기서만 멈춘다.
_WAF_BLOCKED = str(SourceHTTPError(400, "체육시설 공지 상세"))


def _pause(delay: float = 0.0) -> None:
    sleep(max(1.5, delay))  # robots.txt Crawl-delay가 더 길면 그 간격을 쓴다.


SOURCE = WebSource(
    label="체육시설 공지",
    item_label="공지",
    listing_method="GET",
    listing_url=lambda _page: LISTING_URL,
    fetch_listing=lambda _page: fetch_listing(limit=LIST_MAX_BYTES),
    parse_listing=None,  # 페이지 수 표시 형식을 몰라 web_batch.discover를 쓰지 않는다.
    detail_url=detail_url,
    fetch_detail=lambda seq: fetch_detail(seq, limit=DETAIL_MAX_BYTES),
    parse_detail=lambda text, seq: parse_detail(text, seq=seq),
    record_schema=RECORD_SCHEMA,
    parser_version=PARSER_VERSION,
    pause=_pause,
)


def _robots(directory: int) -> tuple[dict, dict | None]:
    """robots.txt를 HTTP 200으로 받아 목록 주소를 허용할 때만 규칙을 돌려준다."""
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
            _pause(rules["delay"])
            pages, ids, discovery, stop = _listing(directory, max_items)
        items = []
        for seq in ids:
            if stop is not None:
                item = {"web_id": seq, "source_url": detail_url(seq), "status": "not_attempted"}
            elif not allowed(rules, detail_url(seq)):
                item = {"web_id": seq, "source_url": detail_url(seq), "status": "not_attempted", "error": _ROBOTS_BLOCKED}
            else:
                _pause(rules["delay"])
                item, stop = capture_detail(directory, SOURCE, seq)
                if item.get("error") == _WAF_BLOCKED:
                    stop = 400
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


def _raw(directory: int, entry: dict, filename: str, url: str, limit: int) -> bytes | None:
    if "file" not in entry:
        return None
    if entry.get("file") != filename or entry.get("source_url") != url:
        raise ValueError("체육시설 공지 수집 기록의 파일 이름 또는 원문 주소가 맞지 않습니다.")
    capture_timestamp(entry.get("fetched_at"))
    raw = read_capture_file(directory, filename, limit)
    if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError("체육시설 공지 원본 해시가 수집 기록과 다릅니다.")
    return raw


def _attempt(parse, raw: bytes | None):
    if raw is None:
        return "fetch_failed", None
    try:
        return "parsed", parse(raw)
    except ValueError:
        return "parse_failed", None


def read_sports_batch(private_root: Path, name: str) -> dict[str, dict]:
    """모든 원본 해시와 원본에서 다시 낸 상태·건수·파싱 결과를 기록과 대조한다."""
    validate_name(name)
    relative = Path(SPORTS_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        robots, items, pages, limit = (receipt.get(key) for key in ("robots", "items", "pages", "max_items"))
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or receipt.get("board") != BOARD or not isinstance(robots, dict)
                or not isinstance(items, list) or not isinstance(pages, list)
                or not all(isinstance(row, dict) for row in pages + items)
                or type(limit) is not int or not 1 <= limit <= 80):
            raise ValueError("체육시설 공지 수집 기록의 규격·이름·상태가 맞지 않습니다.")
        state, rules = _attempt(robots_rules, _raw(directory, robots, "robots.txt", ROBOTS_URL, ROBOTS_MAX_BYTES))
        if state == "parsed":
            state = "allowed" if allowed(rules, LISTING_URL) else "disallowed"
        listed, discovery, page = [], "robots_not_allowed", None
        if state == "allowed" and len(pages) == 1:
            page = _attempt(parse_listing, _raw(directory, pages[0], "list-1.html", LISTING_URL, LIST_MAX_BYTES))
            listed = page[1] or []
            discovery = "item_limit" if len(listed) > limit else "first_page_only" if listed else "failed"
        if (robots.get("status") != state or len(pages) != (state == "allowed")
                or (pages and (pages[0].get("status"), pages[0].get("web_ids")) != page)
                or [row.get("web_id") for row in items] != listed[:limit]):
            raise ValueError("체육시설 공지 robots.txt·목록 기록이 원본과 다릅니다.")
        assets = {}
        for row in items:
            seq = row["web_id"]
            url, filename = detail_url(seq), f"detail-{seq}.html"
            raw = _raw(directory, row, filename, url, DETAIL_MAX_BYTES)
            state, record = _attempt(lambda data: parse_detail(decode_input(data, "체육시설 공지 상세")[0], seq=seq), raw)
            if (row.get("source_url") != url or (raw is not None and not allowed(rules, url))
                    or row.get("status") not in (state, "not_attempted" if raw is None else state)):
                raise ValueError("체육시설 공지 상세 기록이 원본과 다릅니다.")
            if record is None:
                continue
            stored = read_receipt(directory, row["parsed_file"]) if row.get("parsed_file") == f"parsed-{seq}.json" else {}
            if stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            if stored != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": row["sha256"], "record": record}:
                raise ValueError("체육시설 공지 파싱 결과가 원본과 다릅니다.")
            assets[seq] = {"raw_asset_path": (relative / filename).as_posix(), "raw_sha256": row["sha256"],
                           "official_url": url, "collected_at": row["fetched_at"], "record": record}
        status = "complete" if discovery == "first_page_only" and len(assets) == len(items) else "partial"
        if ((receipt.get("status"), receipt.get("discovery_status"), receipt.get("selected"), receipt.get("parsed"))
                != (status, discovery, len(items), len(assets))):
            raise ValueError("체육시설 공지 수집 기록의 상태·건수가 원본과 다릅니다.")
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
