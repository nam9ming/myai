"""공공데이터포털 파일데이터 API 응답과 안성시 행 선택 결과를 비공개로 보관한다."""

from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from time import sleep
from urllib.parse import urlencode

from processing.extraction.validation import MAX_BYTES

from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .official_web import DETAIL_MAX_BYTES, SourceHTTPError, _fetch
from .odcloud_format import DATASETS, dataset, parse_page, row_fingerprints, select_rows, selection_document
from .portal_transport import reject_key_echo, validate_service_key

ODCLOUD_SECTION = "collection-odcloud"
ODCLOUD_ROOT = CAPTURE_ROOT.with_name(ODCLOUD_SECTION)
SCHEMA = "citizen-odcloud-snapshot-v1"
SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
_HOST = "api.odcloud.kr"
PAGE_SIZE = 500
MAX_PAGES = 20
REQUEST_INTERVAL = 0.6


def odcloud_endpoint(name: str) -> str:
    return f"https://{_HOST}{dataset(name).path}"


def page_source(name: str, page: int, per_page: int) -> str:
    """수집 기록에 남기는 요청 주소. 인증 키는 넣지 않는다."""
    return f"{odcloud_endpoint(name)}?page={page}&perPage={per_page}&returnType=JSON"


def fetch_odcloud_page(name: str, page: int, per_page: int, service_key: str) -> bytes:
    path = dataset(name).path
    if type(page) is not int or not 1 <= page <= 2_147_483_647:
        raise ValueError("파일데이터 API 페이지는 양의 32비트 정수여야 합니다.")
    if type(per_page) is not int or not 1 <= per_page <= 1000:
        raise ValueError("파일데이터 API 페이지당 건수는 1~1000의 정수여야 합니다.")
    service_key = validate_service_key(service_key)
    # Swagger는 Authorization 헤더도 허용하지만 공통 요청 함수와 같은 serviceKey 쿼리를 쓴다.
    query = urlencode({"page": page, "perPage": per_page, "returnType": "JSON", "serviceKey": service_key})
    try:
        raw = _fetch("GET", f"{path}?{query}", None, DETAIL_MAX_BYTES, host=_HOST)
    except SourceHTTPError as error:
        raise ValueError(f"파일데이터 API HTTP 응답 오류({error.status}).") from None
    except ValueError as error:
        # 공통 요청 함수의 크기·시간 초과·연결·인코딩 오류 문구를 파일데이터 API 문구로 바꾼다.
        raise ValueError(str(error).replace("공식 웹 상세 응답", "파일데이터 API 응답")) from None
    reject_key_echo(raw, service_key)
    return raw


def read_page(name: str, raw: bytes, page: int, per_page: int, previous_total: int | None,
              seen_rows: set[bytes], matched: list, review: list, unmentioned: list) -> tuple[int, int]:
    total, rows = parse_page(name, raw, page, per_page)
    if previous_total is not None and total != previous_total:
        raise ValueError("파일데이터 API 조회 중 전체 건수가 달라졌습니다.")
    if total == 0:
        # 전국 자료가 비는 것은 API 항목 변경이나 오류일 수 있어 '안성시 자료 없음'과 구별해 실패로 남긴다.
        raise ValueError("파일데이터 API의 전체 건수가 0건이라 완료로 볼 수 없습니다.")
    if total > MAX_PAGES * per_page:
        raise ValueError("파일데이터 API의 전체 건수가 페이지 수집 한도를 초과했습니다.")
    # 정렬 인자 없이 페이지를 넘기므로 서버 정렬이 흔들리면 앞 페이지 행이 다시 오고 다른 행이 빠진다.
    # 한 응답 안의 같은 행은 원본 자료의 중복일 수 있어 허용하고, 페이지를 건너 다시 나온 행만 거부한다.
    fingerprints = row_fingerprints(rows)
    if fingerprints & seen_rows:
        raise ValueError("파일데이터 API가 앞 페이지의 행을 다시 보냈습니다. 페이지 정렬이 흔들려 빠진 행이 있을 수 있습니다.")
    seen_rows |= fingerprints
    select_rows(name, page, rows, matched, review, unmentioned)
    return total, len(rows)


def _selection(name: str, matched: list, review: list, unmentioned: list) -> tuple[bytes, dict]:
    selection = selection_document(name, matched, review, unmentioned)
    if len(selection) > MAX_BYTES:
        raise ValueError("안성시 행 선택 결과가 8 MiB를 초과했습니다.")
    return selection, {"file": "anseong.json", "sha256": hashlib.sha256(selection).hexdigest(),
                       "rows": len(matched), "needs_review": len(review),
                       "blank_location_unmentioned": len(unmentioned)}


def _receipt_base(name: str) -> dict:
    config = dataset(name)
    return {"schema_version": SCHEMA, "dataset": name, "category": config.category, "title": config.title,
            "endpoint": odcloud_endpoint(name), "catalog_url": config.catalog_url,
            "swagger_url": config.swagger_url}


