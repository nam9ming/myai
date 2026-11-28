"""안성청년포털 청년정책 목록·상세를 비공개 묶음으로 보관하고, 보관한 묶음을 요청 없이 다시 검증한다."""

import hashlib
import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name
from .cli import CollectionArguments
from .official_web import DETAIL_MAX_BYTES, OFFICIAL_ORIGIN
from .web_batch import WebSource, capture_web_batch
from .youth_policy import (
    PARSER_VERSION, YOUTH_LISTING_PATH, fetch_youth_detail, fetch_youth_listing, parse_youth_detail,
    parse_youth_listing, youth_detail_url,
)

YOUTH_SECTION = "collection-youth-policies"
YOUTH_ROOT = CAPTURE_ROOT.with_name(YOUTH_SECTION)
BATCH_SCHEMA = "citizen-youth-policy-batch-v1"
RECORD_SCHEMA = "citizen-youth-policy-v1"
_INVALID_ARCHIVE = "청년정책 수집 기록이 원본과 맞지 않습니다."


def _add_cards(cards: dict[str, dict], found: list[dict]) -> list[str]:
    # 앞 페이지와 겹친 번호는 순회가 그 페이지를 거부하므로 먼저 받은 카드만 남긴다.
    for card in found:
        cards.setdefault(card["policy_id"], card)
    return [card["policy_id"] for card in found]


def youth_source() -> WebSource:
    """상세에 없는 신청기간은 목록 카드에만 있으므로 이번 묶음에서 읽은 카드를 상세 기록에 함께 넣는다."""
    cards: dict[str, dict] = {}

    def parse_listing(raw: bytes, page: int):
        total, found = parse_youth_listing(raw, page=page)
        return total, _add_cards(cards, found), None

    return WebSource(
        label="청년정책",
        item_label="정책",
        listing_method="POST",
        listing_url=lambda _page: OFFICIAL_ORIGIN + YOUTH_LISTING_PATH,
        fetch_listing=lambda page: fetch_youth_listing(page, limit=LIST_MAX_BYTES),
        parse_listing=parse_listing,
        detail_url=youth_detail_url,
        fetch_detail=lambda policy_id: fetch_youth_detail(policy_id, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, policy_id: parse_youth_detail(text, policy_id=policy_id, card=cards[policy_id]),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=lambda: sleep(1.5),
    )


def capture_youth_batch(name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                        max_items: int = 20) -> dict:
    return capture_web_batch(youth_source(), name, root, {"schema_version": BATCH_SCHEMA},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


def _raw(directory: int, entry: dict, filename: str, url: str, limit: int) -> bytes:
    if entry.get("file") != filename or entry.get("source_url") != url:
        raise ValueError(_INVALID_ARCHIVE)
    capture_timestamp(entry.get("fetched_at"))
    raw = read_capture_file(directory, filename, limit)
    if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
        raise ValueError("청년정책 원본 해시가 수집 기록과 다릅니다.")
    return raw


def read_youth_batch(private_root: Path, name: str) -> dict[str, dict]:
    """보관 파일을 바꾸지 않고, 원본 해시와 현재 파서로 다시 만든 파싱 결과가 기록과 같은 정책만 돌려준다."""
    validate_name(name)
    relative = Path(YOUTH_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        pages, items = receipt.get("pages"), receipt.get("items")
        if (receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name
                or receipt.get("status") not in ("complete", "partial")
                or not isinstance(pages, list) or not isinstance(items, list)):
            raise ValueError("청년정책 수집 기록의 규격·이름·상태가 맞지 않습니다.")
        cards: dict[str, dict] = {}
        for entry in pages:
            if not isinstance(entry, dict):
                raise ValueError(_INVALID_ARCHIVE)
            if entry.get("status") != "parsed":
                continue
            page = entry.get("page")
            if type(page) is not int or page < 1:
                raise ValueError(_INVALID_ARCHIVE)
            raw = _raw(directory, entry, f"list-{page}.html", OFFICIAL_ORIGIN + YOUTH_LISTING_PATH, LIST_MAX_BYTES)
            total, found = parse_youth_listing(raw, page=page)
            if entry.get("reported_pages") != total or entry.get("web_ids") != _add_cards(cards, found):
                raise ValueError(_INVALID_ARCHIVE)
        records, seen = {}, set()
        for item in items:
            policy_id = item.get("web_id") if isinstance(item, dict) else None
            # 형식 확인을 먼저 해야 손상된 목록·사전 값이 TypeError 대신 검증 실패가 된다.
            if (not isinstance(policy_id, str) or policy_id in seen or policy_id not in cards
                    or item.get("status") not in ("parsed", "parse_failed", "fetch_failed", "not_attempted")):
                raise ValueError(_INVALID_ARCHIVE)
            seen.add(policy_id)
            if item["status"] != "parsed":
                continue
            url = youth_detail_url(policy_id)
            raw = _raw(directory, item, f"detail-{policy_id}.html", url, DETAIL_MAX_BYTES)
            text, digest = decode_input(raw, "청년정책 상세")
            if item.get("parsed_file") != f"parsed-{policy_id}.json":
                raise ValueError(_INVALID_ARCHIVE)
            stored = read_receipt(directory, item["parsed_file"])
            if stored.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            record = parse_youth_detail(text, policy_id=policy_id, card=cards[policy_id])
            if stored != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": digest, "record": record}:
                raise ValueError("청년정책 파싱 결과가 원본과 다릅니다.")
            records[policy_id] = {"raw_asset_path": (relative / item["file"]).as_posix(), "raw_sha256": digest,
                                  "official_url": url, "collected_at": item["fetched_at"], "record": record}
        if ((receipt.get("selected"), receipt.get("parsed")) != (len(seen), len(records))
                or (receipt["status"] == "complete" and len(records) != len(seen))):
            raise ValueError("청년정책 수집 기록의 건수가 맞지 않습니다.")
        return records


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=CollectionArguments)
    capture = commands.add_parser("capture", help="목록과 상세를 받아 보관한다.")
    capture.add_argument("--name", required=True)
    capture.add_argument("--start-page", type=int, default=1)
    capture.add_argument("--max-pages", type=int, default=3)
    capture.add_argument("--max-items", type=int, default=20)
    commands.add_parser("verify", help="보관한 묶음을 요청 없이 다시 검증한다.").add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            records = read_youth_batch(CAPTURE_ROOT.parent, args.name)
            print(json.dumps({"batch_id": args.name, "verified": len(records), "policy_ids": list(records)},
                             ensure_ascii=False))
            return 0
        summary = capture_youth_batch(args.name, YOUTH_ROOT, start_page=args.start_page,
                                      max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"청년정책 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("청년정책 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
