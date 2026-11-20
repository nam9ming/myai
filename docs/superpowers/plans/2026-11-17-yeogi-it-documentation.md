# 여기:it 설계·작업 문서 전환 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 여기:it의 시민 대상5분야 방향·현재 담당·재사용/변경·작업 순서·인수 기준을 활성 문서에 반영한다.

**Architecture:** 기존 구현 API/CLI·데이터·검증 기록을 보존하고 새 설계와 분리한다. 제품·화면·데이터/계산, 실행·검증·WBS, 모듈 안내를 병렬 갱신한 뒤 작성자 종단 검토와 독립 전체 검토1회로 정합성을 확인한다.

**Tech Stack:** Markdown, 기존 Node.js20+·Python3.13 검증 도구. 앱 기술·코드·JSON 변경 없음.

**Spec:** [명세 목차](../../spec/00_목차.md), [결정 기록](../../spec/07_결정사항과자체점검.md), 사용자 제공2026-11-16 백엔드 업무지시서와11월17일 방향·명칭 결정.

## Global Constraints

- 프로젝트명 여기:it·저장소명 myai·기존 Flutter/Spring/MySQL/Python 유지.
- 시민 전체·5분야로 확장하고 기존 소상공인 기능 유지. 우선 분야·수집처·개인화/변경 추적은 합의한다.
- 김윤기 백엔드 변경, 상헌 화면/API 연동, 명묵 반복 검증, 남규민 범위·일정·운영 조율.
- 신청/진행 일정·무료/미상·자격/관심·확인된 변경/미확인을 분리한다.
- 차별화3후보 명칭·최종 범위·실제 성과를 창작하지 않는다. 브라우저 관심 저장을 계정/알림 필수화로 확대하지 않는다.
- 현재3유형 API·원본·합성 예제·과거 계획/검증·기존 정량 목표를 보존한다. 새5분야 완료 실적으로 집계하지 않는다.
- AGENTS.md·사용자.gitignore·원본DOCX/PDF/HTML·코드/JSON·키/실자료는 변경하지 않는다.
- 과거11월3~4일 계획은 역사 기록으로 표시하고 현재 진입점에서 새 기준으로 연결한다.

## Review Focus

1. 진입점에 따라 옛 역할·소상공인 제한·과거 기한을 현행 지시로 오인하는지 확인한다.
2. 새5분야·검색/필터·신청 정보가 이미 구현된 API처럼 보이는지 확인한다.
3. 기존 API·명령·앵커·링크·목표·불확실성/승인 경계가 손실됐는지 확인한다.
4. 시제품·실제 앱·합성 검증·실제 품질/사용자/운영 성과가 섞였는지 확인한다.
5. 미확정 후보·날짜·필드/enum·담당·범위를 임의 확정했는지 확인한다.

## Task 1 활성 문서 전환

**Files:** root README/CONTRIBUTING/CLAUDE, docs/spec/00~11, frontend/backend/processing README·TASK, contracts/README, docs/development-infra, data/public/README, 과거 시연 문서의 구분 안내.

**Interfaces:** 기존 문서 경로·유효 앵커와 api-v1·CLI 규격은 유지한다. 결과는 현행/기존/제안/합의 필요를 구분한 작업 지시와 재사용/변경 범위다.

- [x] 사용자 입력·업무지시서·웹시제품·현재 구현/브랜치 대조, 작업 파일·소유 분리.
- [x] 기존 분리 worktree에 작업 브랜치 생성, Node24 baseline34개·합성 계약9개 통과.
- [x] 본문·역할·작업 순서·변경/재사용·인수와 과거 기록 연결 갱신.
- [x] 작성자 전체 diff·안내/계약 영향·링크/앵커·코드/JSON 불변 검토.
- [x] 독립 전체 검토1회의 유효 지적을 Minor까지 수정·관련 검증.

## Task 2 검증·PR·통합 인계

문서 변경이므로 새 동작 시험을 만들지 않는다. 로컬 문서/도구 검증과 원격 전체 CI를 구분한다.

- [x] `git diff --check`, 변경 Markdown 상대 링크·앵커, 현행/과거 표현 확인.
- [x] Node20+ `npm run lint`, `npm test`, `npm run build`, Python3.13 `contracts/validate_examples.py` 결과 확인.
- [x] 로컬 Java/Python 전체 앱 시험 생략 사유를 PR에 명시. 코드 변경 없는 문서 단계다.
- [ ] 영어 Conventional Commit·한국어 PR을 `develop` 대상으로 제출.
- [ ] 정확 head CI·실제 자동 리뷰·새 사람 리뷰 확인, 유효 지적 수정.
- [ ] 비main 병합 정책에 따라 `develop` 반영 후 통합 결과 확인, 기능 브랜치 정리·사용자 변경/worktree 파일 보존.
- [ ] 변경 문서·검증·남은 합의/개발·제약 인계. `main` 병합·운영 배포는 수행하지 않음.

## 검증 구분

baseline은 수정 전 도구/합성 계약 검증이다. 로컬·원격 결과는 실제 수행 후 각각 기록한다. 문서 전환 완료는 신규 API·5분야 자료·독립 정답표·사용자 평가·배포 완료가 아니다.

## 독립 검토 반영

전체32개 변경 문서·삭제 요구·공개 코드/계약·원본 지시서를 대조한 독립 전체 검토1회를 수행했다. 유효 지적2건을 반영했다: 기존 가게 조건의 URL 비노출·링크 공유 제외를 복원하고 개인 설정과 시민 공개 검색/필터의 정책 합의를 구분했다. 실자료 선별 평가의 옛 지정 담당을 독립 담당 지정/합의로 바꿨다. 수정한 문단·대응 요구·새 링크·diff를 확인했으며 독립 전체 검토를 반복하지 않았다. 원격 검증·통합 결과는 PR 증빙에서 별도 추적한다.

## 로컬 검증 기록 — 2026-11-17

Markdown32개만 변경했다. 기존 T23행·DB/IN12행과 AGENTS·사용자 .gitignore·원본 지시서의 불변을 확인했다. 상대 링크/앵커384개 오류0, diff 공백 검사 통과. Node24.21.0 lint419파일·34시험/실패0/생략0·합성 HTML build, Python3.13 계약9JSON이 통과했다. Java/Python 앱 전체는 코드 변경이 없어 로컬 재실행하지 않았으며 원격 전체 CI로 확인한다. 독립 검토와 정확 head 원격 CI·자동 리뷰·병합/브랜치 정리 증빙은 해당 PR에 이어 기록한다.
