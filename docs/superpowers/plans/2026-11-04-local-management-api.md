# 로컬 관리 HTTP API 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 부모는 HTTP 계약·controller·원본 보관·서비스 연결·통합/Git을 담당한다. 프로필/인증과 기존 reader byte[] 진입점은 파일 소유권을 나눠 독립 worker에 배정한다. 마지막 전체 브랜치 검토는 새 검토자1명에게 맡긴다.

**Goal:** B05/I10/I11의 문서·D05 등록, 사람 검토 수정/승인, 공개 미리보기·공개·복구를 기존 서비스와 같은 검증·트랜잭션으로 로컬 HTTP에서 실행한다.

**Architecture:** `local-api` 단독 프로필은 127.0.0.1에 bind하고 실행마다 준비한 임시 Bearer 토큰·동일 origin을 요구한다. 기존 파일 JSON 규격과 domain 서비스를 재사용하며 공개 프로세스에는 관리 controller를 등록하지 않는다. 원입력 bytes는 private 요청 보관본으로 유지하고 DB와 파일 저장의 결과를 구별한다.

**Tech Stack:** 기존 Java21/Spring Boot3.5/MySQL8.4, JDK/Spring 기본 기능. 새 의존성·JPA entity·DB migration 없음.

**Spec:** `docs/spec/04_계산규칙과기술설계.md` I10/I11·경계, `08_기술구성과연결.md`, `09_DB설계와트랜잭션.md`, `10_인원별WBS.md` B05, 기존 `backend/docs/reviewed-import.md`·`review-publication.md`·`extraction-run-import.md`·`human-handoff-import.md`, 새 `contracts/local-management-api.md`.

## Global Constraints

- 공개 I01~I03·32KiB·오류 DTO·조건 비수집, 기존 CLI 입력8MiB·원본 hash·실패/충돌·승인 경계를 유지한다. Java/Dart에 Python 계산을 복제하지 않는다.
- `/local`은 공개/fixture 실행에서404다. 로컬 관리 실행은 `local-api` 단독·servlet·127.0.0.1만 허용한다. 공개/fixture/CLI 혼합과 외부 bind·빈 설정은 DB/웹 기동 전에 거부한다.
- Bearer 토큰은 환경변수로 제공한32~128자리 URL-safe 문자다. 예시는 합성 값만 쓴다. 토큰·본문·원문·절대 경로·SQL·stack을 HTTP 오류나 요청 로그에 넣지 않는다.
- Origin과 Host는 실제 서버 port의 `http://127.0.0.1:<port>`/`127.0.0.1:<port>`와 같아야 한다. 실제 HTTP port80에서만 기본 port 생략과 명시를 동등하게 허용한다. 누락/null/외부 origin은403, 잘못된/누락 토큰은401이다. forwarded-header 처리는 NONE이며 인증/출처 실패는 body 저장·domain 호출 전에 끝낸다.
- 로컬 JSON body8MiB, 공개 body32KiB를 각각 실제 stream에서 제한하고 초과는413이다. UTF-8·중복/추가키·후행 JSON·타입·버전 검사는 기존 reader를 따른다.
- 설정은 `MYAI_LOCAL_API_TOKEN`, `MYAI_LOCAL_API_ACTOR`, `MYAI_LOCAL_API_SOURCE_ROOT`, `MYAI_LOCAL_API_EXTRACTION_ROOT`, `MYAI_LOCAL_API_HANDOFF_ROOT`, `MYAI_LOCAL_API_REQUEST_ROOT`, `MYAI_LOCAL_API_PORT`다. root는 명시 절대 private 경로이며 임의 client root를 받지 않는다.
- 실제 키/자료/gold/D09·운영 DB/서버·배포는 사용하지 않는다. 합성 DB·원문·보관본만 시험한다. 실제 자료 승인/공개·40문서/90%·기기 인수는 여전히 미완료다.
- 이번 단계는 기존 JSON과 보관본을 연결한다. txt/pdf 새 업로드·텍스트화와 제안20MiB/200000문자/AI5MiB 경로는 전체 후속 범위로 유지하며 이 API 완료로 표시하지 않는다.
- PR44 source `4b6b9ff`는 CI/리뷰를 통과했지만 GitHub develop 쓰기 서버 오류로 원격 병합 대기다. 이 작업은 동일 검증 tree의 별도 worktree에서 진행한다. PR44/로컬 develop7bfe/main·사용자 .gitignore·AGENTS·기존 private pack을 보존한다. 원격 복구 후 실제 base/통합 CI를 다시 확인한다.
- 커밋은 영어 Conventional Commit≤50자·AI trailer 없음. 문서/주석/PR은 한국어. 유효 minor도 수정하며 새 전체 리뷰는1회다.

## Review Focus

