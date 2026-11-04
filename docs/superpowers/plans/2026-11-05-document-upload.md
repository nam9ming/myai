# 로컬 원문 업로드·텍스트화 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 기존 native 실행·독립 파일 worker 방식을 유지한다. 부모는 multipart·metadata·파일 보관·D03 연결·통합/Git을 맡고 Task1과 Task2를 독립 worker에 배정한다. 마지막 전체 코드 검토는 새 검토자1명에게 맡긴다.

**Goal:** 인증된 로컬 HTTP의 txt/pdf/json 원문을 보존·텍스트화하고 기존 D03 등록과 Python 입력 준비까지 연결한다.

**Architecture:** 기존 application/json source-import는 유지한다. 별도 multipart 진입이 명시 metadata·원본 bytes로 D03와5키 AI입력을 만들고 기존 reader/service를 호출한다. raw20MiB와 JSON8MiB를 분리하며 S10·승인/공개·복구도 같은 원문을 검증한다.

**Tech Stack:** Java21·Spring Boot3.5·MySQL8.4·Python3.13, 설치된 Poppler `pdftotext`. 신규 Maven/Python/npm 라이브러리 없음.

**Spec:** `docs/superpowers/specs/2026-11-05-document-upload-design.md`, `docs/spec/03_데이터와AI.md` D03, `04_계산규칙과기술설계.md` I10/한도, `10_인원별WBS.md` B05/G02/G06, 기존 `contracts/local-management-api.md`·`backend/docs/reviewed-import.md`·`review-report.md`·`backup-recovery.md`.

## Global Constraints

- 기존 공개32KiB·JSON/CLI/AI입력8MiB·AI archive/실패 원본 규약을 유지한다. raw asset만20MiB로 분리한다.
- 새 파일20MiB·전체 multipart21MiB·metadata64KiB·cleaned_text200,000 Unicode code point다. 초과는413이며 자르거나 부분 성공으로 바꾸지 않는다.
- txt/pdf/json 모두 실제 D03까지 연결한다. JSON 파일은 정확한 text-body-v1/text 규약, 기존 source-import는 원래 application/json 경로다.
- metadata ID/버전/수집시각을 고정하고 원래 bytes·출처/전처리·실패·기존 자료를 보존한다. 새 자료는 pending/unchecked·checks없음이며 자동 AI·사람 승인·공개 없음.
- local-api의 기존 인증·Origin/Host·공개 분리를 유지한다. 인증 실패/unknown metadata/초과 파일의 저장·DB쓰기0, 경로·본문·키·stderr를 오류/로그에 넣지 않는다.
- PDF stdin은 원래 bytes, stdout≤4MiB/stderr≤64KiB·전체10초·키 없는 환경·종료 회수다. 텍스트 없는 페이지는 전체422, 내장 텍스트만 추출하고 모든 PDF는 실제 원문 대조 필요를 명시한다.
- 새 본문은 LF/NFC·고정 전화/이메일 치환·범주/위치 기록, 최대2,000 code point 블록과 PDF 페이지를 보존한다. 기존 AI입력 블록/bytes는 바꾸지 않는다.
- S10 raw20MiB 전체 embed·기타 artifact8MiB·JSON/HTML 전체64MiB를 유지한다. 총량 초과는 REPORT_TOO_LARGE이며 원문 생략은 하지 않는다.
- 실제키/실자료/gold/운영서버·배포는 사용하지 않는다. 실제 비식별·PDF 완전성·사람 검토·40문서/90%·AI결과5MiB 업로드·UI·main 인수는 후속 전체 목표다.
- 영어 Conventional Commit≤50자·AI trailer없음, 한국어 문서/주석/PR. 사용자 .gitignore/AGENTS·다른 작업/자료는 보존한다. 모든 유효 minor를 수정하며 새 전체 코드 리뷰는1회다.

## Review Focus

