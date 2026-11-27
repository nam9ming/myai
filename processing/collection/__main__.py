"""시민 공지 수집 원본을 로컬에서 비교한다."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

from .events import parse_event_detail, parse_festival_csv
from .libraries import parse_library_csv, parse_library_notice

SOURCE_PAGES = {
    "culture": (
        "https://www.data.go.kr/data/15013104/standard.do",
        "https://www.anseong.go.kr/event/main.do",
    ),
    "living": (
        "https://www.data.go.kr/data/15013109/standard.do",
        "https://www.anseong.go.kr/library/bbs/list.do?mId=0401010000&ptIdx=16",
    ),
}
PORTAL_MAX_BYTES = 20 * 1024 * 1024
DETAIL_MAX_BYTES = 8 * 1024 * 1024
EVENT_IDENTITY_FIELDS = ("start_date", "end_date")


def read_input(path: Path, limit: int, label: str, *, portal_csv: bool = False) -> tuple[str, str]:
    try:
        with path.open("rb") as stream:
            raw = stream.read(limit + 1)
    except OSError as error:
        raise ValueError(f"{label} 파일을 읽을 수 없습니다.") from error
    if len(raw) > limit:
        raise ValueError(f"{label} 파일이 허용 크기를 초과했습니다.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        if not portal_csv:
            raise ValueError(f"{label} 파일은 UTF-8이어야 합니다.") from error
        try:
            text = raw.decode("cp949")
        except UnicodeDecodeError:
            raise ValueError(f"{label} 파일은 UTF-8 또는 EUC-KR이어야 합니다.") from None
    return text, hashlib.sha256(raw).hexdigest()


def normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def event_candidates(portal: list[dict], web: dict) -> list[int]:
    def same_event(item: dict) -> bool:
        return (
            bool(web["official_url"])
            and web["official_url"] == item["official_url"]
            and normalized_text(web["title"]) == normalized_text(item["title"])
            and all(
                bool(web["fields"].get(field)) and web["fields"][field] == item["fields"].get(field)
                for field in EVENT_IDENTITY_FIELDS
            )
        )

    return [index for index, item in enumerate(portal) if same_event(item)]


def library_candidates(portal: list[dict], web: dict) -> list[int]:
    text = normalized_text(web["title"] + " " + web["fields"].get("description", ""))
    return [
        index for index, item in enumerate(portal)
        if re.search(r"(?<!\w)" + re.escape(normalized_text(item["title"])) + r"(?!\w)", text)
    ]


def preview(category: str, portal: list[dict], web: dict,
            portal_sha256: str, web_sha256: str) -> dict:
    matches = event_candidates(portal, web) if category == "culture" else library_candidates(portal, web)
    if len(matches) == 1:
        state = "candidate"
    elif matches:
        state = "ambiguous"
    else:
        state = "unresolved"
    conflicts = {}
    if category == "culture" and len(matches) == 1:
        baseline = portal[matches[0]]["fields"]
        compared = web["fields"]
        conflicts = {
            name: {"portal": baseline[name], "web": compared[name]}
            for name in sorted((baseline.keys() & compared.keys()) - {"description"})
            if normalized_text(baseline[name]) != normalized_text(compared[name])
        }
    portal_page, web_page = SOURCE_PAGES[category]
    return {
        "schema_version": "citizen-source-preview-v1",
        "category": category,
        "portal": {"source_page": portal_page, "sha256": portal_sha256, "records": portal},
        "web": {"source_page": web_page, "sha256": web_sha256, "record": web},
        "relationship": {"state": state, "portal_indexes": matches, "conflicts": conflicts},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("category", choices=("culture", "living"))
    parser.add_argument("--portal-csv", type=Path, required=True)
    parser.add_argument("--web-detail", type=Path, required=True)
    parser.add_argument("--web-id", required=True)
    args = parser.parse_args()

    try:
        portal_text, portal_sha = read_input(args.portal_csv, PORTAL_MAX_BYTES, "포털 CSV", portal_csv=True)
        web_text, web_sha = read_input(args.web_detail, DETAIL_MAX_BYTES, "공식 웹 상세")
        if args.category == "culture":
            portal = parse_festival_csv(portal_text)
            web = parse_event_detail(web_text, event_id=args.web_id)
        else:
            portal = parse_library_csv(portal_text)
            web = parse_library_notice(web_text, notice_id=args.web_id)
        result = preview(args.category, portal, web, portal_sha, web_sha)
    except ValueError as error:
        print(f"수집 원본 검토 실패: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
