"""도서관·시청·안성배움e·읍면동 공지의 매체 링크를 확인하고 운영자가 확보한 원본을 보관한다."""

from collections.abc import Callable
from datetime import UTC, datetime
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile, ZIP_STORED, ZipFile

from .__main__ import decode_input, read_raw
from .batch import LIST_MAX_BYTES
from .board_batch import BATCH_SCHEMA as BOARD_BATCH_SCHEMA, BOARD_SECTION
from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .libraries import parse_board_media, parse_library_media
from .library_listing import parse_board_listing
from .official_web import (
    BOARDS, DETAIL_MAX_BYTES, board as board_info, board_detail_url, detail_url, fetch_board_detail, fetch_detail,
)

NOTICE_SECTION = "collection-media-notices"
MEDIA_SECTION = "collection-media"
PRIVATE_ROOT = CAPTURE_ROOT.parent
NOTICE_SCHEMA = "citizen-media-notice-v1"
MEDIA_SCHEMA = "citizen-supplied-media-v1"
HWPX_MIME = b"application/hwp+zip"
SIGNATURES = {
    "pdf": b"%PDF-",
    "hwp": b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",
    "jpeg": b"\xff\xd8\xff",
    "png": b"\x89PNG\r\n\x1a\n",
}
MEDIA_FILES = {"media.hwpx", *("media." + fmt for fmt in SIGNATURES)}


def _route(board: str) -> tuple[str, Callable, Callable, Callable]:
    """게시판별 문구·원문 주소·요청·매체 파서를 돌려준다. 요청 함수는 호출 시점에 찾는다."""
    if board == "library":
        return ("도서관 공지", lambda web_id: detail_url("living", web_id),
                lambda web_id: fetch_detail("living", web_id, limit=DETAIL_MAX_BYTES),
                lambda text, web_id: parse_library_media(text, notice_id=web_id))
    return (board_info(board).label, lambda web_id: board_detail_url(board, web_id),
            lambda web_id: fetch_board_detail(board, web_id, limit=DETAIL_MAX_BYTES),
            lambda text, web_id: parse_board_media(text, board=board, notice_id=web_id))


def _needs_listing(board: str) -> bool:
    return board != "library" and board_info(board).check_list_form


def _check_listed(private_root: Path, board: str, batch: object, web_id: str) -> None:
    """읍면동 상세는 다른 읍면동 주소로도 열려 소속을 알 수 없으므로 같은 게시판 묶음의 목록 원본에 나온 번호만 받는다."""
    label = board_info(board).label
    if not isinstance(batch, str):
        raise ValueError(f"{label}는 그 게시판 목록에 나온 번호인지 확인할 묶음 수집 이름(--batch)이 필요합니다.")
    validate_name(batch)
    invalid = f"{label} 묶음 수집 기록을 확인할 수 없습니다."
    with open_archive(private_root, Path(BOARD_SECTION) / batch) as directory:
        receipt = read_receipt(directory, "batch.json")
        if (receipt.get("schema_version") != BOARD_BATCH_SCHEMA or receipt.get("batch_id") != batch
                or receipt.get("board") != board or not isinstance(receipt.get("pages"), list)):
            raise ValueError(invalid)
        for entry in receipt["pages"]:
            if not isinstance(entry, dict) or entry.get("status") != "parsed":
                continue
            page = entry.get("page")
            if type(page) is not int or entry.get("file") != f"list-{page}.html":
                raise ValueError(invalid)
            raw = read_capture_file(directory, entry["file"], LIST_MAX_BYTES)
            if entry.get("sha256") != hashlib.sha256(raw).hexdigest():
                raise ValueError(f"{label} 목록 원본 해시가 수집 기록과 다릅니다.")
            _, numbered, pinned = parse_board_listing(raw, board=board, page=page)
            if web_id in numbered or web_id in pinned:
                return
    raise ValueError(f"{label} 묶음 {batch}의 목록 원본에 없는 공지 번호입니다({web_id}).")


