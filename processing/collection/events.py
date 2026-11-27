"""전국문화축제와 안성행사알림이에서 읽은 원문을 수집 후보로 바꾼다."""

import csv
import io
import re
from urllib.parse import urlsplit

from processing.extraction.validation import decode

from . import official_url


FESTIVAL_FIELDS = {
    "축제시작일자": "start_date",
    "축제종료일자": "end_date",
    "개최장소": "place",
    "소재지도로명주소": "road_address",
    "소재지지번주소": "parcel_address",
    "위도": "latitude",
    "경도": "longitude",
    "주최기관명": "organizer",
    "축제내용": "description",
}
EVENT_FIELDS = {
    "eventSdate": "start_date",
    "eventEdate": "end_date",
    "eventTime": "time",
    "eventPlace": "place",
    "eventFee": "fee",
    "eventTarget": "target",
    "deptName": "organizer",
    "contents": "description",
}
ADDRESS_FIELDS = ("소재지도로명주소", "소재지지번주소")
LOCATION_FIELDS = {*ADDRESS_FIELDS, "주최기관명", "홈페이지주소"}
ANSEONG_ADDRESS = re.compile(r"(?:(?:경기도|경기)\s+)?안성시(?:\s|[,<(]|$)")
ANSEONG_ORGANIZERS = {"안성시", "안성시청", "경기도 안성시", "경기도 안성시청"}


def _optional_text(value: object) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or "\x00" in value:
        raise ValueError("수집 후보의 텍스트 필드 형식이 잘못됐습니다.")
    return value.strip()


def _fields(row: dict, mapping: dict[str, str]) -> dict[str, str]:
    fields = {}
    for original, normalized in mapping.items():
        value = _optional_text(row.get(original))
        if value:
            fields[normalized] = value
    return fields


def _in_anseong(row: dict, url: str | None) -> bool:
    addresses = [row.get(name, "").strip() for name in ADDRESS_FIELDS]
    if any(addresses):
        return any(ANSEONG_ADDRESS.match(address) for address in addresses)
    if row.get("주최기관명", "").strip() in ANSEONG_ORGANIZERS:
        return True
    if url is None:
        return False
    hostname = urlsplit(url).hostname
    return hostname == "anseong.go.kr" or hostname.endswith(".anseong.go.kr")


def parse_festival_csv(text: str) -> list[dict]:
    """안성 행만 읽으며 원천 ID가 없으면 그 값을 비워 둔다."""
    if not isinstance(text, str) or "\x00" in text:
        raise ValueError("문화축제 CSV 형식이 잘못됐습니다.")
    reader = csv.DictReader(io.StringIO(text.removeprefix("\ufeff"), newline=""), strict=True)
    records = []
    try:
        columns = reader.fieldnames
        if (not columns or len(columns) != len(set(columns)) or "" in columns
                or "축제명" not in columns or not LOCATION_FIELDS.intersection(columns)):
            raise ValueError("문화축제 CSV의 제목 또는 지역 식별 열이 잘못됐습니다.")
        for number, row in enumerate(reader, start=1):
            if None in row or None in row.values():
                raise ValueError("문화축제 CSV의 행과 헤더 열 개수가 다릅니다.")
            url = official_url(_optional_text(row.get("홈페이지주소")))
            if not _in_anseong(row, url):
                continue
            title = _optional_text(row["축제명"])
            if not title:
                raise ValueError("안성 문화축제 행에 제목이 없습니다.")
            records.append({
                "source": "festival_portal",
                "external_id": None,
                "source_record": number,
                "title": title,
                "official_url": url,
                "fields": _fields(row, FESTIVAL_FIELDS),
            })
    except csv.Error:
        raise ValueError("문화축제 CSV 형식이 잘못됐습니다.") from None
    return records


def parse_event_detail(text: str, *, event_id: str) -> dict:
    """공식 상세 응답 하나에서 확인 가능한 필드를 그대로 읽는다."""
    if not isinstance(event_id, str) or re.fullmatch(r"[1-9][0-9]*", event_id) is None:
        raise ValueError("행사 ID는 양의 ASCII 정수 문자열이어야 합니다.")
    if not isinstance(text, str):
        raise ValueError("행사 상세 JSON은 텍스트여야 합니다.")
    row = decode(text.encode("utf-8"), "input")
    if not isinstance(row, dict):
        raise ValueError("행사 상세 JSON은 객체여야 합니다.")
    if "idx" not in row:
        raise ValueError("행사 상세 JSON에 행사 ID가 없습니다.")
    if type(row["idx"]) not in (int, str) or str(row["idx"]) != event_id:
        raise ValueError("행사 상세 ID가 요청한 값과 다릅니다.")
    title = _optional_text(row.get("title"))
    if not title:
        raise ValueError("행사 상세에 제목이 없습니다.")
    result = {
        "source": "anseong_events",
        "external_id": event_id,
        "title": title,
        "official_url": official_url(_optional_text(row.get("url"))),
        "source_url": f"https://www.anseong.go.kr/event/program/popup/detail.do?idx={event_id}",
        "fields": _fields(row, EVENT_FIELDS),
    }
    media = [
        flag for field, flag in (("attachId", "attachment"), ("thumbnail", "thumbnail"))
        if _optional_text(row.get(field))
    ]
    if media:
        result["review_flags"] = media
    return result
