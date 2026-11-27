"""수집 원본에 수동 검토 자료를 연결해 D03 등록 입력을 만든다."""

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from processing.extraction.schema import UUID
from processing.extraction.validation import MAX_BYTES, day, decode, require, shape, text

from .__main__ import read_raw
from .capture import CAPTURE_ROOT, bundle_directory, validate_name, write_complete, write_new
from .d03_sources import capture_assets

PRIVATE_ROOT = CAPTURE_ROOT.parent
DOCUMENT_FIELDS = ("asset official_url document_id document_version_id version_no publisher title "
                   "published_date official_number collected_at cleaned_text redaction_log")
UTC_STAMP = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z"


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


def prepare(input_path: Path, name: str, private_root: Path) -> dict:
    validate_name(name)
    input_bytes = read_raw(input_path, MAX_BYTES, "D03 검토 JSON")
    review = decode(input_bytes, "input")
    shape(review, "archive_kind archive_name data_kind documents", kind="input")
    kind = review["archive_kind"]
    require(kind in ("single", "batch", "portal", "media", "road", "board"), "$.archive_kind", "input")
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
            require(value not in known, path + "." + key, "input")
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
    output = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(output) > MAX_BYTES:
        raise ValueError("D03 등록 입력이 8 MiB를 초과했습니다.")
    with bundle_directory(private_root / "collection-d03", name) as directory:
        write_new(directory, "review.json", input_bytes)
        write_complete(directory, "source-import.json", output)
    return {"preparation_id": name, "documents": len(choices)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
