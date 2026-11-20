# D08 데이터셋·분할 고정 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 단계별 TDD·전체 자체 리뷰·별도 전체 리뷰1회를 수행한다.

**Goal:** 고정 문서 버전·사건 관계·개발/확인 배정표를 검증하고 비공개 불변 manifest로 보관한다.

**Architecture:** Python3.13 표준 라이브러리와 기존 strict JSON·UUID/시각·비공개 파일 보관 기능을 재사용한다. 문서 연결요소와 split_group_id를 대조하고 원본 manifest 바이트를 hash·읽기 전용 파일·원자적 배치로 고정한다. 입력 본문/금표/점수는 이번 manifest에 넣지 않는다. 실제 평가에서는 별도 원문/D05 hash 대조가 필요하다.

**Tech Stack:** Python3.13 표준 라이브러리. Java·DB·공개 API 변경 없음.

**Spec:** docs/spec/03_데이터와AI.md D03/D04/D08, docs/spec/05_시험과인수기준.md B·T17, 기존 사용자의 단계별 구현→리뷰→PR 반복 지시.

## Global Constraints

- 목표 실제40문서·개발20/확인20 유지. 그룹을 쪼개 숫자를 맞추지 않고 실제 수·부족분을 보고한다.
- 동일 문서의 복수 버전은 문서1개로 집계한다. 같은 사건/공유 문서/확정 관계는 같은 연결요소다.
- 의심 중복은 자동 병합하지 않고 분할 간 의심 중복과 노출 이력을 확인용 상태 경고로 남긴다.
- 금표·사용자 조건·AI 출력은 입력 manifest에서 거부한다. 합성 자료는 실제 실적으로 세지 않는다.
- 같은 dataset_version의 다른 바이트는 충돌이다. 기존 manifest를 바꾸거나 입력 본문을 보관했다고 주장하지 않는다.
- 기존 사용자 .gitignore 수정·AGENTS.md·비밀키·공유 서비스는 변경하지 않는다. 커밋/병합 커밋은 영어, PR 설명은 한국어다.

## Review Focus

- 같은 문서의 복수 버전·공유 문서·정정/재게시가 배정표에서 갈라지는 경우: 연결요소 전체 분할 거부.
- 의심 중복·노출 미상·그룹 검토 미완료: 자동 병합/비노출 확인용 판정 금지.
- 긴 정정 연결·사이클·고립 문서: 재귀 한도 없이 검사하고 모든 문서를 정확히 한 번 배정.
- 같은 버전의 동시 freeze·중단·변조·symlink: 기존 원본 보존·불완전 거부·완료 동일 바이트 재사용.
- 임의 키/잘못된 Unicode/크기 초과·버전 경로 문자열: 원문/경로/민감값을 stdout/stderr로 내보내지 않음.

## Task 1: manifest·연결요소 검증

**Files:** Create processing/evaluation/{__init__,dataset}.py, processing/tests/test_dataset.py, processing/examples/dataset-manifest.json, contracts/dataset-manifest.md.

**Interfaces:** validate_manifest(content: bytes) -> dict. dataset-manifest-v1의 documents(버전/입력 hash·URL·유형/특징·노출), events(문서/그룹/의심 중복), relations(D04), split_assignments(D08), grouping_review를 검증한다. 반환값은 고정 키·집계·hash·경고만 포함한다.

- [ ] 공유/간접 연결 분할·그룹 불일치·문서/버전 중복·미등록 참조·정정 사이클·노출/검토 경고·합성/목표 부족분·잘못된 JSON 시험을 작성한다.
- [ ] `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_dataset -v`: 미구현 RED 확인.
- [ ] union-find와 반복 위상 검사로 구현하고 같은 시험 GREEN 확인. 긴 연결1000건 회귀 포함.
- [ ] 기존 전체 Python 회귀를 실행하고 영어 Conventional Commit으로 저장한다.

## Task 2: 불변 보관·CLI·인계

**Files:** Create processing/evaluation/{storage,__main__}.py, processing/tests/test_dataset_storage.py. Modify processing/{README,TASK}.md.

**Interfaces:** freeze_dataset(input_path, root=DEFAULT_ROOT) -> dict, verify_dataset(dataset_ref, root=DEFAULT_ROOT) -> dict. 기본 root=data/private/evaluation/datasets. dataset_ref는 dataset_version UTF-8의 SHA-256이며 경로 문자열을 직접 사용하지 않는다. 고정 폴더에 manifest.json/identity.json/receipt.json을 원자적으로 배치하고0400/0500으로 봉인한다. identity가 원본 hash·크기·고정 시각을 보존하고 receipt를 재계산한다.

- [ ] 같은 바이트 재사용/다른 바이트 충돌·동시8·변조/쓰기권한/미완료·symlink·부분 배치 실패 보존·실제 CLI 성공/안전 오류 시험 RED 확인.
- [ ] 기존 파일 helper를 재사용해 구현한다. CLI는 check --input FILE, freeze --input FILE, verify DATASET_REF, 선택 --root ROOT다.
- [ ] 전체 Python·Node/JSON·lint·build 실행. 실제 개발3건은 dev만 선언한 manifest로 비공개 검증/고정하며 holdout·금표를 만들지 않는다.
- [ ] 새 별도 전체 리뷰1회·유효 지적 수정·회귀 후 PR 제출. 정확한 head CI·AI 유효 미해결0에서 하위 PR만 병합하고 통합 CI·main 미변경을 확인한다.
