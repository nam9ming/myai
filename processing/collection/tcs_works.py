"""경찰청 도시교통정보센터(UTIC) TCS 공사정보 CSV를 운영자가 받은 파일에서 읽어 비공개로 보관한다.

TCS 자료는 개방데이터 신청(소속·이메일·신청 IP·목적)으로 받은 인증키가 있어야 내려받으므로 자동으로 받지 않는다.
열 배치는 2026-11-28에 받은 공개 레퍼런스 화면의 예제 행을 따른다. 예제에는 항목표에 없는 두 열(8·9번째)이
공사 일자 뒤에 있고 항목표의 공지여부(anouncePol)는 없다. 이 두 열은 이름을 붙이지 않고 `columns`에만 원문으로 둔다.
"""

import csv
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import unicodedata

from .__main__ import PORTAL_MAX_BYTES, read_raw
from .capture import (
    CAPTURE_ROOT, bundle_directory, capture_timestamp, open_archive, read_capture_file, read_receipt,
    validate_name, write_new, write_receipt,
)
from .cli import CollectionArguments
from .road_closures import _no_location, unreadable

REFERENCE_URL = "https://www.utic.go.kr/guide/utisRefTCS.do"
APPLY_URL = "https://www.utic.go.kr/guide/newUtisDataWrite.do"
TCS_SECTION = "collection-tcs"
TCS_ROOT = CAPTURE_ROOT.with_name(TCS_SECTION)
SCHEMA = "citizen-tcs-import-v1"
SELECTION_SCHEMA = "tcs-anseong-v1"
PARSER_VERSION = "tcs-csv-parser-v5"
CSV_MAX_BYTES = PORTAL_MAX_BYTES
# 레퍼런스 예제의 열 순서. None은 항목표에 없는 열이다.
LAYOUT = ("seq", "poliCode", "revYear", "revSeq", "poliName", "constFromDate", "constToDate", None, None,
          "constRoad", "trafficControl", "constName", "builderName")
FIELDS = ("seq", "poliCode", "revYear", "revSeq", "poliName", "constFromDate", "constToDate", "constRoad",
          "trafficControl", "constName", "builderName", "anouncePol")
# 열 밀림을 찾기 위한 모양 검사. 날짜·시각은 해석하지 않는다. 빈 값은 허용한다.
_SHAPES = {1: r"[0-9]{4}", 2: r"[0-9]{4}", 3: r"[0-9]{6}", 5: r"[0-9]{8}|", 6: r"[0-9]{8}|", 7: r"[0-9]{4}|",
           8: r"[0-9]{4}|"}
RULE = "constRoad에 '안성시' 포함 또는 poliName이 '안성'(안성경찰서)"
# 시공사(builderName)는 업체 이름이라 판단·검토에 쓰지 않는다.
OTHER_FIELDS = ("constName", "trafficControl")
READ_FIELDS = ("constRoad", "poliName", *OTHER_FIELDS)


def decode_csv(raw: bytes) -> tuple[str, str]:
    """UTF-8(BOM 허용)과 CP949만 받는다. 둘 다로 읽히는데 글자가 다르면 어느 쪽인지 알 수 없어 거부한다."""
    if b"\x00" in raw:
        raise ValueError("TCS CSV에 NUL 바이트가 있습니다(UTF-16 등은 지원하지 않음).")
    bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = {}
    for name in ("utf-8",) if bom else ("utf-8", "cp949"):
        try:
            decoded[name] = raw.removeprefix(b"\xef\xbb\xbf").decode(name)
        except UnicodeDecodeError:
            pass
    if len(decoded) == 2 and decoded["utf-8"] != decoded["cp949"]:
        raise ValueError("TCS CSV가 UTF-8과 CP949 양쪽으로 읽혀 인코딩을 정할 수 없습니다.")
    if not decoded:
        raise ValueError("TCS CSV는 UTF-8 또는 CP949여야 합니다.")
    name = next(iter(decoded))  # 둘 다 같으면(ASCII) utf-8
    return decoded[name], name


def _row(columns: list[str]) -> tuple[dict | None, str | None]:
    if len(columns) != len(LAYOUT):
        return None, f"열 수가 {len(columns)}개입니다(레퍼런스 예제는 {len(LAYOUT)}개)."
    for index, shape in _SHAPES.items():
        if re.fullmatch(shape, columns[index], re.ASCII) is None:
            return None, f"{index + 1}번째 열의 형식이 레퍼런스 예제와 다릅니다."
    if columns[0] != "-".join(columns[1:4]):
        return None, "일련번호(seq)가 경찰서코드-등록년도-등록일련번호와 다릅니다."
    fields, unknown = {}, {"anouncePol": "not_in_layout"}
    for name, value in zip(LAYOUT, columns):
        if name is not None:
            fields[name] = value if value.strip() else None
            if fields[name] is None:
                unknown[name] = "empty"
    fields["anouncePol"] = None
    return {"columns": columns, "fields": fields, "unknown": unknown}, None


def parse_tcs_csv(text: str) -> tuple[list[dict], list[dict]]:
    """머리글 없는 레퍼런스 예제 배치만 읽는다. 맞지 않는 행은 원문과 사유를 `rejected`에 남긴다."""
    records, rejected, seen = [], [], set()
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    end = 0
    try:
        for columns in reader:
            # line_num은 레코드가 끝난 줄이다. 여러 줄 레코드도 시작 줄을 남긴다.
            start, end = end + 1, reader.line_num
            if not columns:
                continue
            record, reason = _row(columns)
            if record is not None and columns[0] in seen:
                record, reason = None, "같은 일련번호(seq)가 앞 행에 있습니다."
            place = {"line": start}
            if record is None:
                rejected.append({**place, "reason": reason, "columns": columns})
            else:
                seen.add(columns[0])
                records.append({**place, **record})
    except csv.Error:
        raise ValueError(f"TCS CSV {reader.line_num}행 부근의 따옴표·구분자 형식이 올바르지 않습니다.") from None
    return records, rejected


