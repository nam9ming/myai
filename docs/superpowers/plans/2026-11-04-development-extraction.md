# Development Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 사전에 선택한 실제 개발 공지를 기존 AI→D05→D06 경로에 연결하고 실패·재실행·복원을 검증한다.
**Architecture:** 입력·연결 조사는 병렬 에이전트, 새 private 실행 도구의 작은 TDD는 worker, 실제 키/API·DB·Gradle·Git과 전체 검토는 부모가 맡는다. 전체 리뷰는 마지막 새 문맥1회다.
**Tech Stack:** Python3.13 표준 라이브러리, Java21·기존 JAR/RecoveryDatabase·MySQL8.4.13. 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-11-04-development-extraction-design.md

## Global Constraints

- source SHA eec585520b72a5e7c84ef9691cf78a6dde09c8cc5efea49215b53f65fe065d6e·전처리 notice-nfc-lf-contact-v2. 기존575파일·원래199항목·stage37 manifest327항목·보호파일 불변.
- 첫 API 전 개인정보·관계 후보 제외와 게시일 내림차순/identity 오름차순의 최대17개 선택·UUID/hash를 고정한다. 기존 실제 dev3/holdout0·gold·D09는 변경하지 않는다.
- gpt-6.1-sol/prompt-v2·120초·최대3시도·8192출력 유지, 의미 오류 자동 재호출/원출력 수정 금지. 실패·미시작도 분모 보존.
- 키 값은 부모 실행 프로세스 환경에만 둔다. worker 키 접근·Git/DB/Docker/Gradle/API 금지. private0600/0700, 등록본0400/0500, no-clobber.
- stage37의 새47 V4 full SQL만 복원. 기존 V3 SQL 주입 금지. UUID/name/owner·이미지·127.0.0.1의 새 소유 DB만 사용, 다른 서비스 보존.
- validated만 D06 미배정/uncertain/draft/hidden. 사람·권리·gold·40/20-20·운영/main/배포 완료 선언 금지.

## Review Focus

1. 선택이 출력 성공·금표·임의 유형 할당에 좌우되는가 — 첫 호출 전 선택/hash와 제외 이유를 대조한다.
2. 개인정보·관계 미확정을 전송하거나 남은 자료를 blind로 바꾸는가 — 보류 목록·개발 노출·기존 manifest 불변을 확인한다.
3. 키/미완료 실행이 로그·재시도에 새는가 — 가짜 키 자기 시험·안전한 오류·고정UUID·키 없는 완료 재사용으로 검증한다.
4. failed를 성공으로 바꾸거나 한 batch를 단일 source로 잘못 전달하는가 — 모든 원본·정확한1문서 source·D05 상태/전체초안 대조·실패 초안 거부를 확인한다.
5. 재실행·복원이 기존3건/공개/경로를 바꾸는가 — 전체 행/원본·SQL·HTTP·소유 자원 정리 증거를 확인한다.

### Task 1: 개발용 선택·실행 경계

**Files/Owner:** 부모 private selection.json·입력 baseline. worker private run_selected.py·test_run_selected.py만 소유.
**Interfaces:** 선택 행 document_id/document_version_id/input_path/input_sha256/preprocessing_version/run_id를 사용한다. 기존 parse_input·run/verify CLI를 재사용하고 외부 호출 없는 fake runner로 오류 경계를 시험한다.

- [ ] 실제44건 개인정보/관계 조사 결과로 제외와 최대17 선택을 고정한다. Expected: 선택 원문/hash·순서 재현, 개발만 선언, 기존 입력 불변.
- [ ] 새 runner는 입력 hash 변조·미완료 ID·가짜 키/오류 비노출·완료 ID 키 없는 재사용의 작은 실패 시험부터 작성한다. Expected: 실제 동작 RED, 이후 GREEN; 실제 키/API 접근 없음.
- [ ] 최소 구현으로 고정 실행·receipt/실패·미시작 보존을 연결한다. Expected: 기존 CLI 의미·최대3시도 유지, 새 자동 재호출 없음.

### Task 2: 실제 API·D05·숨김 D06·복원

**Files/Owner:** 부모 private API원본·logs/proof·단일source·초안·Java 전용 probe와 보고서.
**Interfaces:** Task1 selection/runner와 stage37 V4 full SQL·RecoveryDatabase/SourceRegistrationGuards·기존 JAR을 소비한다.

- [ ] 키를 출력하지 않고 고정 UUID의 개발 선택을 실행·verify한다. Expected: 각 실제 성공/실패/시도/usage 보존, 완료 전부 키 없이 재사용, 미완료 재전송 없음.
- [ ] 새 빈 소유 DB에47 V4를 복원한 뒤 실제 D05 전체를 등록한다. Expected: 전체 기존 행 불변, 등록 성공과 AI 성공 구별, 실패 원본도 등록.
- [ ] validated만 단일 source로 미배정 숨김 초안을 생성·저장하고 실제 재실행/실패 참조/공개 경계를 확인한다. Expected: 정확 delta·reviewer/time/geometry null·공개0·원본 불변.
- [ ] 새 full/data SQL→두 번째 빈 소유 DB 복원·재검증·자원 정리한다. Expected: 전체 행/dataSQL 동등, 등록본 경로 유지, 타 서비스 불변; 실제 파일유실 복원으로 세지 않음.

### Task 3: 전체 리뷰·원격 gate·인계

**Files/Owner:** 부모 backend/processing README/TASK·private 보고/manifest·GitHub 증거.

- [ ] 작성자 전체 검토·관련 시험/빌드·새 문맥 전체 리뷰1회 후 유효 minor까지 수정한다. Expected: 미해결0·보류0, 실제 실패/미실행 정확 보고.
- [ ] source PR→CI/AI/새 사람 피드백→develop 병합→통합 gate를 확인한다. Expected: 실제 source/tree/head·시험 수·raw지적/판단 구별, main은 사람.
- [ ] 모든 판단/비용과 전체 private 원본·manifest를 보존하고 이번 scratch만 정리한다. Expected: 보호파일·기존 pack 불변, 실제 평가·사람·운영 미완료 유지.
