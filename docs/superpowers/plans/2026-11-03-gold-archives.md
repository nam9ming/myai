# D08 독립 정답표 검증·동결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 기존 연속 native 실행 지시에 따라 구현하고 마지막에 한 번 전체 독립 리뷰한다.

**Goal:** 독립 원문 판독·교차 검토·사건 anchor·판정 지침·의견 차이 해결 기록을 검증하고 원문/manifest와 함께 별도 불변 보관한다.

**Architecture:** extract-schema-v1의 FieldValue/근거/occurrence 검증을 정답 자료 구조에도 재사용한다. 작성자/교차 검토자·독립 판독 선언은 기록일 뿐 실제 신원/의미 정확성 인증이 아니다. 기존 private I/O와 배타 rename을 사용해 gold.json·manifest.json·버전별 원본 input·identity·receipt를 고정한다.

**Tech Stack:** Python3.13 표준 라이브러리·unittest, 새 의존성 없음.

**Spec:** docs/spec/03_데이터와AI.md D03/D05/D08, docs/spec/05_시험과인수기준.md B, contracts/dataset-manifest.md, contracts/dataset-bindings.md.

## Global Constraints

- Java/공개 API/DB/기존 AI 원출력/AGENTS.md/사용자 .gitignore를 변경하지 않는다. 영어 Conventional Commits·한국어 PR·기능 PR 대상 develop·main 배포 기준/사람 병합(PR #20).
- 실제 AI 출력을 gold로 복사하지 않는다. 현재 실제3문서는 개발 노출 자료이며 실제 독립 정답을 새로 작성하거나 검토자 신원을 꾸미지 않는다. 자동 시험은 명시적인 합성 정답만 사용한다.
- 원본8MiB·깊이100, 엄격 JSON, Unicode code point 근거 검사. stdout 안전한 요약 JSON, stderr 고정 코드, 키/AI/네트워크/DB 호출 없음.
- 작성자와 다른 교차 검토자·검토 시각·미해결 의견 없음 선언·판정 지침을 요구한다. 모든 manifest 버전과 원본 바이트 hash를 연결한다.
- 사건 슬롯은 사람이 붙인 slot_id와 manifest event_id, 비어 있지 않은 독립 근거 anchor를 갖는다. AI 출력과의 매칭·8필드 점수·실행 선택 동결·최초/재시험은 후속 단계이며 전체 D08 목표를 유지한다.
- 파일0400/디렉터리0500, 같은 gold_version 다른 바이트/원본 충돌 거부, 검증 완료 staging만 배타 배치, 동일본 재사용, 원본 부재에서도 고정본 재검증.

## Review Focus

1. 실제 정답 독립성 선언을 기계 인증으로 오해하지 않도록 synthetic/real·문서화·요약을 구분한다.
2. 같은 slot_id의 잘못된 사건/문서·잘못된 anchor·누락/중복 버전을 거부한다.
3. manifest 검증 뒤 바뀐 바이트·input 공백/버전/data_kind 변경을 거부한다.
4. 작성/교차/해결 시각의 역전·미해결 의견·동일 작성자/검토자 선언을 거부한다.
5. 동시 충돌·권한 확대·symlink·새 원본 경로 부재·부분 설치에서 기존 버전과 원본을 보존한다.

### Task 1: 독립 정답표 계약·검사

**Files:** Create processing/evaluation/gold.py, processing/tests/test_gold.py, contracts/gold-archive.md.
**Interfaces:** check_gold(content:bytes,dataset_root=DEFAULT_ROOT)->dict; 내부 parse는 고정 manifest와 버전별 원본 bytes를 받아 같은 검증을 재사용한다.

- [x] 실제 합성 입력/manifest를 이용해 근거·slot/event 매핑·전체 버전·작성/교차/해결 기록·지침·미상/명시 빈값·JSON/비노출 시험 작성.
- [x] 새 모듈 부재 RED 확인 후 최소 검증 구현. Expected: 대상 시험 GREEN.
- [x] 전체 Python·npm lint/test/build 성공 확인 후 feat: validate independent gold records 커밋.

### Task 2: 불변 보관·CLI·인계

**Files:** Create processing/evaluation/gold_storage.py, processing/tests/test_gold_storage.py; Modify processing/evaluation/__main__.py, processing/README.md, processing/TASK.md, contracts/README.md, docs/spec/03_데이터와AI.md.
**Interfaces:** freeze_gold(input_path,root=GOLD_ROOT,dataset_root=DATASET_ROOT)->dict; verify_gold(gold_ref,root=GOLD_ROOT)->dict; CLI check-gold/freeze-gold/verify-gold.

- [ ] 원본 byte 보존/삭제 후 재검증·재사용/충돌·동시 실행·변조/권한·symlink/추가 파일·I/O 실패/부분 설치·실제 CLI 종료 코드 시험 RED 확인.
- [ ] 기존 private I/O·배타 rename으로 원본 묶음을 고정하고 검증/CLI/문서를 구현. Expected: 전체 시험 GREEN, 실자료 gold 생성 없음.
- [ ] 전체 자체 리뷰 및 fresh 전체 리뷰 한 번, 유효 지적 RED→GREEN 수정, PR CI/자동 리뷰 지적0 확인. feat: freeze independent gold archives 커밋과 PR 제출, 승인된 non-main만 병합.