def _has(value: str | None, word: str) -> bool:
    return value is not None and word in unicodedata.normalize("NFC", value)


def select_records(records: list[dict]) -> tuple[list, list]:
    matched, review = [], []
    for record in records:
        fields = record["fields"]
        match = {}
        if _has(fields["constRoad"], "안성시"):
            match["constRoad"] = fields["constRoad"]
        if fields["poliName"] is not None and unicodedata.normalize("NFC", fields["poliName"]).strip() == "안성":
            match["poliName"] = fields["poliName"]
        if reason := unreadable(fields, READ_FIELDS):
            review.append({"reason": reason, "record": record,
                           "mentions": [name for name in READ_FIELDS if _has(fields[name], "안성")]})
        elif match:
            matched.append({"match": match, "record": record})
        elif _no_location(fields["constRoad"]) and _no_location(fields["poliName"]):
            # 위치 근거가 없는(자리표시 포함) 행을 버리면 안성 행이 조용히 빠질 수 있다. 저장 값은 원문 그대로다.
            review.append({"reason": "blank_location", "record": record,
                           "mentions": [name for name in OTHER_FIELDS if _has(fields[name], "안성")]})
        elif found := [name for name in ("constRoad", "poliName") if _has(fields[name], "안성")]:
            review.append({"reason": "mention", "mentions": found, "record": record})
        elif found := [name for name in OTHER_FIELDS if _has(fields[name], "안성")]:
            review.append({"reason": "other_mention", "mentions": found, "record": record})
    return matched, review


def _selection(raw: bytes) -> tuple[bytes, dict]:
    """원본에서 선택 결과와 기록 요약을 만든다. 디코딩·CSV 형식 오류는 ValueError로 알린다."""
    text, encoding = decode_csv(raw)
    records, rejected = parse_tcs_csv(text)
    matched, review = select_records(records)
    document = {"schema_version": SELECTION_SCHEMA, "parser_version": PARSER_VERSION, "rule": RULE,
                "encoding": encoding, "rows": matched, "needs_review": review, "rejected": rejected}
    selection = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return selection, {"file": "anseong.json", "sha256": hashlib.sha256(selection).hexdigest(), "encoding": encoding,
                       "records": len(records), "rows": len(matched), "needs_review": len(review),
                       "rejected": len(rejected)}


def _base() -> dict:
    return {"schema_version": SCHEMA, "parser_version": PARSER_VERSION, "reference_url": REFERENCE_URL,
            "apply_url": APPLY_URL, "source_file": "source.csv"}


def import_tcs(csv_file: Path, name: str, root: Path) -> dict:
    """운영자 CSV를 먼저 그대로 쓰고 `tcs.json`을 마지막에 쓴다. 내려받은 시각은 알 수 없어 들여온 시각만 남긴다."""
    validate_name(name)
    raw = read_raw(csv_file, CSV_MAX_BYTES, "TCS CSV")
    with bundle_directory(root, name) as directory:
        write_new(directory, "source.csv", raw)
        receipt = {**_base(), "import_id": name, "imported_at": datetime.now(UTC).isoformat(),
                   "sha256": hashlib.sha256(raw).hexdigest(), "status": "failed"}
        try:
            selection, receipt["selection"] = _selection(raw)
            write_new(directory, "anseong.json", selection)
            counts = receipt["selection"]
            receipt["status"] = "partial" if counts["rejected"] or not counts["records"] else "complete"
        except ValueError as error:
            receipt["error"] = str(error)
        write_receipt(directory, "tcs.json", receipt)
    return {"import_id": name, "status": receipt["status"],
            **{key: receipt.get("selection", {}).get(key) for key in ("records", "rows", "needs_review", "rejected")}}


def read_tcs_snapshot(private_root: Path, name: str) -> tuple[bytes, dict]:
    """보관한 CSV 원본에서 선택 결과를 다시 만들어 `anseong.json`·기록과 대조한다. 실패 기록은 읽지 않는다."""
    validate_name(name)
    with open_archive(private_root, Path(TCS_SECTION) / name) as directory:
        receipt = read_receipt(directory, "tcs.json")
        if (receipt.get("import_id") != name or receipt.get("status") not in ("complete", "partial")
                or any(receipt.get(key) != value for key, value in _base().items())):
            raise ValueError("TCS CSV 보관 기록을 확인할 수 없습니다.")
        capture_timestamp(receipt.get("imported_at"))
        raw = read_capture_file(directory, "source.csv", CSV_MAX_BYTES)
        if receipt.get("sha256") != hashlib.sha256(raw).hexdigest():
            raise ValueError("TCS CSV 원본 해시가 맞지 않습니다.")
        selection, computed = _selection(raw)
        status = "partial" if computed["rejected"] or not computed["records"] else "complete"
        if (read_capture_file(directory, "anseong.json", 8 * CSV_MAX_BYTES) != selection
                or receipt.get("selection") != computed or receipt["status"] != status):
            raise ValueError("TCS 안성 선택 결과가 CSV 원본 또는 보관 기록과 다릅니다.")
        return selection, receipt


def main() -> int:
    parser = CollectionArguments(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        summary = import_tcs(args.csv, args.name, TCS_ROOT)
    except ValueError as error:
        print(f"TCS CSV 보관 실패: {error}", file=sys.stderr)
        return 1
    except OSError:
        print("TCS CSV 원본 또는 보관 기록을 저장할 수 없습니다.", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
