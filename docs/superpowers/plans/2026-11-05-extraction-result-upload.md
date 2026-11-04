# AI 수동 결과 파일 업로드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 기존 native 방식과 독립 파일 소유권의 병렬 agent를 사용한다. 새 문맥 전체 코드 리뷰는 전체 계획에서1회 수행한다.

**Goal:** 실제1~3시도의 수동 AI 결과 파일을 원래 bytes로 받아 기존 Python 보관·Java D05 검증/등록에 연결한다.

**Architecture:** 초기 input/metadata와 시도별 prompt/output을 private CAS staging에 분리 보관하고 명시 finalize에서 기존 import/freeze/DB 서비스를 재사용한다. 현재21MiB 요청 경계와 기존 CLI·AI 원본 보존 한도는 유지한다. 자동 AI·사람 승인/공개·UI는 추가하지 않는다.

**Tech Stack:** 기존 Java21/Spring Boot3.5/MySQL8.4/Python3.13·표준 라이브러리·설치된 Gradle/JUnit/Mockito. 신규 의존성 없음.

**Spec:** `docs/superpowers/specs/2026-11-05-extraction-result-upload-design.md`; 기존 `contracts/local-management-api.md`, `extraction-run.md`, I10·B05/G02/G06.

## Global Constraints

- HTTP control/metadata64KiB·input8MiB·prompt20MiB·output5MiB·전체 multipart21MiB. 기존 source upload20MiB·JSON/CLI/AI입력8MiB·공개32KiB는 유지한다.
- manual_import의 명시 UUID·17키 metadata·실제1..3 prompt/output 순서, 원래 bytes·failed·미상/null·정확 재시도를 보존한다. API wire 기록/시각/모델/승인을 만들어내지 않는다.
- loopback/auth/Origin·인증 전 parsing 차단·private0700/0600·symlink/임의 경로 거부·공개404·로그/응답 비노출을 유지한다.
- 공통 Python 실행 stdout8MiB/stderr64KiB/deadline1..60000ms를 재사용하고 archive import/verify/freeze를 keyless로 한다. 기존 execute의 다른 호출자·CLI 명령은 유지한다.
- S10 AI artifact8MiB/전체64MiB는 유지한다. 초과는 전체 원본 생략 없이 별도 검토 오류다. 실제키/API·실자료·운영 서버를 사용하지 않는다.
- 영어 Conventional Commit 제목50자 이하·영어 본문·AI trailer 없음. 한국어 문서/주석/PR. main 병합·배포는 하지 않는다.

## Review Focus

- 최종 출력이 invalid/빈/비정상UTF-8이어도5MiB 이하면 실패 archive/D05와 전체 원본을 보존한다: Task1/3/4.
- 완료 canonical UUID의 slot 추가·원본 교체·실패를 부재로 오인하거나 중단 동일 HTTP finalize를 막지 않는다: Task2/3/4.
- upload import 뒤의 기존 verify/freeze에 환경 상속이 되살아나지 않고 계산기 등 다른 execute 호출도 깨지지 않는다: Task1/4.
- 초기화·slot·finalize의 동시/중간I/O/DB 실패가 기존 원본·공개본을 덮거나 완료로 잘못 표시하지 않는다: Task2/3/4.
- 새 controller도 기존 body/media/Accept advice와 인증 전 multipart 경계를 빠짐없이 적용한다: Task3/4.

### Task 1: 기존 Python 실행·수동 import 연결

**Files:**
- Modify: `backend/src/main/java/kr/ac/myai/backend/process/PythonProcess.java`
- Modify: `backend/src/main/java/kr/ac/myai/backend/extraction/ExtractionArchiveReader.java`
- Create test: `backend/src/test/java/kr/ac/myai/backend/PythonProcessTest.java`
- Create test: `backend/src/test/java/kr/ac/myai/backend/ExtractionManualImportTest.java`
- Regression: 기존 `ExtractionArchiveReaderTest.java`, `ExtractionArchiveProtocolTest.java`, `PythonCalculatorTest.java`도 실행한다.

**Interfaces:** `PythonProcess.executeKeyless(String executable,String workdir,List<String> arguments,byte[] input,long timeoutMillis): Result`; Result의 bounded stderr 내부 접근과 기존2인자 생성자 호환. Reader의 `record AttemptFiles(Path prompt,Path output)` 및 `importManual(String runId,Path root,Path input,Path metadata,List<AttemptFiles> attempts): JsonNode`. 기존 read/readSealed 서명은 유지한다.

