# Human Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** frozen 사람 수정값의 D06 사실 투영과 전체 출처를 독립 인계 이미지로 보존한다.

**Architecture:** 기존 draft의 검증·순수 투영을 분리해 재사용하고 human_handoff가 정확한 review/부모와 연결한다. 별도 동결기/CLI를 만들며 Java 실제 revision 연결은 다음 전체 목표 단계다.

**Tech Stack:** Python3.13 stdlib/unittest·기존 POSIX 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-human-handoff-design.md`

## Global Constraints

- JSON8MiB/깊이100·키/AI/외부 네트워크/DB/새 의존성 없음. 파일0400/디렉터리0500·배타 설치·덮어쓰기 금지.
- 기존 AI draft 결과 바이트·Java/공개 API·승인 정책 유지. projection_only/backend_import_supported=false, 실제 DB revision·human_overrides·승인·좌표 확정 생성 금지.
- source/review/부모·실패/미상·실제 변경 기록·전체 원본 보존. source D03 파일/권한 검증과 Java 연결은 후속 전체 목표.
- 사용자.gitignore/AGENTS 보존. 영어 Conventional Commit·한국어 문서. develop 대상 PR, main·배포 사람 담당.

## Review Focus

1. 실패 부모를 사람이 고쳐도 원래 실패·입력·receipt가 유지된다. Task1 시험.
2. 미상·중복·빈 사건/미사용 근거·반복/초·장소 대응과 source metadata가 손실/추측 없이 남는다. Task1 시험.
3. 실제 DB revision/승인/신원·D06 변경 기록을 투영이 만들거나 기존 import로 오인되지 않는다. Task1/2 시험.
4. 같은 부모 다른 review·다른 context·source mismatch/receipt·미래 시각을 구분하고 기존 AI draft 바이트를 유지한다. Task1 시험.
5. 원본 경로 제거·nested 변조/권한/symlink·native 경합·복사 변경/I/O 실패에도 원본과 목적지를 보존한다. Task2 시험.

### Task 1: 공통 투영 재사용·사람 수정 사실 투영

**Files:** Modify `processing/extraction/draft.py`; create `processing/evaluation/human_handoff.py`, `processing/tests/test_human_handoff.py`.

**Interfaces:** Existing _project_draft keeps old signature/bytes/order. New draft helpers _context(run_id,source,area_id,split_group_id,dictionary_version)→doc, _source(source,doc,document,metadata)→None, _project_output(run_id,source,extracted,area_id,split_group_id,dictionary_version,*,label='AI')→existing draft object. New project_handoff(content,review_root=REVIEW_ROOT,*,projected_at=None)→projection/summary/sources, _header and HANDOFF_ROOT feed Task2; sources prefix review/REF.

- [x] Capture prechange35a7f8e AI draft7cases and original archives/expected bytes under private evidence before runtime edits.
- [x] Write real frozen review/D03 fixture and tests for corrected/failed/manual parent, exact projection/refs/time/context/source, unknown/duplicates/empty/seconds, no workflow/false review metadata, privacy/default routing/result bound and old bytes.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_handoff -v`; Expected: missing handoff module RED.
- [x] Extract helpers retaining old draft validation order/bytes; project only verified corrected output and preserve original full review sources.
- [x] Run target+old draft tests, prechange7draft/7evaluation outputs+2initials, fullPython; Expected: GREEN.
- [x] Commit `feat: project human review handoff facts`.

### Task 2: 전체 인계 이미지·CLI·계약

**Files:** Create `processing/evaluation/handoff_storage.py`, `processing/tests/test_human_handoff_storage.py`, `contracts/human-handoff.md`; modify evaluation/__main__.py, contracts/README.md·human-review.md, processing/README.md·TASK.md, backend/docs/ai-review-draft.md, backend/src/test/java/kr/ac/myai/backend/ReviewedImportReaderTest.java, docs/spec/03_데이터와AI.md.

**Interfaces:** Consumes Task1 projection/summary/sources and house _tree/_sealed/_copy/_identity/_rename_exclusive. Produces freeze_handoff(input_path,root=HANDOFF_ROOT,review_root=REVIEW_ROOT), verify_handoff(handoff_ref,root=HANDOFF_ROOT), check/freeze/verify-handoff with0/2/3/5. Frozen replay uses directory/review and original projected_at.

- [x] Test full review/parent image copy, no-original-path/reuse/conflict, native races, nested tamper/modes/symlink/extra, copy change/partial destination/install failure cleanup, real CLI0/2/3/5/privacy and current Java rejecting unsupported projection format.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_handoff_storage -v`; Expected: missing storage/CLI RED.
- [x] Implement with house helpers and document exact selection/projection/receipt/context/limits·Java next-stage boundary in Korean.
- [x] Run targets/fullPython/npm lint/test/build, legacy helpers and whole self-review; Expected: GREEN.
- [x] Commit `feat: freeze human handoff provenance`.

## Final integration

- [ ] One fresh whole-branch review; all valid findings inclminor fixed/verified, unresolved0 before PR develop.
- [ ] Exact-head CI/AI/new human review loop, authorized develop merge/integration verification and evidence/rulings report. Cleanup only own workspace, keep full goal active for Java ingestion and remaining real-data/engine tasks.
