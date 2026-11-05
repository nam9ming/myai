# 블록 근거 메타데이터·prompt-v2 실행 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 각 변경은 TDD로 확인한다.

**Goal:** 개발용 실제 공지3건에서 확인한 블록 hash 대응 오류를 줄이도록 입력 블록별 hash·문자 수를 제공한다. 기존 실행 원본과 검증 결과는 바꾸지 않는다.

**Spec:** docs/spec/03_데이터와AI.md D05·근거 검증·프롬프트 버전 고정, contracts/extraction-run.md, 사용자 요청의 실제 공지3건 추출.

**Architecture:** 수동 기본 prompt-v1의 바이트는 유지한다. API 신규 실행만 prompt-v2를 사용하고 archive 검증은 metadata의 버전에 따라 원래 요청을 재구성한다. v2는 원문에서 계산한 블록 ID별 SHA-256·Unicode code point 길이를 추가하고 전체 블록 인용 시 위치값 복사를 안내한다. 모델 출력의 hash·인용·위치를 자동 보정하지 않는다.

**Tech Stack:** Python3.13 표준 라이브러리, 기존 Java21 등록·전용 MySQL 시험.

## 경계·인터페이스

- PROMPT_VERSION=prompt-v1 유지, API_PROMPT_VERSION=prompt-v2 추가.
- render_prompt(document, version=PROMPT_VERSION), instructions(version).
- request_bytes와 check_api_attempt에 마지막 선택 인자 prompt_version을 추가한다. archive가 실제 metadata 버전을 명시한다.
- 기존 완료 v1 ID는 키·네트워크 없이 그대로 재사용한다. 미지원 버전은 검증 실패한다.
- 스키마·공개 API·의존성·DB migration·AGENTS.md 변경 없음. 기존3건은 개발용이며 정답/평가 자료가 아니다.

## Task 1: 버전 고정·블록 메타데이터

**Files:** processing/extraction/{prompt,api,archive}.py, processing/tests/test_extraction_{prompt_metadata,api}.py.

- [x] v1 고정 바이트·v2 블록 hash/길이·미지원 버전·API v1 재검증/재사용·v2 변조 거부 시험을 작성하고 RED를 확인한다.
- [x] 최소 구현 후 전체 Python·계약·Node·lint·build, 전용 MySQL 포함 Java179개·JAR를 확인한다.

## Task 2: 실제 개발 추출·인계·리뷰

**Files:** processing/{README,TASK}.md, contracts/extraction-run.md, docs/spec/03_데이터와AI.md.

- [x] 기존 v1 실제/합성 archive를 다시 검증한다. 개발용3건은 새 run_id로 v2 실행하고 성공·실패·원본·사용량을 모두 남긴다. 실패 시 의미 오류를 자동 반복/보정하지 않는다.
- [x] 검증 성공한 실행만 Java D05 등록·숨김 초안 파일에 연결한다. 실제 구역·사전이 미배정인 실자료 초안은 D06 DB에 저장하지 않는다. 사람 검토·승인·공개로 표시하지 않는다.
- [ ] 전체 자체 리뷰와 새 별도 전체 리뷰1회를 수행한다. 유효 지적은 재현→수정→회귀로 확인한다.
- [ ] PR의 정확한 head CI·자동 리뷰를 확인하고 유효 미해결0이면 하위 PR만 병합한다. 커밋·병합 커밋은 영어, PR 설명은 한국어다. main은 사람만 병합한다.

## Review Focus

- v1 원본/receipt/freeze가 코드 갱신 후 동일하게 재검증되는지.
- v2 메타데이터가 블록별로 정확히 대응하고 emoji·결합문자·개행의 길이를 Unicode code point로 세는지.
- 재시도에도 같은 원문·버전·메타데이터를 유지하고 위조 hash/offset을 그대로 거부하는지.
- 실제 실패 원본과 새 실행을 분리하고 실제 처리·검증·사람 승인을 구분하는지.
