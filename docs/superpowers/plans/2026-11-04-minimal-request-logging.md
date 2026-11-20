# 최소 요청 로그 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자 승인에 따라 독립 파일을 병렬 구현하고 마지막 전체 브랜치 리뷰는 새 검토자 한 명에게 맡긴다.

**Goal:** R15/R16의 요청 ID·오류 코드·처리시간·확인된 snapshot/rules 버전만 요청당1회 기록한다.

**Architecture:** Servlet `OncePerRequestFilter`가 요청별 상태와 서버 UUID·단조 시간을 관리한다. 기존 오류 handler와 작은 response advice가 같은 상태에 오류/응답 metadata를 전달하고, 실제 조회 서비스는 선택한 snapshot 세 지점만 연결한다. 로그는 `public_request ` 뒤 compact JSON5필드이며 기존 API JSON·Python CLI 계약은 유지한다.

**Tech Stack:** 기존 Java21·Spring Boot3.5·SLF4J/Jackson·MySQL8.4·Python3.13. 새 의존성 없음.

**Spec:** `docs/spec/04_계산규칙과기술설계.md:168`, `backend/TASK.md`, 기존 공개 API·계산 계약.

## Global Constraints

- 공개 웹 프로세스의 동기 HTTP 요청 전체에 적용한다. health·알 수 없는 경로·CORS 거부·본문 제한도 기록하며 URI를 읽어 로그에 넣지 않는다. CLI는 필터가 등록되지 않고 stdout을 유지한다.
- 허용 로그 필드는 `request_id`, `error_code`, `latency_ms`, `snapshot_id`, `rules_version`5개다. 본문·query/URI·IP·Origin·User-Agent·영업시간·예외 message/stack을 수집하지 않는다.
- 외부 요청 ID는 사용하지 않는다. 서버 UUID를 `X-Request-ID` 응답 헤더와 오류 body의 기존 `request_id`에 연결한다. CORS는 이 응답 헤더만 추가 노출하며 요청 허용 헤더/origin은 유지한다.
- metadata는 검증한 서비스 선택본 또는 응답의 정확한 기술 필드에서만 얻는다. 퇴역 오류의 `current_snapshot_id`·replay 목록·history를 선택본으로 간주하지 않는다. 확인 전 실패·없는 버전은 null이다.
- 로깅용 버전은 최대100 UTF-16자·비공백이며 제어/서로게이트 오류/줄·문단 구분자/format 문자는 null로 처리한다. 정상 Unicode는 보존하고 JSON escaping으로 값 경계를 유지한다. snapshot은 canonical UUID만 허용한다.
- 기존 JSON 응답·상태·계산 판정·DB schema·자료/공개 상태·언어/프레임워크는 유지한다. 실제 자료·키·gold/D09·운영 서버를 사용하지 않는다.
- 사용자 `.gitignore` 변경과 모든 AGENTS·기존 동결 pack 보존. 영어 Conventional Commit 제목50자 이내, 문서/PR/주석 한국어. main 병합·배포는 사람 담당.

## Review Focus

1. 정상/422/413/404/503/500·CORS/health에서도 ID·종료 로그가 정확히1회이고 오류 body와 헤더가 일치한다.
2. 요청/응답/예외에 주입한 비밀 문자열·영업시간·URI/IP·개행이 로그에 섞이지 않으며 관찰 실패가 응답을 바꾸지 않는다.
3. 선택 후 계산 실패에는 확인된 원래 버전을 남기고, config replay 목록·상세 history·퇴역 current ID가 덮어쓰지 않는다.
4. 연속 요청과 요청 밖 서비스/CLI 호출에 이전 metadata가 남지 않는다. ThreadLocal/MDC를 새로 만들지 않는다.
5. fallback 오류·filter chain 예외·누락/비정상 metadata에서도 값 추측이나 중복 stack 로그 없이 기존 오류 동작을 유지한다.

### Task 1: 요청 상태·필터

**Files:** 신규 `backend/.../logging/PublicRequestLogContext.java`, `PublicRequestLogFilter.java`, `backend/src/test/.../PublicRequestLogTest.java`.

