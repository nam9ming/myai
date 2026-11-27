"""공공데이터포털 표준 API 응답과 비교용 CSV를 비공개로 보관한다."""

import csv
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from time import sleep

from processing.extraction.validation import MAX_BYTES

from .__main__ import PORTAL_MAX_BYTES, SOURCE_PAGES, parse_portal
from .capture import (
    CAPTURE_ROOT, PORTAL_SECTION, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .portal_format import csv_header, csv_row, parse_page
from .portal_transport import fetch_portal_page, portal_endpoint, validate_service_key

PORTAL_ROOT = CAPTURE_ROOT.with_name(PORTAL_SECTION)
PAGE_SIZE = 500
MAX_PAGES = 20
SCHEMA = "citizen-portal-snapshot-v1"
SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"


def page_source(category: str, page: int, page_size: int) -> str:
    return f"{portal_endpoint(category)}?pageNo={page}&numOfRows={page_size}&type=json"


def append_csv(output: bytearray, rows) -> None:
    line = io.StringIO(newline="")
    writer = csv.writer(line)
    for values in rows:
        writer.writerow(values)
        raw = line.getvalue().encode("utf-8")
        if len(output) + len(raw) > PORTAL_MAX_BYTES:
            raise ValueError("포털 비교용 CSV가 20 MiB를 초과했습니다.")
        output.extend(raw)
        line.seek(0)
        line.truncate()


def ordered_json(value):
    if isinstance(value, dict):
        return {key: ordered_json(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [ordered_json(item) for item in value]
    return value


def read_page(output: bytearray, category: str, raw: bytes, page: int, page_size: int,
              previous_total: int | None, seen_pages: set[bytes]) -> tuple[int, int]:
    total, rows = parse_page(raw, page, page_size)
    if previous_total is not None and total != previous_total:
        raise ValueError("포털 API 조회 중 전체 건수가 달라졌습니다.")
    if total > MAX_PAGES * page_size:
        raise ValueError("포털 API의 전체 건수가 페이지 수집 한도를 초과했습니다.")
    # 응답에서 페이지 번호가 바뀌어도 같은 레코드 묶음의 재전송을 감지한다.
    fingerprint = hashlib.sha256(repr(ordered_json(rows)).encode("utf-8")).digest()
    if fingerprint in seen_pages:
        raise ValueError("포털 API가 같은 자료 페이지를 반복했습니다.")
    seen_pages.add(fingerprint)
    append_csv(output, (csv_row(category, row) for row in rows))
    return total, len(rows)


def collect_portal(category: str, name: str, root: Path, service_key: str) -> dict:
    validate_name(name)
    validate_service_key(service_key)
    endpoint = portal_endpoint(category)
    projection = bytearray()
    append_csv(projection, [csv_header(category)])
    seen_pages = set()
    pages = []
    total = None
    rows = 0
    result = {"snapshot_id": name, "status": "failed", "pages": 0, "rows": 0}
    with bundle_directory(root, name) as directory:
        receipt = {"schema_version": SCHEMA, "category": category, "endpoint": endpoint,
                   "catalog_url": SOURCE_PAGES[category][0], "page_size": PAGE_SIZE, "responses": pages}
        try:
            for page in range(1, MAX_PAGES + 1):
                if page > 1:
                    sleep(0.5)
                raw = fetch_portal_page(category, page, PAGE_SIZE, service_key)
                now = datetime.now(UTC).isoformat()
                name_on_disk = f"page-{page}.json"
                write_new(directory, name_on_disk, raw)
                entry = {"page": page, "file": name_on_disk, "source_url": page_source(category, page, PAGE_SIZE),
                         "fetched_at": now, "sha256": hashlib.sha256(raw).hexdigest()}
                pages.append(entry)
                total, received = read_page(projection, category, raw, page, PAGE_SIZE, total, seen_pages)
                entry["rows"] = received
                rows += received
                if rows == total:
                    break
            if rows != total:
                raise ValueError("포털 API의 보고 건수를 모두 수집하지 못했습니다.")
            anseong_rows = len(parse_portal(category, projection.decode("utf-8")))
            write_new(directory, "portal.csv", projection)
            receipt["projection"] = {"file": "portal.csv", "sha256": hashlib.sha256(projection).hexdigest(),
                                     "anseong_rows": anseong_rows}
            result["status"] = "complete"
        except ValueError as error:
            receipt["error"] = str(error)
        result.update(pages=len(pages), rows=rows)
        write_receipt(directory, "portal.json", {**receipt, **result})
    return result


def read_portal_snapshot(private_root: Path, name: str) -> tuple[bytes, dict]:
    validate_name(name)
    with open_archive(private_root, Path(PORTAL_SECTION) / name) as directory:
        receipt = read_receipt(directory, "portal.json")
        category = receipt.get("category")
        page_size = receipt.get("page_size")
        responses = receipt.get("responses")
        if (receipt.get("schema_version") != SCHEMA or receipt.get("snapshot_id") != name
                or receipt.get("status") != "complete" or not isinstance(category, str)
                or category not in SOURCE_PAGES or receipt.get("endpoint") != portal_endpoint(category)
                or receipt.get("catalog_url") != SOURCE_PAGES[category][0]
                or type(page_size) is not int or not 1 <= page_size <= 1000
                or not isinstance(responses, list) or not 1 <= len(responses) <= MAX_PAGES):
            raise ValueError("완료된 포털 API 수집 기록을 확인할 수 없습니다.")
        projection = bytearray()
        append_csv(projection, [csv_header(category)])
        seen_pages = set()
        total = None
        rows = 0
        for page, entry in enumerate(responses, 1):
            filename = f"page-{page}.json"
            if (not isinstance(entry, dict) or type(entry.get("page")) is not int
                    or entry["page"] != page or entry.get("file") != filename
                    or entry.get("source_url") != page_source(category, page, page_size)
                    or (total is not None and rows == total)):
                raise ValueError("포털 API 수집 기록의 페이지가 맞지 않습니다.")
            capture_timestamp(entry.get("fetched_at"))
            raw = read_capture_file(directory, filename, MAX_BYTES)
            if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("포털 API 응답 원본 해시가 맞지 않습니다.")
            total, received = read_page(projection, category, raw, page, page_size, total, seen_pages)
            if type(entry.get("rows")) is not int or entry["rows"] != received:
                raise ValueError("포털 API 수집 기록의 페이지 건수가 맞지 않습니다.")
            rows += received
        if (rows != total or type(receipt.get("rows")) is not int or receipt["rows"] != rows
                or type(receipt.get("pages")) is not int or receipt["pages"] != len(responses)):
            raise ValueError("포털 API 수집 기록의 전체 건수가 맞지 않습니다.")
        csv_raw = read_capture_file(directory, "portal.csv", PORTAL_MAX_BYTES)
        computed = {"file": "portal.csv", "sha256": hashlib.sha256(csv_raw).hexdigest(),
                    "anseong_rows": len(parse_portal(category, projection.decode("utf-8")))}
        if csv_raw != projection or receipt.get("projection") != computed:
            raise ValueError("포털 비교용 CSV가 API 응답 원본 또는 수집 기록과 다릅니다.")
        return csv_raw, receipt


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("category", choices=SOURCE_PAGES)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = collect_portal(args.category, args.name, PORTAL_ROOT, os.environ.get(SERVICE_KEY_ENV, ""))
    except ValueError as error:
        print(f"포털 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("포털 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
