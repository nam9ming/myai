# Human Review Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** AI 원본과 사람 수정후 값·실제 변경/검토 시간 선언을 분리 검증·불변 보관한다.

**Architecture:** 기존 D05/출력 검증·hash 복사·tree 검사·배타 rename을 재사용한다. 별도 human-review archive를 만들고 기존 evaluation CLI로 check/freeze/verify한다.

**Tech Stack:** Python3.13 stdlib/unittest, 기존 POSIX 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-human-review-archive-design.md`

## Global Constraints

- JSON8MiB·깊이100·POSIX0400/0500·배타 설치·원본 덮어쓰기 금지.
- 키/AI/네트워크/DB 호출·새 패키지 없음. 기존 AI/규칙 평가·보관 형식/바이트 변경 없음.
- 실제 사람/독립 gold/40건 성능/승인 기록을 생성하지 않는다. D06 역변환·채점/세 방법 비교는 후속 전체 목표.
- 사용자 .gitignore 보존, 커밋 영어 Conventional·문서 한국어, PR develop/main 사람 전용.

## Review Focus

1. 실패·수동 D05를 정상 API/사람 승인으로 바꾸지 않는지 Task1에 시험.
2. before/after의 true=1 등 타입 혼동·가짜/겹친 변경 기록 우회를 Task1에 시험.
3. 나노초·소스 기록 이후·미래/역전 시각·basis 선언이 정확한지 Task1에 시험.
4. 원본 경로 제거/복사 중 변경/동시 동일·상이 입력/부분 목적지에 원본이 보존되는지 Task1에 시험.
5. import cycle·CLI stdout/오류의 실제 값/검토자/경로 유출과 legacy 명령 회귀를 Task2에 시험.

### Task 1: 수정 원본·이력 검사와 전체 이미지 보관

**Files:** Create `processing/evaluation/reviews.py`, `processing/tests/test_human_reviews.py`.

**Interfaces:** Consumes unchanged verify_run/_frozen/parse_output/_copy/_identity/_rename_exclusive/instant_ns; lazy imports existing evaluation_storage._tree to avoid future records dependency cycle. Produces check_review(content,run_root=EXTRACTION_ROOT,*,checked_at=None), freeze_review(input_path,root=REVIEW_ROOT,run_root=EXTRACTION_ROOT), verify_review(review_ref,root=REVIEW_ROOT). Public functions return safe summary/receipt only.

- [x] Write meaningful tests for unchanged/changed/failed/manual source, exact original bytes and all source files, header/ref/hash/knowledge/evidence, strict actual changes/typed values/no-op/duplicate/overlap, time/basis, immutable replay without sources, corruption/modes/extra/symlinks, conflicts/concurrent/native install failure/source mutation.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_reviews -v`; Expected: missing module is RED, then each behavior must pass after implementation.
- [x] Implement minimal strict review validation and source/image freeze/replay using house helpers; preserve actual original and reviewer/time declarations privately.
- [x] Run target and existing evaluation/rule suites; Expected: GREEN, no original artifacts changed.
- [x] Commit `feat: preserve human review source archives`.

### Task 2: CLI·한국어 계약·전체 인계

**Files:** Modify `processing/evaluation/__main__.py`, `contracts/README.md`, `processing/README.md`, `processing/TASK.md`, `docs/spec/03_데이터와AI.md`; create `contracts/human-review.md`, `processing/tests/test_human_review_cli.py`.

**Interfaces:** Consumes Task1 public functions and REVIEW_ROOT. Produces CLI check-review/freeze-review/verify-review with existing safe exit conventions; legacy defaults unchanged.

- [x] Write real subprocess check/freeze/verify/reuse/input2/archive3/IO5 tests with safe stdout/stderr and source deletion replay.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_review_cli -v`; Expected: unknown command/input2 RED.
- [x] Add CLI commands and concise Korean input/examples/limitations; no fabricated human/API/D06/evaluation claims.
- [x] Run target, full Python suite, npm lint/test/build and preserved legacy4 byte/frozen initial verifier; Expected: GREEN.
- [x] Commit `feat: expose private human review commands`.

## Final integration

- [ ] Whole self-review and one fresh whole-branch independent reviewer, all valid findings fixed/retested; user zero-unresolved rule includes minor documentation findings.
- [ ] PR develop after native gates; exact-head CI/AI/new human review loop, authorized develop merge and integration verification. Preserve evidence/all rulings, cleanup only this workspace; full goal active.
