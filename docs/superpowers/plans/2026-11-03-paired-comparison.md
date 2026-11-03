# Paired Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 gold·원문·평가 회차의 세 방법을 필드별로 짝지어 개선·악화와 선언 검토 시간을 비교한다.

**Architecture:** 기존 frozen evaluation을 재검증해 비교하고 전체 세 원본을 별도 동결한다. 기존 scorer/records/evaluation_storage는 변경하지 않는다.

**Tech Stack:** Python3.13 stdlib/unittest·기존 POSIX 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-paired-comparison-design.md`

## Global Constraints

- 키/AI/네트워크/DB/새 의존성/공개 endpoint 없음. JSON8MiB/깊이100·POSIX0400/0500·배타 설치·덮어쓰기 금지.
- 사용자.gitignore/AGENTS 보존. 영어 Conventional Commit·한국어 문서. PR develop, main·배포 사람 전용.
- 실제40/독립 gold/사람 신원/노동시간/선별 성능을 합성 검증으로 인증하지 않는다. 기존 평가 결과·원본 바이트 유지.

## Review Focus

1. 비슷한 정답·같은 점수라도 다른 gold/입력/회차/부모면 비교를 거부한다. Task1에 시험.
2. 문서/슬롯의 순서·로컬 ID 차이가 대응을 바꾸거나 일부 필드만 선택하지 못한다. Task1에 시험.
3. 실패·누락·gold 미상·생성 미확정·개선과 악화 상쇄가 분모와 상세에 남는다. Task1에 시험.
4. retest/노출 차이·재사용 검토 시간을 새 성능·노동 감소로 오해시키지 않는다. Task1/2에 시험.
5. 원래 경로 제거·nested 변조·복사 변경·native 경쟁·I/O 실패에도 전체 출처와 기존 원본을 보존한다. Task2에 시험.

### Task 1: 동일 원본 검증·짝지은 필드 비교

**Files:** Create `processing/evaluation/comparison.py`, `processing/tests/test_paired_comparison.py`.

**Interfaces:** Consumes verify_evaluation/_collect/_aggregate and frozen evaluation result/receipt. Produces compare_evaluations(content, evaluation_root=EVALUATION_ROOT, *, compared_at=None) → result/sources packet, strict _header and COMPARISON_ROOT for Task2. sources prefix evaluations/REF includes every file of each original evaluation.

- [x] Write real archive fixture for all three methods with unique evaluation IDs. Test hand-counted transitions/fields/splits, first/final/failure/unknown/pending, strict method/hash/gold/phase/parent/clock/coverage, order independence and declared time/privacy.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_paired_comparison -v`; Expected: new comparison function missing, RED.
- [x] Implement strict source revalidation/identity pairing and deterministic three-pair summaries; cap canonical result8MiB. Do not edit existing scorer/records/storage.
- [x] Run target and fullPython plus existing prechange compatibility helper; Expected: GREEN.
- [x] Commit `feat: compare paired extraction methods`.

### Task 2: 전체 비교 보관·CLI·문서

**Files:** Create `processing/evaluation/comparison_storage.py`, `processing/tests/test_paired_comparison_storage.py`, `contracts/extraction-comparison.md`; modify `processing/evaluation/__main__.py`, `contracts/README.md`, `contracts/extraction-evaluation.md`, `processing/README.md`, `processing/TASK.md`, `docs/spec/03_데이터와AI.md`.

**Interfaces:** Consumes Task1 result/sources and existing _tree/_sealed/_copy/_identity/_rename_exclusive. Produces freeze_comparison(input_path, root=COMPARISON_ROOT, evaluation_root=EVALUATION_ROOT), verify_comparison(comparison_ref,root=COMPARISON_ROOT), and check/freeze/verify-comparison CLI with0/2/3/5.

- [ ] Test full nested sources/initial copy, no-original-path/reuse/conflict, native same/conflict races, tamper/modes/symlink/extra, source-copy mutation/install failure cleanup, actual CLI success/input/archive/I/O and privacy.
- [ ] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_paired_comparison_storage -v`; Expected: missing storage/CLI RED.
- [ ] Implement using house helpers, preserving original source images and existing CLI behavior. Document exact schema/outputs/limits/current real-data status in Korean.
- [ ] Run both targets, fullPython, npm lint/test/build, legacy compatibility and whole self-review; Expected: GREEN.
- [ ] Commit `feat: freeze paired comparison evidence`.

## Final integration

- [ ] One fresh whole-branch review; reproduce/fix all valid findings inclminor, full self-review and unresolved0 before PR develop.
- [ ] Exact-head CI/AI/new human review loop; authorized develop merge and current integration verification. Preserve evidence and report every ruling/cost before cleaning only this workspace. Full goal remains active.