1. part 중복/추가·Content-Length 없는 전송·외부 Origin이 servlet parsing/임시파일이나 D03 저장을 유발하지 않는다.
2. PDF 입력 재읽기·timeout·stderr 폭주·일부 빈 페이지가 다른 원문/일부 본문을 정상 문서로 등록하지 않는다.
3. 같은 버전의 동시 재시도·정책/도구 버전 변화·중간 파일 실패가 ID/원본/과거 전처리 결과를 바꾸지 않는다.
4. 8MiB보다 큰 원문이 등록에서만 통과하고 source-review/preview/approve/publish·S10·복구에서 뒤늦게 거부되지 않는다.
5. Unicode 보조문자·정규화/치환·긴 한 행에서 code point와 블록/hash/페이지가 어긋나거나 원래 연락처가 기록에 복제되지 않는다.

---

### Task 1: raw20MiB 검증과 S10 전체 원문

**Files:** `backend/src/main/java/kr/ac/myai/backend/importing/ReviewedImportReader.java`, `review/ReviewReportService.java`, `backend/src/test/java/kr/ac/myai/backend/ReviewedImportReaderTest.java`, `ReviewReportMySqlTest.java`, 관련 source-review/publication 검증 시험. 이 파일들만 raw worker 소유이며 공통 error/controller는 부모 소유다.

**Interfaces:** `ReviewedImportReader.RAW_ASSET_LIMIT=20*1024*1024`를 원문 전용으로 공개한다. 기존 `readBounded(Path,String)`·`parseJson(byte[])`의8MiB는 유지한다. `read/validateStored`의 D03 raw 검사와 S10 raw capture만 새 한도를 사용한다.

- [ ] RED: 정확한 SHA의 raw8MiB+1/20MiB 허용·20MiB+1 거부, JSON8MiB+1 거부를 각각 assert한다. 기존 hash 불일치에 가려진 oversized 시험을 분리한다.
- [ ] RED: 실제 MySQL에서 >8MiB raw 등록→source-review→preview/승인·공개 검증→S10 전체 원문 text/base64 보존을 assert한다. raw20MiB+1·기타 AI artifact8MiB+1·보고서 전체64MiB 초과는 기존 자료를 보존하고 거부한다.
- [ ] GREEN: 원문 전용 읽기 한도를 분리하고 기존 범용 JSON 한도·원문 hash·전체 보고서 제한/오류를 유지한다.
- [ ] 관련 reader/source-review/publication/report 시험을 격리 MySQL로 실행하고 `feat: support larger private source assets`로 커밋한다.

### Task 2: 결정적 텍스트화와 bounded PDF 실행

**Files:** 신규 `backend/src/main/java/kr/ac/myai/backend/local/SourceTextPreprocessor.java`, `PdfTextExtractor.java`, `backend/src/test/java/kr/ac/myai/backend/SourceTextPreprocessorTest.java`, `PdfTextExtractorTest.java`. 이 파일들만 text worker 소유다. profile YAML/CI/metadata/보관은 부모 소유다.

**Interfaces:**
- `SourceTextPreprocessor.prepare(String format, byte[] raw) -> Prepared`.
- `Prepared(String cleanedText, List<Block> blocks, List<Redaction> redactionLog, String preprocessingVersion, String textScope, boolean textReviewRequired)`.
- `Block(String blockId,Integer page,String text)`, `Redaction(String category,String location)`은 기존 D03 snake_case 직렬화로 투영한다.
- `PdfTextExtractor.extract(byte[] raw) -> PdfText(List<String> pages,String toolVersion)`; Spring의 선택 설정 `myai.local-api.pdftotext`/`MYAI_LOCAL_API_PDFTOTEXT`는 절대 실행 파일이다. 미설정은 PDF 요청만503이며 기존 local-api/CLI 기동을 막지 않는다.
- 공통 ApiException을 사용하며 payload/metadata 오류422, 한도413, `PDF_TOOL_NOT_READY`503, `PDF_PAGE_REVIEW_REQUIRED`422, 변환 실패는 안전한 `PDF_EXTRACTION_FAILED`422로 구별한다. 실제 stdout/stderr는 오류에 포함하지 않는다.

