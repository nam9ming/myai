# Citizen API Reproduction Bundle Implementation Plan

[PR #57](https://github.com/nam9ming/myai/pull/57)이 반영된 develop `9870c18`에서 시작한다.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자 goal에 따라 소유권을 나눠 구현하고 마지막 독립 전체 리뷰는 정확히1회다.

**Goal:** 기존 시민 공개 API 시험의 실제 합성 요청·응답·공개 snapshot을 명묵/Flutter 담당이 반복 재생성하고 오프라인 대조할 수 있게 남긴다.

**Architecture:** 기존 MySQL/실제 JAR 시험과 소유 정리, SnapshotExportService를 재사용한다. 시험 지원 클래스에 작은 저장 접점만 추가한다. 앱·API·DB·Python 계약과 고정 fixture를 바꾸지 않는다.

**Tech Stack:** Java21/Spring Boot3.5.x/MySQL8.4/Python3.13, 기존 JUnit/Gradle/Jackson, 현행 CI artifact.

**Spec:** contracts/citizen-api.md, docs/spec/06_개발실행계획.md·10_인원별WBS.md·11_개발착수가이드.md. 또한 docs/spec/05_시험과인수기준.md의 Y01~Y10을 대조한다.

## Global Constraints

- G5 exact head CI·실제 리뷰·develop 병합/tree 검증을 마친 뒤 착수한다. 전체 Java/Python goal을 이 묶음으로 축소하지 않는다.
- 출력은 합성 공개 JSON/snapshot만이다. DB 계정/Bearer/원문/D03~D06/S10/AI 원출력/실제 평가/환경변수 값/절대 host·경로/전체 로그를 넣지 않는다.
- build/repro/citizen-api-v1/ 아래 새 배타 run 디렉터리만 만든다. 이전 결과·DB·고정 expected·user files를 삭제하거나 덮지 않는다. 새 provisioner/reset/라이브러리/인증/업무 규칙은 없다.
- 응답 원래 UTF-8 bytes·동적 UUID/시각을 보존한다. 기대값은 요청 전 공개 canonical과 기존 명시 assertion으로 정하고 actual을 복사해 정답으로 만들지 않는다.
- manifest의 완료 의미는 기록한 response checks 통과다. 전체 시험/cleanup·CI 성공과 구분한다. 중간 실패 출력에 완료 manifest를 쓰지 않는다.
- 저장한 주소로 지속 접속할 수 있다고 안내하지 않는다. 서버/소유 Docker는 기존 시험 종료 시 정리하며 오프라인 기록 소비와 재생성만 제공한다.
- main 병합/배포0. 부모만 Gradle. 영어 Conventional Commits·명령형50자 이내, 한국어 docs/PR. 유효 Minor까지 수정하고 정확 head CI·실제 AI/도착한 사람 리뷰 후 non-main merge한다.

## Interfaces and Files

- Existing test-only CitizenNoticeFixtures: record ReproCase(String id, HttpResponse<String> response, int expectedStatus, Map<String, ?> checks); static Path createReproDirectory(String scenario); static void writeRepro(Path directory, String scenario, String mysqlVersion, List<ReproCase> cases).
- createReproDirectory는 고정 build 출력 아래 새 run+snapshots 폴더를 배타 생성한다. SnapshotExportService.export(UUID,Path)는 각 시험의 열린 Spring context에서 먼저 호출한다. JAR setup context 생명주기를 늘리지 않는다.
- writeRepro는 GET 시민 경로만 기록한다. request={method,path_query,body:null}, actual=원래 본문, expected={status,checks:{JSON_pointer:기대JSON}}. 전체 header/host는 저장하지 않는다. 생성 시각/request_id는 원본에 보존하고 선택 비교에서만 제외한다.
- manifest=citizen-api-repro-v1, api/snapshot schema·synthetic·scenario·Java/MySQL 버전·JAR hash·실제 snapshot/event/revision ID와 파일 상대 경로/SHA256/크기·response_checks=passed. 검증한 CI checkout SHA를 기록하고 로컬에서는 null로 둔다. 파일은 CREATE_NEW로 쓰며 manifest를 마지막에 쓴다.
- CitizenNoticeReproTest: 저장기 빠른 회귀. CitizenNoticeMySqlTest의 5분야 목록/상세 10건, 공개 준비 오류 1건, 빈 목록/교체/누락/복구 6건, 복수 분야·출처와 이력 조회 불가 각 1건 및 CitizenNoticeJarMySqlTest의 목록/상세/최신·과거페이지/잘못된필터5건을 기존 내용 검증 뒤 저장한다.
- backend/docs/citizen-api-repro.md, backend README/TASK·contracts/citizen-api.md의 실행 링크. CI는 공개 재현 자료 전용 artifact를 보관한다. 기존 JAR artifact 경로와 시험은 유지한다.

## Review Focus

1. 공개 합성 응답에 private/자격증명이 섞이지 않으며 요청 host/header와 환경 값은 기록하지 않는다(Task1/2).
2. UTF-8/emoji/UUID/원래 생성 시각과 HTTP 오류 status를 잃지 않고 기대값을 actual로 만들지 않는다(Task1/2).
3. 반복 실행/실패/동일 이름/출력 충돌에서 이전 run 불변·새 실패 manifest 부재를 보장한다(Task1).
4. 동적 ID와 이력 실제 cursor를 같은 공개 canonical/응답에 연결한다(Task2).
5. 저장 실패는 시험 실패이며 소유 DB/원본 불변·cleanup과 실제 Docker8.4/JAR 검증을 유지한다(Task2/3).

### Task 1: 기존 시험 지원 클래스의 최소 기록 접점

**Files:** CitizenNoticeFixtures.java, 새 CitizenNoticeReproTest.java. 저장기 담당 에이전트 단독 소유.

- [x] UTF-8·실제 GET 상대 경로·독립 checks·raw bytes·새 run/기존 파일 보존·실패 시 manifest 부재를 요구하는 실제 파일 시험을 먼저 작성한다. 컴파일/누락 이름 오류와 행동 RED를 구분한다.
- [x] 정한 두 저장 접점만 구현한다. 새 공유 helper 클래스/일반 실행 framework는 만들지 않는다. snapshot 파일은 기존 exporter를 사용한 결과만 기록한다.
- [x] 부모가 집중 Java 시험과 diff 검사를 실행해 GREEN을 확인한다. 커밋 test: retain citizen API repro bundles.

### Task 2: 기존 실제 HTTP 시험·공개 artifact·인계 설명

**Files:** CitizenNoticeMySqlTest.java, CitizenNoticeJarMySqlTest.java, .github/workflows/ci.yml의 artifact path, 새 backend/docs/citizen-api-repro.md와 관련 README/TASK/contract 링크. MySQL·JAR 시험은 각각 담당 에이전트가 소유한다. 문서·CI는 주 작업자가 소유한다.

- [x] 기존 get/json assertion을 보존하고 원래 HttpResponse를 변수로 유지해24건을 수집한다. MySQL5분야는 공개 canonical/원시 사실, JAR는 canonical+명시 history kinds/window/cursor/error.code를 기대값으로 전달한다.
- [x] Spring context가 열려 있을 때 관련 공개 snapshot을 기존 exporter로 새 run의 snapshots/에 내보낸다. 모든 기존 내용/DB/원본 불변 검사 뒤 완료 manifest를 저장한다. 실패를 catch해 성공으로 바꾸지 않는다.
- [x] 실제 생성한 실제 파일·hash·ID·status·기대/실제 선택 필드를 소비자 관점으로 대조한다. 로컬 격리 Docker와 정확 CI에서 실제 JAR/MySQL 8.4 경로를 확인한다. 기존 테스트 삭제/생략0.
- [x] 문서에 Java21/Python3.13/MySQL8.4/Docker·전용 DB allowlist·실행 명령·출력/초기화·예상 결과·버전·재생성·오프라인 제한을 적는다. 운영/공유 DB 초기화 명령은 추가하지 않는다.
- [x] CI는 기존 JAR와 별도로 공개 repro 폴더를 보관한다. 합성 자료·실제 팀원/Flutter 인수·실자료 품질·지속 서버를 구분한다.

### Task 3: 전체 검토·정확 source gate·develop 반영

**Files:** 이 계획 최종본, G5 완료 증빙·이번 단계 결과를 관련 문서/ledger에만 반영한다.

- [ ] 관련 Java/bootJar·npm lint/test/build·계약·문서 상대 링크·범위 diff 검사와 필요한 기존 회귀를 실행한다. Python 미변경은 명시하며 전체 원격 회귀를 유지한다.
- [ ] 전체 diff/호출부/저장 원본/출력 경계/실패/cleanup/계약/docs 자체 검토·수정 후 독립 전체 리뷰 정확1회. 유효 Minor까지 수정·검증하고 전체 자체 검토를 반복한다.
- [ ] 유효 미해결0에서 develop PR. exact source CI·실제 AI 코멘트/부분 범위·도착한 사람 리뷰/threads를 확인하고 유효 지적을 원인 수정한다. 오탐은 실제 근거로 기록한다.
- [ ] expected head로 non-main 병합·source/CI후보/병합/develop tree 검증·사용자 변경 보존 FF·본인 병합 브랜치만 정리·main PR20 증빙 갱신. main/배포는 실행하지 않는다.

## 계획 자체 검토

기존 테스트/공개 exporter/동적 ID/실패와 소유 정리를 재사용한다. 24응답은 이번 묶음의 명시 범위이며 API 전체/정규화/새 검색·Flutter·사용자 인수 완료를 뜻하지 않는다. 목록·상세·오류·이력의 공개 HTTP 요청과 응답을 근거로 삼는다. 미확정 사업 규칙은 기존 open-items에 유지하며 추가 질문을 하지 않는다.


## 로컬 실행 결과

- 저장기 시험 21건에서 데이터 파일과 유효성 검사를 요구해 구현 전에 실패를 확인했다. 기록기를 연결한 뒤 같은 21건이 통과했다.
- 문서의 명령으로 MySQL 8.4.13과 실제 JAR 시험 32건을 통과했다. 합성 10개 시나리오에서 HTTP 응답 24건, snapshot 12개, 파일 해시 84개를 확인했다. 최신 이력 응답의 커서와 다음 실제 요청, 목록·상세의 동일 공개 ID를 대조했다.
- CI에서는 별도 재현 artifact를 같은 checkout SHA에 연결한다. 내려받은 파일 검사와 develop 병합 증빙은 PR에 기록한다.