def inspect_notice(private_root: Path, web_id: str, name: str, *, board: str = "library",
                   batch: str | None = None) -> dict:
    validate_name(name)
    label, detail, fetch, parse_media = _route(board)
    url = detail(web_id)
    if len(web_id) > 18:
        raise ValueError("공식 웹 게시물 번호는 최대 18자리여야 합니다.")
    if batch is not None or _needs_listing(board):
        _check_listed(private_root, board, batch, web_id)
    with bundle_directory(private_root / NOTICE_SECTION, name) as directory:
        fetched_at = digest = None
        status = "fetch_failed"
        error = None
        try:
            raw = fetch(web_id)
            fetched_at = datetime.now(UTC).isoformat()
            write_new(directory, "notice.html", raw)
            digest = hashlib.sha256(raw).hexdigest()
            status = "parse_failed"
            text, _ = decode_input(raw, label)
            candidates = parse_media(text, web_id)
            status = "parsed"
        except ValueError as failure:
            candidates, error = [], str(failure)
        # 도서관 기록은 기존 형식을 유지하고 다른 게시판만 board를 남긴다.
        record = {"schema_version": NOTICE_SCHEMA, "notice_id": name, "web_id": web_id, "status": status,
                  "source_url": url, "fetched_at": fetched_at, "sha256": digest,
                  "media": candidates, "error": error}
        if board != "library":
            record["board"] = board
        if batch is not None:
            record["listing_batch"] = batch
        write_receipt(directory, "notice.json", record)
    return {"notice_id": name, "status": status, "media": len(candidates)}


def _notice(private_root: Path, name: str) -> dict:
    validate_name(name)
    with open_archive(private_root, Path(NOTICE_SECTION) / name) as directory:
        receipt = read_receipt(directory, "notice.json")
        web_id = receipt.get("web_id")
        board = receipt.get("board", "library")
        if "board" in receipt and (not isinstance(board, str) or board == "library" or board not in BOARDS):
            raise ValueError("공지 수집 기록을 확인할 수 없습니다.")
        label, detail, _, parse_media = _route(board)
        if (receipt.get("schema_version") != NOTICE_SCHEMA or receipt.get("notice_id") != name
                or receipt.get("status") != "parsed" or receipt.get("error") is not None
                or not isinstance(web_id, str) or not re.fullmatch(r"[1-9][0-9]{0,17}", web_id)
                or receipt.get("source_url") != detail(web_id)):
            raise ValueError(f"{label} 수집 기록을 확인할 수 없습니다.")
        if "listing_batch" in receipt or _needs_listing(board):
            _check_listed(private_root, board, receipt.get("listing_batch"), web_id)
        capture_timestamp(receipt.get("fetched_at"))
        raw = read_capture_file(directory, "notice.html", DETAIL_MAX_BYTES)
        text, digest = decode_input(raw, label)
        if receipt.get("sha256") != digest or receipt.get("media") != parse_media(text, web_id):
            raise ValueError(f"{label} 원본 또는 매체 목록이 수집 기록과 다릅니다.")
        return receipt


def _chosen(notice: dict, asset: int) -> dict:
    if type(asset) is not int or not 1 <= asset <= len(notice["media"]):
        raise ValueError("공지 매체 목록의 번호를 지정해 주세요.")
    candidate = notice["media"][asset - 1]
    if not candidate["source_url"]:
        raise ValueError("공지 원문에서 연결 주소를 확인할 수 있는 매체만 연결할 수 있습니다.")
    return candidate


def _file_format(raw: bytes, candidate: dict) -> str:
    formats = ("jpeg", "png") if candidate["kind"] == "image" else (candidate["format"],)
    for fmt in formats:
        if fmt in SIGNATURES and raw.startswith(SIGNATURES[fmt]):
            return fmt
        if fmt == "hwpx" and raw.startswith(b"PK\x03\x04"):
            try:
                with ZipFile(BytesIO(raw)) as package:
                    entry = package.getinfo("mimetype")
                    if (entry.compress_type == ZIP_STORED and entry.file_size == entry.compress_size == len(HWPX_MIME)
                            and package.read(entry) == HWPX_MIME):
                        return fmt
            except (BadZipFile, KeyError, RuntimeError, UnicodeError):
                pass
    raise ValueError("선택한 공지의 첨부 형식 또는 이미지 서명과 파일이 일치하지 않습니다.")


def _downloaded_timestamp(value: object) -> str:
    timestamp = capture_timestamp(value)
    if datetime.fromisoformat(timestamp).year < 1000:
        raise ValueError("매체 다운로드 시각의 연도는 1000년 이상이어야 합니다.")
    return timestamp


