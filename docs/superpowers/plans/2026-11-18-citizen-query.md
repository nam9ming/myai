# 시민 목록·상세 조회 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자 goal의 agents 분담·계획별 독립 전체 리뷰1회·Minor 포함 수정·정확 head CI/실제 자동 리뷰 후 develop 반영을 적용한다.

**Goal:** 승인·공개한 시민5분야 사실을 지점 없이 같은 불변 공개본의 목록·상세·확보된 공개 이력으로 조회한다.

**Architecture:** `develop@4c2dd1b06487162f75ebb340c7f6cf50e2b8c366`의 시민 공개본·검증·JDBC·공통 오류/로그/CORS를 재사용한다. 별도 controller/service와 시민 공개 이력 SELECT만 추가하고 기존3 API·legacy 이력 SQL은 유지한다. 아래 경로·응답은 작성자 구현 검토안이며 실제 팀원·Flutter 최종 합의가 아니다.

**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4.13·기존 Jackson/JUnit. 새 의존성·migration 없음. 공개 조회에서 Python/AI·원문 파일을 호출하지 않는다.

**Spec:** [제품 요구 R17~R22](../../spec/01_제품요구사항.md), [Y01~Y10 인수](../../spec/05_시험과인수기준.md#여기it-새-범위-인수), [계약 협의 기준](../../../contracts/README.md#yeogi-it-contract-agreement), [시민 공개본](../../../backend/docs/citizen-publication.md), [재사용 조사](../../../backend/docs/citizen-backend-reuse.md).

## Global Constraints

- 사용자 지시에 따라 미확정 검색/필터·개인화·사업/평가 규칙은 별도 기록한다. 구현 경로/필드의 기술 선택을 팀원 합의로 쓰지 않는다.
- 기존3유형·5지점·500m·14일·Python 계산 단일 원본과 V1~V5·과거 canonical/hash를 변경하지 않는다.
- 시민 신청/진행·지역/장소/거주 조건·비용/모집/자격·미상은 공개본의12개 FieldValue 그대로다. 날짜·무료·자격·취소를 추론하지 않는다.
- 조회는 읽기 전용 REPEATABLE READ로 head·공개 감사·canonical을 같은 DB snapshot에서 읽는다. 공개/수정/계정/사용자 설정 저장 동작을 추가하지 않는다.
- 공개 controller는 `!fixture & !local-api`다. 기존 fixture3 API는 유지하고 시민 API는 합성 DB 등록/공개로 재현한다. local-api의 Bearer/loopback/Host/Origin·비공개 원본 경계를 유지한다.
- 새 DB 시험은 연결/Flyway 전에 전용 DB명을 확인하고 소유 snapshot/head/audit만 정리한다. 전역 DELETE·공유/운영 DB·private 원문/키/gold/D09 열람 금지.
- 사용자 .gitignore·AGENTS·미병합 작업·worktree 파일을 보존한다. main 병합/push·배포 금지. Gradle 실행은 주 작업자 전담이다.

## Approaches

기존 PublicNoticeService에 시민 필드를 섞으면 기존3유형 소비자의 필드/계산 의미까지 변경된다. 별도 시민 경로에서 기존 시민 validator와 저장소를 재사용하는 방식을 택한다. 새 저장 계층·계산기·fixture 서버를 만들 필요는 없다. 사용자의 질문 생략·agents 실행 지시에 따라 작성자가 정한 기술 선택이며 실제 제품 합의를 뜻하지 않는다.

## Review Focus

- legacy/미공개/손상 시민 UUID를 새 경로에서 공개하지 않는다. 시민 UUID도 기존3 API의 공개본으로 읽지 않는다.
- head 없음503·유효한 빈 공개본200·미등록404·교체된 공개본409를 구분하며 복구 후 과거 ID가 현재 head이면 다시 읽힌다.
- 미지원/중복/빈 query와 비정규 UUID는422다. 미구현 무료/모집/기간 조건을 조용히 무시하지 않는다.
- 현재 head까지의 실제 공개·철회·복구만 반환한다. 최초 확보 이전/다른 자료 종류/원문 밖 이력을 생성하거나 검토자·사유·원출력·private 경로를 노출하지 않는다.
- 최대1000개 이력과 읽는 canonical 총8MiB를 넘으면 명시503·retryable=false이며 일부 이력을 전부인 것처럼 반환하지 않는다. SELECT 전용 실제 HTTP/JAR에서도 DB·원본은 불변이다.

## 계약·공유 인터페이스

- `GET /api/v1/citizen/notices`: query는 선택 `snapshot_id` 하나뿐이다. 생략하면 현재 `citizen:current` head다. `GET /api/v1/citizen/notices/{eventId}`는 같은 query가 필수다. 모든 UUID는 소문자 표준36자 형식이며 추가/반복 query는422다. 일반 검색·분야/지역/비용/모집/기간 필터·페이지/정렬은 이번 경로의 지원 조건으로 가장하지 않는다.
- 정상 envelope의 정확한 키는 `schema_version/snapshot_id/generated_at/data`, schema는 `citizen-api-v1`이다. generated_at은 응답 시각, data.created_at은 불변 공개본 생성 시각이다.
- 목록 data의 정확한 키는 `created_at/data_kind/mode/timezone/notice_count/notices/sources`다. notices/sources는 검증한 시민 공개본의 공개 투영을 보존한다. mode=current이며 지점/규칙/사전·사용자 조건은 없다.
- 상세 data의 정확한 키는 `created_at/data_kind/mode/timezone/notice/sources/history`다. notice는 선택 event_id의 전체 공개 사실이며 sources는 그 source_version_ids만 포함한다.
- history의 정확한 키는 `scope/completeness/entries`다. scope=`same_data_kind_published_snapshots`, completeness=`unknown`이다. 항목 키는 `kind/snapshot_id/published_at/action/before/after`. before/after는 `{notice,sources}` 또는 null이다. 처음 확보한 상태는 kind=`first_observed`·before=null이며 이전에 공지가 없었다는 뜻이 아니다. 이후 실제 공개 상태의 변경은 `changed/withdrawn/restored`로 구분한다. 같은 상태 재공개는 새 사실 변경으로 만들지 않는다. 권한/사람 검토의 비공개 감사는 반환하지 않는다.
- `CitizenNoticeService(PublicSnapshotRepository,CitizenPublicationContent,PublicationContent,ObjectMapper)`; `JsonNode list(UUID snapshotId)`와 `JsonNode notice(UUID eventId,UUID snapshotId)`. class에 읽기 전용 REPEATABLE_READ를 적용하고 `PublicRequestLogContext.selected(id,null)`로 지점 없는 선택을 기록한다.
- 저장소에 `MAX_CITIZEN_HISTORY=1000`, `List<Historic> citizenHistory(String eventId,String selectedSnapshot)`를 추가한다. 기존 Historic4필드를 사용하고 revisionId는 철회 때 null이다. 현재 시민 head와 선택 ID를 묶고, 해당 사건을 처음 공개한 감사부터 현재 head의 lock_version까지 읽는다. LEFT JOIN membership으로 사건 없는 중간 공개도 보존하고 head_version/audit_id 순·LIMIT1001을 적용한다. 기존 history의 MIN 최초발행 경계는 변경하지 않는다.
- service는 모든 사용 공개본의 schema/channel/audit·checksum·created_at·공개 allowlist를 기존 시민 validator로 검사한다. 이력의 membership과 canonical 내 event/revision도 대조한다. 같은 자료 종류만 비교하며, 누락/손상된 과거본은500 SNAPSHOT_INVALID다.
- 현재/이전 canonical 원래 UTF-8 bytes의 누적8MiB·이력1000개를 읽기 한도로 사용한다. 이력 초과는503 CITIZEN_HISTORY_TOO_LARGE·retryable=false다. 현재 사실/이력을 다른 snapshot이나 빈 값으로 대체하지 않는다. 이 한도는 원문 내용/사업 의미가 아닌 작성자의 읽기 자원 경계다.
- 오류는 기존 envelope/요청 UUID/field_errors 배열을 재사용한다. head 없음503 PUBLIC_DATA_NOT_READY; 미등록/다른 계열404 SNAPSHOT_NOT_FOUND; 교체409 SNAPSHOT_RETIRED+current_snapshot_id; 해당 사건 없음404 NOTICE_NOT_FOUND; 손상500 SNAPSHOT_INVALID다. DB 연결 실패는 기존 안전한503 경로다.

## 파일·소유권

| 소유자 | 책임·파일 |
| --- | --- |
| 조회 worker | 새 `service/CitizenNoticeService.java`, 새 `CitizenNoticeServiceTest.java`: 검증/선택·공개 투영·확보 이력·누적 한도. ROOT 행동 RED 전에는 production 작성/새 class 참조 시험 승격을 기다린다. |
| DB/JAR worker | 새 `CitizenNoticeMySqlTest.java`, `CitizenNoticeJarMySqlTest.java`, 필요한 test-only `CitizenNoticeFixtures.java`: 전용 DB·실제 HTTP/JAR·SELECT 계정·철회/복구·legacy/파일/행 보존. ROOT RED는 기존 타입+HTTP URL만 사용한다. |
| 주 작업자 | 새 `controller/CitizenNoticeController.java`, 새 `CitizenNoticeApiTest.java`, 기존 PublicSnapshotRepository·PublicApiTest·contracts 예제/검증·README/TASK/인계 문서·전체 검증/리뷰/PR/정리 |

같은 worktree에서 다른 작업자의 변경을 되돌리지 않는다. 소유 파일만 수정하며 공유 인터페이스 변경은 주 작업자와 먼저 맞춘다.

### Task 1: 같은 시민 공개본의 실제 조회

**Files:** 소유권 표의 service/controller/repository 및 관련 단위/실제 HTTP 시험.

**Interfaces:** 위 ctor/method·DTO/오류·citizenHistory를 그대로 사용한다. 기존 PublicNoticeService·SnapshotNoticeService·PublicSnapshotRepository.history는 변경하지 않는다.

- [ ] `CitizenNoticeMySqlTest.noCitizenHeadIsUnavailableRatherThanEmpty`를 먼저 작성한다. 실제 HTTP GET의 기대는503 PUBLIC_DATA_NOT_READY·안전한 공통 오류이며 현재 경로 미구현의404를 확인한다. 새 class를 참조해 compile 오류를 RED로 대신하지 않는다.
- [ ] Run: `./gradlew test --tests '*CitizenNoticeMySqlTest.noCitizenHeadIsUnavailableRatherThanEmpty'`를 전용 DB·MYAI_MYSQL_TESTS=true로 실행한다. Expected: 신규 경로404 때문에 assertion FAIL.
- [ ] controller·시민 이력 SELECT·service와 관련 시험을 구현한다. worker의 새 class 참조 단위시험은 ROOT RED 확인 뒤 승격한다.
- [ ] `CitizenNoticeServiceTest`는 현재/지정/교체/빈/미등록/계열/손상·5분야/복수분야·12개 사실/출처 고정·최초 미확인/실제 철회·복구·종류 분리·누적8MiB/1001개·membership 손상을 검사한다. 큰 유효 JSON은 허용된 공백 bytes로 구성해 형식 실패와 읽기 한도 실패를 구분한다.
- [ ] `CitizenNoticeApiTest`는 빈/중복/추가 query·비정규 path/query UUID·snapshot 필수·공통422/404/409/503/500·요청 ID/로그를 검사한다. Expected: `./gradlew test --tests '*CitizenNoticeServiceTest' --tests '*CitizenNoticeApiTest' --tests '*CitizenNoticeMySqlTest'` FAIL/SKIP0.

### Task 2: 실제 연결·재현 자료

**Files:** DB/JAR worker 시험/fixture, 주 작업자의 기존 PublicApiTest·`contracts/citizen-api.md`·시민 응답 예제2개·기존 validate_examples.py·backend README/TASK/연결 안내.

**Interfaces:** Task1의 경로·공개 envelope·이력/오류를 그대로 소비한다. 고정 예제는 합성 계약 설명이며 현재 DB의 snapshot을 선언하지 않는다.

- [ ] 실제 DB/HTTP에서5분야·미상/명시 비용·신청/진행 분리·다대다 출처를 게시하고 같은 ID의 목록→상세를 대조한다. head/근거/계열/멤버십 손상·과거 ID409·명시 철회·원문 삭제 뒤 복구·새시민 UUID의 기존 events/matches 거부와 기존 config/지점 보존을 검사한다.
- [ ] SELECT 전용 계정의 실제 public JAR에서 목록/상세/이력을 읽고 모든 DB 행·원문 전후를 대조한다. Python 실행 파일/작업 경로를 사용할 수 없어도 시민 조회는 성공해야 하며 기존 matches의 실패는 그대로다. local-api/fixture에서 시민 공개 route가 제공되지 않음을 확인한다.
- [ ] 합성 목록/상세 예제와 원문/생성/확인 시각·12개 FieldValue·history unknown·미지원 query·오류/복구·실행/초기화·예상 결과를 문서화한다. 실제 Flutter 연동·강명묵 인수·최종 API 합의로 쓰지 않는다. 기존 validate_examples.py에 새 예제 간 ID/사실/출처/근거 일치 검사를 추가한다.
- [ ] Run: `./gradlew test --tests '*CitizenNotice*' --tests '*PublicApiTest'`와 `python3 contracts/validate_examples.py`. Expected: 실제 MySQL8.4.13/Docker에서 FAIL/SKIP0, 기존 예제/계약도 유지. 로컬9.6 보충 결과와 Docker 미가용을 구분한다.

### Task 3: 전체 검증·리뷰·develop 반영

**Files:** 전체 변경·해당 작업 기록·PR.

**Interfaces:** source/CI candidate/develop 전체 tree·실제 자동 코멘트를 대조한다. 이전 PR20 통합 CI는 별도 추적하며 main은 사람이 병합한다.

- [ ] Java 전체·Python 전체·Node lint/test/build·기존/신규 계약·변경 문서 링크와 실제 readonly/JAR를 검증하고 실패 원인을 기록한다. 적용한 migration·과거 bytes·사용자 변경이 보존됐는지 확인한다.
- [ ] 호출자/예외/권한/조회·이력/복구/계약/문서 전체 자체 검토와 유효 지적 수정을 반복한다. 계획별 독립 전체 리뷰1회를 수행하고 Minor도 수정·관련 검증한다.
- [ ] 유효 미해결0일 때 영어 Conventional Commit·한국어 develop PR을 제출한다. 정확 head CI·실제 AI 코멘트·도착한 사람 지적을 대조하고 수정/검증한다. 부분 AI 검토는 전체 검토로 쓰지 않는다.
- [ ] CI 성공·유효 미해결0 뒤 비main PR을 병합하고 tree·사용자 파일·기존 기능/원본 보존을 확인한다. 본인 병합 브랜치만 정리하고 다음 Java/Python 단계로 진행한다.

## 남은 전체 goal

이 단계는 시민 조회의 수직 연결이다. 검색/복합 필터·날짜/모집/비용 정규화·개인화·Python 시민 출력/보관/사람 인계·새 평가의 호환 보호·최종 화면 연동·실자료/사용자 평가·운영 인수는 실제 기준과 결과를 구분해 계속 진행한다. 이번 단계나 합성 처리 건수로 전체 goal 완료를 판단하지 않는다.
