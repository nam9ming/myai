# Human Handoff Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. User requested parallel agents; file ownership below prevents conflicting edits. Steps use checkbox syntax.

**Goal:** 검증한 사람 수정 인계 이미지를 비공개 D06에 저장하고 수정·승인·공개까지 출처를 재검증한다.
**Architecture:** Python 전체 이미지 검증을 Java에서 호출하고 private payload/배치 결과에 출처 참조를 보존한다. 기존 import·D05 행 검증·revision CAS·공개 트랜잭션을 확장한다.
**Tech Stack:** Java21, Spring Boot3.5.16, Gradle8.14.3, MySQL8.4.13, Python3.13 stdlib.
**Spec:** docs/superpowers/specs/2026-11-03-human-handoff-import-design.md

## Global Constraints

- 새 의존성·Flutter/UI·AI 호출·키 읽기·기존 서비스/DB 변경·main 병합·운영 배포 없음.
- 사용자 .gitignore 수정 보존, 영어 Conventional Commit 제목/본문, 한국어 문서.
- private 원본 전체 보존, 실패 부모를 validated로 꾸미지 않음, 실제/합성 구별.
- 파일/Python 검증은 트랜잭션 밖, 쓰기/재사용/중복 복구는 D03/D05 FOR SHARE 재검증.
- 명시 expected revision, 과거 audit/proof 보존, 승인 strict facts, 공개 경로/검토자 비노출.

## Review Focus

1. 같은 run 캐시의 다른 사건으로 failed 허용 증거가 번지지 않아야 한다 — Task3 사건별 proof 시험.
2. 재사용/중복 복구 직전 D03 전체 본문·D05 등록 행 변경도 차단해야 한다 — Task3 DB fingerprint 시험.
3. 역사 인용이 현재 근거에서 제거돼도 정확한 과거 기록을 보존하고 새 허위 인용은 거부해야 한다 — Task2/3 역사 인용 시험.
4. 기존 사람이 보정한 좌표를 새 투영의 null로 덮어쓰지 않아야 한다 — Task3 보호된 revision 충돌 시험.
5. 원본이 사라진 반려/불변 공개본 복구와 새 승인 차단을 구분해야 한다 — Task3 publication 회귀.

## File Ownership

- Archive worker: 새 backend/.../handoff/HandoffReference.java, VerifiedHandoff.java, HumanHandoffArchiveReader.java 및 HumanHandoffArchiveReaderTest.java만.
- Revision worker: ReviewedImportReader.java, ReviewedBatch.java, HumanReviewChanges.java, PublicationContent.java 및 해당 단위 시험만.
- DB test worker: 새 HumanHandoffMySqlTest.java 및 본인 전용 private fixture helper만.
- Coordinator: import adapter/service·repository·CLI·build inputs·문서/계약/계획·통합 검증/PR.
- 다른 작업자의 변경은 되돌리지 않는다. 공용 파일 변경이 필요하면 coordinator에 먼저 전달한다.

### Task 1: 동결 인계 이미지 Java 검증

**Interfaces:** HandoffReference(directory, handoffRef, receiptSha256), static list(JsonNode); VerifiedHandoff(directory, projection, review, receipt, receiptSha256), reference(); HumanHandoffArchiveReader.read(HandoffReference), read(String ref, String receiptHash, Path root).

- [ ] 실제 Python freeze_review/freeze_handoff로 만든 합성 보관본의 오프라인 읽기 시험을 작성한다. 성공/실패·빈 사건·원래 경로 제거·검토 나노초 원본을 확인한다.
- [ ] 새 reader 부재 RED를 관찰한다.
- [ ] 기존 PythonProcess·ReviewedImportReader.parseJson을 사용한다. verify-handoff 출력과 저장 receipt·projection SHA·review ref/parent·경로/형식을 대조한다. 안전한 ExtractionException으로 변환한다.
- [ ] 잘못된 ref/hash, 변조/누락/권한/symlink, Python 실패/과다 출력·정리 시험을 실행한다.
- [ ] Java21 대상 시험 GREEN 확인 후 담당 파일만 커밋한다.

### Task 2: 비공개 D06와 감사 역사

**Interfaces:** ReviewedBatch에 handoffJson(String nullable)을 추가한다. ReviewedImportReader.prepareHandoff(JsonNode envelope, Path sourceRoot, String inputHash, String runId)는 검증한 내부 envelope를 human-handoff-import-v1 batch로 만든다. 일반 read는 원래 schema 및 optional human_handoffs를 처리한다. HumanReviewChanges.record(JsonNode previous, ObjectNode next, String actor, Instant at, String reason)는 실제 diff와 과거 기록을 보존한다. validate(previous,next,boolean generatedHandoff)는 새 빈근거 허용을 제한한다; 기존2인자 메서드는 false로 위임한다.

