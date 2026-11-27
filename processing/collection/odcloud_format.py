"""공공데이터포털 파일데이터 API(api.odcloud.kr) 응답을 검증하고 안성시 행을 고른다.

API 경로·인자·응답 구조는 2026-11-27에 받은 공개 Swagger 문서를 근거로 한다.
- 디지털배움터 교육장 현황: https://infuser.odcloud.kr/oas/docs?namespace=15134509/v1
- 도로 공사정보: https://infuser.odcloud.kr/oas/docs?namespace=15052289/v1
두 문서 모두 GET `page`·`perPage`·`returnType`, 인증은 `serviceKey` 쿼리 또는 `Authorization` 헤더,
응답은 `page`·`perPage`·`totalCount`·`currentCount`·`matchCount`·`data`로 적혀 있다.
인증된 실제 응답은 확인하지 못했으므로 문서와 다른 구조는 추정하지 않고 거부한다.
"""

import hashlib
import json
from types import MappingProxyType
from typing import NamedTuple
import unicodedata

from processing.extraction.validation import decode


class Dataset(NamedTuple):
    """Swagger에 적힌 최신 API 하나. fields는 Swagger 모델의 열 이름 그대로다."""

    namespace: str
    uddi: str
    title: str
    category: str
    fields: tuple[str, ...]
    # 판정에 쓰는 열 가운데 모두 비면(null·공백·자리표시) 판정할 수 없는 열.
    judged_fields: tuple[str, ...]
    # 규칙에 맞지 않아도 '안성'이 보이면 사람 검토로 넘기는 위치 열(mention)과 그 밖의 열(other_mention).
    location_fields: tuple[str, ...]
    other_fields: tuple[str, ...]
    rule: str

    @property
    def path(self) -> str:
        return f"/api/{self.namespace}/{self.uddi}"

    @property
    def catalog_url(self) -> str:
        return f"https://www.data.go.kr/data/{self.namespace.split('/')[0]}/fileData.do"

    @property
    def swagger_url(self) -> str:
        return f"https://infuser.odcloud.kr/oas/docs?namespace={self.namespace}"


DATASETS = MappingProxyType({
    # 교육장 위치·유형·정원만 있고 수업 일정은 없다.
    "digital-learning": Dataset(
        "15134509/v1", "uddi:b87e06b5-9a2a-4627-a3b3-c7a850904a62",
        "한국지능정보사회진흥원_디지털배움터 교육장 현황_20260814", "education",
        ("관리지역", "시군구", "배움터명", "배움터주소", "배움터 유형", "이용정원"),
        ("시군구",),
        ("관리지역", "시군구", "배움터명", "배움터주소"),
        (),
        "관리지역=경기도 그리고 시군구=안성시",
    ),
    # 현장주소(현장사무실)는 공사 구간과 다를 수 있고 시공사는 업체 이름이라 판단·표기 검토에 쓰지 않는다.
    "road-construction": Dataset(
        "15052289/v1", "uddi:7cb3d05a-3099-4572-8a39-997740b78f76",
        "국토교통부_도로 공사정보_20260801", "construction",
        ("발주청", "공사명", "공사구분", "주요사업지", "사업개요", "노선명", "공사위치", "시공사",
         "현장주소", "시작일", "준공일", "도급액(원)"),
        ("주요사업지", "공사위치"),
        ("주요사업지", "공사위치"),
        ("발주청", "공사명", "사업개요", "노선명"),
        "주요사업지 또는 공사위치에 '안성시' 포함",
    ),
})
ENVELOPE = frozenset({"page", "perPage", "totalCount", "currentCount", "matchCount", "data"})
MATCH_SCHEMA = "odcloud-anseong-v1"


def dataset(name: str) -> Dataset:
    if not isinstance(name, str) or name not in DATASETS:
        raise ValueError("지원하지 않는 파일데이터 API입니다.")
    return DATASETS[name]


def _count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("파일데이터 API 응답의 페이지 또는 건수 형식이 올바르지 않습니다.")
    return value


def parse_page(name: str, raw: bytes, page: int, per_page: int) -> tuple[int, list[dict]]:
    """응답 한 페이지의 건수가 요청·전체 건수와 맞는지 확인하고 행을 그대로 돌려준다."""
    config = dataset(name)
    if type(page) is not int or page < 1 or type(per_page) is not int or per_page < 1:
        raise ValueError("파일데이터 API의 요청 페이지와 페이지당 건수는 양의 정수여야 합니다.")
    document = decode(raw, "input")
    if not isinstance(document, dict) or set(document) != ENVELOPE:
        raise ValueError("파일데이터 API 응답 구조가 Swagger 문서와 다릅니다.")
    if _count(document["page"]) != page or _count(document["perPage"]) != per_page:
        raise ValueError("파일데이터 API 응답의 페이지 또는 페이지당 건수가 요청과 다릅니다.")
    total = _count(document["totalCount"])
    # 조건(cond) 인자를 보내지 않으므로 조건 일치 건수는 전체 건수와 같아야 한다.
    if _count(document["matchCount"]) != total:
        raise ValueError("파일데이터 API 응답의 조건 일치 건수가 전체 건수와 다릅니다.")
    rows = document["data"]
    expected = max(0, min(per_page, total - (page - 1) * per_page))
    if (not isinstance(rows, list) or _count(document["currentCount"]) != len(rows)
            or len(rows) != expected):
        raise ValueError("파일데이터 API 응답의 행 개수가 페이지 정보와 맞지 않습니다.")
    for row in rows:
        if not isinstance(row, dict) or set(row) != set(config.fields):
            raise ValueError("파일데이터 API 응답의 열이 Swagger 문서와 다릅니다.")
        for value in row.values():
            # 실수·논리값·중첩 값은 원문 그대로 다시 쓸 수 없어 거부한다.
            if not (value is None or type(value) is int or (type(value) is str and "\x00" not in value)):
                raise ValueError("파일데이터 API 응답에 지원하지 않는 값 형식이 있습니다.")
    return total, rows


