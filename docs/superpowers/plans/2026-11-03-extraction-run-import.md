# D05 실행 기록 DB 등록 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 구현은 native로 진행하고 마지막에 한 번의 별도 전체 리뷰를 수행한다. main은 사람 병합, 다른 PR은 최신 CI·유효 미해결0 후 병합한다.

**Goal:** 원문만 먼저 등록한 뒤 Python 비공개 실행 기록을 검증해 D05의 성공·실패·측정값·원본 추적을 DB에 불변 등록하고 기존 D06 AI-origin 검토본과 연결한다.

**Architecture:** `source-import-v1`은 기존 D03 검증·저장 경로를 재사용하며 사건/근거가 빈 배치다. Java의 비공개 `local-extraction`은 Python verify를 DB 트랜잭션 밖에서 호출하고 receipt 및 hash가 일치하는 입력/metadata 원본을 읽는다. 등록된 D03의 제목·게시일·전체 블록·data_kind·전처리 버전과 대조 후 원자적으로 D05 한 행을 저장한다. raw AI는 D06으로 자동 변환/승인/공개하지 않는다.

**Tech Stack:** Java21·Spring Boot3.5.16·Gradle8.14.3·MySQL8.4.13·Python3.13 stdlib. 새 의존성 없음.

**Spec:** `docs/spec/03_데이터와AI.md` D03/D05/D06·AI 계약, `09_DB설계와트랜잭션.md` DB07/DB09, backend/TASK.md·processing/TASK.md·contracts/extraction-run.md.

## Global Constraints

- 기준477c6f0dbcd909a920527d89903a8b57b1968ddf. Java/Python만 개발하며 공개 API·계산 결과·기존 V1/V2 migration을 바꾸지 않는다.
- Python이 추출 검증의 단일 원본이다. 기존 verify의0/4를 성공/실패 D05로 등록하며2/3/5/1은 등록하지 않는다. 모든 상태는 사람 검토 필요다.
- 원문·raw output·프롬프트는 비공개 archive에 유지한다. stdout/stderr/공개 API에 본문·실제 경로·하위 프로세스 진단을 내보내지 않는다.
- 기존 bounded process의 동시 IO·공통 deadline·크기 제한·interrupt/프로세스 정리를 공유하고 계산기의 외부 오류 계약을 유지한다.
- D05 provider/model을 nullable로 전환하고 metadata/receipt 원본 UTF-8·SHA-256을 LONGTEXT로 보존한다. Decimal 비용·외부 나노초 시각을 DB 열 변환으로 잃지 않는다. 기존 legacy 행의 없는 metadata를 채워 꾸미지 않는다.
- 같은 run_id·같은 원본은 재사용, 다른 원본/문서/참조는 충돌. FK·트랜잭션·동시 중복 복구를 유지한다. 실패 run은 D06 originating_run_ids로 사용할 수 없다.
- 등록에는 이미 저장한 전체 D03 블록과 일치하는 입력을 요구한다. chunk 처리·실제 API/재시도·실자료·D06 자동 초안 생성·평가·배포는 후속 전체 Goal이다.

## Review Focus

1. 사건을 만들기 전에 원문을 등록할 수 있으며 source-only 배치가 D06 승인·공개로 오인되지 않는가.
2. Python 실패/timeout/손상·원본 변경·다른 문서/전처리/합성 태그가 D05 validated로 저장되지 않는가.
3. nullable 모델·정밀 비용·나노초·실패 원출력의 hash/상태/metadata를 손실 없이 보존하는가.
4. 중복/동시 경합·저장 중 실패에서 원본 행/공개 head를 덮거나 부분 저장하지 않는가. Python 실행 중 DB 트랜잭션을 유지하지 않는가.
5. 강제 웹/혼합 local profile을 시작 전에 차단하며 로그·오류·공개 조회에 raw/경로를 노출하지 않는가.

### Task 1: D03 선등록·D05 확장

**Files:** Modify ReviewedImportReader.java, ReviewedImportRepository.java; create V3__extend_extraction_run_metadata.sql; tests ReviewedImportReaderTest.java·ExtractionRunMySqlTest.java; source-only 합성 예제.

**Interfaces:** `source-import-v1`은 reviewed-import-v1과 같은5키, documents≥1·evidence=[]·events=[]이며 source_kind=source로 저장. 기존 reviewed-import-v1의 사건/근거 최소1은 유지. V3는 provider/model nullable, model_version/schema_version/preprocessing_version/execution_mode/attempts/data_kind/metadata_json/metadata_sha256/receipt_json/receipt_sha256/registered_by/registered_at을 추가하며 legacy 값은 null 유지.