- [x] RED: synthetic 자격정보 환경을 준 실제 JVM/자식 process에서 새 entry·Reader import/verify/freeze의 허용 환경만 남음, 기존 execute 동작, stdout/stderr 초과·timeout/interrupt·종료 회수를 assert한다.
- [x] RED: 실제 Python CLI로1·3시도 성공/failed·빈/invalidUTF8 출력, 기존 완료 UUID의 정확 재사용/다른 bytes 충돌409·임의 stderr 비노출·exit0/4/receipt 일치를 assert한다. 기존 freeze/readSealed·api/v2 원본 검증도 유지한다.
- [x] 기존 공통 runner와 CLI를 재사용해 최소 구현한다. 정확한 고정 ARCHIVE_CONFLICT만 내부 분류하고 Python17키/identity 의미를 재구현하지 않는다. Reader의 archive 명령도 keyless를 사용한다.
- [x] `./backend/gradlew -p backend test --tests '*PythonProcessTest' --tests '*ExtractionManualImportTest' --tests '*ExtractionArchiveReaderTest' --tests '*PythonCalculatorTest' --tests '*ExtractionArchiveProtocolTest' --no-daemon`을 실행한다. 실제 설정한 Python3.13/절대 workdir로 실패/오류/skip0을 확인한다.
- [x] Commit: `feat: import manual extraction files`

### Task 2: 불변 private staging 저장소

**Files:** Create `backend/src/main/java/kr/ac/myai/backend/local/ExtractionUploadStore.java`; test `backend/src/test/java/kr/ac/myai/backend/ExtractionUploadStoreTest.java`.

**Interfaces:** Store의 `record Artifact(String name,long sizeBytes,String sha256)`와 `record Staged(String runId,String expectedInputHash,int attempts,Path directory,byte[] control,List<Artifact> artifacts)`. `initialize(String runId,String expectedInputHash,int attempts,byte[] control,byte[] metadata,byte[] input): Staged`; `find(String runId): Optional<Staged>`; `put(String runId,int attempt,String artifact,byte[] content): Staged`; `ready(String runId,String expectedInputHash): Staged`. 생성자는 기존 request-root와 JSON reader를 받는다. 이름/직렬화 필드는 spec과 일치시킨다.

- [x] RED: root/중간/파일 symlink·권한·기존 손상, 동일/상이 초기 bytes, slot1..3·범위/이름, 정확 재시도·동시 설치·다른 bytes409, 미완성 쌍/finalize 거부를 assert한다. 모든 원본 bytes/hash를 대조한다.
- [x] RED: 실제 두 파일 기록 뒤 I/O 실패를 주입해 index 부재·자기 후보만 정리·기존 bundle/raw 불변·정확 재시도를 assert한다. JVM lock만 믿지 않는 두 Store instance의 경합도 포함한다.
- [x] 기존 SourceUploadStore/LocalRequestStore의 private root·배타 hard link 패턴으로 구현한다. 초기 identity/index·고정 slot만 쓰며 원본 교체/자동 정리/새 DB 테이블은 추가하지 않는다.
- [x] `./backend/gradlew -p backend test --tests '*ExtractionUploadStoreTest' --tests '*SourceUploadStoreTest' --tests '*LocalRequestStoreTest' --no-daemon`: 전체 대상 실패/오류/skip0.
- [x] Commit: `feat: stage extraction upload files`

### Task 3: 로컬 HTTP·기존 D05 서비스 연결

**Files:**
- Create: `backend/src/main/java/kr/ac/myai/backend/local/ExtractionUploadService.java`, `backend/src/main/java/kr/ac/myai/backend/local/ExtractionUploadController.java`
- Modify: `backend/src/main/java/kr/ac/myai/backend/local/LocalManagementService.java`, `backend/src/main/java/kr/ac/myai/backend/local/LocalBodyLimitAdvice.java`
- Test: `backend/src/test/java/kr/ac/myai/backend/ExtractionUploadApiTest.java`, `backend/src/test/java/kr/ac/myai/backend/ExtractionUploadServiceTest.java`와 기존 관리/auth/advice 시험.

**Interfaces:** LocalManagementService에 공유3키 `readExtractionRequest(byte[] body): ExtractionRequest`와 nested record를 두고 기존 extraction도 같은 검사를 사용한다. 새 Service는 `initialize(byte[] control,byte[] metadata,byte[] input): Result`, `put(String runId,int attempt,String artifact,byte[] content): Result`, `finalizeUpload(String runId,byte[] control): LocalManagementService.Result`를 제공한다. Result는 spec의 extraction-upload-result-v1 필드다. Controller는 spec의 정확3경로/part/MIME만 매핑한다.

