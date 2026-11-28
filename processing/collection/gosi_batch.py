"""안성시 고시·공고 목록과 상세를 비공개 묶음으로 보관하고, 보관한 묶음을 다시 검증한다."""

import hashlib
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name
from .cli import CollectionArguments
from .gosi_notices import (
    LABEL, PARSER_VERSION, fetch_gosi_detail, fetch_gosi_listing, gosi_detail_url, gosi_listing_path,
    parse_gosi_detail, parse_gosi_listing,
)
from .official_web import DETAIL_MAX_BYTES, OFFICIAL_ORIGIN
from .web_batch import WebSource, capture_web_batch

GOSI_SECTION = "collection-gosi"
GOSI_ROOT = CAPTURE_ROOT.with_name(GOSI_SECTION)
BATCH_SCHEMA = "citizen-gosi-batch-v1"
RECORD_SCHEMA = "citizen-gosi-notice-v1"
# 파싱에 실패해도 원본은 남으므로 파일과 해시는 함께 대조한다.
_RAW_KEPT = ("parsed", "parse_failed")


def _remember(rows: dict[str, dict], items: list[dict]) -> list[str]:
    # 페이지 사이 중복은 공통 순회가 실패로 남긴다. 앞 페이지의 항목을 유지해 재검증과 같은 순서로 고른다.
    for item in items:
        rows.setdefault(item["notice_id"], item)
    return [item["notice_id"] for item in items]


def gosi_source() -> WebSource:
    """상세에는 번호가 없을 수 있어 목록에서 읽은 항목을 기억했다가 상세 머리 항목과 대조한다."""
    rows: dict[str, dict] = {}

    def parse_listing(raw: bytes, page: int):
        total, items = parse_gosi_listing(raw, page=page)
        return total, _remember(rows, items), None

    return WebSource(
        label=LABEL,
        item_label="게시물",
        listing_method="GET",
        listing_url=lambda page: OFFICIAL_ORIGIN + gosi_listing_path(page),
        fetch_listing=lambda page: fetch_gosi_listing(page, limit=LIST_MAX_BYTES),
        parse_listing=parse_listing,
        detail_url=gosi_detail_url,
        fetch_detail=lambda notice_id: fetch_gosi_detail(notice_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, notice_id: parse_gosi_detail(text, notice_id=notice_id, listing=rows.get(notice_id)),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=lambda: sleep(1.5),
    )


def capture_gosi_batch(name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                       max_items: int = 20) -> dict:
    return capture_web_batch(gosi_source(), name, root, {"schema_version": BATCH_SCHEMA},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


def _checked(directory: int, entry: object, filename: str, url: str, limit: int) -> bytes:
    if (not isinstance(entry, dict) or entry.get("file") != filename or entry.get("source_url") != url
            or not isinstance(entry.get("sha256"), str)):
        raise ValueError(f"{LABEL} 수집 기록의 파일 이름 또는 원문 주소가 맞지 않습니다.")
    capture_timestamp(entry.get("fetched_at"))
    raw = read_capture_file(directory, filename, limit)
    if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError(f"{LABEL} 원본 해시가 수집 기록과 다릅니다({filename}).")
    return raw


def read_gosi_batch(private_root: Path, name: str) -> dict[str, dict]:
    """보관한 목록·상세 원본의 해시와 파싱 결과를 현재 파서로 다시 만들어 대조하고 파싱된 게시물만 돌려준다."""
    validate_name(name)
    relative = Path(GOSI_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        pages, items = receipt.get("pages"), receipt.get("items")
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or not isinstance(pages, list) or not isinstance(items, list)):
            raise ValueError(f"{LABEL} 수집 기록의 규격·이름이 맞지 않습니다.")
        rows: dict[str, dict] = {}
        for entry in pages:
            status = entry.get("status") if isinstance(entry, dict) else None
            if status not in _RAW_KEPT:
                continue
            page = entry.get("page")
            if type(page) is not int or page < 1:
                raise ValueError(f"{LABEL} 수집 기록의 목록 페이지가 맞지 않습니다.")
            raw = _checked(directory, entry, f"list-{page}.html", OFFICIAL_ORIGIN + gosi_listing_path(page),
                           LIST_MAX_BYTES)
            if status != "parsed":
                continue
            total, found = parse_gosi_listing(raw, page=page)
            if entry.get("reported_pages") != total or entry.get("web_ids") != _remember(rows, found):
                raise ValueError(f"{LABEL} 목록 원본과 수집 기록의 게시물 번호가 다릅니다.")
        records, seen = {}, set()
        for item in items:
            notice_id = item.get("web_id") if isinstance(item, dict) else None
            if notice_id not in rows or notice_id in seen:
                raise ValueError(f"{LABEL} 수집 기록의 게시물 번호가 목록 원본과 맞지 않습니다.")
            seen.add(notice_id)
            if item.get("status") not in _RAW_KEPT:
                continue
            url = gosi_detail_url(notice_id)
            raw = _checked(directory, item, f"detail-{notice_id}.html", url, DETAIL_MAX_BYTES)
            if item["status"] != "parsed":
                continue
            text, digest = decode_input(raw, f"{LABEL} 상세")
            parsed_file = f"parsed-{notice_id}.json"
            stored = read_receipt(directory, parsed_file) if item.get("parsed_file") == parsed_file else None
            if not isinstance(stored, dict) or stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            record = parse_gosi_detail(text, notice_id=notice_id, listing=rows[notice_id])
            if stored != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": digest, "record": record}:
                raise ValueError(f"{LABEL} 파싱 결과가 원본과 다릅니다({notice_id}).")
            records[notice_id] = {
                "record": record,
                "raw_asset_path": (relative / f"detail-{notice_id}.html").as_posix(),
                "raw_sha256": digest,
                "official_url": url,
                "collected_at": item["fetched_at"],
            }
        if (receipt.get("selected"), receipt.get("parsed")) != (len(items), len(records)):
            raise ValueError(f"{LABEL} 수집 기록의 게시물 건수가 맞지 않습니다.")
        return records


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("command", choices=("capture", "verify"))
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    if args.command == "verify":
        try:
            records = read_gosi_batch(GOSI_ROOT.parent, args.name)
        except ValueError as error:
            print(f"{LABEL} 수집 기록 확인 실패: {error}", file=sys.stderr)
            return 1
        print(json.dumps({"batch_id": args.name, "parsed": len(records),
                          "attachments": sum(len(item["record"]["attachments"]) for item in records.values())},
                         ensure_ascii=False))
        return 0
    try:
        summary = capture_gosi_batch(args.name, GOSI_ROOT, start_page=args.start_page,
                                     max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"{LABEL} 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print(f"{LABEL} 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