1. local-api/공개/CLI 프로필·bind 강제 덮어쓰기에서 토큰이나 관리 동작이 공개되지 않는다.
2. 인증 없는 oversized/chunked body·중복 Authorization/Origin·Host 변경이 원문 저장/DB 동작을 유발하지 않는다.
3. URL 사건ID·원입력 hash·expected_revision_no/head_version 불일치가 부분 저장·다른 사건 수정·묵시적 최신 선택으로 바뀌지 않는다.
4. 원본 요청 파일의 symlink·기존 내용 충돌·동시 동일 body·저장 실패가 DB 성공을 가장하거나 다른 파일을 덮어쓰지 않는다.
5. 사람 인계/실패 D05·preview·공개 경합에서도 기존 source/AI/수정본·SELECT 전용 미리보기·이전 공개본을 보존한다.

### Task 1: 로컬 프로세스·인증·요청 경계

**Files:** `config/LocalApiStartupGuard.java`, `local/LocalApiSecurityFilter.java`, `logging/PublicRequestLogContext.java`, `resources/application-local-api.yml`, `MyaiBackendApplication.java`, `controller/PublicNoticeController.java`, `controller/StatusController.java`와 `LocalApiStartupTest.java`·`LocalApiSecurityTest.java`. 보안 worker 소유; controller의 실제 API 메서드는 부모 소유다.

**Interfaces:** 프로필 이름 `local-api`; 공통 설정 prefix `myai.local-api`. 실제 필수 환경과 같은 alias만 소비한다. 필터는 local-api의 모든 servlet 요청을 검사하고 기존 `PublicRequestLogFilter` 다음 순서에서 `ApiExceptionHandler.ErrorResponse`·서버 request_id·오류 code를 사용한다. DispatcherServlet 전에도 같은 요청 상태를 쓰도록 `PublicRequestLogContext.requestId(HttpServletRequest)`/`error(HttpServletRequest,String)`를 추가하고 기존 no-arg 동작을 유지한다. raw/decoded 경로 차이로 인증을 건너뛰지 않는다. 로컬 HTTP body 제한은 부모가 새 controller에만 적용한다.

- [x] RED: 실제 JAR의 빈 토큰/actor/root·외부 bind·non-web·공개/fixture/CLI 혼합을 기동 실패로 assert한다. 합성 토큰/본문/경로가 결과에 없는지 검사한다.
- [x] RED: 401/403·정상 Bearer/Origin, 중복 헤더·Host/remote 주소·실제 port·OPTIONS·encoded path/forwarded header를 검사하고 body/domain 호출0을 assert한다.
- [x] GREEN: early initializer·단독 프로필·loopback·constant-time 토큰 검사·Origin/Host 검사를 구현한다. 0번 port는 시험/실제 임시 포트로 허용한다.
- [x] 추가 경계 RED→GREEN: 실제 port80의 기본 port 생략/명시를 허용하며 다른 port/host/scheme은 거부한다. actor128자 상한·ISO control 거부는 기존 서비스 검증을 기동 전에 재사용한다.
- [ ] 공개/fixture `/local`404, 올바른 로컬 인증을 보낸 local `/api/v1`404, 기존 CLI 동작·공개 오류/로그 회귀를 실행하고 커밋한다.

### Task 2: 파일 reader의 원입력 byte[] 재사용

**Files:** `importing/ReviewedImportReader.java`, `publication/PublicationCommandReader.java`, `ReviewedImportReaderTest.java`, `PublicationCommandReaderTest.java`. reader worker 소유. 기존 파일 method와 byte[] method는 같은 검증 본문을 사용한다.

**Interfaces:** `ReviewedImportReader.read(byte[] content, Path sourceRoot) -> ReviewedBatch`, `PublicationCommandReader.read(byte[] content) -> PublicationCommand`. 기존 `read(Path,...)`는 실제 파일 읽기 경계를 유지한 채 위 공통 검증으로 위임한다. `validateStored`는 HTTP 신규 입력에 사용하지 않는다.

- [x] RED: 동일 파일/bytes의 결과와 원본 SHA 일치, 공백만 다른 body의 서로 다른 inputSha256을 assert한다.
- [x] RED: malformed/후행/중복키/잘못된 UTF-8·추가키·8MiB 초과와 source symlink/hash·revision/승인 상태 오류를 두 경로에서 동일하게 거부한다.
- [x] GREEN: 기존 private batch/strict publication 변환·Bean Validation을 재사용한다. 새 coercion/자동 보정/재직렬화 hash를 넣지 않는다.
- [ ] 관련 reader 전체와 기존 파일 CLI 시험을 실행하고 커밋한다.

### Task 3: 원본 보관·네 관리 HTTP 경로

**Files:** `local/LocalManagementController.java`, `LocalManagementService.java`, `LocalRequestStore.java`, `LocalBodyLimitAdvice.java`, `service/ExtractionImportService.java`, `controller/ApiExceptionHandler.java` 및 `LocalManagementApiTest.java`·`LocalManagementServiceTest.java`·`LocalRequestStoreTest.java`·`ExtractionImportServiceTest.java`. 부모가 전체 연결을 소유하며 `LocalRequestStore.java`·`LocalRequestStoreTest.java`만 기존 reader worker가 독립 담당한다.

