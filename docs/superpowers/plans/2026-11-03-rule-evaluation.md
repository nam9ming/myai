# Rule Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 명시한 rules 원본을 기존 D08 채점·최초/재시험 불변 보관에 연결하고 AI 자동 평가와 구분한다.

**Architecture:** records의 엄격한 정책/원본 분기를 추가하고 공통 내부 attempt packet과 기존 scorer/보관기를 사용한다. AI의 기존 결과 바이트는 유지하며 method별 기본 run root만 선택한다.

**Tech Stack:** Python3.13 stdlib/unittest·기존 POSIX 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-rule-evaluation-design.md`

## Global Constraints

- 키·AI·네트워크·DB 호출·새 의존성 없음. 공개 API/DB·출시한 규칙 알고리즘 변경 없음.
- 기존 AI 선택/결과/보관본 재검증 바이트 유지, 실제 평가·검토 신원 인증으로 표현하지 않음.
- JSON8MiB/깊이100·정확한 source hash·파일0400/디렉터리0500·배타 설치·원본 덮어쓰기 금지.
- 사용자 `.gitignore` 변경 보존. 영어 Conventional Commit·한국어 문서. PR 대상 develop, main/배포는 사람 전용.

## Review Focus

1. method와 source 형식/registered 경로를 섞어 AI 성능을 주장할 수 없는지 Task1 시험.
2. profile hash·검토/고정 선언·실행 시각·피드백 출처가 충돌하면 거부하는지 Task1 시험.
3. 실패/미상/첫 최종 동일 annotation에서 분모와 생성 N/A가 유지되는지 Task1 시험.
4. 기존 AI 성공/실패/재시도/재시험 결과와 동결본 바이트가 유지되는지 사전 private fixture·Task1/2 시험.
5. 원래 경로 제거·동시 충돌·메타데이터 변조·실제 CLI가 규칙 전체 출처를 검사하는지 Task2 시험.

---

### Task 1: 규칙 정책·원본·채점 연결

**Files:** Modify `processing/evaluation/records.py`; create `processing/tests/test_rule_evaluation.py`.

**Interfaces:** Consumes unchanged `verify_rules_run`, `score_document`, frozen gold. Produces `evaluate_record(content,gold_root=GOLD_ROOT,run_root=None,initial_root=EVALUATION_ROOT,*,evaluated_at=None)` with rules and legacy ai_auto; internal packets carry attempts without mutating original receipt.

- [x] Capture pre-change synthetic AI success/failure/retry/retest result bytes and frozen initial in ignored private evidence; verify their source before using them as compatibility evidence.
- [x] Write strict rules policy/profile/input/receipt/method/time/feedback tests, successful/failed scoring and AI-only M02 gate; preserve explicit manual event/occurrence links.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_rule_evaluation -v`; Expected: rules rejected by old header, RED.
- [x] Implement conditional policy/source handling and common internal attempt access; preserve existing AI result shape/values exactly and test old private bytes unchanged.
- [x] Run the same tests plus existing record tests; Expected: all pass and legacy byte comparisons equal.
- [x] Commit `feat: score frozen rule extraction runs`.

### Task 2: 동결·재시험·CLI·인계

**Files:** Modify `processing/evaluation/evaluation_storage.py`, `processing/evaluation/__main__.py`, `contracts/extraction-evaluation.md`, `contracts/rule-baseline.md`, `contracts/README.md`, `processing/README.md`, `processing/TASK.md`, `docs/spec/03_데이터와AI.md`; create `processing/tests/test_rule_evaluation_storage.py`.

**Interfaces:** Consumes Task1 evaluate_record packets unchanged. Produces method-aware default source root for freeze/check and existing embedded source paths for verify; existing schema/CLI names/exit codes unchanged.

- [x] Write freeze/verify tests for full6-file source copy, original path removal, unchanged AI archives, retest policy/gold/source identity, cross-method initial rejection, collision/concurrency/corruption, and actual CLI stdout/error/exit codes.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_rule_evaluation_storage -v`; Expected: default routing/new source behavior RED.
- [x] Implement method-aware defaults and Korean contract/usage/status; keep stored source mode rules and no fabricated AI provenance.
- [x] Run both new test modules, full Python suite, npm lint/test/build, old compatibility fixture; Expected: all pass.
- [x] Commit `feat: freeze rule evaluation provenance`.

## Final integration

- [x] Whole-branch self-review, one fresh independent review; valid findings reproduced/fixed and whole regression green, unresolved0 before PR to develop.
- [ ] Exact-head CI/AI/arriving human review loop until valid unresolved0; authorized develop merge, integration verification, evidence/limitations report, next full-goal stage.