- [ ] private partial/null/중복/부분 시간·빈 사건·근거0와 기존 strict 승인, 과거 audit/인용 보존·새 허위/빈근거 거부 시험을 먼저 작성한다.
- [ ] 해당 새 동작이 없는 RED를 관찰한다.
- [ ] optional 참조를 private Event payload에 보존한다. private needs_review만 partial facts를 허용하고 approved facts는 기존 strict로 검사한다.
- [ ] record는 실제 이전/다음의 coarse fields와 전체 배열을 비교하고 actor/now/reason을 사용한다. 과거 기록은 prefix 그대로 보존하며 새 인용은 이전/다음 근거만 허용한다.
- [ ] PublicationContent.validate가 참조를 envelope와 반환 Event에 보존하고 공개 snapshot에는 내보내지 않는지 확인한다.
- [ ] 기존 reader/감사/공개 단위 시험과 새 대상 GREEN 후 담당 파일만 커밋한다.

### Task 3: 실제 import·D05/D03·공개 연결

**Interfaces:** HumanHandoffImportService가 명시 request를 이미지/현재 DB와 대조해 Task2 batch를 준비한 뒤 기존 ReviewedImportService에 전달한다. ExtractionImportService.verifyReferences(ReviewedBatch)와 기존 List<Event> overload는 Task1 증거를 사건별로 확인한다. ExtractionRunRepository의 handoffParentDirectory/verifiedHandoffParent는 검증한 VerifiedHandoff만 받는다. Reference에는 optional documentRowSha256을 보존한다.

- [ ] 무작위 synthetic D03/run과 실제 Python review/handoff를 준비하고 성공/failed/manual·숨김 저장·재사용·빈 사건·충돌·보호된 좌표 시험을 작성한다.
- [ ] adapter 부재/검증 누락의 실제 RED를 관찰한다.
- [ ] local-import의 새 request schema를 분기한다. 정확한 사건 매핑/expected 번호·reason을 검사하고 reviewer/time은 actor/실제 MICROS로 기록한다.
- [ ] 기존 raw 또는 이전 인계 사실과 같은 비공개 revision만 자동 투영한다. 보정/승인/반려한 기존 revision은 conflict로 보존한다. 과거 proof/audit는 이어 붙이고 전용 실제 diff만 빈근거를 허용한다.
- [ ] 원래 D05 경로·행/status/mode/receipt와 full D03 metadata/hash/private_ref를 대조한다. 사건별 proof 권한은 캐시 전에 확인한다. 재사용·중복 복구도 트랜잭션 안에서 D03/D05 fingerprint를 검사한다.
- [ ] 배치 결과에 sourceRun/proof를 보존하며 verifyDraft는 ai-draft-import-v1에만 실행한다. 빈 사건은 기존 사건을 바꾸지 않는다.
- [ ] 실제 격리 MySQL8.4.13에서 동시 동일 입력·상충 revision·늦은 INSERT rollback·DB/원본 변조/복원·후속 수동 수정·승인/preview/publish·반려/복구·공개 불변/비노출을 검증한다.
- [ ] build.gradle 시험 입력에 processing/evaluation/**/*.py를 추가하고 실제 JAR 명령/오류·profile guard를 확인한다.
- [ ] contracts/human-handoff.md, backend 문서/README/TASK, processing/TASK와 관련 설계를 구현 범위에 맞게 갱신한다. Python projection 자체의 기존 summary는 projection-only 의미를 유지한다.
- [ ] 전체 Python/Java·Node/JSON/lint/build와 전체 자체 리뷰, 별도 전체 리뷰를 실행한다. 유효 지적은 모두 수정·검증하고 PR→정확 head CI/자동/새 사람 리뷰→develop 병합까지 진행한다. main은 사람이 진행한다.

## Plan Self-Review

입력·원본 전체/빈 사건·보호된 기존 수정·감사/인용·D03/D05 재사용·failed 제한·공개/복구·비노출·실제 DB/JAR 검증을 위3개 task에 대응했다. Task1의 참조 타입을 Task2/3이 소비하고 Task2의 batch/감사 API를 Task3이 사용한다. 구조 선택·추가 판단은 전용 ledger에 비용과 함께 기록한다.
