# 장문 분할 추출 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 부모는 계약·API/archive·평가·Git/실행을 담당하고, 독립 chunk/prompt와 Java 지원은 명시 소유 worker에 병렬 배정한다. 마지막 전체 검토는 새 검토자1명에게 맡긴다.

**Goal:** 긴 다중 블록 문서를 실제 분할 요청으로 추출하고, 전체 문서 시도·근거·실패·원본 보관·평가·Java 검토 인계를 재현 가능하게 연결한다.

**Architecture:** 작은 API 입력은 기존 prompt-v2/archive-v1을 유지한다. 큰 입력은 결정적 block 분할·인접1block 문맥과 prompt-v3/archive-v2를 사용하며 문서 cycle1~3과 실제 HTTP 호출수를 구별한다. chunk별 원출력과 전체 파생 출력을 모두 보존하고, 교차 chunk 사건 관계는 사람 검토로 넘긴다.

**Tech Stack:** Python3.13 stdlib, 기존 Java21/Spring Boot3.5/MySQL8.4. 새 의존성 없음.

**Spec:** `docs/spec/03_데이터와AI.md` D05·원문 전처리·재시도, `contracts/extraction-run.md`, 새 `contracts/chunked-extraction.md`, 기존 human-review/handoff·extraction-evaluation 계약.

## Global Constraints

- 입력/출력 ai-input-v1/extract-schema-v1과 D03 전체 원문을 유지한다. 기존 prompt-v1/v2·archive-v1 bytes/완료ID/봉인/재검증은 보존한다.
- 실제 키·원문·gold/D09·운영 DB/서버를 사용하지 않는다. API/HTTP는 합성 응답·기존 모의 transport로 시험한다. 새 실제 추출 호출0.
- 입력/출력8MiB·깊이100, 요청120초·출력8192tokens·문서 cycle 최대3·오류의 기존 재시도 분류를 유지한다. cycle 내부 중첩 재시도는 없다.
- 팀 요청 body 예산131072bytes/구조 피드백 여유4096bytes는 공급자 token 한도가 아니다. 실제 사용량 미상이 하나라도 있으면 합계null. 추가 token계산 API 없음.
- 자동 source/draft/사람 수정·승인·공개 경계를 완화하지 않는다. 분할 자동 결과의 직접 ai-draft는 막고 실제 사람 검토/handoff를 사용한다.
- 사용자 .gitignore·AGENTS·기존 private pack·main 보존. 영어 Conventional Commit≤50자, 문서/주석/PR 한국어. 비main만 승인된 기준으로 병합한다.

## Review Focus

1. 중복 문맥과 같은 local ID가 별개의 사건/일정을 자동 합치거나 버리지 않도록 정확한 참조를 보존한다.
2. chunk 밖 미관측 값을 문서 전체 not_stated로 바꾸지 않고 ambiguous·사유·경고를 요구한다.
3. 일부/전부 실패·미시도는 문서 실패이며 빈 정상 결과나 NO_EVENT_FOUND로 숨기지 않는다.
4. 완료/중단/동시 실행·봉인 뒤 변조/읽기 전용 검증에서 기존 v1 의미와 모든 v2 원출력을 유지한다.
5. D08 첫/최종은 전체 문서 cycle이며 HTTP 호출 수·metadata attempts·비용/사용량·Java 마지막 output 참조를 혼동하지 않는다.

### Task 1: 결정적 계획·부분 문맥 prompt

**Files:** `processing/extraction/chunks.py` 신규, `prompt.py` 수정, `processing/tests/test_extraction_chunks.py` 신규. 소유 worker1.
**Interfaces:** `plan_chunks(document, model, input_sha256, *, request_limit=131072)`→계약 plan dict; `chunk_document(document, chunk)`→기존 입력5키의 부분집합; `chunk_request_bytes(document, model, chunk, error_path=None)`→실제 v3 request bytes; `validate_chunk_output(content, document)`→기존 parse_output+부분 문맥 검사; `assemble_outputs(document, plan, outputs)`→문서 전체 파생 output dict. `outputs`는 plan 순서의 validated chunk output dict를 순차 제공하는 iterable이다.

- [x] RED: 강제 작은 예산의2+chunk·core 전체 coverage·정확한 인접1block·원문 ID/hash/emoji offset·계획 재현성/경계·단일 oversized block requires_review를 assert한다.
- [x] RED: v1/v2 byte 고정, v3 범위/metadata·외부 block 인용/전체 not_stated/경고 누락 거부, 같은 local ID remap·사건 임의 융합 없음·전부 사건 없음/일부 사건 없음 경고를 assert한다.
- [x] GREEN: 위 순수 함수를 구현하고 해당 unittest를 실행한다. 모델 호출·키·DB·파일 쓰기를 넣지 않는다.
- [x] 전체 입력8MiB의 다수 블록에서 불필요한 반복 직렬화를 피하고, 계약/부모 caller와 signature를 맞춘 뒤 커밋한다.

