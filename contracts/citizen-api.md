# 시민 목록·상세 API 구현 검토안

Java21·Spring Boot3.5·MySQL8.4의 시민 공개본을 읽는 작성자 구현안이다. 이상헌과 화면별 최종 계약을 대조하는 작업은 남아 있다. 기존3유형 API는 [api-v1](README.md)을 따르며, 이 경로는 `citizen:current/citizen-snapshot-v1`과 `citizen-api-v1`을 사용한다.

## 요청·응답

| 요청 | query | 결과 |
| --- | --- | --- |
| `GET /api/v1/citizen/notices` | `snapshot_id` 선택 | 생략하면 현재 시민 공개본의 전체 목록 |
| `GET /api/v1/citizen/notices/{eventId}` | 목록의 `snapshot_id` 필수, `history_before_version/history_limit` 선택 | 같은 공개본의 상세·관련 출처와 지정 범위의 확보 이력 |

`eventId`는 notice의 `event_id`다. UUID는 소문자 표준36자 형식을 사용한다. 목록은 `snapshot_id` 하나만 지원하며 이력 페이지 query도 받지 않는다. 상세는 `history_before_version`과 `history_limit`을 추가로 지원한다. query의 중복/빈 값과 `q/category/district/free/open/period/sort/point_id` 등 미지원 조건은422다. 현재 경로를 검색·기간/비용/모집 필터 완료로 집계하지 않는다.

상세의 `history_before_version`은 제외할 상한 버전으로, 양의 Long 정수이며 현재 head_version+1 이하다. 생략하면 최신 페이지다. `history_limit`은 페이지에서 검증할 공개 감사 수로1~1000의 정수이며 기본값1000이다. 이 값은 변경 항목 수나 공지 수가 아니다. 이전 이력 페이지로 이동해도 notice/sources는 선택한 현재 공개본의 사실로 유지된다.

정상 root는 `schema_version/snapshot_id/generated_at/data`다. 목록 data는 `created_at/data_kind/mode/timezone/notice_count/notices/sources`, 상세 data는 `created_at/data_kind/mode/timezone/notice/sources/history`를 가진다. mode는 current이며 지점·영업시간·반경을 요구하지 않는다.

필드와 연결의 고정 합성 예제:

- [목록](examples/citizen-list-response.json)·[상세](examples/citizen-detail-response.json). ID·시각은 설명용이며 현재 DB의 공개 상태를 선언하지 않는다.
- `python3 contracts/validate_examples.py`는 기존 예제와 새 목록/상세의 동일 snapshot·사실·출처·원문 code point 근거·최초 미확인 이력을 대조한다.

## 원문 사실·시각