**Interfaces:** `PublicRequestLogContext.requestId()` → String; `selected(String snapshotId,String rulesVersion)`은 실제 선택본, `response(String snapshotId,String rulesVersion)`은 선택본이 아직 없을 때만 응답 metadata, `error(String code)`는 오류 코드. 모두 static이며 상태는 filter가 만든 request attribute에만 존재한다. 요청 밖 setter는 noop, ID는 기존 handler용 새 UUID fallback이다. 필터는 public no-arg 생성자이며 Servlet web context에서만 component로 등록한다.

- [x] ID 생성·헤더/외부ID무시·정확1회 compact JSON·시간≥0·성공null·예외fallback·연속 요청·요청 밖·Unicode/제어값·본문 미노출 시험부터 작성한다. 부모가 새 class/method 부재 RED를 확인한다.
- [x] 플랫폼 필터·request attribute·기존 Jackson/SLF4J만 사용해 구현한다. 요청 body/경로/주소를 읽거나 response wrapper를 만들지 않는다. 부모가 집중 시험 GREEN을 확인한다.
- [x] 소유 파일만 부모 검토/커밋 대상으로 전달한다. DB/Docker/Gradle/Git·외부 API·private 자료 접근은 부모만 수행한다.

### Task 2: 오류·응답 관찰

**Files:** `backend/.../controller/ApiExceptionHandler.java`, `backend/src/test/.../DatabaseErrorResponseTest.java`, 신규 `PublicRequestLogAdviceTest.java`.

**Interfaces:** Task1의4개 public static 메서드만 사용한다. 기존 `ErrorResponse` record/JSON shape를 유지하고 UUID 생성·중복 protocol/Throwable 로그를 공통 상태로 옮긴다. 기존 advice에 `ResponseBodyAdvice<Object>`를 구현해 ErrorResponse.code와 JsonNode의 snapshot_id/data.rules_version만 관찰한다. body 객체는 그대로 반환한다.

- [x] 정상·domain/DB/일반/잘못된 입력·퇴역 오류·없는/비정상 metadata·기존 선택본 보존·private cause 미노출 시험부터 작성한다. 부모가 RED를 확인한다.
- [x] 공통 ID·필드 관찰을 연결한다. 오류 응답 메시지/상태/필드/재시도 의미는 유지한다. 필터 포함 MockMvc에서 로그1회·동일 ID·본문/stack 미노출 GREEN을 확인한다.

### Task 3: 실제 선택 버전·웹 연결·전체 검증

**Files:** `SnapshotNoticeService.java`의 config/calculationInput/event 선택 직후3지점, `WebConfig.java`, `PublicApiTest.java`, `SnapshotCalculationTest.java`, backend README/TASK·로그 안내.

**Interfaces:** `PublicRequestLogContext.selected(snapshot_id,rules_version)`만 실제 load/active 성공 직후 호출한다. 일반 load/envelope/history 루프에 넣지 않는다. HTTP 응답 JSON은 수정하지 않고 CORS exposedHeaders에 X-Request-ID만 추가한다.

- [x] fixture 정상/422/413/CORS와 실제 서비스 계산 protocol 실패·재현 목록/history/retired 경계에서 metadata 보존·null·ID와1회 로그를 먼저 시험해 RED 확인한다.
- [x] 세 선택 지점과 CORS를 연결하고 코드/문서에 로그 범위·알 수 없는 값·운영 보존 정책 미확정을 기록한다.
- [ ] 부모가 Java/MySQL·계약/Node/lint/build 및 필요한 Python 회귀를 실행한다. 저자 전체 리뷰 후 새 whole reviewer1명에게 전체 브랜치 검토를 맡긴다. 유효 지적은 minor 포함 모두 수정·RED→GREEN, PR 제출 후 정확 head CI/AI/사람 피드백을 확인해 미해결0을 유지한다.
- [ ] 승인된 develop 병합·통합 PR20 검증·인계 기록 후 다음 남은 요구를 점검한다. main/배포·실자료/운영 인수 완료로 표시하지 않는다.

**Expected:** 의미 있는 전체/집중 시험 실패·skip0, 허용5필드만 기록, 공개 JSON/계산/원본/DB 보존. 새 프레임워크·추적 서버·요청 저장소·기본 보존 일수는 추가하지 않는다.