def row_fingerprints(rows: list[dict]) -> set[bytes]:
    """열 순서와 관계없이 같은 행을 찾는 지문."""
    return {hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).digest()
            for row in rows}


def _nfc(value: object) -> str | None:
    """판정에만 쓰는 NFC 정규화 값. 원본 record는 바꾸지 않는다."""
    return unicodedata.normalize("NFC", value) if isinstance(value, str) else None


# shortcut: 알려 둔 낱말 자리표시만 빈 값으로 본다. 첫 실제 수집에서 판정 열의 서로 다른 값을 보고 늘린다.
# 공백을 모두 지우고 casefold로 비교한다('해당 없음'·'n/a'도 같다).
PLACEHOLDERS = frozenset({"미정", "미상", "없음", "해당없음", "n/a"})


def _blank(value: object) -> bool:
    # 글자·숫자가 없는 값('-' 등)과 낱말 자리표시도 위치·날짜를 알려 주지 않으므로 빈 값으로 본다.
    if not isinstance(value, str):
        return value is None
    text = "".join(_nfc(value).split()).casefold()
    return not any(char.isalnum() for char in text) or text in PLACEHOLDERS


def _mentions(row: dict, fields: tuple[str, ...], word: str) -> list[str]:
    return [field for field in fields if isinstance(row[field], str) and word in _nfc(row[field])]


def anseong_match(name: str, row: dict) -> dict | None:
    """정해진 열만 보고 판단한다. 근거가 된 열의 원문 값을 함께 돌려준다."""
    config = dataset(name)
    if name == "digital-learning":
        region, district = row["관리지역"], row["시군구"]
        if (isinstance(region, str) and isinstance(district, str)
                and _nfc(region).strip() == "경기도" and _nfc(district).strip() == "안성시"):
            return {"rule": config.rule, "fields": {"관리지역": region, "시군구": district}}
        return None
    # 군 단위 '안성면'(무주군) 등과 섞이지 않도록 '안성시'만 일치로 본다.
    fields = _mentions(row, config.location_fields, "안성시")
    return {"rule": config.rule, "fields": {field: row[field] for field in fields}} if fields else None


def select_rows(name: str, page: int, rows: list[dict], matched: list, review: list, unmentioned: list) -> None:
    """안성시 행과 사람이 확인할 행을 원본 위치와 함께 모은다.

    검토 대상(review)의 reason은 다음과 같다.
    - blank_location: 판정 열이 모두 비어 판정할 수 없는 행. mentions는 모든 열에서 찾은 '안성' 표기다.
    - mention: 위치 열에 '안성'이 보이지만 규칙에 맞지 않는 행.
    - other_mention: 위치 열에는 없지만 그 밖의 검토 열에 '안성'이 보이는 행.
    판정 열이 비고 '안성' 표기도 없는 행은 전국 행이 모두 들어갈 수 있어 record 없이 위치만 unmentioned에 남긴다.
    """
    config = dataset(name)
    for position, row in enumerate(rows, 1):
        match = anseong_match(name, row)
        place = {"page": page, "position": position}
        if match is not None:
            missing = [field for field in config.fields if _blank(row[field])]
            # 빈 값(예: 공사 시작일·준공일)은 채우지 않고 미상으로 표시한다.
            matched.append({**place, "match": match, "missing": missing, "record": row})
        elif all(_blank(row[field]) for field in config.judged_fields):
            if mentions := _mentions(row, config.fields, "안성"):
                review.append({**place, "reason": "blank_location", "mentions": mentions, "record": row})
            else:
                unmentioned.append(place)
        elif mentions := _mentions(row, config.location_fields, "안성"):
            review.append({**place, "reason": "mention", "mentions": mentions, "record": row})
        elif mentions := _mentions(row, config.other_fields, "안성"):
            review.append({**place, "reason": "other_mention", "mentions": mentions, "record": row})


def selection_document(name: str, matched: list, review: list, unmentioned: list) -> bytes:
    config = dataset(name)
    document = {"schema_version": MATCH_SCHEMA, "dataset": name, "category": config.category,
                "rule": config.rule, "rows": matched, "needs_review": review,
                "blank_location_unmentioned": unmentioned}
    return (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
