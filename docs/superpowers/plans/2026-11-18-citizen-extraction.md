# Citizen Extraction Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자의 agents 분담 지시를 적용하되 계획당 독립 전체 리뷰는 마지막에 정확히1회 수행한다.

**Goal:** 시민5분야 원출력을 명시 계약으로 검증·보관하고 사람 수정 선언과 Java D05/S10 판독에 연결하면서 기존 추출·평가 원본을 보존한다.

**Architecture:** 기존 입력·근거 검증·manual archive-v1·human-review-v1·Java 등록 경로를 재사용한다. metadata의 명시 schema로 기존/시민 출력 parser를 선택하고, 기존8필드 평가·D06 투영은 시민 family를 조기에 거부한다. 별도 provider·의존성·DB migration은 추가하지 않는다.

**Tech Stack:** Python3.13 표준 라이브러리, Java21·Spring Boot3.5.x·MySQL8.4, 기존 Gradle·JUnit·unittest·Node 도구.

**Spec:** `docs/spec/00_목차.md`, `docs/spec/01_제품요구사항.md`, `docs/spec/07_결정사항과자체점검.md`, `backend/docs/citizen-review.md`, `contracts/citizen-api.md`, `contracts/extraction-run.md`, `contracts/human-review.md`. 새 family 세부는 작성자의 호환성 검토안이며 팀원·Flutter 합의를 의미하지 않는다.

## Global Constraints

- G3 PR55 정확 head CI·자동 코멘트 확인·develop 병합·tree 검증·본인 브랜치 정리 뒤 시작한다. 전체 Java/Python goal을 이 계획으로 축소하지 않는다.
- Java21·Spring Boot3.5.x·MySQL8.4·Python3.13과 현재 의존성을 유지한다. 적용 V1~V6·과거 snapshot·기존 추출 원본은 수정하지 않는다.
- 교육/지원/문화/공사·교통/생활5분야다. 신청/진행, 적용 지역/장소/거주 조건, 비용 미상/무료, 자격/관심을 구별하며 없는 날짜·자격·취소·일정 대응을 생성하지 않는다.
- 실제 키·비공개 원문·독립 정답·D09를 열거나 API를 호출하지 않는다. 합성 처리·선언 검토를 실제 정확도·신원·사람 승인으로 집계하지 않는다.
- 원출력/실패/원래 prompt bytes·제공 metadata/사람 수정·불변 봉인과 loopback/Bearer/Host/Origin 경계를 보존한다. 공개 조회 중 AI/Python 호출·사용자 설정 저장을 추가하지 않는다.
- AGENTS.md·사용자 .gitignore·타인 브랜치/worktree를 보존한다. Gradle 실행은 주 작업자만 한다.
- 커밋은 영어 Conventional Commits·명령형·50자 이내다. 문서·PR은 한국어다. 유효 Minor까지 수정하고 정확 head 원격 CI/실제 AI/도착한 사람 지적0 뒤 develop에 병합한다. main/배포는 수행하지 않는다.

## Files and Interfaces

- 신규 `processing/extraction/citizen.py`: `SCHEMA_VERSION='extract-citizen-v1'`, `PROMPT_VERSION='citizen-prompt-v1'`, `output_schema()`, `parse_output(content: bytes, document: dict) -> dict`, `render_prompt(document: dict) -> bytes`.
- `validation.py`: 기존 evidence 검증을 동일 오류 경로의 `parse_evidence(value: dict, document: dict) -> set`로 공유하고 `parse_versioned_output(content, document, schema_version)`을 추가한다. 기존 `parse_output`은 기존 family만 받는다.
- 신규 계약 `contracts/citizen-extraction.md`, schema `contracts/schemas/extract-citizen-v1.json`, 공개 합성 `contracts/examples/citizen-ai-input.json`·`citizen-ai-extraction.json`. root는 schema_version/document_version_id/items/evidence/warnings다. item은 local_item_id/title/categories와 기존 시민12사실이다.
- title은 text FieldValue, categories는 unique nonempty5enum 배열 FieldValue이고 미상 분류는 null+ambiguous다.12사실은 원문 문자열/unique 문자열 배열/null FieldValue다. known은 근거 필수, null은 unknown knowledge+reason 필수, 알려진 빈 배열은 명시적 없음 표현만 나타낸다.
- `archive.prepare(input_path, root=DEFAULT_ROOT, schema_version=기존버전)`: prepare CLI에만 `--schema-version` 선택을 추가한다. 기존 기본 경로/출력 bytes는 그대로, 시민 경로는 `prepared/extract-citizen-v1/<input_sha>`다. 미지원 버전은 쓰기 전에 거부한다.
- `metadata.parse_metadata`는 두 명시 schema만 받는다. 시민은 manual_import만 허용하며 실제 수동 prompt_version 라벨을 그대로 보존한다. 준비 템플릿 사용·제공되지 않은 모델/시각을 인증하거나 생성하지 않는다.
- archive-v1 파일 집합/identity/receipt·1~3시도·실패 전체 bytes·재실행/봉인은 그대로다. 시민 API/archive-v2 혼용은 거부한다. 원출력 자기 선언으로 parser를 선택하지 않는다.
- `evaluation.reviews`는 부모 metadata family로 이전/수정 출력을 검증하고 전체 changes 감사·실패 부모·선언 시각·전체 보관을 재사용한다. legacy draft/check-draft/human-handoff·D08 bindings/records는 시민을 scoring/투영 전에 명시 거부한다.
- `ExtractionArchiveReader`만 두 schema/manual 제약을 허용한다. D05 등록은 기존 generic 저장을 사용한다. `ExtractionRunRepository.referenceDirectory/handoffParentDirectory`의 기존 D06 schema 게이트는 유지한다.
- S10은 새 raw output/실패/metadata·근거를 판독한다. 시민 human-review의 Java 표시/저장·시민 D06·승인/공개 연결은 다음 G5다. 이 계획의 사람 수정 연결은 Python 별도 보관본까지다.

