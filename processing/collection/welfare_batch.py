"""안성시 지자체복지서비스 OpenAPI 목록·상세 응답을 비공개 묶음으로 보관한다. D03 재검증은 `d03_sources`가 한다."""

import json
import os
from pathlib import Path
import sys
from time import sleep

from .batch import STOP_STATUSES, save_web
from .capture import CAPTURE_ROOT, bundle_directory, validate_name, write_receipt
from .cli import CollectionArguments
from .official_web import SourceHTTPError
from .portal_transport import validate_service_key
from .welfare_api import (
    CATALOG_URL, DETAIL_PATH, HOST, LIST_PATH, REGION, WelfareResultError, detail_source_url, fetch_detail,
    fetch_list, list_source_url, parse_detail, parse_list,
)

WELFARE_SECTION = "collection-welfare"
WELFARE_ROOT = CAPTURE_ROOT.with_name(WELFARE_SECTION)
BATCH_SCHEMA = "citizen-welfare-batch-v1"
RECORD_SCHEMA = "citizen-welfare-service-v1"
PARSER_VERSION = "welfare-api-parser-v2"
SERVICE_KEY_ENV = "DATA_GO_KR_SERVICE_KEY"
PAGE_SIZE = 100


def _pause() -> None:
    sleep(0.6)


def _stop(error: ValueError) -> ValueError | None:
    """차단·한도 HTTP 상태나 HTTP 200의 서비스 오류면 남은 요청을 멈추도록 그 오류를 돌려준다."""
    if isinstance(error, WelfareResultError) or (isinstance(error, SourceHTTPError) and error.status in STOP_STATUSES):
        return error
    return None


def service_record(service_id: str, page: int, item: dict, detail: dict) -> dict:
    """목록 항목(서비스상세링크 포함)과 상세 응답을 원문 그대로 묶는다."""
    return {"servId": service_id, "list_page": page, "list": item, "detail": detail}


def discover(directory: int, service_key: str, max_pages: int, max_items: int) -> tuple:
    pages, found = [], []
    listed: dict[str, dict] = {}
    expected_total = None
    for page in range(1, max_pages + 1):
        if page > 1:
            _pause()
        entry = {"page": page, "source_url": list_source_url(page, PAGE_SIZE)}
        pages.append(entry)
        try:
            raw = fetch_list(page, PAGE_SIZE, service_key)
        except ValueError as error:
            entry.update(status="fetch_failed", error=str(error))
            return pages, found, listed, "failed", _stop(error)
        entry.update(save_web(directory, f"list-{page}.xml", raw))
        try:
            total, items = parse_list(raw, page=page, page_size=PAGE_SIZE)
            ids = [item["fields"]["servId"] for item in items]
            if expected_total is not None and total != expected_total:
                raise ValueError("목록을 순회하는 중 복지 API의 전체 건수가 달라졌습니다.")
            if listed.keys() & set(ids):
                raise ValueError("복지 API 목록의 페이지 사이에 같은 서비스 ID가 있습니다.")
        except ValueError as error:
            entry.update(status="parse_failed", error=str(error))
            return pages, found, listed, "failed", _stop(error)
        entry.update(status="parsed", total_count=total, serv_ids=ids)
        expected_total = total
        for item in items:
            listed[item["fields"]["servId"]] = {"page": page, "item": item}
        found.extend(ids)
        done = len(found) == total
        if len(found) > max_items or (len(found) == max_items and not done):
            return pages, found[:max_items], listed, "item_limit", None
        if done:
            return pages, found, listed, "complete", None
    return pages, found, listed, "page_limit", None


def capture_detail(directory: int, service_key: str, service_id: str, listing: dict, list_digest: str) -> tuple:
    item = {"servId": service_id, "source_url": detail_source_url(service_id), "list_page": listing["page"]}
    try:
        raw = fetch_detail(service_id, service_key)
    except ValueError as error:
        item.update(status="fetch_failed", error=str(error))
        return item, _stop(error)
    item.update(save_web(directory, f"detail-{service_id}.xml", raw))
    try:
        detail = parse_detail(raw, service_id=service_id)
    except ValueError as error:
        item.update(status="parse_failed", error=str(error))
        return item, _stop(error)
    parsed_file = f"parsed-{service_id}.json"
    write_receipt(directory, parsed_file, {
        "schema_version": RECORD_SCHEMA, "parser_version": PARSER_VERSION, "list_sha256": list_digest,
        "sha256": item["sha256"], "record": service_record(service_id, listing["page"], listing["item"], detail),
    })
    item.update(status="parsed", parsed_file=parsed_file)
    return item, None


def collect_welfare(name: str, root: Path, service_key: str, *, max_pages: int = 5, max_items: int = 200) -> dict:
    """원본 응답을 먼저 쓰고 `batch.json`을 마지막에 쓴다. 인증 키는 요청에만 쓰고 기록하지 않는다."""
    validate_name(name)
    if type(max_pages) is not int or not 1 <= max_pages <= 20 or type(max_items) is not int or not 1 <= max_items <= 500:
        raise ValueError("요청 한도는 목록 1~20페이지, 상세 1~500건입니다.")
    if not service_key:
        raise ValueError(f"{SERVICE_KEY_ENV}에 공공데이터포털 인증 키(디코딩)를 설정해 주세요.")
    validate_service_key(service_key)
    with bundle_directory(root, name) as directory:
        pages, ids, listed, discovery, stop = discover(directory, service_key, max_pages, max_items)
        digests = {entry["page"]: entry.get("sha256") for entry in pages}
        items = []
        for service_id in ids:
            listing = listed[service_id]
            if stop is None:
                _pause()
                item, stop = capture_detail(directory, service_key, service_id, listing, digests[listing["page"]])
            else:
                item = {"servId": service_id, "source_url": detail_source_url(service_id),
                        "list_page": listing["page"], "status": "not_attempted"}
            items.append(item)
        parsed = sum(item["status"] == "parsed" for item in items)
        status = "complete" if discovery == "complete" and parsed == len(items) else "partial"
        summary = {"batch_id": name, "status": status, "discovery_status": discovery,
                   "selected": len(items), "parsed": parsed}
        write_receipt(directory, "batch.json", {
            **summary, "schema_version": BATCH_SCHEMA, "catalog_url": CATALOG_URL,
            "list_endpoint": f"https://{HOST}{LIST_PATH}", "detail_endpoint": f"https://{HOST}{DETAIL_PATH}",
            "region": REGION, "page_size": PAGE_SIZE, "max_pages": max_pages, "max_items": max_items,
            "stop_http_status": getattr(stop, "status", None), "stop_reason": None if stop is None else str(stop),
            "pages": pages, "items": items,
        })
    return summary


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-items", type=int, default=200)
    args = parser.parse_args()
    try:
        summary = collect_welfare(args.name, WELFARE_ROOT, os.environ.get(SERVICE_KEY_ENV, ""),
                                  max_pages=args.max_pages, max_items=args.max_items)
    except ValueError as error:
        print(f"복지 API 수집 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("복지 API 원본 또는 완료 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