def store_media(private_root: Path, notice_name: str, asset: int, file: Path, name: str,
                downloaded_at: str) -> dict:
    validate_name(name)
    downloaded_at = _downloaded_timestamp(downloaded_at)
    notice = _notice(private_root, notice_name)
    candidate = _chosen(notice, asset)
    raw = read_raw(file, DETAIL_MAX_BYTES, "선택한 매체")
    fmt = _file_format(raw, candidate)
    filename = "media." + fmt
    with bundle_directory(private_root / MEDIA_SECTION, name) as directory:
        write_new(directory, filename, raw)
        write_receipt(directory, "media.json", {
            "schema_version": MEDIA_SCHEMA, "media_id": name, "notice_id": notice_name,
            "notice_sha256": notice["sha256"], "asset": asset, "linked_source_url": candidate["source_url"],
            "file": filename, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
            "operator_downloaded_at": downloaded_at,
        })
    return {"media_id": name, "asset": asset, "format": fmt, "bytes": len(raw)}


def read_media_assets(private_root: Path, name: str, asset_keys: set[str]) -> dict[str, dict]:
    validate_name(name)
    relative = Path(MEDIA_SECTION) / name
    with open_archive(private_root, relative) as directory:
        receipt = read_receipt(directory, "media.json")
        notice_name = receipt.get("notice_id")
        number = receipt.get("asset")
        if (receipt.get("schema_version") != MEDIA_SCHEMA or receipt.get("media_id") != name
                or not isinstance(notice_name, str) or type(number) is not int or asset_keys != {str(number)}):
            raise ValueError("선택한 매체가 보관 기록과 일치하지 않습니다.")
        notice = _notice(private_root, notice_name)
        candidate = _chosen(notice, number)
        if receipt.get("notice_sha256") != notice["sha256"] or receipt.get("linked_source_url") != candidate["source_url"]:
            label = _route(notice.get("board", "library"))[0]
            raise ValueError(f"보관 파일과 {label}의 연결 기록이 일치하지 않습니다.")
        filename = receipt.get("file")
        if not isinstance(filename, str) or filename not in MEDIA_FILES:
            raise ValueError("보관 파일 이름을 확인할 수 없습니다.")
        raw = read_capture_file(directory, filename, DETAIL_MAX_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if (receipt.get("sha256") != digest or type(receipt.get("bytes")) is not int
                or receipt["bytes"] != len(raw) or filename != "media." + _file_format(raw, candidate)):
            raise ValueError("보관 파일 원본 또는 형식이 기록과 다릅니다.")
        return {str(number): {
            "raw_asset_path": (relative / filename).as_posix(), "raw_sha256": digest,
            "official_url": notice["source_url"], "collected_at": _downloaded_timestamp(receipt.get("operator_downloaded_at")),
            "collection_method": "official-web-media-manual",
        }}


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True, parser_class=CollectionArguments)
    inspect = commands.add_parser("inspect", help="도서관·시청·안성배움e·읍면동 공지 HTML과 매체 목록을 보관한다.")
    inspect.add_argument("--board", choices=("library", *BOARDS), default="library")
    inspect.add_argument("--web-id", required=True)
    inspect.add_argument("--name", required=True)
    inspect.add_argument("--batch", help="읍면동 공지는 필수. 이 번호가 목록에 나온 같은 게시판 board_batch 묶음 이름")
    store = commands.add_parser("store", help="운영자가 확보한 파일 한 개를 매체 항목과 연결한다.")
    store.add_argument("--notice", required=True)
    store.add_argument("--asset", required=True, type=int)
    store.add_argument("--file", required=True, type=Path)
    store.add_argument("--downloaded-at", required=True)
    store.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        if args.action == "inspect":
            result = inspect_notice(PRIVATE_ROOT, args.web_id, args.name, board=args.board, batch=args.batch)
        else:
            result = store_media(PRIVATE_ROOT, args.notice, args.asset, args.file, args.name, args.downloaded_at)
    except ValueError as error:
        print(f"공지 매체 처리 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("공지 매체의 원본 또는 기록을 보관할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 2 if result.get("status") in ("parse_failed", "fetch_failed") else 0


if __name__ == "__main__":
    raise SystemExit(main())