**Interfaces:**
- POST `/local/documents`: 원본 `source-import-v1` JSON만 받는다. 기존 read/importBatch 결과를 반환하며 사건/공개를 만들지 않는다.
- POST `/local/extractions/import`: 정확히 `schema_version:extraction-import-request-v1,run_id,expected_input_hash`. 서버 extraction root의 원본을 검증하고 hash가 같을 때만 D05를 저장한다. 기존 `importRun(String,Path,String)`는 유지하고 expected hash를 받는 overload를 추가해 DB 쓰기 전에 검사한다.
- PUT `/local/events/{id}/review`: 기존 `reviewed-import-v1`의 사건1개 또는 `human-handoff-import-v1`, 혹은 `publication-command-v1` approve/reject다. URL ID는 해당 유일 사건과 같아야 하며 expected 번호·원래 AI/사람 인계를 보존한다.
- POST `/local/reviews/import`: 기존 `reviewed-import-v1`/`human-handoff-import-v1` 전체 배치다. 다중 사건의 원래 인계 이미지를 유지하며 단일 사건 URL에 다른 사건 수정을 섞지 않는다. handoff의 유일/전체 대상은 `revisions[].event_id`로 검사한다.
- POST `/local/publish`: 기존 `publication-command-v1` preview/publish/rollback만 받는다. `PublicationService.execute`의 mode/revision/head/권한 재검증을 그대로 사용한다.
- 성공200: `schema_version:local-management-result-v1,request_sha256,data`이며 data는 기존 결과 record다. 오류는 기존 error/request_id 형태로401/403/413/415/422/404/409/503/500을 구별한다. 경로·본문·비밀값은 반환하지 않는다.
- 원입력은 request root0700의 `<sha256>.json`0600에 원자적으로 배타 설치한다. 같은 bytes는 무쓰기 재사용하며 다른 기존 bytes·symlink·권한 오류는 거부한다. 재직렬화본으로 대체하지 않는다. preview는 요청 파일을 만들지 않는 읽기 전용이다. 인증/본문 한도/잘못된 JSON·미지원 schema는 보관하지 않는다. 인식한 관리 요청의 원본 보관과 DB 성공/실패를 구별하며 실패 batch DB 기록은 추가하지 않는다. 파일 저장 실패는 domain 호출 전에 끝낸다.

- [x] RED: 필수 네 경로와 배치 인계 경로의 byte/ID/hash/행위 dispatch, source-only·사건1개·URL ID/다중 배치 구별, expected hash 불일치 때 DB 쓰기0을 assert한다.
- [x] RED: 8MiB+1/Content-Length 없음·잘못된 media·UTF-8/중복키, 인증 실패 때 body 저장0, preview 때 파일/DB 쓰기0을 검사한다.
- [x] RED: 원본 공백/hash·같은 body 동시 설치·기존 충돌/symlink·파일 실패 시 domain 호출0과 원본 보존을 검사한다.
- [x] GREEN: 기존 서비스·readers·예외·파일 원자 설치 패턴을 연결한다. field 값이나 exception message의 원문을 오류에 반사하지 않는다.
- [ ] 관련 HTTP/reader/CLI·공개 회귀를 실행하고 커밋한다.

### Task 4: 실제 MySQL·JAR HTTP 흐름과 최종 검증

**Files:** `LocalManagementMySqlTest.java`, `LocalManagementJarMySqlTest.java`, `contracts/local-management-api.md`, `backend/docs/local-management-api.md`, README/TASK·계획 체크박스. 부모 소유.

- [ ] RED→GREEN: 별도 MySQL에서 실제 HTTP 문서/D05(성공·실패) 등록→수정→승인/반려→preview→publish→공개 조회→rollback, 중복·stale·동시 충돌·권한 미확인/실패 부모를 검증한다. 원본·행·이전 공개본을 대조한다.
- [ ] 실제 합성 JAR를 loopback 임시 port에 실행하고 토큰/Origin·공개/관리 분리·안전한 오류·파일/DB 보존을 확인한다. 시험용 프로세스/컨테이너만 정리한다.
- [ ] Python 전체·Java/MySQL 전체·Node/계약/lint/build를 실행하고 전체 호출부·상태·보관/복구·문서 자체 리뷰를 완료한다.
- [ ] fresh 전체 검토1회→유효 minor 포함 수정·재검증→PR→정확 head CI/AI/새 사람 피드백→비main 병합·통합 검증→비공개 증거 동결을 완료한다. provider 오류가 지속되면 정확한 대기 상태를 유지한다.

**Expected:** 네 관리 JSON 경로가 실제 기존 DB/승인 서비스에 연결되고 공개·CLI 경계와 원입력/실패·충돌을 유지한다. txt/pdf 새 업로드·관리 UI·실자료 사람 검토·40문서/gold/D09·실제 배포/main 인수를 완료로 확대하지 않는다.