### Task 2: API cycle·v2 원본 보관·오프라인 재검증

**Files:** `processing/extraction/chunk_archive.py` 신규, `api.py`, `archive.py`, 필요 CLI, `processing/tests/test_chunked_extraction.py`. 부모 소유.
**Interfaces:** 기존 `run_api`/`verify_run`/`freeze_run`/`verify_sealed_run` 반환/종료는 유지한다. v2 exact receipt/artifact는 새 계약에 고정한다. 큰 새 입력에서만 분할 실행하고 완료 ID는 저장 형식으로 키 없이 재사용한다.

- [x] RED: 실제 모의 transport 다중chunk 호출·cycle 첫 실패/최종 성공·모든 cycle 실패·영구 오류 뒤 미시도·계획 불가 호출0·실제 total_calls/nullable usage·전체 파생 output을 assert한다.
- [x] GREEN: 기존 request/response 검사·archive 쓰기/identity·freeze를 재사용하고 v2에서만 확장한다. chunk마다 중첩 재시도하지 않는다.
- [x] RED→GREEN: 정확한 plan/요청/응답/실행 순서/receipt·전체 output 재계산, artifact 누락/추가/변조·동시ID/중단·원본 보존·봉인 무쓰기를 검사한다.
- [x] v1 전체 회귀와 새 CLI subprocess를 실행한다. 실제 외부 API 없이 통과한 뒤 커밋한다.

### Task 3: Java 등록·보고서·사람 인계

**Files:** `ExtractionArchiveReader.java`, `HumanHandoffArchiveReader.java`, `ReviewReportService.java`와 관련 backend test. 소유 worker2.
**Interfaces:** v2도 metadata attempts/receipt.attempts.size는1~3이며 마지막 `attempt-N.output`은 전체 파생 출력이다. v1 exact branch 유지. 새 `ExtractionArchiveReader.artifactNames(JsonNode)`는 버전별 exact names·v2 chunk status/attempted 구조를 검증해 반환한다.

- [x] RED→GREEN: 실제 Python v2 봉인 생성→Java reader의 validated/failed·재사용·참조변조·마지막 output hash를 검사한다. 기존 DB CHECK/VerifiedExtraction 변경이나 migration은 필요가 입증되지 않으면 추가하지 않는다.
- [x] RED→GREEN: 보고서 모든 subrequest와 파생 output 표시·8MiB/artifact/64MiB 전체 한도·악성 파일명/누락 거부, v2 부모의 실제 human-review/handoff 인계를 검사한다.
- [x] parent의 Python 생성기가 준비되면 실제 관련 Java/MySQL/JAR 시험을 부모가 단독 실행한다. worker는 Git·Gradle·Docker를 실행하지 않는다.

### Task 4: 평가·직접 초안 경계·전체 통합

**Files:** Python `draft.py`, evaluation `records.py`/관련 tests, `contracts/chunked-extraction.md`·기존 계약/README/TASK. 부모 소유.
**Interfaces:** v2 직접 draft는 `CHUNK_DRAFT_REVIEW_REQUIRED`; 실제 사람 검토는 기존 전체 first/final/changes·handoff 경로. 새 평가 policy `api-document-cycle-v1`은 v1 단일 요청/v2 분할의 전체 문서 cycle을 허용하며 기존 policy는 v1만 받는다.

- [x] RED→GREEN: 직접 v2 draft 거부·사람 수정/인계 성공, 첫 실패/최종 성공과 전체 실패·누락/중복 분모, 혼합 버전 policy·원본 동결/이전 v1 bytes를 검사한다.
- [x] Python 전체·Java/MySQL 전체·실제 합성 JAR·계약/Node/lint/build 실행, 전체 호출부/실패/원본 보존 자체 검토를 완료한다.
- [ ] fresh 전체 검토1회→유효 minor 포함 수정·재검증→PR→정확 head CI/AI/새 사람 피드백→develop 병합·통합 gates→비공개 실행 증거 동결을 완료한다.

**Expected:** 단순 길이 거부로 대체하지 않고 실제 여러 chunk의 결과를 끝까지 처리한다. oversized 단일 block 예외·사람 관계 확정·실제40문서/독립 gold/90%·기기/D09·운영/main은 구별해 기록한다.