## Review Focus

1. metadata/출력 family 불일치·API/v2 혼용·다른 문서/근거 위변조를 거부하며 실패 원출력 전체를 보존한다(Task1/2).
2. 기존13pin·96파일 기준본의 원본 bytes/receipt/mode·CLI 결과가 유지된다. expected를 새 코드로 재생성하지 않는다(Task1/3).
3. 시민12필드·미상·명시 없음·Unicode 근거와 모든 사람 수정이 보존되며 old8필드 분모에 섞이지 않는다(Task1).
4. 재실행·충돌·심볼릭 링크·봉인 실패·원본 경로 유실 후 재검증에서 타 run/원본을 덮어쓰지 않는다(Task1/2).
5. 실제 Java D05/S10·HTTP 경계에서 metadata/원문/실패 bytes는 같고 D06·승인·공개 행은 생성되지 않는다(Task2/3).

---

### Task 1: 시민 수동 출력·보관·사람 수정과 기존 평가 격리

**Files:** 신규 citizen.py/schema/examples·`processing/tests/test_citizen_extraction.py`·`test_citizen_extraction_cli.py`·`test_citizen_extraction_compatibility.py`; 수정 validation.py/metadata.py/archive.py/__main__.py/draft.py, evaluation/reviews.py/bindings.py/records.py/human_handoff.py와 해당 시험.

**Interfaces:** 위 Files and Interfaces의 Python 서명을 생산한다. Java는 동일 schema/manual metadata와 archive-v1 receipt를 소비한다. worker는 citizen.py·schema/examples·parser 단위 시험만 소유하며, 공통 helper/CLI/archive/reviews/legacy guards와 회귀 기준은 주 작업자가 소유한다. 같은 worktree의 다른 변경을 되돌리지 않는다.

- [ ] **Step 1:** 실제 CLI prepare에 `--schema-version extract-citizen-v1`과 공개 입력·소유 임시 root를 전달하는 시험을 먼저 작성한다. 기대 exit0/status prepared인데 현행은 exit2/ARGUMENT_INVALID인 행동 RED를 관찰한다. 누락 import/compile 오류를 RED로 삼지 않는다. worker도 새 parser를 작성하기 전 잘못 수용되는 계약 또는 동일 CLI RED를 확인한다.
- [ ] **Step 2:** 해당 입력·schema/근거·5분야/12사실·분류 미상·복수 사건·추가 키/중복/증거/크기·family/API 혼용 거부를 최소 구현한다. `parse_evidence` 추출 전 기존 잘못된 근거의 code/path/kind를 고정한다. 준비 템플릿 bytes와 실제 수동 prompt bytes/hash를 구분한다.
- [ ] **Step 3:** 실제 CLI prepare/import/verify/freeze/verify-sealed·수정 선언/보관 시험을 추가하고 관찰한 실패부터 수정한다. 비UTF8·큰 실패·3시도·정확 재실행·다른 원본 충돌·symlink/권한·원래 경로 삭제 뒤 재검증·failed 부모 전체 변경·교차 family 수정 거부를 확인한다. 시민 old draft/handoff/D08 경로는 schema unsupported를 scoring 전에 반환한다.
- [ ] **Step 4:** 구현 전 고정 `/tmp/yeogi-citizen-python-legacy-baseline/`13pin과 `/tmp/yeogi-citizen-python-legacy-archives/`96파일을 검증한다. portable 회귀 fixture는 필요한 최소 공개 bytes/고정 hashes를 저장하고 봉인0400/0500은 시험 setup에서 재현한다. old source file SHA는 provenance이며 새 소스 일치를 강제하지 않는다. manifest SHA0cdb9589b6f1acc66075cec2a2651e23546a3dbb8747e127ff17349b67eab77f를 고정한다.
- [ ] **Step 5:** Run `python3.13 -B -m unittest discover -s processing/tests -p 'test_citizen*.py' -v` 및 영향받는 기존 extraction/human/evaluation 시험. Expected: 새/기존 성공, 실패 case의 기대 오류·원본 불변 확인. 커밋 `feat: archive citizen extraction outputs`.

### Task 2: Java D05·S10·기존 업로드 연결

