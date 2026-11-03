# Human Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 사람 수정 원본을 D08 동일8필드·최초/재시험 불변 보관에 연결한다.

**Architecture:** 기존 records에 method별 source/시간/뷰를 추가하고 공통 scorer/동결기를 재사용한다. 실제 review와 parent D05를 구분하며 AI/규칙 결과 바이트를 유지한다.

**Tech Stack:** Python3.13 stdlib/unittest·기존 POSIX 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-human-evaluation-design.md`

## Global Constraints

- 키/AI/네트워크/DB/새 의존성 없음. JSON8MiB/깊이100·POSIX0400/0500·배타 설치·덮어쓰기 금지.
- human_reviewed는 별도 뷰/review_id이며 M02 N/A. 실제 사람/독립 gold/성능/승인 인증을 만들지 않는다.
- AI/규칙 선택·결과·동결본 바이트 유지. 명시 root/내부 root 우선·기존 CLI/check-bindings 기본값 유지.
- 사용자.gitignore/AGENTS 보존, 영어 Conventional Commit·한국어 문서, PR develop/main·배포 사람 전용.

## Review Focus

1. human 결과에 AI attempt/run metadata가 섞이지 않는지 Task1에 시험.
2. parent 입력/문서/data_kind/receipt와 review identity를 바꿔 선택을 우회하지 못하는지 Task1에 시험.
3. 최초 gold/parent/검토 시각과 피드백 선언, 재시험 same-ID 원본 교체를 Task1/2에 시험.
4. 금표 수정/새 검토·parent 재사용/원래 경로 제거에서도 최초 이미지와 분모가 유지되는지 Task2에 시험.
5. 기존 두 방법의 실제 결과 바이트/CLI와 native 경쟁·손상/실패 cleanup이 유지되는지 사전 fixture/Task2에 시험.

### Task 1: 사람 원본·시간·채점 연결

**Files:** Modify `processing/evaluation/records.py`; create `processing/tests/test_human_evaluation.py`.

**Interfaces:** Consumes verify_review/receipt artifacts and score_document. Produces existing evaluate_record packet with human_reviewed method, one view/review_ids/human_review_time and complete source mapping; default run_root=None routes REVIEW_ROOT only for human method.

- [x] Before editing runtime code, freeze pre-change7be AI4/rules3 canonical results and initial images under ignored evidence, remove original fixture paths and verify compatibility helper.
- [x] Write tests for human score/view/IDs/no fake attempts/time totals, failed parent/missing event denominator, strict policy/ref/hash/coverage/source input, initial parent/gold/basis clocks/feedback, default root and legacy bytes.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_evaluation -v`; Expected: old header rejects human_reviewed, RED.
- [x] Add minimal strict human source/time branch, method views/IDs and declared time summaries. Preserve both legacy methods byte-for-byte.
- [x] Run target plus existing AI/rule record tests and compatibility helper; Expected: GREEN.
- [x] Commit `feat: score frozen human review records`.

### Task 2: 동결·재시험·CLI·계약

**Files:** Create `processing/tests/test_human_evaluation_storage.py`; modify `contracts/extraction-evaluation.md`, `contracts/human-review.md`, `contracts/README.md`, `processing/README.md`, `processing/TASK.md`, `docs/spec/03_데이터와AI.md`; adjust storage/CLI only for demonstrated contract defects.

**Interfaces:** Consumes Task1 packet and unchanged freeze_evaluation/verify_evaluation. Produces full human+parent archive replay/retest and Korean usage/status, existing check/freeze/verify-evaluation commands.

- [x] Test entire source/initial copies, no-original-path/reuse/tamper/modes/symlink, gold correction preserving original, new review after initial/same parent, same review/parent ID conflict, cross-method/retest-chain rejection, native same/conflicting races/failure cleanup, real CLI0/2/3/5 and method default None boundaries.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_human_evaluation_storage -v`; Expected: newly exposed edge behavior RED where missing, fix at shared boundary only.
- [x] Document exact human selection/policy/view/IDs/declared time/initial/retest/M02/default roots and real-data limitations.
- [x] Run target, fullPython, npm lint/test/build and pre-change7method compatibility; Expected: GREEN.
- [x] Commit `test: verify frozen human evaluation records`.

## Final integration

- [ ] Whole self-review and one fresh whole-branch review; all valid findings inclminor fixed/verified, unresolved0 before PR develop.
- [ ] Exact-head CI/AI/new human review loop, authorized develop merge/integration verification and evidence/rulings report. Cleanup only this plan workspace; full goal remains active.