notices는 제목·`education/support/culture/construction_traffic/living` 중 하나 이상의 분야와 [12개 시민 사실](../backend/docs/citizen-review.md#보관하는-정보), 문서 관계·근거를 보존한다. 각 사실은 `value/knowledge/evidence_ids/reason`이다. value는 원문의 문자열/문자열 배열 또는 null이다.

신청 기간과 실제 진행 일정, 적용 지역/장소/거주 조건, 비용 미상과 명시 금액을 구별한다. 이 응답은 무료 여부·신청 자격·모집 가능·취소 여부를 자동 계산하지 않는다. `FieldValue.reason`과 공개 문서 관계의 reason은 근거 설명이며 비공개 검토 감사와 구별한다.

`generated_at`은 응답 시각, `data.created_at`은 불변 공개본의 생성 시각이다. UTC 문자열을 사용하고 표시 기준은 Asia/Seoul이다. sources의 `last_verified_at/latest_check_attempt_at/check_result/checks`는 공개 당시 고정 기록이다. 응답 생성 시각을 원문 재확인 시각으로 표시하지 않는다. 상세 sources는 선택 notice가 참조한 문서 버전만 포함한다.

근거의 start_char/end_char는 원문 block 안의 Unicode code point 위치다. Flutter/Dart의 UTF-16 문자열 인덱스와 변환 없이 혼용하지 않는다.

## 공개 이력

history의 정확한 키는 `scope/completeness/status/window/entries/error`다. scope는 `same_data_kind_published_snapshots`, completeness는 `unknown`이다. 선택한 자료 종류에서 확인된 공개 상태만 비교하며, 원문의 모든 변경·검토 revision을 수집했다는 뜻은 아니다. 페이지 밖의 미확인 상태나 다른 자료 종류의 등장을 철회·복구 이력으로 만들지 않는다.

정상 이력은 `status=available`, `error=null`이며 window는 다음5개 키를 가진다.

| window 키 | 의미 |
| --- | --- |
| `from_version` / `to_version` | 이번 페이지에서 검증한 감사의 양끝 버전, 둘 다 포함 |
| `has_more` | 더 이전 버전을 읽을 수 있는지 여부 |
| `next_before_version` | 이전 페이지 요청에 넣을 제외 상한. 더 없으면 null |
| `limit` | 요청한 감사 수 한도, 기본1000 |

페이지 끝은 `history_before_version`이 없으면 현재 head, 있으면 그 값-1이다. 시작은 `max(0, 끝-limit+1)`이다. `has_more`는 시작이0보다 클 때 true이며 다음 커서는 시작 버전이다. 전후 연결·이전 상태를 검증하기 위해 바로 앞 감사1개를 문맥으로 읽을 수 있으나, 그 감사의 항목은 반환하지 않는다. 따라서 채널 전체 이력이1000개를 넘더라도 페이지별 최대1000개와 문맥1개를 읽는다.

| kind | 의미 |
| --- | --- |
| `first_observed` | 페이지가 버전0부터 검증한 범위에서 처음 확보한 공개 상태. before=null은 원문 이전 상태 미확인 |
| `observed` | 페이지 이전의 같은 종류 상태·등장을 확정할 수 없어 이번 상태만 표시. after=null은 그 공개본에서 사건 부재를 확인한 기록이며 이전 존재·철회·복구를 단정하지 않음 |
| `changed` | 확보한 공개 사실·출처가 바뀜 |
| `withdrawn` | 실제 공개본에서 사건을 제외함. after=null |
| `restored` | 제외 뒤 실제 공개본에 다시 포함함. before=null |

각 항목은 `kind/snapshot_id/published_at/action/before/after`를 가진다. before/after는 `{notice,sources}` 또는 null이며 출처·근거도 당시 값으로 보존한다. 문맥에 같은 종류의 공지가 있으면 그 값을 before로 검증해 첫 항목도 `changed/withdrawn`으로 구분할 수 있다. 문맥이 다른 종류이거나 공지가 없으면 과거 등장을 알 수 없으므로 첫 확보 상태는 `observed`이며 복구를 추측하지 않는다. 페이지 안에서 존재를 확인한 뒤 실제 제외→재등장을 확인하면 `restored`다. 같은 상태의 재공개는 새 사실 변경으로 만들지 않아 정상 entries가 빈 배열일 수 있다. 이때도 `has_more`와 커서를 확인해 이전 페이지를 읽는다. `withdrawn`은 공지 공개 목록에서 빠졌다는 뜻으로, 원문 행사의 취소 판정과 구별한다. 검토자·비공개 감사 사유·AI 원출력·원문 파일 경로는 반환하지 않는다.

한 요청에서 검증하는 고유 canonical의 원래 UTF-8 bytes 합은 현재본을 포함해8MiB다. 이번 페이지·문맥의 다른 자료 종류 공개본도 검증·한도에 포함하며 같은 공개본은 요청 내부에서 재사용한다. 이력 항목의 누적 직렬화 크기도 검사한다. 이력 읽기·출력 한도를 넘으면 현재 notice/sources는200으로 반환하고 history를 다음과 같이 표시한다. 더 작은 `history_limit`으로 다시 요청할 수 있다.

```json
{
  "scope": "same_data_kind_published_snapshots",
  "completeness": "unknown",
  "status": "unavailable",
  "window": null,
  "entries": null,
  "error": {"code": "CITIZEN_HISTORY_TOO_LARGE", "retryable": false}
}
```

조회 불가를 빈 배열로 표시하거나 일부 이력을 전부처럼 반환하지 않는다. 일반 목록/상세 응답 한도는8MiB다. 유효한 최대8MiB 공개본의 현재 사실이 이력 조회 불가 상태를 표시할 수 있도록, 위 unavailable 대체 응답에만1KiB 상태 메타데이터 여유를 별도로 허용한다. 이 대체 응답도8MiB+1KiB를 넘으면503 CITIZEN_HISTORY_TOO_LARGE·retryable=false다. 공개본·원문/AI 입력·일반 응답의8MiB 한도는 늘리지 않는다. 이력의 누락·hash·metadata·구성 참조 손상은 여전히500이다. 현재 공개본에 없는 사건은404이며 과거 상세를 현재로 대신 표시하지 않는다.

V6는 `publication_audits(channel_key,head_version,audit_id)`의 일반 색인만 추가해 페이지 범위를 읽는다. 적용된 V1~V5·기존 행·canonical/hash는 변경하지 않는다. 페이지·응답 필드·자원 한도는 작성자의 내부 기술 선택이며 실제 팀원·Flutter 최종 합의와 구별한다.

## 오류·일관성

| 상태·코드 | 의미·다음 동작 |
| --- | --- |
| 422 INVALID_REQUEST | 필수 ID·형식·지원 query를 확인 |
| 503 PUBLIC_DATA_NOT_READY | 아직 시민 head가 없음. 공개 준비 상태를 확인 |
| 404 SNAPSHOT_NOT_FOUND | 미등록·미공개·다른 계열의 ID |
| 409 SNAPSHOT_RETIRED | 공개본 교체. 교체본의 공개·무결성을 검증한 current_snapshot_id 또는 목록을 다시 읽음 |
| 404 NOTICE_NOT_FOUND | 선택한 현재 공개본에 해당 사건이 없음 |
| 500 SNAPSHOT_INVALID | 고정 JSON/hash/metadata·과거 구성 참조의 무결성을 확인할 수 없음 |
| 503 CITIZEN_HISTORY_TOO_LARGE | 이력 조회 불가 대체 응답도8MiB+1KiB 초과. 반복 재시도로 해결되지 않음 |
| 503 DATABASE_UNAVAILABLE | 저장소 연결 실패. retryable을 확인 |

이력의 자원 한도 초과는 HTTP200의 `data.history.status=unavailable`과 해당 history.error로 구분한다. 유효한 빈 공개본은200·notice_count0·notices/sources 빈 배열이다. 준비/연결/무결성 실패를 빈 성공으로 바꾸지 않는다. HTTP 오류는 기존 `error.code/message/field_errors/retryable`·request_id·선택 current_snapshot_id 형식이고 `X-Request-ID`와 연결된다.

교체된 ID의409 안내는 이전 공개본과 현행 교체본을 각각8MiB 상한에서 독립 검증한다. 이 검증 두 개를 이력 누적 예산으로 합산해 정상 교체 안내를 차단하지 않는다. 일반 상세의 현재본 포함 고유 canonical 이력 예산8MiB는 유지한다.

조회는 읽기 전용 REPEATABLE READ에서 head·감사·공개본을 함께 읽는다. Python/AI·원문 파일을 호출하지 않으며 사용자 설정을 저장하지 않는다. CORS·최소 요청 로그는 기존 `/api/v1/**` 설정을 사용하고 시민 로그의 rules_version은 null이다.

## 새 전용 개발 DB에서 재현

1. [백엔드 환경](../backend/README.md#mysql-기초-실행)·V6까지 준비하고 [합성 입력/승인](../backend/docs/citizen-review.md#합성-자료로-재현)과 [별도 시민 공개](../backend/docs/citizen-publication.md#입력과-실행)를 실행한다. 실제 승인 결과 ID를 작업본에 넣는다. 기존 DB를 지워 예제 상태로 만들지 않는다.
2. 저장소 루트에서 `java -jar backend/build/libs/myai-backend-0.1.0.jar`로 public 서버를 실행한다. DB 환경변수는 별도로 전달한다. 이미 V6가 적용된 SELECT 전용 계정은 `--spring.flyway.enabled=false`를 사용한다. `.env`만 작성해 Java에 전달된 것으로 간주하지 않는다.
3. 목록의 snapshot_id·event_id를 그대로 상세에 사용한다.

```bash
curl 'http://127.0.0.1:8080/api/v1/citizen/notices'
curl --get 'http://127.0.0.1:8080/api/v1/citizen/notices/<event_id>' \
  --data-urlencode 'snapshot_id=<목록의 snapshot_id>'
curl --get 'http://127.0.0.1:8080/api/v1/citizen/notices/<event_id>' \
  --data-urlencode 'snapshot_id=<같은 snapshot_id>' \
  --data-urlencode 'history_before_version=<이전 응답의 next_before_version>' \
  --data-urlencode 'history_limit=100'
```

4. 새 공개 후 이전 ID는409다. 빈 목록을 명시 공개하면 새 목록은200/0건이며, 원문 파일 없이 이전 공개본으로 rollback한 뒤에는 복구한 ID로 다시 조회한다. 고정 created_at·사실·출처와 새 응답 generated_at을 구별한다.
5. 재현 시험은 `CitizenNoticeServiceTest/CitizenNoticeApiTest/CitizenNoticeMySqlTest/CitizenNoticeJarMySqlTest`와 기존 전체 회귀다. 실제 DB/JAR·환경·명령·결과·독립/원격 리뷰는 [작업 계획](../docs/superpowers/plans/2026-11-18-citizen-query.md)과 PR에서 확인한다.

기존 fixture 프로필은 기존3 API의 가상 응답용이다. 시민 경로는 public의 실제 합성 DB로 검증하며 local-api 프로세스에는 등록하지 않는다. 새 SQL·관리 계정·원문은 공개 경로로 노출하지 않는다. Flutter 실제 연결·강명묵 인수·최종 계약 합의·실자료/독립 평가·운영 배포는 후속이다.