**Files:** 수정 `backend/src/main/java/kr/ac/myai/backend/extraction/ExtractionArchiveReader.java`; 관련 `ExtractionArchiveReaderTest`, `ExtractionArchiveProtocolTest`, `ExtractionManualImportTest`, `ExtractionRunMySqlTest`, `ExtractionUploadJarMySqlTest`, `ReviewReportMySqlTest`·필요시 별도 CitizenExtractionIntegrationTest. 관리/보고서 본문은 필요성이 재현될 때만 수정한다.

**Interfaces:** Task1의 새 수동 metadata/schema와 동일 receipt·봉인 파일을 소비한다. Java worker는 이 파일/시험만 소유한다. 공통 Python/계약 문서·다른 worker 변경을 되돌리지 않는다. 시험 실행은 주 작업자의 Gradle 한 세션으로 한다.

- [ ] **Step 1:** 실제 시민 manual 봉인본을 readSealed/freeze로 읽고 D05 등록·재실행·보고서까지 검사하는 시험을 먼저 작성한다. Task1이 CLI 통과한 뒤 현행 Java schema gate가 EXTRACTION_ARCHIVE_INVALID를 반환하는 행동 RED를 관찰한다. fake Python packet만으로 연결 완료를 주장하지 않는다.
- [ ] **Step 2:** allowlist2개·시민 manual/archive-v1 제약만 최소 변경한다. metadata/input/document/hash/receipt/0400/0500·정확 파일 집합을 유지한다. unsupported 시민 API/v2·출력/metadata 불일치·원본 변조를 거부한다.
- [ ] **Step 3:** 실제 MySQL D03→성공/실패 D05→정확 재실행→S10 raw/metadata와 기존 HTTP upload/finalize를 검증한다. HTTP metadata64KiB/prompt20MiB/output5MiB, CLI JSON8MiB·큰 실패 보존은 그대로다. D06·승인/공개0·old rows/원문 불변과 Bearer/Host/Origin 거부를 확인한다. Java human-review 연결/G5는 아직 완료 처리하지 않는다.
- [ ] **Step 4:** Run parent-only `./gradlew test --tests '*Extraction*' --tests '*ReviewReport*' bootJar`에 필요한 전용 DB 환경을 제공한다. Expected: 환경 가능한 시험 성공; Docker daemon 부재는 이름·원인을 기록하고 원격 MySQL8.4 exact head 전체 검사로 보완한다. 커밋 `feat: import citizen extraction archives`.

### Task 3: 문서·전체 검증·독립 전체 리뷰·develop 반영

**Files:** 신규 `contracts/citizen-extraction.md`; 수정 contracts/README.md·extraction-run.md·human-review.md·dataset-bindings.md·extraction-evaluation.md, processing/README.md·TASK.md, backend/README.md·TASK.md·docs/extraction-run-import.md·extraction-upload.md·review-report.md·citizen-backend-reuse.md·citizen-open-items.md. 영향 없는 문서는 수정하지 않는다.

**Interfaces:** Task1/2의 실제 동작과 검증 결과를 인계한다. 새 처리/실패/수정과 legacy평가 거부·G5 잔여 범위를 명시한다.

- [ ] **Step 1:** 실행 명령·예상 경로·새/기존 family·수동 prompt label·미상·기계/선언 검토·보관 한도·오류·미완료를 실제 출력 기준으로 문서화한다. 미확정 자료/평가/모델·팀원/Flutter 합의는 open-items에 기록하며 질문을 요청하지 않는다.
- [ ] **Step 2:** Run `python3.13 -B -m unittest discover -s processing/tests -v`, parent-only `./gradlew test bootJar`, `npm run lint`, `npm test`, `npm run build`, `python3 contracts/validate_examples.py`, `git diff --check`, 변경 문서의 실제 상대 링크 검사. Expected: 전체 기능 회귀 통과·누락0. 실제 키/자료/독립 평가를 읽지 않는다. 로컬 Docker 불가 항목은 exact CI에서 반드시 실행·통과한다.
- [ ] **Step 3:** 전체 diff·호출자·예외·권한·원본/복구·회귀/계약·문서를 자체 검토하고 유효 지적은 Minor 포함 root RED→수정→관련 검증한다. 마지막에 fresh 독립 전체 리뷰 정확1회 수행한다. 심각도와 무관하게 모든 유효 지적을 수정하고 whole author review를 반복한다. 커밋 `docs: describe citizen extraction workflow`.
- [ ] **Step 4:** develop 대상 PR에 실제 검증·제약·전체/부분 리뷰를 구분해 적는다. 정확 head의 CI/실제 AI 코멘트·도착한 사람 리뷰/threads를 확인하고 유효 미해결0까지 수정한다. 자동 오탐은 원인·증거를 기록한다.
- [ ] **Step 5:** exact green/head0을 확인한 non-main PR만 expected_head_sha로 병합한다. source/실제CI후보/병합/develop tree를 비교하고 root develop을 사용자 변경 보존하며 FF한다. 재사용 worktree를 detach하고 본인의 병합 브랜치만 lease 확인 뒤 정리한다. main PR20 통합 증빙을 갱신·검사하되 병합하지 않는다. 다음 전체 goal의 시민 D06/G5로 계속한다.
