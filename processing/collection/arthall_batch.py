"""안성맞춤아트홀 공연·전시 월별 전체일정 목록과 상세를 비공개 묶음으로 보관하고 다시 검증한다."""

import hashlib
import json
from pathlib import Path
import re
import sys
from time import sleep

from .__main__ import decode_input
from .arthall import (
    CONCERT_ID, PARSER_VERSION, detail_url, fetch_detail, fetch_listing, listing_path, parse_detail, parse_listing,
)
from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name
from .cli import CollectionArguments
from .official_web import DETAIL_MAX_BYTES, OFFICIAL_ORIGIN
from .web_batch import WebSource, capture_web_batch

ARTHALL_SECTION = "collection-arthall"
ARTHALL_ROOT = CAPTURE_ROOT.with_name(ARTHALL_SECTION)
BATCH_SCHEMA = "citizen-arthall-batch-v1"
RECORD_SCHEMA = "citizen-arthall-concert-v1"
_SHA256 = re.compile(r"[0-9a-f]{64}")


def arthall_source(year: int, month: int) -> WebSource:
    listing_path(year, month, 1)
    return WebSource(
        label="안성맞춤아트홀",
        item_label="공연",
        listing_method="GET",
        listing_url=lambda page: OFFICIAL_ORIGIN + listing_path(year, month, page),
        fetch_listing=lambda page: fetch_listing(year, month, page, limit=LIST_MAX_BYTES),
        parse_listing=lambda raw, page: (*parse_listing(raw, year=year, month=month, page=page), None),
        detail_url=detail_url,
        fetch_detail=lambda concert_id: fetch_detail(concert_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, concert_id: parse_detail(text, concert_id=concert_id),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=lambda: sleep(1.5),
    )


def capture_arthall_batch(year: int, month: int, name: str, root: Path, *, start_page: int = 1,
                          max_pages: int = 3, max_items: int = 20) -> dict:
    return capture_web_batch(arthall_source(year, month), name, root,
                             {"schema_version": BATCH_SCHEMA, "year": year, "month": month},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


def _checked(directory: int, entry: object, filename: str, url: str, limit: int) -> bytes | None:
    # 받기 실패·미시도만 원본이 없고, 파싱 실패를 포함한 나머지는 원본 해시까지 대조한다.
    if isinstance(entry, dict) and entry.get("status") in ("fetch_failed", "not_attempted") and "file" not in entry:
        return None
    if (not isinstance(entry, dict) or entry.get("file") != filename or entry.get("source_url") != url
            or not isinstance(entry.get("sha256"), str) or _SHA256.fullmatch(entry["sha256"]) is None):
        raise ValueError("아트홀 수집 기록의 파일 이름·원문 주소·해시 형식이 맞지 않습니다.")
    capture_timestamp(entry.get("fetched_at"))
    raw = read_capture_file(directory, filename, limit)
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("아트홀 원본 해시가 수집 기록과 다릅니다.")
    return raw


def read_arthall_batch(private_root: Path, name: str) -> tuple[dict, dict[str, dict]]:
    """보관한 목록·상세 원본의 해시와 현재 파서 결과를 기록과 대조하고, 수집 기록과 파싱된 공연 기록(번호별)을 돌려준다."""
    validate_name(name)
    with open_archive(private_root, Path(ARTHALL_SECTION) / name) as directory:
        receipt = read_receipt(directory, "batch.json")
        year, month, pages, items = (receipt.get(key) for key in ("year", "month", "pages", "items"))
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or receipt.get("status") not in ("complete", "partial")
                or not isinstance(pages, list) or not isinstance(items, list)):
            raise ValueError("아트홀 수집 기록의 규격·이름·상태가 맞지 않습니다.")
        listing_path(year, month, 1)
        listed = []
        for entry in pages:
            if not isinstance(entry, dict):
                raise ValueError("아트홀 수집 기록의 목록 페이지가 맞지 않습니다.")
            page = entry.get("page")
            raw = _checked(directory, entry, f"list-{page}.html", OFFICIAL_ORIGIN + listing_path(year, month, page),
                           LIST_MAX_BYTES)
            if entry.get("status") != "parsed":
                continue
            if [*parse_listing(raw, year=year, month=month, page=page)] != [entry.get("reported_pages"),
                                                                            entry.get("web_ids")]:
                raise ValueError("아트홀 목록 파싱 결과가 원본과 다릅니다.")
            listed.extend(entry["web_ids"])
        # 완료 묶음의 목록 원본은 1쪽부터 보고된 전체 쪽까지 빠짐없이 파싱되어 있어야 한다.
        if receipt["status"] == "complete" and (
                receipt.get("discovery_status") != "complete" or receipt.get("start_page") != 1 or not pages
                or [entry.get("page") for entry in pages] != list(range(1, len(pages) + 1))
                or any(entry.get("status") != "parsed" or entry.get("reported_pages") != len(pages)
                       for entry in pages)):
            raise ValueError("아트홀 완료 묶음의 목록 원본이 전체 쪽을 덮지 않습니다.")
        records, seen = {}, set()
        for row in items:
            key = row.get("web_id") if isinstance(row, dict) else None
            if (not isinstance(key, str) or CONCERT_ID.fullmatch(key) is None or key in seen or key not in listed
                    or row.get("source_url") != detail_url(key)):
                raise ValueError("아트홀 수집 기록의 공연 번호 또는 원문 주소가 맞지 않습니다.")
            seen.add(key)
            raw = _checked(directory, row, f"detail-{key}.html", detail_url(key), DETAIL_MAX_BYTES)
            if row.get("status") != "parsed":
                continue
            if row.get("parsed_file") != f"parsed-{key}.json":
                raise ValueError("아트홀 수집 기록의 파싱 파일 이름이 맞지 않습니다.")
            text, digest = decode_input(raw, "안성맞춤아트홀 상세")
            stored = read_receipt(directory, row["parsed_file"])
            if stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            record = parse_detail(text, concert_id=key)
            if stored != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": digest, "record": record}:
                raise ValueError("아트홀 파싱 결과가 원본과 다릅니다.")
            records[key] = record
        if ((receipt.get("selected"), receipt.get("parsed")) != (len(items), len(records))
                or (receipt["status"] == "complete"
                    and (len(records) != len(items) or [row["web_id"] for row in items] != listed))):
            # 완료 묶음은 목록 원본의 공연을 순서대로 빠짐없이 담아야 한다.
            raise ValueError("아트홀 수집 기록의 공연 건수가 맞지 않습니다.")
        return receipt, records


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True, parser_class=CollectionArguments)
    capture = commands.add_parser("capture", help="한 달의 전체일정 목록과 상세를 받아 보관한다.")
    capture.add_argument("--year", required=True, type=int)
    capture.add_argument("--month", required=True, type=int)
    capture.add_argument("--name", required=True)
    capture.add_argument("--start-page", type=int, default=1)
    capture.add_argument("--max-pages", type=int, default=3)
    capture.add_argument("--max-items", type=int, default=20)
    verify = commands.add_parser("verify", help="보관한 묶음을 요청 없이 다시 검증한다.")
    verify.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.action == "capture":
            summary = capture_arthall_batch(args.year, args.month, args.name, ARTHALL_ROOT,
                                            start_page=args.start_page, max_pages=args.max_pages,
                                            max_items=args.max_items)
        else:
            receipt, records = read_arthall_batch(ARTHALL_ROOT.parent, args.name)
            summary = {"batch_id": args.name, "status": "verified", "batch_status": receipt["status"],
                       "selected": receipt["selected"], "parsed": len(records)}
    except ValueError as error:
        print(f"아트홀 일정 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("아트홀 일정 원본 또는 완료 기록을 저장·확인할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    # 검증을 통과해도 일부 실패·한도 도달 묶음이면 수집과 같은 종료 코드 2다.
    return 0 if summary.get("batch_status", summary["status"]) == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
