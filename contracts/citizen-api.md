# 시민 목록·상세 API 구현 검토안

Java21·Spring Boot3.5·MySQL8.4의 시민 공개본을 읽는 작성자 구현안이다. 이상헌과 화면별 최종 계약을 대조하는 작업은 남아 있다. 기존3유형 API는 [api-v1](README.md)을 따르며, 이 경로는 `citizen:current/citizen-snapshot-v1`과 `citizen-api-v1`을 사용한다.

## 요청·응답

| 요청 | query | 결과 |
| --- | --- | --- |
| `GET /api/v1/citizen/notices` | `snapshot_id` 선택 | 생략하면 현재 시민 공개본의 전체 목록 |
| `GET /api/v1/citizen/notices/{eventId}` | 목록의 `snapshot_id` 필수 | 같은 공개본에 속한 사건의 상세·관련 출처·확보 이력 |

`eventId`는 notice의 `event_id`다. UUID는 소문자 표준36자 형식을 사용한다. 지원하는 query는 `snapshot_id` 하나이며 중복/빈 값도 거부한다. `q/category/district/free/open/period/sort/point_id` 등 미지원 조건은422다. 현재 경로를 검색·기간/비용/모집 필터 완료로 집계하지 않는다.

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

history의 scope는 `same_data_kind_published_snapshots`, completeness는 `unknown`이다. 동일 자료 종류의 실제 시민 공개 기록을 현재 head까지 읽는다. 원문의 모든 변경·검토 revision을 수집했다는 뜻은 아니다.

| kind | 의미 |
| --- | --- |
| `first_observed` | 처음 확보한 공개 상태. before=null은 이전 상태 미확인 |
| `changed` | 확보한 공개 사실·출처가 바뀜 |
| `withdrawn` | 실제 공개본에서 사건을 제외함. after=null |
| `restored` | 제외 뒤 실제 공개본에 다시 포함함. before=null |

각 항목은 `kind/snapshot_id/published_at/action/before/after`를 가진다. before/after는 `{notice,sources}` 또는 null이며 출처·근거도 당시 값으로 보존한다. 같은 상태의 재공개는 새 사실 변경으로 만들지 않는다. `withdrawn`은 공지 공개 목록에서 빠졌다는 뜻으로, 원문 행사의 취소 판정과 구별한다. 검토자·비공개 감사 사유·AI 원출력·원문 파일 경로는 반환하지 않는다.

한 요청에서 검증·조립하는 고유 canonical의 원래 UTF-8 bytes 합은 현재본을 포함해8MiB, 읽는 공개 감사는1000개 이하다. 같은 공개본의 반복 참조는 요청 내부에서 재사용한다. 한도를 넘으면503 CITIZEN_HISTORY_TOO_LARGE·retryable=false이며 일부 이력을 전체인 것처럼 돌려주지 않는다. 현재 공개본에 없는 사건은404이며 과거 상세를 현재로 대신 표시하지 않는다.

## 오류·일관성

| 상태·코드 | 의미·다음 동작 |
| --- | --- |
| 422 INVALID_REQUEST | 필수 ID·형식·지원 query를 확인 |
| 503 PUBLIC_DATA_NOT_READY | 아직 시민 head가 없음. 공개 준비 상태를 확인 |
| 404 SNAPSHOT_NOT_FOUND | 미등록·미공개·다른 계열의 ID |
| 409 SNAPSHOT_RETIRED | 공개본 교체. 제공된 current_snapshot_id 또는 목록을 다시 읽음 |
| 404 NOTICE_NOT_FOUND | 선택한 현재 공개본에 해당 사건이 없음 |
| 500 SNAPSHOT_INVALID | 고정 JSON/hash/metadata·과거 구성 참조의 무결성을 확인할 수 없음 |
| 503 CITIZEN_HISTORY_TOO_LARGE | 공개 이력 조회 한도 초과. 반복 재시도로 해결되지 않음 |
| 503 DATABASE_UNAVAILABLE | 저장소 연결 실패. retryable을 확인 |

유효한 빈 공개본은200·notice_count0·notices/sources 빈 배열이다. 준비/연결/무결성 실패를 빈 성공으로 바꾸지 않는다. 오류는 기존 `error.code/message/field_errors/retryable`·request_id·선택 current_snapshot_id 형식이고 `X-Request-ID`와 연결된다.

조회는 읽기 전용 REPEATABLE READ에서 head·감사·공개본을 함께 읽는다. Python/AI·원문 파일을 호출하지 않으며 사용자 설정을 저장하지 않는다. CORS·최소 요청 로그는 기존 `/api/v1/**` 설정을 사용하고 시민 로그의 rules_version은 null이다.

## 새 전용 개발 DB에서 재현

1. [백엔드 환경](../backend/README.md#mysql-기초-실행)·V5를 준비하고 [합성 입력/승인](../backend/docs/citizen-review.md#합성-자료로-재현)과 [별도 시민 공개](../backend/docs/citizen-publication.md#입력과-실행)를 실행한다. 실제 승인 결과 ID를 작업본에 넣는다. 기존 DB를 지워 예제 상태로 만들지 않는다.
2. 저장소 루트에서 `java -jar backend/build/libs/myai-backend-0.1.0.jar`로 public 서버를 실행한다. DB 환경변수는 별도로 전달한다. 이미 V5가 적용된 SELECT 전용 계정은 `--spring.flyway.enabled=false`를 사용한다. `.env`만 작성해 Java에 전달된 것으로 간주하지 않는다.
3. 목록의 snapshot_id·event_id를 그대로 상세에 사용한다.

```bash
curl 'http://127.0.0.1:8080/api/v1/citizen/notices'
curl --get 'http://127.0.0.1:8080/api/v1/citizen/notices/<event_id>' \
  --data-urlencode 'snapshot_id=<목록의 snapshot_id>'
```

4. 새 공개 후 이전 ID는409다. 빈 목록을 명시 공개하면 새 목록은200/0건이며, 원문 파일 없이 이전 공개본으로 rollback한 뒤에는 복구한 ID로 다시 조회한다. 고정 created_at·사실·출처와 새 응답 generated_at을 구별한다.
5. 재현 시험은 `CitizenNoticeServiceTest/CitizenNoticeApiTest/CitizenNoticeMySqlTest/CitizenNoticeJarMySqlTest`와 기존 전체 회귀다. 실제 DB/JAR·환경·명령·결과·독립/원격 리뷰는 [작업 계획](../docs/superpowers/plans/2026-11-18-citizen-query.md)과 PR에서 확인한다.

기존 fixture 프로필은 기존3 API의 가상 응답용이다. 시민 경로는 public의 실제 합성 DB로 검증하며 local-api 프로세스에는 등록하지 않는다. 새 SQL·관리 계정·원문은 공개 경로로 노출하지 않는다. Flutter 실제 연결·강명묵 인수·최종 계약 합의·실자료/독립 평가·운영 배포는 후속이다.