def collect_odcloud(name: str, snapshot: str, root: Path, service_key: str) -> dict:
    validate_name(snapshot)
    validate_service_key(service_key)
    dataset(name)
    pages = []
    matched, review, unmentioned = [], [], []
    seen_rows = set()
    total = None
    rows = 0
    result = {"snapshot_id": snapshot, "status": "failed", "pages": 0, "rows": 0}
    with bundle_directory(root, snapshot) as directory:
        receipt = {**_receipt_base(name), "page_size": PAGE_SIZE, "responses": pages}
        try:
            for page in range(1, MAX_PAGES + 1):
                if page > 1:
                    sleep(REQUEST_INTERVAL)
                raw = fetch_odcloud_page(name, page, PAGE_SIZE, service_key)
                filename = f"page-{page}.json"
                write_new(directory, filename, raw)
                entry = {"page": page, "file": filename, "source_url": page_source(name, page, PAGE_SIZE),
                         "fetched_at": datetime.now(UTC).isoformat(), "sha256": hashlib.sha256(raw).hexdigest()}
                pages.append(entry)
                total, received = read_page(name, raw, page, PAGE_SIZE, total, seen_rows, matched, review, unmentioned)
                entry["rows"] = received
                rows += received
                if rows == total:
                    break
            if rows != total:
                raise ValueError("파일데이터 API의 보고 건수를 모두 수집하지 못했습니다.")
            selection, receipt["selection"] = _selection(name, matched, review, unmentioned)
            write_new(directory, "anseong.json", selection)
            result["status"] = "complete"
        except ValueError as error:
            receipt["error"] = str(error)
        result.update(pages=len(pages), rows=rows)
        write_receipt(directory, "odcloud.json", {**receipt, **result})
    return result


def read_odcloud_snapshot(private_root: Path, snapshot: str) -> tuple[bytes, dict]:
    """보관한 응답 원본에서 검증과 안성시 선택을 다시 수행해 기록·선택 결과와 대조한다."""
    validate_name(snapshot)
    with open_archive(private_root, Path(ODCLOUD_SECTION) / snapshot) as directory:
        receipt = read_receipt(directory, "odcloud.json")
        name = receipt.get("dataset")
        page_size = receipt.get("page_size")
        responses = receipt.get("responses")
        if (receipt.get("snapshot_id") != snapshot or receipt.get("status") != "complete"
                or not isinstance(name, str) or name not in DATASETS):
            raise ValueError("완료된 파일데이터 API 수집 기록을 확인할 수 없습니다.")
        base = _receipt_base(name)
        endpoint = receipt.get("endpoint")
        if (isinstance(endpoint, str) and endpoint != base["endpoint"]
                and endpoint.startswith(f"https://{_HOST}/api/{dataset(name).namespace}/uddi:")):
            # 자료가 개정되면 같은 namespace에 새 uddi가 붙는다. 코드의 항목을 바꾼 뒤의 옛 보관본은 변조와 구별해 알린다.
            raise ValueError("현재 코드와 다른 파일데이터 API 항목(uddi)으로 수집한 기록입니다. 현재 항목으로 다시 수집해 주세요.")
        if (any(receipt.get(key) != value for key, value in base.items())
                or type(page_size) is not int or not 1 <= page_size <= 1000
                or not isinstance(responses, list) or not 1 <= len(responses) <= MAX_PAGES):
            raise ValueError("완료된 파일데이터 API 수집 기록을 확인할 수 없습니다.")
        matched, review, unmentioned = [], [], []
        seen_rows = set()
        total = None
        rows = 0
        for page, entry in enumerate(responses, 1):
            filename = f"page-{page}.json"
            if (not isinstance(entry, dict) or type(entry.get("page")) is not int
                    or entry["page"] != page or entry.get("file") != filename
                    or entry.get("source_url") != page_source(name, page, page_size)
                    or (total is not None and rows == total)):
                raise ValueError("파일데이터 API 수집 기록의 페이지가 맞지 않습니다.")
            capture_timestamp(entry.get("fetched_at"))
            raw = read_capture_file(directory, filename, DETAIL_MAX_BYTES)
            if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError("파일데이터 API 응답 원본 해시가 맞지 않습니다.")
            total, received = read_page(name, raw, page, page_size, total, seen_rows, matched, review, unmentioned)
            if type(entry.get("rows")) is not int or entry["rows"] != received:
                raise ValueError("파일데이터 API 수집 기록의 페이지 건수가 맞지 않습니다.")
            rows += received
        if (rows != total or type(receipt.get("rows")) is not int or receipt["rows"] != rows
                or type(receipt.get("pages")) is not int or receipt["pages"] != len(responses)):
            raise ValueError("파일데이터 API 수집 기록의 전체 건수가 맞지 않습니다.")
        selection, computed = _selection(name, matched, review, unmentioned)
        if read_capture_file(directory, "anseong.json", MAX_BYTES) != selection or receipt.get("selection") != computed:
            raise ValueError("안성시 행 선택 결과가 API 응답 원본 또는 수집 기록과 다릅니다.")
        return selection, receipt


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("dataset", choices=DATASETS)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = collect_odcloud(args.dataset, args.name, ODCLOUD_ROOT, os.environ.get(SERVICE_KEY_ENV, ""))
    except ValueError as error:
        print(f"파일데이터 API 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("파일데이터 API 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
