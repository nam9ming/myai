# Rule Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 고정 프로필의 오프라인 규칙 추출과 실패를 포함한 불변 실행 원본을 제공한다.

**Architecture:** 순수 규칙 함수가 extract-schema-v1 바이트를 생성하고 전용 rules-run-v1 보관기가 입력/프로필/출력을 묶는다. 기존 AI D05 소비 경로와 분리하며 기존 8필드 채점 함수를 재사용한다.

**Tech Stack:** Python3.13 표준 라이브러리, unittest, 기존 POSIX 배타 보관 helper.

**Spec:** `docs/superpowers/specs/2026-11-03-rule-baseline-design.md`

## Global Constraints

- 키·AI·네트워크·DB 호출 없음, 새 의존성 없음.
- 입력/프로필/출력 각각8MiB, 기존 JSON 깊이100·UTF-8·중복 키 검증.
- private root·파일0400/디렉터리0500·배타 설치·원본 덮어쓰기 금지.
- 기존 공개 API/DB/AI D05 형식과 사용자 `.gitignore` 변경 보존.
- 영어 Conventional Commit, 한국어 문서, main 병합은 사람 전용.

## Review Focus

1. 게시일/연도 없는 날짜·복수 일정에서 값이 발명되지 않는지 Task1 시험.
2. 사전 별칭 충돌·주소 미기재·키워드 중복에서 결정성이 유지되는지 Task1 시험.
3. UTF-8/emoji 근거 위치·8MiB 초과 실패가 조용히 잘리지 않는지 Task1/2 시험.
4. 원본 경로 제거·다른 바이트 재사용·권한/파일 변조를 Task2에서 거부하는지 시험.
5. 동시 배치·rename 실패가 기존 원본을 덮어쓰거나 잔여 완성본을 노출하지 않는지 Task2 시험.

---

### Task 1: 고정 프로필과 순수 규칙 추출

**Files:** Create `processing/extraction/rules.py`, `processing/tests/test_rules.py`, `processing/examples/rule-profile.json`, `contracts/rule-baseline.md`.

**Interfaces:** Consumes `parse_input(bytes)`, `parse_output(bytes,document)`, `score_document(...)`. Produces `parse_profile(content:bytes)->dict`, `extract_rules(input_bytes:bytes,profile_bytes:bytes)->tuple[bytes,str|None]`, `RULE_VERSION='rule-extract-v1'`.

- [x] Write tests for strict profile, three types, explicit/full/partial/conflicting dates and clocks, overnight/all-day, known-empty exceptions, aliases, Unicode evidence, deterministic output, output budget, unchanged 8-field denominator.
- [x] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_rules -v`; Expected: missing rules implementation RED.
- [x] Implement the pure functions and document exact supported patterns/limits; do not use evaluation answers to choose values.
- [x] Run the same command; Expected: all pass, including honest partial baseline score.
- [x] Commit `feat: add deterministic rule extraction`.

### Task 2: 불변 규칙 실행 원본과 CLI

**Files:** Create `processing/extraction/rule_runs.py`, `processing/tests/test_rule_runs.py`; modify `processing/extraction/__main__.py`, `processing/README.md`, `processing/TASK.md`, `contracts/README.md`, `docs/spec/03_데이터와AI.md`.

**Interfaces:** Consumes Task1 functions unchanged. Produces `run_rules(input_path,profile_path,preprocessing_version,root=RULE_ROOT,run_id=None)->dict`, `verify_rules_run(run_id,root=RULE_ROOT)->dict`; CLI `rules-run`/`rules-verify`.

- [ ] Write tests for successful/failed run preservation, same-ID reuse/conflict, deleted source path, offline verify, changed metadata/output/profile, permissions/symlink/extra files, concurrency, failed install, AI-format isolation, actual subprocess stdout/error/exit codes.
- [ ] Run `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_rule_runs -v`; Expected: missing rules-run implementation RED.
- [ ] Implement exact six-file image and safe receipt using existing I/O/rename helpers; wire CLI and Korean guides/status.
- [ ] Run the same command and full Python suite, `npm run lint`, `npm test`, `npm run build`; Expected: all pass.
- [ ] Commit `feat: preserve immutable rule runs`.

## Final integration

- [ ] Whole-branch self-review, one fresh independent review, valid finding RED→GREEN fixes and full regression; unresolved0 before PR to develop.
- [ ] Exact-head CI/AI review and arriving human reviews; fix valid findings until0, merge only into develop when green, report concrete evidence/limitations and proceed to D08 adapters.
