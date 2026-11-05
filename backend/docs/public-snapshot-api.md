# DB 공개 snapshot 조회

기본 `public` 프로필은 로컬 명령으로 공개한 불변 snapshot을 조회한다. DB 없이 화면을 연결하는 `fixture` 프로필과 구분한다. 실제 원문 검토·공개는 [승인·공개 안내](review-publication.md)를 따른다.

## 실행·연결

DB 환경변수를 설정하고 `./backend/gradlew -p backend bootRun`으로 실행한다. `local-import` → `local-publication`의 approve → publish를 마친 뒤 다음 요청을 사용한다.

matches에는 [백엔드 Python 설정](../README.md#python-계산-연결)이 필요하다. 같은 서버의 Python3.13과 같은 버전의 `processing/` 소스를 사용한다.

```bash
curl http://localhost:8080/api/v1/config
# config의 snapshot_id와 공개 사건 ID를 사용한다.
curl 'http://localhost:8080/api/v1/events/EVENT_UUID?snapshot_id=SNAPSHOT_UUID'
curl 'http://localhost:8080/api/v1/config?mode=replay&case_id=CASE_UUID'
```

config는 구역·고정 5지점·자료 수·수집/확인 범위·버전·현재 서버 시각을 반환한다. data.created_at은 고정된 snapshot 작성 시각이고, generated_at과 server_now는 요청 시각이다. cases에는 같은 구역·자료 종류의 활성 replay 사례만 담는다. DB에서 해당 범위를 먼저 선별한 뒤 각 공개본의 무결성을 검증하므로 다른 구역·자료 종류의 손상된 사례는 현재 config를 막지 않는다. replay 응답에는 case_id·anchor_date·reference_instant·knowledge_cutoff·history_fidelity를 보존한다. 현재와 재현을 혼합하지 않는다.

각 요청은 읽기 전용 REPEATABLE READ에서 공개 포인터와 canonical JSON을 읽는다. SHA-256·스키마·저장 문맥을 확인하며 최신 작업 revision·지점·비공개 문서 행으로 사실을 보충하지 않는다. publish와 동시에 조회해도 한 응답의 지점·사건·snapshot_id는 같은 버전이다.

## 상세 응답

공통 `api-v1 / snapshot_id / generated_at / data` 안에 자료 종류·재현 문맥과 event를 담는다.

- event의 사실 필드, occurrence, 장소, 대상·예외·노선·정류장·방향, 생애 상태·문서 관계를 반환한다.
- `field_values`는 각 값의 knowledge·근거ID·미상 이유를 보존한다. null은 알려진 빈 배열 `[]`과 다르다. 장소 name/address에도 적용한다.
- evidence는 event별 근거ID, 문서 버전, 블록, 인용, code point 오프셋, 본문 hash를 제공한다. source_refs의 url은 공개 원문 링크다. is_fixture는 data_kind=synthetic 여부다.
- replay의 last_verified_at/check_result는 cutoff 당시 상태다. current_*는 snapshot 생성 때 확보한 현재 확인 상태이며 요청할 때 원문을 재조회하지 않는다.
- 원문 전체·로컬 경로·검토자·AI 원출력·비공개 수정 기록을 반환하지 않는다.

실제 응답 형식은 [사실 전용 합성 예제](../../contracts/examples/event-facts-response.json)를 따른다. 원래 화면 fixture와 별도 snapshot이며 API 통합 시험에서 전체 필드 일치를 검사한다.

I03은 조건 없는 사실 응답이다. 분류·거리·시간 겹침·matched occurrence는 I02 결과에서 결합하며 Java가 추정하지 않는다. fixture에만 있는 계산 표시값을 실제 결과로 사용하지 않는다.

## 조건 계산 응답

`POST /api/v1/matches`는 유효한 snapshot·문맥·지점을 먼저 검사한다. current는 서버 시각을 한 번 정하고 KST 기준일을 계산하며, replay는 공개본의 고정 reference/cutoff를 전달한다. 사용자 조건은 한 요청의 stdin으로만 전달한다.

응답에는 `query_context`, 유형 필터 후·상태 선택 전 `counts`, 선택 상태의 `items`, 후보만의 `overlap_groups`, `rules_version`이 담긴다. 실제 Python이 시간·거리·3값 결합·취소·최신성·재현을 판정한다. Java는 기존 공개 사실 projection과 반환 사실 전체를 대조하고 ID·버전·hash·필수 구조·참조·집계의 일관성을 검사한다. 내부 diagnostics나 이중 envelope는 반환하지 않는다.

알려진 빈 결과는200·0건이며, 계산 실패는 오류 응답이다. 실패를 고정 fixture나0건으로 바꾸지 않는다. 공개본과 DB는 조건 조회로 변경되지 않는다.

## 공개 변경이력

history는 선택 snapshot의 최초 공개 감사 순번까지 같은 채널에서 실제 공개된 revision을 순서대로 비교한다. 최초 공개는 변경 항목이 없고, 다음 revision부터 `revision_id/snapshot_id/published_at/action/changes`를 담는다. action은 publish 또는 rollback이다. 각 changes 항목은 `field/before/after`다. 이전 근거와 출처는 `before_revision_id/before_evidence/before_source_refs`, 새 근거와 출처는 `evidence/source_refs`에 담는다. 비공개 draft나 human_overrides의 임의 before/after는 읽지 않는다.

head_version으로 공개 순서와 조회 경계를 정한다. snapshot 생성 시각과 감사 시각의 차이로 현행 변경이 누락되지 않는다. 공개·복구 포인터 전환 순서로 비교하며 연속된 같은 revision만 중복 제거한다. 다른 revision을 거쳐 이전 revision으로 복구한 경우도 변경으로 기록한다. replay는 DB에서 구역·자료 종류·기준일·reference_instant·knowledge_cutoff가 같은 이력만 먼저 선별한 뒤 무결성을 검증하여 다른 역사 문맥이 유입되지 않게 한다. rollback하면 선택한 이전 snapshot 이후의 변경을 보여주지 않는다. 자료가 늘면 사례 목록 projection과 이력 pagination을 별도 설계한다.

## 실패와 현재 제한

| 상태 | 코드 | 의미 |
|---|---|---|
| 404 | CASE_NOT_FOUND / SNAPSHOT_NOT_FOUND / EVENT_NOT_FOUND | 미등록 사례·공개한 적 없는 snapshot·해당 공개본에 없는 사건 |
| 409 | SNAPSHOT_RETIRED | 해당 채널의 공개본이 교체됨. 최상위 current_snapshot_id로 사용자가 새 버전을 선택 |
| 422 | INVALID_REQUEST / INVALID_POINT | 잘못된 모드·사례·snapshot 조합 또는 해당 공개본에 없는 지점 |
| 503 | PUBLIC_DATA_NOT_READY | current 공개본 없음 |
| 503 | DATABASE_UNAVAILABLE | 접속·자원 장애 또는 일시적 DB 오류. 내부 SQL·접속 정보는 반환하지 않음 |
| 503 | CALCULATION_UNAVAILABLE | 계산 설정·기동·종료·출력 한도 문제. timeout/interrupt/동시 한도 초과만 retryable=true |
| 500 | CALCULATION_PROTOCOL_ERROR | 응답 JSON·hash·ID·버전·사실/집계/참조 불일치. 재시도 불가 |
| 500 | SNAPSHOT_INVALID | checksum·저장 문맥 등 공개본 무결성 실패 |
| 500 | INTERNAL_ERROR | SQL 문법·스키마·제약/사용 오류 등 예상치 못한 실패. 재시도 불가, 서버 로그의 request_id로 추적 |

공개 포인터에서 제외된 이전본은 복구·평가용으로 DB에 보존하지만 직접 공개 조회는 허용하지 않는다. rollback으로 다시 선택하면 같은 고정 사실로 계산할 수 있다. 사용자 조건은 저장하지 않는다. 프런트 구현·실제 자료 검수·운영 배포는 후속 작업이다. fixture 프로필은 기존 고정 예제와 CALCULATOR_NOT_READY 오류를 유지한다.

area_membership=outside 사건은 비공개 검토 단계에서 보존할 수 있지만 snapshot 생성·기존 공개본 검증·복구에서 차단한다. 이미 저장된 잘못된 공개본은 집계나 사건을 임의로 빼지 않고500 SNAPSHOT_INVALID로 차단한다.
