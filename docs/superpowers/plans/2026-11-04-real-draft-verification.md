# Real Draft Storage Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 실제 개발 공지3건의 D03/D05/D06 숨김 저장·정확 재실행·공개 불변을 실제 JAR/격리 DB로 검증한다.
**Architecture:** 기존 importer와 frozen archive를 그대로 사용한다. 새 production 코드를 추가하지 않고 비공개 표준 라이브러리 실행/assert harness와 한국어 결과 문서를 남긴다.
**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4.13·Python3.13 stdlib·Docker.
**Spec:** docs/superpowers/specs/2026-11-04-real-draft-verification-design.md

## Global Constraints

- 실제 사람/gold/승인·새 AI 호출·키 접근·공개/배포·기존 서비스 변경 금지.
- 기존 원본 바이트·권한·raw_ref 경로, 사용자 .gitignore·다른 작업 공간 보존.
- 후보 area/dictionary는 미확정으로 유지하고 ai_draft/draft/hidden·uncertain·null 검토자/좌표를 확인.
- 공개 자료에는 실제 입력/원출력/비공개 경로/키를 포함하지 않는다.
- 새 의존성·계산 엔진·DB migration 없음. 커밋 제목/본문 영어 Conventional Commits, main은 사람 담당.

## Review Focus

1. 세 실제 문서와 v1/v2 여섯 실행을 다른 문서 건수로 중복 집계하지 않는가 — Task2 DB/원본 참조 대조.
2. 후보 연결을 확정 구역·좌표·사람 검토로 기록하지 않는가 — Task1 파일 메타데이터와 Task2 모든 D06 payload 검사.
3. 재실행 성공을 새 revision 생성이나 상태 변경과 혼동하지 않는가 — Task2 전체 DB dump/hash 동일 검사.
4. 부정 시험이 원래 archive/초안을 편집하거나 공개 테이블을 바꾸지 않는가 — Task2 새 입력 복사·전후 원본/공개 dump 검사.
5. 일시 DB 정리 후에도 private 증거·원래 frozen raw_ref를 재확인할 수 있는가 — Task3 명령·JSON 결과·dump/checksum 보존, 본인 container만 제거.

## Files and Ownership

- Coordinator: 이 spec/plan, backend/README.md·TASK.md·docs/ai-review-draft.md, processing/README.md·TASK.md의 확인 결과와 private 실행/증거.
- Read-only data agent: 기존 자료 경로·ID·hash/상태 조사만. DB·키·파일 수정 금지.
- Fresh final reviewer: 전체 단계 증거/변경 검토1회. 본인 지정 scratch 외 수정·기존 자료/DB 변경 금지.
- 같은 저장소의 다른 담당 변경을 되돌리거나 stage하지 않는다.

### Task 1: 원본과 격리 환경

**Interfaces:** 기존 source JSON·raw asset root, 각 v1/v2 run UUID·frozen root, 후보 초안 파일3개를 private selection.json에 명시한다.

- [ ] 자료 agent 결과와 원본 metadata/receipt/hash를 대조하고 실행 전 원본 경로·바이트·권한 기준선을 남긴다.
- [ ] 새 Docker container ID/name/label/image·localhost 포트·빈 DB와 Flyway V1~V3 적용을 확인한다.
- [ ] 기존 JAR SHA/Java21/Python3.13을 확인하고 자체 DB 비밀번호는0600 임시 파일만 사용한다.
- [ ] harness의 사전 조건 assert가 누락/잘못된 선택을 실제로 거부하는 자체 검사 후 정상 선택을 통과하는지 확인한다.
- [ ] Expected: 실제3문서/6실행/3개 미검토 후보 초안, 기존 원본 변경0, 기존 DB 접속0.

### Task 2: 실제 저장·재실행·거부

**Interfaces:** Task1 selection·localhost 임시 DB·기존 JAR을 소비하고 stdout 결과/DB 조회·dump/hash를 private 증거로 남긴다.

- [ ] source-import로 D03 3문서/3버전, local-extraction으로 failed3/validated3을 등록한다.
- [ ] 기존 후보 초안3개를 local-import하고 모든 private payload·D05 원본 참조/상태·D03·code point 근거를 대조한다.
- [ ] 정확한 source/6실행/3초안 재실행 결과·전체 application DB dump/hash 불변을 확인한다.
- [ ] failed 초안·raw 직접 승인·의미값 위조·참조 불일치의 실제 거부/기존 행 불변을 확인한다. 원본 대신 새 입력만 만든다.
- [ ] Expected: D06 사건3/revision3·ai_draft/draft/hidden·reviewer/time null·공개4테이블0, 원본/원래 미배정 초안/후보 초안 바이트·권한 동일.

### Task 3: 기록·전체 리뷰·PR

**Interfaces:** Task2 실제 결과만 한국어 문서에 반영하며 actual real-data 내용·raw·경로는 공개하지 않는다.

- [ ] README/TASK/초안 안내를 실제 저장3건·후보 미확정·사람/gold/40건/운영 미완료로 일치시킨다.
- [ ] 적절한 lint/계약/문서 검증과 전체 자체 리뷰를 수행한다. production 소스 미변경이면 불필요한 native 전체 재시험은 반복하지 않는다.
- [ ] private actual evidence를 포함한 fresh 전체 리뷰1회, 유효 지적 모두 수정·검증.
- [ ] 유효 미해결0에서 PR→정확한 head CI/자동/새 사람 리뷰→develop 병합·통합 확인. main 미변경.
- [ ] 판단/비용과 보고 초안을 먼저 보존하고 본인 DB/임시 credential/이번 workspace만 정리한다.
- [ ] Expected: 확인한 실적만 기록, 유효 미해결0·보류0, 원본/사용자 변경/기존 서비스 보존, 전체 목표는 진행 중.

## Plan Self-Review

Task1 선택/원본/DB를 Task2가 사용하고 Task2 실제 결과만 Task3가 보고한다. 새 제품 동작은 없어 TDD 대신 harness 사전 조건의 실제 실패/정상 제어와 실제 JAR 성공/거부·DB/원본 불변을 검증한다. 실제 사실성/사람 검토를 만들지 않는다.

