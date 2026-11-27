"""수집 기록과 비공개 원본을 대조해 등록에 필요한 정보를 돌려준다."""

from pathlib import Path
import re

from .__main__ import PORTAL_MAX_BYTES, SOURCE_PAGES, decode_input, parse_detail, parse_portal
from .capture import PORTAL_SECTION, capture_timestamp, open_archive, validate_name
from .capture import read_capture_file as _read
from .capture import read_receipt as _receipt
from .media import read_media_assets
from . import board_batch, road_batch
from .libraries import board_parser_version, parse_board_notice
from .official_web import BOARDS, DETAIL_MAX_BYTES, ROAD_STATES, board_detail_url, detail_url, road_detail_url
from .odcloud import ODCLOUD_SECTION, read_odcloud_snapshot
from .portal import read_portal_snapshot
from .road_works import PARSER_VERSION as ROAD_PARSER_VERSION, parse_road_detail


_ARCHIVES = {
    "single": ("collection", "capture.json", "citizen-source-capture-v1", "capture_id"),
    "batch": ("collection-batches", "batch.json", "citizen-source-batch-v1", "batch_id"),
}
_WEB_ID = re.compile(r"[1-9][0-9]{0,17}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DETAIL_STATUSES = ("parsed", "parse_failed", "fetch_failed", "not_attempted")


def _web_id(value: object) -> bool:
    return isinstance(value, str) and _WEB_ID.fullmatch(value) is not None


def _reference(record: object, filename: str, url_key: str, url: str) -> str:
    if not isinstance(record, dict) or record.get("file") != filename or record.get(url_key) != url:
        raise ValueError("수집 기록의 파일 이름 또는 원문 주소가 맞지 않습니다.")
    digest = record.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("수집 기록의 원본 해시 형식이 맞지 않습니다.")
    return digest


def _batch_items(record: dict, source_url) -> dict[str, dict]:
    rows = record.get("items")
    if not isinstance(rows, list) or record.get("status") not in ("complete", "partial"):
        raise ValueError("묶음 수집 기록의 상태 또는 게시물 목록이 맞지 않습니다.")
    items = {}
    for row in rows:
        if not isinstance(row, dict) or not _web_id(row.get("web_id")) or row.get("status") not in _DETAIL_STATUSES:
            raise ValueError("묶음 수집 기록의 게시물 번호 또는 상태가 맞지 않습니다.")
        web_id = row["web_id"]
        if web_id in items:
            raise ValueError("묶음 수집 기록에 중복 게시물 번호가 있습니다.")
        if row.get("source_url") != source_url(web_id):
            raise ValueError("수집 기록의 게시물 원문 주소가 맞지 않습니다.")
        items[web_id] = row
    parsed = sum(row["status"] == "parsed" for row in items.values())
    counts = (record.get("selected"), record.get("parsed"))
    if (any(type(value) is not int for value in counts) or counts != (len(items), parsed)
            or (record["status"] == "complete" and parsed != len(items))):
        raise ValueError("묶음 수집 기록의 게시물 건수가 맞지 않습니다.")
    return items


def _check_preview(web: object, category: str, web_id: str, digest: str) -> None:
    if (not isinstance(web, dict) or web.get("source_page") != SOURCE_PAGES[category][1]
            or web.get("sha256") != digest):
        raise ValueError("수집 비교 결과가 원본과 맞지 않습니다.")
    row = web.get("record")
    url_key = "source_url" if category == "culture" else "official_url"
    if not isinstance(row, dict) or row.get("external_id") != web_id or row.get(url_key) != detail_url(category, web_id):
        raise ValueError("수집 비교 결과의 게시물 번호 또는 원문 주소가 맞지 않습니다.")


def _web_asset(directory: int, archive_kind: str, receipt: dict, items: dict[str, dict],
               category: str, web_id: str) -> tuple[str, str, str, str]:
    extension = "json" if category == "culture" else "html"
    url = detail_url(category, web_id)
    if archive_kind == "single":
        if receipt.get("web_id") != web_id:
            raise ValueError("선택한 게시물이 단건 수집 기록에 없습니다.")
        row = receipt.get("web")
        filename = f"web.{extension}"
        collected_at = capture_timestamp(receipt.get("web_fetched_at"))
        comparison = receipt.get("comparison")
        if (not isinstance(comparison, dict) or comparison.get("schema_version") != "citizen-source-preview-v1"
                or comparison.get("category") != category):
            raise ValueError("단건 수집 기록의 비교 결과를 확인할 수 없습니다.")
    else:
        row = items.get(web_id)
        if row is None or row["status"] != "parsed":
            raise ValueError("선택한 게시물은 파싱이 완료된 묶음 수집 원본이어야 합니다.")
        filename = f"detail-{web_id}.{extension}"
        collected_at = capture_timestamp(row.get("fetched_at"))
        parsed_file = f"parsed-{web_id}.json"
        if row.get("parsed_file") != parsed_file:
            raise ValueError("묶음 수집 기록의 비교 파일 이름이 맞지 않습니다.")
        comparison = _receipt(directory, parsed_file)

    recorded = _reference(row, filename, "source_url", url)
    text, digest = decode_input(_read(directory, filename, DETAIL_MAX_BYTES), "공식 웹 상세")
    if digest != recorded:
        raise ValueError("공식 웹 상세 원본 해시가 수집 기록과 다릅니다.")
    parse_detail(category, text, web_id)
    _check_preview(comparison.get("web"), category, web_id, digest)
    return filename, digest, url, collected_at


# 포털 비교 원본 없이 공식 웹 목록·상세만 보관한 묶음의 재검증 설정
_WEB_ARCHIVES = {
    "road": {
        "section": road_batch.ROAD_SECTION, "schema": road_batch.BATCH_SCHEMA, "record": road_batch.RECORD_SCHEMA,
        "version": lambda _state: ROAD_PARSER_VERSION, "scope_key": "state", "scopes": ROAD_STATES, "label": "도로 공사현황", "item": "공사",
        "url": road_detail_url, "method": "official-web-road-works",
        "parse": lambda text, scope, key: parse_road_detail(text, state=scope, project_id=key),
    },
    "board": {
        "section": board_batch.BOARD_SECTION, "schema": board_batch.BATCH_SCHEMA, "record": board_batch.RECORD_SCHEMA,
        "version": board_parser_version, "scope_key": "board", "scopes": BOARDS, "label": "공지 게시판", "item": "공지",
        "url": board_detail_url, "method": "official-web-board",
        "parse": lambda text, scope, key: parse_board_notice(text, board=scope, notice_id=key),
    },
}


def _web_assets(private_root: Path, kind: str, name: str, asset_keys: set[str]) -> dict[str, dict]:
    """보관한 상세 원본·해시·파싱 결과와 파서 버전을 다시 대조한다."""
    config = _WEB_ARCHIVES[kind]
    label = config["label"]
    if "portal" in asset_keys:
        raise ValueError(f"{label} 수집에는 포털 원본이 없습니다.")
    relative = Path(config["section"]) / name
    with open_archive(private_root, relative) as directory:
        receipt = _receipt(directory, "batch.json")
        scope = receipt.get(config["scope_key"])
        if (receipt.get("schema_version") != config["schema"] or receipt.get("batch_id") != name
                or not isinstance(scope, str) or scope not in config["scopes"]):
            raise ValueError(f"{label} 수집 기록의 규격·이름·구분이 맞지 않습니다.")
        items = _batch_items(receipt, lambda web_id: config["url"](scope, web_id))
        assets = {}
        for key in sorted(asset_keys):
            row = items.get(key)
            if row is None or row["status"] != "parsed" or row.get("parsed_file") != f"parsed-{key}.json":
                raise ValueError(f"선택한 {config['item']}는 파싱이 완료된 {label} 수집 원본이어야 합니다.")
            filename = f"detail-{key}.html"
            recorded = _reference(row, filename, "source_url", config["url"](scope, key))
            text, digest = decode_input(_read(directory, filename, DETAIL_MAX_BYTES), f"{label} 상세")
            if digest != recorded:
                raise ValueError(f"{label} 상세 원본 해시가 수집 기록과 다릅니다.")
            parsed = _receipt(directory, row["parsed_file"])
            version = config["version"](scope)
            if parsed.get("parser_version") != version:
                raise ValueError("다른 파서 버전으로 만든 파싱 결과입니다. 현재 버전으로 다시 수집해 주세요.")
            if parsed != {"schema_version": config["record"], "parser_version": version,
                          "sha256": digest, "record": config["parse"](text, scope, key)}:
                raise ValueError(f"{label} 파싱 결과가 원본과 다릅니다.")
            assets[key] = {
                "raw_asset_path": (relative / filename).as_posix(),
                "raw_sha256": digest,
                "official_url": row["source_url"],
                "collected_at": capture_timestamp(row.get("fetched_at")),
                "collection_method": config["method"],
            }
        return assets


# 응답 페이지 원본을 그대로 등록하는 API 묶음. 읽기 함수가 원본 해시와 파생 결과를 먼저 다시 대조한다.
_API_ARCHIVES = {
    "portal": (PORTAL_SECTION, read_portal_snapshot, "포털 API", "data-go-kr-api"),
    "odcloud": (ODCLOUD_SECTION, read_odcloud_snapshot, "파일데이터 API", "data-go-kr-odcloud-api"),
}


def capture_assets(private_root: Path, archive_kind: str, archive_name: str,
                   asset_keys: set[str]) -> dict[str, dict]:
    """정해진 수집 경로 안의 원본만 읽으며 파일이나 기록을 바꾸지 않는다."""
    if not isinstance(archive_kind, str) or (archive_kind not in _ARCHIVES and archive_kind not in _WEB_ARCHIVES
                                             and archive_kind not in _API_ARCHIVES and archive_kind != "media"):
        raise ValueError("지원하지 않는 수집 기록 종류입니다.")
    if not isinstance(archive_name, str):
        raise ValueError("수집 이름이 유효하지 않습니다.")
    validate_name(archive_name)
    if not isinstance(asset_keys, set) or not asset_keys or any(
        key != "portal" and not _web_id(key) for key in asset_keys
    ):
        raise ValueError("선택한 수집 원본 키가 유효하지 않습니다.")
    if archive_kind == "media":
        return read_media_assets(private_root, archive_name, asset_keys)
    if archive_kind in _WEB_ARCHIVES:
        return _web_assets(private_root, archive_kind, archive_name, asset_keys)
    if archive_kind in _API_ARCHIVES:
        section, read_snapshot, label, method = _API_ARCHIVES[archive_kind]
        _, receipt = read_snapshot(private_root, archive_name)
        pages = {str(entry["page"]): entry for entry in receipt["responses"]}
        if not asset_keys <= pages.keys():
            raise ValueError(f"선택한 응답 페이지가 {label} 수집 기록에 없습니다.")
        return {
            key: {
                "raw_asset_path": (Path(section) / archive_name / pages[key]["file"]).as_posix(),
                "raw_sha256": pages[key]["sha256"],
                "official_url": pages[key]["source_url"],
                "collected_at": pages[key]["fetched_at"],
                "collection_method": method,
            }
            for key in sorted(asset_keys, key=int)
        }

    section, receipt_file, schema, name_key = _ARCHIVES[archive_kind]
    relative = Path(section) / archive_name
    with open_archive(private_root, relative) as directory:
        receipt = _receipt(directory, receipt_file)
        category = receipt.get("category")
        if (receipt.get("schema_version") != schema or receipt.get(name_key) != archive_name
                or not isinstance(category, str) or category not in SOURCE_PAGES):
            raise ValueError("수집 기록의 규격·이름·분야가 맞지 않습니다.")
        if archive_kind == "single" and (receipt.get("status") != "parsed"
                or receipt.get("parse_error") is not None or not _web_id(receipt.get("web_id"))):
            raise ValueError("단건 수집은 원본을 정상 파싱한 기록이어야 합니다.")
        items = _batch_items(receipt, lambda web_id: detail_url(category, web_id)) if archive_kind == "batch" else {}
        url = SOURCE_PAGES[category][0]
        portal_hash = _reference(receipt.get("portal"), "portal.csv", "catalog_url", url)

        assets = {}
        for key in sorted(asset_keys):
            if key == "portal":
                if "api_snapshot" in receipt["portal"]:
                    raise ValueError("API 비교용 CSV 대신 포털 API 응답 페이지를 선택해 주세요.")
                text, digest = decode_input(_read(directory, "portal.csv", PORTAL_MAX_BYTES),
                                            "포털 CSV", portal_csv=True)
                if digest != portal_hash:
                    raise ValueError("포털 CSV 원본 해시가 수집 기록과 다릅니다.")
                parse_portal(category, text)
                file, official, collected_at = "portal.csv", url, None
            else:
                file, digest, official, collected_at = _web_asset(directory, archive_kind, receipt, items, category, key)
            assets[key] = {
                "raw_asset_path": (relative / file).as_posix(),
                "raw_sha256": digest,
                "official_url": official,
                "collected_at": collected_at,
            }
        return assets
