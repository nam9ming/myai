# Notice Input Preparation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 신규 공지44개의 D03·AI 입력을 실제 수신 원본과 연결해 준비·검증한다.
**Architecture:** 형식별 본문 선정은 병렬 수행하고 공통 비공개 변환기·기존 Java Reader/Python prepare는 부모가 실행한다. 제품 API·계약·의존성은 바꾸지 않는다.
**Tech Stack:** Python3.13 표준 라이브러리·기존 추출 모듈, Java21·기존 앱 클래스/JAR.
**Spec:** docs/superpowers/specs/2026-11-04-notice-input-preparation-design.md

## Global Constraints

- 대상44개 전부 추적. 기존3건·원래 intake255파일·AGENTS·사용자.gitignore 보존. 원문·키/D09·검토 기록 Git 금지, 부모만 Git.
- raw 복사는 bytes/SHA 그대로, NFC/LF/비식별화는 선정 본문·제목에만 적용. 전화/이메일 제거값 로그 금지. 날짜·노선·금액·미상은 추정/수정하지 않는다.
- D03 23키/AI 입력5키 유지, pending/unchecked·빈checks·null확인시각. 신규 안정UUID/버전1, 기존3건/별칭/검색전용 제외.
- private0600/0700·새 파일 no-clobber·8MiB·일반 파일/경로 경계. 외부 추출 API·로컬 키·DB·사람/분할/gold·main/배포는 후속.

## Review Focus

1. 제목/목록/footer/ALT가 본문으로 둔갑하거나 이미지·첨부 미확인을 숨기는가 — 원문 선정 전후 근거·보류를44개 모두 대조.
2. 비식별화가 날짜·시간·노선·금액을 바꾸거나 연락처 값을 로그에 남기는가 — 실제 치환 범위와 회귀 대조.
3. NFC/LF 정리로 raw가 바뀌거나 D03/AI 블록·hash가 어긋나는가 — 원본 hash·전체 투영·실제 Reader/parse_input 대조.
4. 별칭/기존3개에 새ID를 붙이거나 재실행이 다른 파일/등록본을 덮는가 — 신규44집합·안정ID·no-clobber·경로 검증.
5. 부분 실패·준비 receipt를 실제 호출/DB/사람 승인/40·20·20 성과로 과대 표시하는가 — receipt는 최종검증 뒤, 미확정 조건 유지.

### Task 1: 본문 선정·공통 변환

**Files/Owner:** private 새 root의 `selections/direct.json`(13개), `html.json`(13개), `markdown.json`(18개)은 각 worker. 부모 `prepare_inputs.py`, `test_prepare_inputs.py`, `package/` 산출물.
**Interfaces:** 선정 JSON은 `records` 배열; 각 항목 `identity,evidence_path,evidence_sha256,source_field,selection_method,selected_text,selected_text_sha256,flags,notes`. 부모만 NFC/LF·고정 연락처 치환·블록·D03/AI 파일을 생성한다.

- [ ] 선정은 실제 본문13/13/18을 정확한 증거 경로·hash·선정 범위에 연결. 추가/미확인 의미값 생성 금지, 보류도 대상에 포함.
- [ ] 먼저 `normalize_text`, `redact_contacts`, `make_blocks`, `stable_ids`와 no-clobber의 작은 실패 시험을 작성·실행한다. Expected: 누락 동작의 실제 RED.
- [ ] 최소 변환 구현 후 같은 시험을 실행한다. Expected: NFC/LF·제거값 없는 로그·날짜/노선 유지·빈/제목대용 거부·안정 ID·충돌 시 원본 불변 GREEN.
- [ ] 선정 원본과 실제44건 파일을 생성·대조한다. Expected: 원본 raw/input/manifest 불변, rawcopySHA·새UUID44·pending/unchecked·23/5키·전체 블록 투영 일치. 본문 부족은 해결 전 성공으로 표시하지 않는다.

### Task 2: 기존 Java/Python 경로의 실제 검증

**Files/Owner:** 부모 private `validation/ValidatePreparedSource.java`, 고정 로컬 JAR 의존성 복사·실제 Reader/prepare 로그·receipt. 제품 클래스 수정 없음.
**Interfaces:** Task1 source-import.json/source-root와 inputs/*.json을 기존 `ReviewedImportReader.read`, `parse_input(bytes)`, `prepare(path, root)`가 소비한다.

- [ ] Java21 `classes`와 기존 JAR/클래스 hash를 확인하고 Reader만 호출한다. Expected:44문서·real/source-import-v1·이벤트0; DB/웹 시작 없음.
- [ ] raw/text hash를 바꾼 새 음성 복사본은 거부하고 원래 배치를 재검증한다. Expected: 실제 실패 대조군 후 원본44 GREEN.
- [ ] AI 입력44개를 parse_input·기존 prepare로 처리하고 input/prompt hash·D03 전체 블록/metadata를 대조한다. Expected:44실제 prepared, source/API/DB/gold 상태는 별도 미실행.
- [ ] private 단위 시험·Python 전체·기존 Node/계약/lint/build를 실행한다. 무거운 작업은 순차. Expected: 실제 terminal PASS, 실패·생략을 숨기지 않는다.

### Task 3: 검토·PR·인계

**Files/Owner:** 부모 README/TASK의 실제 준비 현황과 private 보고·manifest·GitHub 증거. 원문/변환기·산출물은 private 유지.

- [ ] 작성자 전체 검토 후 새 문맥 전체 리뷰1회, 모든 유효 minor 포함 수정·실제 재검증. Expected: 유효 미해결0·보류0 전에 PR 제출하지 않음.
- [ ] source CI/자동 리뷰·새 사람 피드백을 확인하고 develop만 병합한 뒤 통합 gate·PR20 기록을 확인한다. Expected: 정확한 코드/나무 비교·모든 필수 gate 성공, main은 사람.
- [ ] 모든 Ruling/비용·실제 테스트·44개 원본/출력 대조를 비공개 evidence에 보존하고 이번 scratch만 정리한다. Expected: 원본255파일/기존3건 불변, 전체goal의 평가·사람·운영 조건은 유지.
