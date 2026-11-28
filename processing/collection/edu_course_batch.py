"""안성배움e 전체 강좌 목록과 상세를 비공개 묶음으로 보관하고, 보관본을 현재 파서로 다시 대조해 읽는다."""

import json
from pathlib import Path
import sys
from time import sleep

from .__main__ import decode_input
from .batch import LIST_MAX_BYTES
from .capture import CAPTURE_ROOT, capture_timestamp, open_archive, read_capture_file, read_receipt, validate_name
from .cli import CollectionArguments
from .edu_courses import (
    PARSER_VERSION, detail_url, fetch_detail, fetch_listing, listing_path, parse_course_detail, parse_course_listing,
)
from .official_web import DETAIL_MAX_BYTES, OFFICIAL_ORIGIN
from .web_batch import WebSource, capture_web_batch

COURSE_SECTION = "collection-edu-courses"
COURSE_ROOT = CAPTURE_ROOT.with_name(COURSE_SECTION)
BATCH_SCHEMA = "citizen-edu-course-batch-v1"
RECORD_SCHEMA = "citizen-edu-course-v1"
_LABEL = "안성배움e 강좌"


def course_source() -> WebSource:
    return WebSource(
        label=_LABEL,
        item_label="강좌",
        listing_method="GET",
        listing_url=lambda page: OFFICIAL_ORIGIN + listing_path(page),
        fetch_listing=lambda page: fetch_listing(page, limit=LIST_MAX_BYTES),
        parse_listing=lambda raw, page: (*parse_course_listing(raw, page=page), None),
        detail_url=detail_url,
        fetch_detail=lambda course: fetch_detail(course, limit=DETAIL_MAX_BYTES),
        parse_detail=lambda text, course: parse_course_detail(text, course_id=course),
        record_schema=RECORD_SCHEMA,
        parser_version=PARSER_VERSION,
        pause=lambda: sleep(1.5),
    )


def capture_course_batch(name: str, root: Path, *, start_page: int = 1, max_pages: int = 3,
                         max_items: int = 20) -> dict:
    return capture_web_batch(course_source(), name, root, {"schema_version": BATCH_SCHEMA},
                             start_page=start_page, max_pages=max_pages, max_items=max_items)


def read_course_batch(private_root: Path, name: str, course_ids: set[str]) -> dict[str, dict]:
    """보관한 상세 원본의 해시와 파싱 결과를 현재 파서로 다시 만들어 대조한 뒤 강좌별 기록을 돌려준다."""
    # d03_sources가 나중에 이 모듈을 불러와도 순환하지 않도록 함수 안에서 부른다.
    from .d03_sources import _batch_items, _reference

    validate_name(name)
    if not isinstance(course_ids, set) or not course_ids:
        raise ValueError("대조할 강좌 번호를 하나 이상 지정해 주세요.")
    relative = Path(COURSE_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "batch.json")
        if receipt.get("schema_version") != BATCH_SCHEMA or receipt.get("batch_id") != name:
            raise ValueError(f"{_LABEL} 수집 기록의 규격 또는 이름이 맞지 않습니다.")
        items = _batch_items(receipt, detail_url)
        courses = {}
        for key in sorted(course_ids):
            row = items.get(key)
            if row is None or row["status"] != "parsed" or row.get("parsed_file") != f"parsed-{key}.json":
                raise ValueError(f"선택한 강좌는 파싱이 완료된 {_LABEL} 수집 원본이어야 합니다.")
            filename = f"detail-{key}.html"
            recorded = _reference(row, filename, "source_url", detail_url(key))
            text, digest = decode_input(read_capture_file(directory, filename, DETAIL_MAX_BYTES), f"{_LABEL} 상세")
            if digest != recorded:
                raise ValueError(f"{_LABEL} 상세 원본 해시가 수집 기록과 다릅니다.")
            parsed = read_receipt(directory, row["parsed_file"])
            if parsed.get("parser_version") != PARSER_VERSION:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            record = parse_course_detail(text, course_id=key)
            if parsed != {"schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION,
                          "sha256": digest, "record": record}:
                raise ValueError(f"{_LABEL} 파싱 결과가 원본과 다릅니다.")
            courses[key] = {
                "record": record,
                "raw_asset_path": (relative / filename).as_posix(),
                "raw_sha256": digest,
                "official_url": row["source_url"],
                "collected_at": capture_timestamp(row.get("fetched_at")),
            }
        return courses


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--max-items", type=int, default=20)
    args = parser.parse_args()
    try:
        summary = capture_course_batch(args.name, COURSE_ROOT, start_page=args.start_page,
                                       max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"{_LABEL} 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print(f"{_LABEL} 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
