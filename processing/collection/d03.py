"""수집 원본에 수동 검토 자료를 연결해 D03 등록 입력을 만든다."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import unicodedata

from processing.extraction.schema import UUID
from processing.extraction.validation import MAX_BYTES, day, decode, require, shape, text

from .__main__ import read_raw
from .capture import (
    CAPTURE_ROOT, bundle_directory, open_archive, private_stat, read_receipt, validate_name, write_complete, write_new,
)
from .cli import CollectionArguments
from .d03_sources import capture_assets
from .official_web import BOARDS, board_detail_url, detail_url

PRIVATE_ROOT = CAPTURE_ROOT.parent
DOCUMENT_FIELDS = ("asset official_url document_id document_version_id version_no publisher title "
                   "published_date official_number collected_at cleaned_text redaction_log")
UTC_STAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"
D03_SECTION = "collection-d03"
_BOARD_ID = re.compile(r"[?&]bIdx=([1-9][0-9]{0,17})(?:&|$)")
_BODY = "official-web-board"


def kept_text(value, field: str, limit: int, *, multiline: bool = False) -> str:
    content = text(value, field, "input")
    allowed = "\r\n\t" if multiline else ""
    require(len(content.encode("utf-16-le")) // 2 <= limit
            and all((ord(char) >= 32 and ord(char) != 127) or char in allowed for char in content),
            field, "input")
    return content


def utc_timestamp(value, field: str) -> str:
    value = text(value, field, "input")
    if value.endswith("+00:00"):
        value = value.removesuffix("+00:00") + "Z"
    text(value, field, "input", UTC_STAMP)
    try:
        require(datetime.fromisoformat(value).year >= 1000, field, "input")
    except ValueError:
        require(False, field, "input")
    return value


def canonical_text(value, field: str, *, multiline: bool = False) -> str:
    content = kept_text(value, field, MAX_BYTES, multiline=multiline)
    return unicodedata.normalize("NFC", content.replace("\r\n", "\n").replace("\r", "\n"))


def document(review: dict, asset: dict, path: str) -> dict:
    require(review["official_url"] == asset["official_url"], path + ".official_url", "input")
    is_portal = review["asset"] == "portal"
    if is_portal:
        collected_at = utc_timestamp(review["collected_at"], path + ".collected_at")
    else:
        require(review["collected_at"] is None, path + ".collected_at", "input")
        collected_at = utc_timestamp(asset["collected_at"], path + ".collected_at")
    version = review["version_no"]
    require(type(version) is int and 1 <= version <= (1 << 63) - 1, path + ".version_no", "input")
    published_date = review["published_date"]
    if published_date is not None:
        require(day(published_date, path + ".published_date", "input").year >= 1000,
                path + ".published_date", "input")
    number = review["official_number"]
    if number is not None:
        kept_text(number, path + ".official_number", 255)
    redactions = review["redaction_log"]
    require(type(redactions) is list, path + ".redaction_log", "input")
    for index, entry in enumerate(redactions):
        field = f"{path}.redaction_log[{index}]"
        shape(entry, "category location", field, "input")
        kept_text(entry["category"], field + ".category", 128)
        kept_text(entry["location"], field + ".location", 512)

    cleaned = canonical_text(review["cleaned_text"], path + ".cleaned_text", multiline=True)
    return {
        "document_id": review["document_id"],
        "publisher": kept_text(review["publisher"], path + ".publisher", 255),
        "official_url": asset["official_url"],
        "title": canonical_text(review["title"], path + ".title"),
        "official_number": number,
        "published_date": published_date,
        "collected_at": collected_at,
        "document_version_id": review["document_version_id"],
        "version_no": version,
        "raw_asset_path": asset["raw_asset_path"],
        "raw_sha256": asset["raw_sha256"],
        "cleaned_text": cleaned,
        "text_sha256": hashlib.sha256(cleaned.encode("utf-8")).hexdigest(),
        "block_index": [{"block_id": "reviewed", "page": None, "text": cleaned}],
        "redaction_log": redactions,
        "preprocessing_version": "collection-manual-v1",
        "use_review": "pending",
        "use_note": "수집 원본 등록용입니다. 사용권과 원문 검증은 별도 기록합니다.",
        "collection_method": "portal-csv-manual" if is_portal else asset.get("collection_method", "official-web-capture"),
        "latest_check_attempt_at": None,
        "last_verified_at": None,
        "check_result": "unchecked",
        "checks": [],
    }


def _board_notice(url: str) -> tuple[str, str] | None:
    """게시판·도서관 공지와 그 매체 문서의 주소면 (게시물 번호 공간 ptIdx, 공지 번호)를 돌려준다."""
    match = _BOARD_ID.search(url)
    if match:
        # 도서관 상세도 시청과 같은 ptIdx=16 번호를 쓰고, 같은 공지가 시청 목록에도 실린다(예: 202960).
        if url == detail_url("living", match[1]):
            return "16", match[1]
        for key, info in BOARDS.items():
            if url == board_detail_url(key, match[1]):
                return info.pt_idx, match[1]
    return None


def _prepared_documents(private_root: Path) -> list[tuple[str, dict]]:
    """완료된 기존 D03 준비본의 문서를 읽는다. 완료 파일이 없는 준비본은 등록할 수 없으므로 건너뛴다."""
    if not os.path.lexists(private_root / D03_SECTION):
        return []
    found = []
    with open_archive(private_root, Path(D03_SECTION)) as section:
        for name in sorted(os.listdir(section)):
            try:
                validate_name(name)
            except ValueError:
                continue
            directory = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=section)
            try:
                private_stat(directory)
                receipt = read_receipt(directory, "source-import.json")
            except FileNotFoundError:
                continue
            finally:
                os.close(directory)
            documents = receipt.get("documents")
            if not isinstance(documents, list) or not all(
                    isinstance(document, dict) and isinstance(document.get("official_url"), str)
                    and isinstance(document.get("document_id"), str) for document in documents):
                raise ValueError("기존 D03 준비본을 확인할 수 없습니다.")
            found.extend((name, document) for document in documents)
    return found


def _check_board_notices(private_root: Path, name: str, documents: list[dict]) -> None:
    """시청·도서관·읍면동 공지는 게시물 번호(ptIdx=16)를 공유하고 원본 해시가 게시판마다 달라 같은 공지가 별개 문서로 들어간다.

    그래서 같은 번호 공간의 같은 공지 번호는 모든 준비본에서 한 게시판 주소만 쓰고, 공지 본문 문서는 한 문서 ID(그 문서의
    새 버전 포함)만 허용한다. 같은 게시판의 매체 문서는 여러 개일 수 있다. 도서관 본문은 등록 방식이 달라 주소만 대조한다.
    안성배움e(ptIdx=300)는 따로 대조한다.
    shortcut: 동시에 실행한 준비끼리는 서로 보지 못한다. 여러 운영자가 동시에 준비하게 되면 잠금을 둔다.
    """
    keys = [_board_notice(document["official_url"]) for document in documents]
    if not any(keys):
        return
    prepared: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    for source, document in _prepared_documents(private_root):
        key = _board_notice(document["official_url"])
        if key:
            prepared.setdefault(key, []).append((source, document))
    for key, document in zip(keys, documents):
        if key is None:
            continue
        for source, other in prepared.get(key, ()):
            if other["official_url"] != document["official_url"]:
                raise ValueError(f"공지 번호 {key[1]}의 문서가 D03 준비본 {source}에 다른 게시판 주소로 이미 있습니다. "
                                 "같은 공지는 한 게시판의 원본만 등록합니다.")
            if (_BODY == document["collection_method"] == other.get("collection_method")
                    and other["document_id"] != document["document_id"]):
                raise ValueError(f"공지 번호 {key[1]}의 본문이 D03 준비본 {source}에 다른 문서 ID로 이미 있습니다. "
                                 "내용이 바뀌었으면 기존 문서 ID의 새 버전으로 준비합니다.")
        prepared.setdefault(key, []).append((name, document))


def prepare(input_path: Path, name: str, private_root: Path) -> dict:
    validate_name(name)
    input_bytes = read_raw(input_path, MAX_BYTES, "D03 검토 JSON")
    review = decode(input_bytes, "input")
    shape(review, "archive_kind archive_name data_kind documents", kind="input")
    kind = review["archive_kind"]
    require(kind in ("single", "batch", "portal", "odcloud", "media", "road", "board"), "$.archive_kind", "input")
    archive_name = text(review["archive_name"], "$.archive_name", "input")
    validate_name(archive_name)
    require(review["data_kind"] in ("real", "synthetic"), "$.data_kind", "input")
    choices = review["documents"]
    require(type(choices) is list and 1 <= len(choices) <= 81, "$.documents", "input")
    selected = set()
    doc_ids = set()
    version_ids = set()
    for index, item in enumerate(choices):
        path = f"$.documents[{index}]"
        shape(item, DOCUMENT_FIELDS, path, "input")
        for key, known, pattern in (
            ("asset", selected, r"portal|[1-9][0-9]{0,17}"),
            ("document_id", doc_ids, UUID),
            ("document_version_id", version_ids, UUID),
        ):
            value = text(item[key], path + "." + key, "input", pattern)
            # API 응답 한 페이지에 안성시 행이 여러 개 있을 수 있어 그 페이지는 여러 문서의 원본이 될 수 있다.
            require(value not in known or (key == "asset" and kind in ("portal", "odcloud")),
                    path + "." + key, "input")
            known.add(value)

    assets = capture_assets(private_root, kind, archive_name, selected)
    result = {
        "schema_version": "source-import-v1",
        "data_kind": review["data_kind"],
        "documents": [document(item, assets[item["asset"]], f"$.documents[{index}]")
                      for index, item in enumerate(choices)],
        "evidence": [],
        "events": [],
    }
    _check_board_notices(private_root, name, result["documents"])
    output = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(output) > MAX_BYTES:
        raise ValueError("D03 등록 입력이 8 MiB를 초과했습니다.")
    with bundle_directory(private_root / D03_SECTION, name) as directory:
        write_new(directory, "review.json", input_bytes)
        write_complete(directory, "source-import.json", output)
    return {"preparation_id": name, "documents": len(choices)}


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = prepare(args.input, args.name, PRIVATE_ROOT)
    except ValueError as error:
        print(f"D03 준비 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("D03 준비 묶음을 읽거나 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
