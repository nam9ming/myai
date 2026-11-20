# D08 입력·실행 연결 검사 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. 기존 연속 실행 지시에 따라 native로 구현하고 마지막에 전체 변경을 독립 리뷰한다.

**Goal:** 동결한 manifest의 모든 문서 버전을 실제 입력 바이트·별도 읽기 전용 D05 보관본에 연결하고 실패/복수 실행을 중복 문서로 집계하지 않는다.

**Architecture:** 기존 manifest 보관 검증과 extraction 원본 재검증을 재사용한다. 연결 명세의 원본 SHA와 manifest/receipt SHA를 반환하는 읽기 전용 검사이며, 별도 금표·채점·실행 선택 잠금은 후속 평가 단계에서 이 해시를 고정한다.

**Tech Stack:** Python3.13 표준 라이브러리, unittest. 외부 의존성 없음.

**Spec:** `docs/spec/03_데이터와AI.md` D03/D05/D08, `docs/spec/05_시험과인수기준.md` B, `contracts/dataset-manifest.md`, `contracts/extraction-run.md`.

## Global Constraints

- Java21·Spring Boot3.5.x·MySQL8.4·Flutter 계약과 기존 extraction 원본은 변경하지 않는다.
- 실제 문서40/dev20/holdout20 목표, 독립 원문 판독 금표, 8필드 분모·누락/생성 오류·최초/재시험 요구를 유지한다. 이번 연결 검사를 평가 완료로 표시하지 않는다.
- 입력8MiB·깊이100, 중복 키/잘못된 Unicode 거부, CLI stdout 안전한 JSON 한 건·stderr 고정 코드.
- 원문/프롬프트/경로·키를 출력하지 않는다. 키·네트워크·AI·DB·freeze 쓰기를 호출하지 않는다.
- 모든 manifest 버전을 정확히 한 번 연결하고 버전마다 하나 이상 명시 선택한 D05 실행을 제공한다. 자동으로 성공 실행만 고르지 않는다.
- 기존 사용자 `.gitignore` 변경과 기존 AGENTS.md를 보존한다. 커밋 제목/본문은 영어 Conventional Commits, PR은 한국어, main은 사람이 병합한다.

## Review Focus

1. manifest 검증 뒤 다른 바이트를 읽어 연결하는 경합: 실제 읽은 manifest도 고정 hash와 대조한다(Task1).
2. 같은 버전ID지만 개행/공백/종류가 다른 입력: raw SHA와 data_kind까지 일치해야 한다(Task1).
3. 정상 receipt를 제공한 다른 실행·수정 원출력·확장된 권한: 원본 재검증과 정확0400/0500 확인(Task1).
4. 빠진 버전·중복 실행·경로 탈출/심볼릭 링크: 일부 성공 집계를 반환하지 않고 실패한다(Task1).
5. 실패/여러 시도를 버리거나 raw 내용을 CLI에 노출: 첫/최종 상태·실행 수를 분리하고 실제 subprocess로 검사한다(Task2).

### Task 1: 입력·D05 연결 검사

**Files:** Create `processing/evaluation/bindings.py`, `processing/tests/test_dataset_bindings.py`.

**Interfaces:** consumes `_parse_manifest`, `verify_dataset`, `verify_run`, `_read_checked`, `_root`; produces `check_bindings(content: bytes, dataset_root=DEFAULT_ROOT, run_root=EXTRACTION_ROOT) -> dict`.

- [x] 합성 실제 archive/manifest로 검사를 호출하는 실패 시험 작성. 문서1·버전1·실행2(실패/성공), raw hash 불일치·빠진/중복 버전·run ID 재사용·등록 경로·권한·원본 변조를 검증한다.
- [x] `python3.13 -m unittest processing.tests.test_dataset_bindings -v`: 새 모듈 부재로 RED 확인.
- [x] `dataset-bindings-v1`의 정확 키·참조와 모든 원본을 검증하는 최소 구현. 각 실행의 first/final 상태는 보관 receipt에서 도출하고 raw/메타데이터 전문은 출력하지 않는다.
- [x] 동일 시험 GREEN 후 전체 Python·npm lint/test/build 실행. Expected: 전부 성공.
- [x] `feat: verify dataset source and run bindings` 커밋.

### Task 2: CLI·계약·실제 개발 연결 확인

**Files:** Modify `processing/evaluation/__main__.py`, `processing/README.md`, `processing/TASK.md`, `contracts/README.md`, `docs/spec/03_데이터와AI.md`; Create `contracts/dataset-bindings.md`. Test `processing/tests/test_dataset_bindings.py`.

**Interfaces:** Task1 `check_bindings` → `check-bindings --input FILE [--dataset-root ROOT] [--run-root ROOT]`.

- [x] 실제 subprocess의 성공/입력2/보관3/I/O5·경로/본문 비노출 시험 작성·RED 확인.
- [x] 기존 CLI 오류 처리에 명령을 추가하고 명세·입출력 예시·제한을 문서화한다.
- [x] 실제 개발3건의 v1 실패/v2 성공6개 기존 frozen D05를 연결한 비공개 명세를 생성·검증한다. Expected: 문서3·버전3·실행6·실패3·성공3, 파일/DB/AI 원본 변경 없음. 이것을 gold/채점/재시도 정책 입증으로 표시하지 않는다.
- [ ] 전체 Python·npm lint/test/build, 전체 자체 리뷰·한 번의 fresh 전체 리뷰·유효 지적 수정 후 PR CI/자동 리뷰 확인. Expected: 유효 미해결0.
- [ ] `feat: expose dataset binding checks` 커밋 후 PR 제출. main 외 승인된 기준 브랜치만 병합한다.