- [ ] RED: txt/json의 엄격 UTF-8·추가/중복키·후행 JSON·제어문자·CRLF/NFC, 연락처 치환과 값 미기록, emoji 포함 최종 cleaned_text200,000/200,001 code point를 assert한다. 줄바꿈 없는200,000자 입력의 추가 분할 LF로 최종 한도가 넘으면413이며 자르지 않는다.
- [ ] RED: 긴 한 행을2,000 code point 이하 블록으로 분리하고 순서/결합/페이지·블록 유일ID·UTF-8 hash가 일치함을 assert한다. 기존 Python parse_input·chunk planner가 이 투영을 받아 입력 한도 내 장문 계획을 만든다(API0회).
- [ ] RED: 실제 합성 다페이지 PDF의 stdin/stdout 텍스트·페이지를 검사한다. 중간/마지막 빈 페이지·깨짐/암호화·비정상 종료·timeout·stdout4MiB+1/stderr64KiB+1·키 없는 환경·프로세스 회수를 별도 고정 fixture로 assert한다.
- [ ] GREEN: 설치된 도구의 shell 없는 고정 argv·동시 bounded drain·공통 deadline·실행 버전 기록, 순수 변환/블록 정책을 구현한다. 기존 PythonProcess는 키 없는 환경/20MiB 입력 계약이 달라 임의 전역 확장을 하지 않는다.
- [ ] 관련 전체 변환/PDF 시험을 실행하고 `feat: prepare uploaded notice text`로 커밋한다.

### Task 3: multipart·원본 보관·D03 연결

**Files:** 신규 `local/SourceUploadService.java`, `SourceUploadStore.java`; 수정 `LocalManagementController.java`, `ApiExceptionHandler.java`, `resources/application-local-api.yml`, 필요 시 `config/LocalApiStartupGuard.java`; 신규 `SourceUploadStoreTest.java`, `SourceUploadServiceTest.java`, `SourceUploadApiTest.java`. 부모 소유다.

**Interfaces:**
- `SourceUploadService.upload(byte[] metadata, byte[] raw, String fileMediaType) -> Result`는 설계의 source-upload-v1 정확14키를 검증한다. 기존 reader의 strict JSON/형식 검증과 Task2 `Prepared`를 재사용해 `source-import-v1` 한 문서와5키 AI입력을 만든다.
- 기존 controller의 `/documents`에 multipart 전용 method를 추가한다. 정확히 metadata/file 한 개씩만 허용하고 metadata64KiB·file20MiB를 실제 stream에서 확인한다. filename은 경로에 쓰지 않는다.
- `SourceUploadStore.retainRaw(byte[],String format) -> Path`, `find(String versionId,byte[] metadata,byte[] raw) -> Stored|null`, `commit(String versionId,byte[] metadata,byte[] sourceImport,byte[] aiInput,JsonNode receipt) -> Stored`.
- `Stored`는 검증한 metadata/원문 hash와 원래 생성 sourceImport/aiInput bytes·전처리/도구 정보를 제공한다. 준비한 bundle을 모두 검증한 뒤 버전ID receipt index를 hard link로 배타 설치해 ready 상태를 공개한다. 같은 버전의 원본이 다르면409, 같은 원본은 기존 frozen 생성물을 재사용한다. 미완료 후보와 기존 bundle을 덮어쓰지 않고 자기 임시 후보만 정리한다.
- metadata 원bytes는 기존 LocalRequestStore의8MiB 경로로도 보관할 수 있다. 원문20MiB를 그 JSON store에 넣지 않는다. 파일/DB commit은 별개이며 DB 실패 후에도 재시도할 원본·ready 생성물을 보존한다.

