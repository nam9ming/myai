# 여기:it 시민 화면과 공개 API 차이

확인일: 2026-11-17 KST. 기준: `develop` 커밋 `339e04f6d2bfac386fbc973fbe3e3b5b0aa02677`, `contracts/README.md`, `backend/docs/public-snapshot-api.md`와 실제 controller/config 코드.

현재 계약은 지점·영업시간을 기준으로 공사/행사/교통을 조회한다. 시민용 5개 분야 화면 전체를 이 계약에 매핑할 수는 없다. Spring fixture의 실제 HTTP·CORS는 검증했으며, 다음 시민용 확장 항목은 협의 초안이다. public DB·실제 시민 자료는 연결하지 않았다.

## 기존 기능과 재사용 범위

| 기존 계약 | 프론트 사용 범위 | 연결 상태 |
|---|---|---|
| `GET /api/v1/config` | 공개 준비 상태·자료 범위·현재 snapshot·서버/KST 기준일 | fixture 실제 HTTP 확인, public 미검증 |
| `POST /api/v1/matches` | 명시적인 고정 조건의 개발 호환 검증, 기존 공사/행사/교통 결과 | fixture 실제 HTTP와 미지원 조건 503 확인 |
| `GET /api/v1/events/{id}?snapshot_id=...` | 공개 사실·근거·출처·이력 상세 | fixture 실제 HTTP, 사실 전용 DTO 단위 검증 |
| 공통 오류 envelope | 404/409/422/503/500, request_id·retryable | 매핑·준비/오류 UI 구현, 503은 실제 HTTP, 나머지는 테스트 응답 |

실제 DB 상세에는 계산 필드가 없다. 동일 snapshot의 I02 결과가 있을 때만 함께 표시한다. fixture의 계산값을 실제 상세의 기본값으로 쓰지 않는다.

기존 fixture의 `503 CALCULATOR_NOT_READY`는 `retryable=true`로 응답하는 것을 실제 확인했다. 프론트는 이를 보존해 수동 재시도를 제공한다. 조건을 바꿔 같은 요청을 자동 반복하거나 성공·0건으로 바꾸지 않는다.

## 확장 협의 항목

| ID | 필요한 기능과 이유 | 화면 영향 | 현재 처리 |
|---|---|---|---|
| G01 | 지점·영업시간 없는 시민용 공개 목록과 교육/지원/생활 분류 | 홈·목록·관심 분야 전체 | prototype에서 재현, api에서는 지원 범위 표시 |
| G02 | 동네·시 전체 범위, 지역 선택지와 서비스 가능 지역 | 온보딩·설정·지역 필터 | 예시 지역 사전만 사용, 안성 외 준비 안내 |
| G03 | 신청 시작/마감·진행 기간·비용/통화·대상 조건의 별도 필드 | 무료·모집 중·마감순·상세 | null 보존, 기존 진행일에서 신청일 추정 금지 |
| G04 | 서버 검색 대상·AND 필터·정렬·전체 건수·페이지 범위 | 검색·목록 결과의 완전성 | 미지원 전역 검색·전체 건수를 구현된 것처럼 표시하지 않음 |
| G05 | 좌표→행정구역과 실제 주변 검색 계약 | 현재 위치 이용 | 버튼에서 권한만 확인, 지점ID 대체·실거리 계산 금지 |
| G06 | 실제 포스터 출처·권한·비율/대체 텍스트, 기능 지원 범위 | API 카드·모드별 필터 표시 | 예시 자산과 실제 자산 분리, 무포스터 카드 사용 |
| G07 | 공개 자료 전체의 변경 소식 피드와 정렬·조회 범위 | 홈의 달라진 소식 패널 | 개별 상세 history는 재사용, 전체 변경 피드는 prototype에서 재현 |

## 시민 목록 협의 예시

아래 경로·필드명은 논의를 위한 제안이다. 기존 `/matches` 요청·enum을 변경하거나 이 경로가 이미 있다고 가정하지 않는다.

```http
GET /api/v1/notices?category=education&district=공도읍&free=true&open=true&period=week&sort=deadline
```

응답은 기존 `schema_version/snapshot_id/generated_at/data` 구조와 합성/실제 구분을 유지하고, 다음 의미를 합의해야 한다.

```json
{
  "category": "education",
  "application_period": null,
  "occurrences": [],
  "cost": null,
  "currency": null,
  "district_scope": null,
  "field_values": {},
  "source_refs": [],
  "evidence": []
}
```

이는 기존 API의 완전한 사건 예제가 아니라 **신규 필드 의미 검토용 조각**이다. 예를 들어 신청 기간을 모르는 `application_period: null`은 모집 중으로 분류하지 않으며, 비용 미상 `cost: null`은 무료에 포함하지 않는다. 실제 필드의 knowledge·미상 이유·근거 관계는 기존 `field_values` 원칙을 따라야 한다.

서버 필터의 기준일은 KST·서버 시각으로 고정하고 이번 주는 월~일 진행 구간과의 교집합으로 합의한다. 동네 선택은 해당 동네와 시 전체 공지를 포함한다. 페이지가 일부라면 전체 건수·전역 검색 지원 여부와 커서/페이지 범위를 명시한다. 여러 출처·게시일·확인 시각·revision/history·공개본 교체 오류는 기존 의미를 유지한다.

## 프론트에서 유지할 경계

- 시민 설정에 고정 지점·영업시간을 자동 주입하지 않는다.
- `traffic` 화면 탭은 `construction/traffic`을 묶어 표시할 수 있지만 공통 enum에 교육·지원·생활을 임의 추가하지 않는다.
- 저장은 로컬에서 모드·event_id·snapshot_id/revision_id를 보존한다. 서버 계정 동기화 API는 이번 필수 확장으로 요청하지 않는다.
- API 오류를 예시 데이터·빈 결과로 대체하지 않는다. 공개에서 제외된 snapshot 접근을 우회하지 않는다.
- 백엔드 변경 전 필드별 요청/응답·오류·기존 소비자 영향과 인수 기준을 담당자와 합의한다.
