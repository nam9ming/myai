# AI 검토 초안 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 검증된 D05의 마지막 AI 출력을 원본·미상·근거를 보존한 숨김 검토 초안으로 생성하고 Java가 별도로 저장한다.

**Architecture:** 기존 freeze/hash/비공개 파일 설치와 import 트랜잭션을 재사용한다. `ai-draft-import-v1`은 기존 D04/D06 구조와 envelope에 originating_run_id를 추가해 사용하되 `origin=ai_draft`, `draft/hidden`, 검토자 null만 허용한다. 제목 null·유형 빈 배열은 이 미검토 단계에서만 허용하며 직접 승인할 수 없다. 사람은 원문을 대조하고 필요한 값·좌표·수정 이력을 작성한 `reviewed-import-v1`, `origin=ai_reviewed`의 다음 revision을 전달한다.

**Tech Stack:** Python3.13 표준 라이브러리, Java21·Spring Boot3.5.16·MySQL8.4.13. 새 의존성 없음.

**Spec:** `docs/spec/03_데이터와AI.md` D05/D06·extract-schema-v1, `docs/spec/09_DB설계와트랜잭션.md` raw/검토 import 분리, `processing/TASK.md` G06, `backend/docs/reviewed-import.md`.

## Global Constraints

- Java/Python만 구현. 공개 API·계산 규칙·기존 reviewed/source 규격·AGENTS.md·V1~V3 SQL을 바꾸지 않는다.
- 실제 AI/API·자료·검토·평가 실적을 합성 시험으로 대신하지 않는다. 모델·네트워크·DB 호출을 Python 초안 생성에 넣지 않는다.
- 미상 제목/유형은 null/[]로 두고, 좌표·지명 대응·반복 날짜·지역 소속·사람 검토를 추정하지 않는다.
- 출력은 비공개 경로의 UTF-8/LF JSON, 최대8MiB, 배타 생성·동일 바이트 재사용. stdout은 안전한 결과 JSON 한 건.
- 재실행 ID는 run UUID와 종류별 로컬 ID의 UUID5로 고정한다. 다른 실행의 사건 통합·정정·중복 판단은 사람이 수행한다.

## 설계 판단

기존 reviewed 규격에 빈 유형·미검토 AI를 허용하면 사람 검토 경계를 흐린다. 파일에서만 보류하면 기존 DB 검토 흐름과 연결되지 않는다. 따라서 새 로컬 schema와 origin으로 저장·승인을 구분한다. D06 초안은 확정 형식으로 승격하기 전까지 불완전 값을 허용하며 원래 FieldValue의 세부 사유는 불변 D05에서 보존한다.

AI 근거는 블록 hash를 먼저 검증한 뒤 D06의 문서 전체 hash로 변환한다. 장소 대응이 비어 있으면 독립 unknown 장소를 연결한다. 명시된 반복 문구는 날짜로 전개하지 않고 unknown·normalization_note로 보존한다. 확정된 연속 기간/종일/날짜만의 precision만 정규화한다.

## Review Focus

1. 같은 본문의 여러 블록·한글/emoji: 블록 hash와 전체 본문 hash, code point가 뒤섞이지 않는다.
2. 유형/제목/근거 없는 사건·NO_EVENT_FOUND: 허위 값 없이 숨김 저장하거나 빈 사건 배치를 보존한다.
3. 반복/부분 시간/초 단위·미상 장소 대응: 알려진 값을 보존하고 확정하지 못한 조건은 unknown이다.
4. 실패/변조/서로 다른 입력·동시 파일 생성: 원본과 기존 초안 파일을 보존하며 실패한다.
5. 직접 승인·위조된 검토 metadata·기존 공개 자료: raw 초안은 승인 불가, 사람 검토 다음 revision 이후에만 기존 승인 흐름 사용.

## Task 1: Python 초안 변환·CLI

**Files:** `processing/extraction/draft.py`, `__main__.py`, `processing/tests/test_extraction_draft.py`.

**Interfaces:** `draft_run(run_id, source_path, output_path, area_id, split_group_id, dictionary_version, root=DEFAULT_ROOT) -> dict`. source는 문서1개인 source-import-v1, output은 originating_run_id를 포함한 ai-draft-import-v1. freeze의 최종 validated 출력과 전체 D03 projection/전처리/data_kind가 같아야 한다.

- [x] RED: 합성 실행의 생성·재실행·원본 보존·UUID/근거 변환 시험을 작성하고 미구현 실패 확인.
- [x] 구현: UUID5·FieldValue 근거 ID 변환·nullable 제목/유형·uncertain lifecycle/지역·미검증 geometry·보수적 occurrence 정규화·배타 파일 생성. 실제 출력을 읽을 때도 hash 재검증.
- [x] 회귀: 미상/반복/HH:mm:ss/빈 사건·장소 대응 미상·실패/변조/입력 불일치·파일 충돌/동시 실행·공개 경로 거부·안전한 CLI 실패.
- [x] `python3.13 -m unittest processing.tests.test_extraction_draft -v` → 전부 통과. 관련 Python 전체도 통과 후 commit.

## Task 2: Java 숨김 저장·승인 경계

**Files:** `ReviewedImportReader.java`, `ReviewedImportRepository.java`, `PublicationService.java`, reader/MySQL 시험.

**Interfaces:** 기존 `read(Path, Path) -> ReviewedBatch`, `importBatch`, 승인 API를 유지. 새 schema는 source_kind=ai_draft이며 결과 참조 JSON에도 originating_run_id를 보존한다. 사건0개도 D05/원문을 검증하고 쓰기 전 등록 행을 재확인한다. draft origin에는 실행1개·원문1개·최초 revision·검토자 null·빈 overrides·비확정 장소/지역만 허용한다.

- [x] RED: 새 schema·부분 미상·빈 사건 수락과 raw 직접 승인 거부 시험. 기존 reviewed의 불완전 값 거부는 유지.
- [x] reader에서 새 schema 예외를 raw draft에만 제한하고 source_kind 분리. approve는 raw origin을 원문 검증/쓰기 전에 거부. stored 검증도 raw의 상태 승격을 거부.
- [x] 실제 Python→Java→MySQL: D03→D05→초안→재실행, source_kind·원본/출처·공개 테이블 불변 확인. 직접 승인 거부 후 사람이 작성한 다음 ai_reviewed revision은 기존 승인 가능. failed/삭제 원본은 새 import 거부.
- [x] 실제 MySQL을 켠 전체 Java 시험·JAR 빌드 통과 후 commit.

## Task 3: 문서·전체 검토·PR

**Files:** `processing/README.md`, `processing/TASK.md`, `backend/docs/reviewed-import.md`, `backend/docs/extraction-run-import.md`, `backend/TASK.md`, `contracts/extraction-run.md`, 관련 spec 구현 상태.

- [x] 새 명령·입력/출력·안전 경계·사람 검토 다음 revision 작성법·오류·원본 보관·실제 AI 미완료를 한국어로 기록한다.
- [x] Python 전체, Java/MySQL 전체, lint·Node·JSON 계약·build 및 실제 JAR 연결 시험 통과.
- [x] 작성자가 호출부/승인/반려/공개/재실행/실패/원본/계약 전체를 검토한다. 마지막에 별도 전체 리뷰1회, 유효 지적은 RED→GREEN·전체 회귀로 수정한다.
- [ ] 유효 미해결0이면 foundation 대상 PR 제출. 정확한 head CI·AI/사람 리뷰를 확인하고 유효 미해결0일 때만 하위 PR 머지. main #4는 사람에게 남긴다.
