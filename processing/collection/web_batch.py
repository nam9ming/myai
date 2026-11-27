"""포털 비교 원본 없는 공식 웹 목록·상세 묶음의 공통 순회·보관 규칙."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .__main__ import decode_input
from .batch import STOP_STATUSES, save_web
from .capture import bundle_directory, validate_name, write_receipt
from .official_web import SourceHTTPError


@dataclass(frozen=True)
class WebSource:
    """한 공식 목록의 요청·파싱 방법. 함수는 호출 시점에 찾아 시험의 대체 함수도 그대로 쓴다."""

    label: str
    item_label: str
    listing_method: str
    listing_url: Callable[[int], str]
    fetch_listing: Callable[[int], bytes]
    parse_listing: Callable[[bytes, int], tuple[int, list[str], list[str] | None]]
    detail_url: Callable[[str], str]
    fetch_detail: Callable[[str], bytes]
    parse_detail: Callable[[str, str], dict]
    record_schema: str
    parser_version: str
    pause: Callable[[], None]


def check_limits(name: str, start_page: int, max_pages: int, max_items: int) -> None:
    validate_name(name)
    if type(max_pages) is not int or not 1 <= max_pages <= 20 or type(max_items) is not int or not 1 <= max_items <= 80:
        raise ValueError("요청 한도는 페이지 1~20장, 게시물 1~80건입니다.")
    if type(start_page) is not int or not 1 <= start_page <= 10000:
        raise ValueError("시작 페이지는 1~10000 사이의 정수여야 합니다.")


def _stop(error: ValueError) -> int | None:
    return error.status if isinstance(error, SourceHTTPError) and error.status in STOP_STATUSES else None


def discover(directory: int, source: WebSource, start_page: int, max_pages: int,
             max_items: int) -> tuple[list[dict], list[str], str, int | None]:
    """고정 글은 시작 페이지에서 한 번만 받고, 이후 페이지의 고정 글이 다르면 순회를 멈춘다."""
    pages, ids = [], []
    numbered: set[str] = set()
    expected_total = expected_pins = None
    for page in range(start_page, start_page + max_pages):
        if page > start_page:
            source.pause()
        entry = {"page": page, "method": source.listing_method, "source_url": source.listing_url(page)}
        pages.append(entry)
        try:
            raw = source.fetch_listing(page)
        except ValueError as error:
            entry.update(status="fetch_failed", error=str(error))
            return pages, ids, "failed", _stop(error)
        entry.update(save_web(directory, f"list-{page}.html", raw))
        try:
            total, found, pinned = source.parse_listing(raw, page)
            if expected_total is not None and total != expected_total:
                raise ValueError("목록을 순회하는 중 공식 사이트의 전체 페이지 수가 달라졌습니다.")
            if numbered.intersection(found):
                raise ValueError(f"공식 목록의 페이지 사이에 같은 {source.item_label} 번호가 있습니다.")
            if expected_pins is not None and pinned != expected_pins:
                raise ValueError("목록을 순회하는 중 상단 고정 글이 달라졌습니다.")
        except ValueError as error:
            entry.update(status="parse_failed", error=str(error))
            return pages, ids, "failed", None
        entry.update(status="parsed", reported_pages=total, web_ids=found)
        if pinned is not None:
            entry["pinned_ids"] = pinned
        if expected_pins is None:
            ids.extend(pinned or [])
        expected_total, expected_pins = total, pinned
        numbered.update(found)
        ids.extend(item for item in found if item not in ids)
        done = page >= total
        if len(ids) > max_items or (len(ids) == max_items and not done):
            return pages, ids[:max_items], "item_limit", None
        if done:
            return pages, ids, "complete" if start_page == 1 else "end_reached", None
    return pages, ids, "page_limit", None


def capture_detail(directory: int, source: WebSource, web_id: str) -> tuple[dict, int | None]:
    item = {"web_id": web_id, "source_url": source.detail_url(web_id)}
    try:
        raw = source.fetch_detail(web_id)
    except ValueError as error:
        item.update(status="fetch_failed", error=str(error))
        return item, _stop(error)
    item.update(save_web(directory, f"detail-{web_id}.html", raw))
    try:
        text, digest = decode_input(raw, f"{source.label} 상세")
        record = source.parse_detail(text, web_id)
    except ValueError as error:
        item.update(status="parse_failed", error=str(error))
        return item, None
    parsed_file = f"parsed-{web_id}.json"
    write_receipt(directory, parsed_file, {"schema_version": source.record_schema,
                                           "parser_version": source.parser_version,
                                           "sha256": digest, "record": record})
    item.update(status="parsed", parsed_file=parsed_file)
    return item, None


def capture_web_batch(source: WebSource, name: str, root: Path, receipt: dict, *, start_page: int,
                      max_pages: int, max_items: int) -> dict:
    """목록·상세 원본과 파싱 결과를 남기고 `batch.json`을 마지막에 쓴다."""
    check_limits(name, start_page, max_pages, max_items)
    with bundle_directory(root, name) as directory:
        pages, ids, discovery, stop = discover(directory, source, start_page, max_pages, max_items)
        items = []
        for web_id in ids:
            if stop is None:
                source.pause()
                item, stop = capture_detail(directory, source, web_id)
            else:
                item = {"web_id": web_id, "source_url": source.detail_url(web_id), "status": "not_attempted"}
            items.append(item)
        parsed_count = sum(item["status"] == "parsed" for item in items)
        status = "complete" if discovery == "complete" and parsed_count == len(items) else "partial"
        summary = {"batch_id": name, "status": status, "discovery_status": discovery,
                   "selected": len(items), "parsed": parsed_count}
        write_receipt(directory, "batch.json", {
            **summary, **receipt, "start_page": start_page, "max_pages": max_pages, "max_items": max_items,
            "stop_http_status": stop, "pages": pages, "items": items,
        })
    return summary