- [ ] RED: multipart3형식 성공·metadata64KiB/파일20MiB/전체21MiB 경계·chunked·추가/중복part·지원하지 않는형식·인증/Origin 실패의 쓰기0·공통 request_id/413/422/415를 assert한다.
- [ ] RED: strict metadata·공식 URL/ID/버전·알 수 없는 schema/키·pending 강제와 D03/AI5키/hash 투영을 assert한다. 자동 D05/사건/승인/공개·외부 호출은0이다.
- [ ] RED: source/request root의 링크/권한/기존 다른 내용, 같은 업로드 동시 설치·정확 재시도·메타/원본변경 충돌·중간 I/O/DB실패·도구버전 변화 후 원래 결과 재사용을 assert한다.
- [ ] GREEN: 기존 D03 reader/service의 전체 검증·버전/CAS·rollback과 원래 bytes를 재사용한다. local-api multipart만20/21MiB로 설정하고 in-memory threshold≥21MiB로 공용 임시파일을 만들지 않는다. safe multipart 오류 handler를 연결하고 공개32KiB/기존JSON8MiB를 유지한다.
- [ ] 관련 전체 단위/MockMvc·기존 API/security/startup/CLI 회귀를 실행하고 `feat: register uploaded source documents`로 커밋한다.

### Task 4: 실제 JAR·MySQL·보고서/복구·최종 검증

**Files:** 신규 `SourceUploadMySqlTest.java`, `SourceUploadJarMySqlTest.java`; 관련 `DatabaseRecoveryTest.java`/S10 시험; `.github/workflows/ci.yml`, `contracts/source-upload.md`, `contracts/local-management-api.md`, `backend/README.md`·`TASK.md`·`docs/local-management-api.md`·`reviewed-import.md`·`review-report.md`·`backup-recovery.md`. 부모가 소유하며 합의한 테스트 파일만 독립 worker에 인계할 수 있다.

- [ ] RED→GREEN: 실제 multipart HTTP로3형식→D03→Python 입력 검사→정확 재실행/거부를 검증한다. >8MiB와 최대20MiB 원문을 포함하고 새 자료는 pending/unchecked·공개0이다. 기존 source-review/preview/승인 경계·S10 full raw·선택 복구 후 원래 등록 재실행을 대조한다.
- [ ] 실제 JAR에서 chunked/인증 전 parsing/part/크기 오류·키/본문/경로 비노출·공용 임시파일0·정상/빈페이지 PDF·전용 DB를 검증한다. `MYAI_LOCAL_API_PDFTOTEXT`만 설정하며 실제 키는 전달하지 않는다.
- [ ] CI에서 Poppler 실행 파일을 확인/준비하고 실제 버전을 기록해 PDF시험을 건너뛰지 않는다. 기존 Node·계약·Python·전용MySQL·JAR 전체 검증을 유지한다.
- [ ] `python3.13 -m unittest discover -s processing/tests -v`, `npm run lint`, `npm test`, `npm run build`, 전용 MySQL의 `./backend/gradlew -p backend test bootJar --no-daemon`을 실행한다. 실패/오류/skip0·종료코드/실제 실행 버전을 기록한다. 기존 공유/운영 DB에 시험하지 않는다.
- [ ] 계약·실행/한도·원본/실패·PDF/비식별 검토·백업/복구·미완료를 기록한다. 실제키/API/실자료/운영 인수를 실행했다고 표시하지 않는다.
- [ ] 부모 전체 자체 리뷰→유효 minor 포함 수정·재검증→새 문맥 전체 코드 리뷰1회→PR→정확 head CI/AI/새 피드백→비main 병합·통합 검증→비공개 증거 동결을 완료한다. main은 병합하지 않는다.

**Expected:** txt/pdf/json의 원문·metadata·전처리·AI입력을 보존하면서 D03 저장과 기존 검토/공개/보고서/복구를 연결한다. 실제 AI 추출·사람 검토·정확도·UI·운영 배포 완료로 범위를 확대하지 않는다.