- [x] Step1: source-only 정상·사건/근거 혼입 거부·기존 빈 reviewed 거부·동일 배치 재사용·D03만 저장·V3 기존 행 보존/null·정밀 원본 시험 작성 후 RED 확인.
- [x] Step2: 기존 문서 검증/저장을 재사용하고 V3 migration만 추가한다. source-only는 별도 schema/source_kind로 식별한다.
- [x] Step3: 해당 단위·실제 MySQL 시험 GREEN 후 커밋. Expected: 사건/공개 행 증가 없음, migration 재실행0.

### Task 2: Python 검증·archive 읽기

**Files:** Create process/PythonProcess.java, extraction/VerifiedExtraction.java·ExtractionArchiveReader.java; modify PythonCalculator.java·build.gradle; create ExtractionArchiveReaderTest.java.

**Interfaces:** `PythonProcess.execute(executable,workdir,args,input,timeout)->Result(exitCode,stdout)`는 기존 안전 IO를 이동한다. `ExtractionArchiveReader.read(runId,root)->VerifiedExtraction`은 Python verify의 receipt와 입력/metadata/receipt 원본 hash를 대조하고0/4·상태 일치를 확인한다. 기본 실행 파일/workdir는 기존 Python 설정을 사용하며 extraction timeout은60000ms(1~60000)다.

- [x] Step1: 실제 Python 생성 archive의 성공/실패·다중 시도·정밀 metadata·손상/미완료/다른 run·잘못된 root/파일·timeout/비정상 출력·안전한 오류·기존 계산 프로세스 회귀 RED.
- [x] Step2: 중복 subprocess 구현 대신 기존 IO를 공유한다. root/run/artifact는 일반 파일·고정 파일명만 사용하며 입력/metadata 각각8MiB로 제한한다. Python 작업·파일 읽기는 DB 밖이다.
- [x] Step3: 관련 시험·기존 계산 시험 GREEN 후 커밋. Expected: 원문 없이 안전한 실패, child 정리, 원본 bytes/hash 보존.

### Task 3: 원자 등록·CLI·D06 연결·전체 검토

**Files:** Create repository/ExtractionRunRepository.java, service/ExtractionImportService.java, extraction/LocalExtractionCommand.java, config/LocalExtractionStartupGuard.java·application-local-extraction.yml; modify application main/spring.factories/기존 local profile guards; tests ExtractionRunMySqlTest.java·ExtractionCommandTest.java; backend/processing/contracts/spec 실행 문서.

**Interfaces:** `ExtractionImportService.importRun(runId,root,actor)->Result`는 먼저 archive를 검증하고 짧은 REQUIRES_NEW에서 D03 projection·전처리 버전을 대조해 INSERT한다. Result는 ID·상태·attempts·data_kind·hash·already_registered·review_required만 반환한다. actor≤128, main profile `local-extraction`; 설정 myai.extraction.run-id/archive-root/actor, 기존 MYAI_PYTHON_EXECUTABLE/WORKDIR 및 MYAI_EXTRACTION_TIMEOUT_MS 사용.

- [x] Step1: 등록/재실행·다른 원본 충돌·문서/블록/전처리/tag 불일치·실패run 보존/D06참조거부·동시 등록·DB rollback·Python 진입 트랜잭션 없음·공개 미노출·강제web/혼합profile·CLI exit0/2/3/4/5/1 RED.
- [x] Step2: V3에 입력/출력 hash·nullable표시값·원본 metadata/receipt·archive 참조·최초 actor를 불변 저장한다. duplicate 경합 복구 조회는 실패 트랜잭션 종료 후 새 트랜잭션에서 대조한다. legacy 행을 검증 없이 성공으로 승격하지 않는다.
- [x] Step3: 실제 MySQL 전체 Java·Python97+·npm lint/test/build·실제 JAR 원문→D05→AI-origin D06 import/공개 미반영·실패/재실행·출력 안전성 검증. Expected: 모든 시험 GREEN·생략0, 기존 공개 head 불변.
- [ ] Step4: 한국어 실행/미완료·hash 대상·원본 보관/복구 책임을 갱신한다. 자체 전체 리뷰 후 한 번의 fresh 전체 reviewer, 유효 지적 RED→GREEN·전체 회귀로0까지 수정한다.
- [ ] Step5: backend/api-foundation PR 제출·최신 CI/AI/사람 지적 검토. CI 성공·유효 미해결0이면 expected-head 병합, main PR4는 사람 대기. 이번 작업의 전용 임시 DB/자료만 정리하며 전체 Goal은 유지한다.