- [ ] RED: initial/slot/finalize의 정확 성공응답·snake_case·수신 size/hash, UUID/입력hash/metadata 연결·mode/attempts·완료 canonical의 전체 원본/추가 slot 충돌을 assert한다. Python의17키/출력 의미 검증을 대신하지 않는다.
- [ ] RED: 기존 JSON API는 유지하며 새 controller에 control/metadata64KiB·input8MiB·prompt20MiB·output5MiB와 전체21MiB를 실제 읽기부터 적용한다. 기존 controller JSON8MiB·source metadata64KiB는 유지한다. 크기/추가·중복 part/MIME·charset·Accept·auth/Origin·공개404와 로그/오류 비노출을 검증한다.
- [ ] RED: Python 완료0/failed4 뒤 기존 D05 등록을 호출하고 DB 실패 후 같은 staging/UUID/hash 재-finalize, 중단 canonical의 동일 완성 staging 재개, canonical 손상을 부재로 바꾸지 않음을 assert한다. 기존 공개/원본을 변경하지 않는다.
- [ ] 새 Service/Controller를 기존 LocalBodyLimitAdvice에 포함해 구현한다. 새 controller의 control/metadata/JSON finalize64KiB와 기존 controller JSON8MiB/source metadata64KiB를 구별한다. 공통 ApiExceptionHandler·LocalApiSecurityFilter·WebConfig의 media/Accept/auth 동작을 재사용한다. metadata3연결 필드만 읽고 전체 의미는 Task1 import에 맡긴다. 정확한 body bytes를 기존 request 보관과 D05 등록으로 전달한다. 새 상태조회/취소/자동재시도는 추가하지 않는다.
- [ ] 새 API/Service와 기존 LocalManagementApiTest/LocalManagementServiceTest/LocalApiSecurityTest/LocalApiStartupTest/SourceUploadApiTest를 실행해 실패/오류/skip0을 확인한다. 실제 class명/명령을 구현 기록에 남긴다.
- [ ] Commit: `feat: expose extraction file uploads`

### Task 4: 실제 Python·MySQL·JAR·복구·문서

**Files:** Create `backend/src/test/java/kr/ac/myai/backend/ExtractionUploadMySqlTest.java`, `backend/src/test/java/kr/ac/myai/backend/ExtractionUploadJarMySqlTest.java`, `contracts/extraction-upload.md`, `backend/docs/extraction-upload.md`. Modify `contracts/local-management-api.md`, `backend/README.md`, `backend/TASK.md`, `processing/README.md`, `processing/TASK.md`, `backend/docs/backup-recovery.md`, `backend/docs/review-report.md`와 이전 단계 종료 기록.

- [ ] RED→GREEN: 실제 MySQL·JAR HTTP에서1·3시도·failed/빈/invalidUTF8·5MiB 경계·20MiB prompt·중복/경합·DB rollback·봉인 후 재-finalize를 기존 실제 Python으로 대조한다. 전체 D05 원본·오류·측정값을 보존하며 D06/공개는0으로 유지한다.
- [ ] 실제 JAR에서 인증 전 multipart parsing/공용 원문 임시파일0·chunked/한도 오류와 자식 import/verify/freeze의 keyless 환경을 검증한다. 실제 자격정보 대신 합성 marker를 사용한다.
- [ ] 작은 정상/실패 archive의 S10 전체 원본과 큰 prompt의 기존8MiB 보고서 거부를 대조한다. staging/extraction/source root와 DB를 같은 경로로 복원한 뒤 정확 재등록·기존 공개본 불변을 확인한다.
- [ ] 실제 CLI 명령·명시 metadata/미상·새 HTTP/기존 CLI 한도·완료/중단 UUID·정확 재시도·private 보존/백업·오류·S10 경계·미완료를 한국어로 문서화한다. curl은 `--noproxy '*'`로 합성 proxy/direct 검증한다.
- [ ] 전체 Java/MySQL test+bootJar, Python630 기존 전체 회귀, Node lint/test/build·계약 검증을 실행하고 실제 count/버전/exit/skip·원본 proof를 기록한다. CI 기존20분·모든 시험/산출물을 유지한다. 시간 초과 시 실제 원인을 확인한 뒤 수정한다.
- [ ] Commit: `test: verify extraction upload integration`

## 최종 게이트

- [ ] 모든 호출부·환경·metadata/원본·기존 API·생성/조회/복구/오류·문서/계약의 전체 자체 검토, 유효 minor 포함 수정·재검증을 마친다.
- [ ] 새 문맥의 전체 브랜치 코드 리뷰1회 후 유효 지적을 전부 고치고 회귀·전체 자체 검토한다. 재리뷰를 추가하지 않는다.
- [ ] PR→정확 head CI/AI 원문/새 사람 피드백→유효 미해결0→비main 병합·통합 검증·판단/비용 인계·비공개 증거 동결을 완료한다. main은 사람이 병합한다.

## 계획 자체 검토

각 spec 요구는 Task1(기존 Python/원본/환경), Task2(staging/CAS), Task3(HTTP/등록/경계), Task4(실제 연결/복구/문서)에 대응한다. Review Focus5개는 각 소유 Task의 RED 항목에 포함했다. 공통 API 이름/한도는 위 Interfaces를 사용하며 검사 count는 예상으로 완료 처리하지 않는다. 이전 PR46 통합/동결이 미완료면 제품 구현을 시작하지 않는다.

