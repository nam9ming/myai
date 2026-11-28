"""안성시 도서관 행사신청 목록·상세를 비공개 묶음으로 보관하고 다시 대조한다. D03 연결은 후속이다."""

import hashlib
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name
from .cli import CollectionArguments
from .library_programs import (
    PARSER_VERSION, PROGRAM_ID, SOURCE_LABEL, fetch_program_detail, fetch_program_listing, parse_program_detail,
    parse_program_listing, program_detail_url, program_listing_url, program_record,
)
from .official_web import DETAIL_MAX_BYTES
from .web_batch import WebSource, capture_web_batch

PROGRAM_SECTION = "collection-library-programs"
PROGRAM_ROOT = CAPTURE_ROOT.with_name(PROGRAM_SECTION)
BATCH_SCHEMA = "citizen-library-program-batch-v1"
RECORD_SCHEMA = "citizen-library-program-v1"
COLLECTION_METHOD = "official-web-library-program"


def _pause() -> None:
    sleep(1.5)


def program_source() -> WebSource:
    """상세에는 접수현황 문구가 없어 목록 행을 행사 번호별로 기억했다가 상세 파싱 결과 옆에 둔다."""
    listed: dict[str, tuple[int, dict]] = {}

    def parse_listing(raw: bytes, page: int) -> tuple[int, list[str], None]:
        total, rows = parse_program_listing(raw, page=page)
        for program_id, fields in rows:
            # 페이지 사이 중복 번호는 discover가 그 페이지를 거부하므로 먼저 받은 행만 남긴다.
            listed.setdefault(program_id, (page, fields))
        return total, [program_id for program_id, _ in rows], None

    return WebSource(
        label=SOURCE_LABEL,
        item_label="행사",
        listing_method="GET",
        listing_url=program_listing_url,
        fetch_listing=lambda page: fetch_program_listing(page, limit=LIST_MAX_BYTES),
        parse_listing=parse_listing,
        detail_url=program_detail_url,
        fetch_detail=lambda program_id: fetch_program_detail(program_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, program_id: program_record(*listed[program_id],
                                                             parse_program_detail(text, program_id)),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=_pause,
    )


def capture_program_batch(name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                          max_items: int = 20) -> dict:
    return capture_web_batch(program_source(), name, root, {"schema_version": BATCH_SCHEMA},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


def read_program_assets(private_root: Path, name: str, program_ids: set[str]) -> dict[str, dict]:
    """보관한 목록·상세 원본의 해시를 확인하고 파싱 결과를 현재 파서로 다시 만들어 대조한다. 파일은 바꾸지 않는다."""
    validate_name(name)
    if (not isinstance(program_ids, set) or not program_ids
            or any(not isinstance(key, str) or PROGRAM_ID.fullmatch(key) is None for key in program_ids)):
        raise ValueError("선택한 도서관 행사 번호가 유효하지 않습니다.")
    relative = Path(PROGRAM_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        pages, items = receipt.get("pages"), receipt.get("items")
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or not isinstance(pages, list) or not isinstance(items, list)
                or not all(isinstance(entry, dict) for entry in pages + items)):
            raise ValueError("도서관 행사신청 수집 기록의 규격·이름이 맞지 않습니다.")
        rows = {item.get("web_id"): item for item in items}
        if len(rows) != len(items):
            raise ValueError("도서관 행사신청 수집 기록에 중복 행사 번호가 있습니다.")
        assets = {}
        for key in sorted(program_ids):
            row = rows.get(key)
            if (row is None or row.get("status") != "parsed" or row.get("file") != f"detail-{key}.html"
                    or row.get("parsed_file") != f"parsed-{key}.json" or row.get("source_url") != program_detail_url(key)):
                raise ValueError("선택한 행사는 파싱이 완료된 도서관 행사신청 수집 원본이어야 합니다.")
            listed = [entry for entry in pages if entry.get("status") == "parsed"
                      and isinstance(entry.get("web_ids"), list) and key in entry["web_ids"]]
            page = listed[0].get("page") if len(listed) == 1 else None
            if (type(page) is not int or page < 1 or listed[0].get("file") != f"list-{page}.html"
                    or listed[0].get("source_url") != program_listing_url(page)):
                raise ValueError("선택한 행사의 목록 페이지 기록이 맞지 않습니다.")
            list_raw = read_capture_file(directory, listed[0]["file"], LIST_MAX_BYTES)
            raw = read_capture_file(directory, row["file"], DETAIL_MAX_BYTES)
            list_digest = hashlib.sha256(list_raw).hexdigest()
            if (list_digest != listed[0].get("sha256")
                    or hashlib.sha256(raw).hexdigest() != row.get("sha256")):
                raise ValueError("도서관 행사신청 원본 해시가 수집 기록과 다릅니다.")
            stored = read_receipt(directory, row["parsed_file"])
            if stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            listing = dict(parse_program_listing(list_raw, page=page)[1]).get(key)
            text, digest = decode_input(raw, f"{SOURCE_LABEL} 상세")
            if listing is None or stored != {
                "schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION, "sha256": digest,
                "record": program_record(page, listing, parse_program_detail(text, key)),
            }:
                raise ValueError("도서관 행사신청 파싱 결과가 원본과 다릅니다.")
            assets[key] = {
                "raw_asset_path": (relative / row["file"]).as_posix(),
                "raw_sha256": digest,
                "official_url": row["source_url"],
                "collected_at": capture_timestamp(row.get("fetched_at")),
                "collection_method": COLLECTION_METHOD,
                # 접수현황 문구의 원본은 목록 페이지라서 그 원본·주소·수신 시각을 따로 돌려준다.
                "listing_raw_asset_path": (relative / listed[0]["file"]).as_posix(),
                "listing_raw_sha256": list_digest,
                "listing_url": listed[0]["source_url"],
                "listing_collected_at": capture_timestamp(listed[0].get("fetched_at")),
            }
        return assets


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    try:
        summary = capture_program_batch(args.name, PROGRAM_ROOT, start_page=args.start_page,
                                        max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"도서관 행사신청 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("도서관 행사신청 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
