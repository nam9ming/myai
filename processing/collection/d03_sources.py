"""수집 기록과 비공개 원본을 대조해 등록에 필요한 정보를 돌려준다."""

from contextlib import ExitStack
from datetime import datetime
import os
from pathlib import Path
import re
import stat

from processing.extraction.validation import decode

from .__main__ import PORTAL_MAX_BYTES, SOURCE_PAGES, decode_input, parse_detail, parse_portal
from .capture import CAPTURE_RECEIPT_MAX_BYTES, validate_name
from .official_web import DETAIL_MAX_BYTES, detail_url


_ARCHIVES = {
    "single": ("collection", "capture.json", "citizen-source-capture-v1", "capture_id"),
    "batch": ("collection-batches", "batch.json", "citizen-source-batch-v1", "batch_id"),
}
_WEB_ID = re.compile(r"[1-9][0-9]{0,17}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UTC_TIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:\+00:00|Z)"
)
_DETAIL_STATUSES = ("parsed", "parse_failed", "fetch_failed", "not_attempted")


def _private(descriptor: int) -> os.stat_result:
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError("수집 디렉터리와 원본은 실행 사용자만 접근할 수 있어야 합니다.")
    return info


def _read(directory: int, filename: str, limit: int) -> bytes:
    options = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(filename, options, dir_fd=directory), "rb") as stream:
        if not stat.S_ISREG(_private(stream.fileno()).st_mode):
            raise ValueError("수집 원본과 기록은 일반 파일이어야 합니다.")
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("수집 원본 또는 기록이 허용 크기를 초과했습니다.")
    return raw


def _receipt(directory: int, filename: str) -> dict:
    data = decode(_read(directory, filename, CAPTURE_RECEIPT_MAX_BYTES),
                  "input", max_bytes=CAPTURE_RECEIPT_MAX_BYTES)
    if not isinstance(data, dict):
        raise ValueError("수집 기록 형식을 확인할 수 없습니다.")
    return data


def _web_id(value: object) -> bool:
    return isinstance(value, str) and _WEB_ID.fullmatch(value) is not None


def _reference(record: object, filename: str, url_key: str, url: str) -> str:
    if not isinstance(record, dict) or record.get("file") != filename or record.get(url_key) != url:
        raise ValueError("수집 기록의 파일 이름 또는 원문 주소가 맞지 않습니다.")
    digest = record.get("sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        raise ValueError("수집 기록의 원본 해시 형식이 맞지 않습니다.")
    return digest


def _timestamp(value: object) -> str:
    if isinstance(value, str) and _UTC_TIME.fullmatch(value):
        try:
            datetime.fromisoformat(value)
            return value
        except ValueError:
            pass
    raise ValueError("공식 웹 수신 시각은 UTC 날짜와 시각이어야 합니다.")


def _batch_items(record: dict, category: str) -> dict[str, dict]:
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
        if row.get("source_url") != detail_url(category, web_id):
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
        collected_at = _timestamp(receipt.get("web_fetched_at"))
        comparison = receipt.get("comparison")
        if (not isinstance(comparison, dict) or comparison.get("schema_version") != "citizen-source-preview-v1"
                or comparison.get("category") != category):
            raise ValueError("단건 수집 기록의 비교 결과를 확인할 수 없습니다.")
    else:
        row = items.get(web_id)
        if row is None or row["status"] != "parsed":
            raise ValueError("선택한 게시물은 파싱이 완료된 묶음 수집 원본이어야 합니다.")
        filename = f"detail-{web_id}.{extension}"
        collected_at = _timestamp(row.get("fetched_at"))
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


def capture_assets(private_root: Path, archive_kind: str, archive_name: str,
                   asset_keys: set[str]) -> dict[str, dict]:
    """정해진 수집 경로 안의 원본만 읽으며 파일이나 기록을 바꾸지 않는다."""
    if not isinstance(archive_kind, str) or archive_kind not in _ARCHIVES:
        raise ValueError("지원하지 않는 수집 기록 종류입니다.")
    if not isinstance(archive_name, str):
        raise ValueError("수집 이름이 유효하지 않습니다.")
    validate_name(archive_name)
    if not isinstance(asset_keys, set) or not asset_keys or any(
        key != "portal" and not _web_id(key) for key in asset_keys
    ):
        raise ValueError("선택한 수집 원본 키가 유효하지 않습니다.")
    section, receipt_file, schema, name_key = _ARCHIVES[archive_kind]
    relative = Path(section) / archive_name
    dir_options = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as stack:
            if not private_root.is_absolute() or private_root.resolve(strict=True) != private_root:
                raise ValueError("수집 원본 루트는 심볼릭 링크 없는 절대 경로여야 합니다.")
            directory = os.open(private_root, dir_options)
            stack.callback(os.close, directory)
            if (private_root.resolve(strict=True) != private_root
                    or not os.path.samestat(os.fstat(directory), private_root.lstat())):
                raise ValueError("수집 원본 루트가 확인 중에 바뀌었습니다.")
            for part in relative.parts:
                directory = os.open(part, dir_options, dir_fd=directory)
                stack.callback(os.close, directory)
                _private(directory)
            receipt = _receipt(directory, receipt_file)
            category = receipt.get("category")
            if (receipt.get("schema_version") != schema or receipt.get(name_key) != archive_name
                    or not isinstance(category, str) or category not in SOURCE_PAGES):
                raise ValueError("수집 기록의 규격·이름·분야가 맞지 않습니다.")
            if archive_kind == "single" and (receipt.get("status") != "parsed"
                    or receipt.get("parse_error") is not None or not _web_id(receipt.get("web_id"))):
                raise ValueError("단건 수집은 원본을 정상 파싱한 기록이어야 합니다.")
            items = _batch_items(receipt, category) if archive_kind == "batch" else {}
            url = SOURCE_PAGES[category][0]
            portal_hash = _reference(receipt.get("portal"), "portal.csv", "catalog_url", url)

            assets = {}
            for key in sorted(asset_keys):
                if key == "portal":
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
    except OSError:
        raise ValueError("수집 원본 또는 기록을 안전하게 읽을 수 없습니다.") from None
