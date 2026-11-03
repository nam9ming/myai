# Notice Source Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 실제 공지 D03 47건의 등록·보존·rollback·재실행·새 DB 복원과 공개 미노출을 증명한다.
**Architecture:** 기존 `RecoveryDatabase`·실제 JAR10개 seed·source-only CLI를 사용한다. worker는 private 실행 가드만 구현하고 부모가 전체 DB 시나리오·Git을 수행한다.
**Tech Stack:** Java21·기존 Jackson/JDBC/MySQL8.4.13, Python3.13 표준 라이브러리. 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-11-04-notice-source-registration-design.md

## Global Constraints

- 기존3건·stage36 immutable575파일·173파일/26디렉터리·AGENTS·사용자.gitignore 보존. 초기 package 사용 금지, final source SHA eec585520b72a5e7c84ef9691cf78a6dde09c8cc5efea49215b53f65fe065d6e.
- UUID/name/owner·127.0.0.1의 새 소유 MySQL8.4.13만 사용. 부모만 DB/Gradle/Git, 다른 연구실 서비스·공용 DB 수정 금지. private0700/0600·새 출력 no-clobber.
- legacy V3 data-only SQL 변환/주입 금지. 원본10 CLI 재구성을 과거 등록시각까지 같은 복구로 세지 않는다. 이후 JAR은 Flyway=false.
- D03 신규44 pending/unchecked·checks[]·head0/null, 기존3 pending/uncertain·D05실패3/성공3·D06hidden3 유지. 공개/사람/데이터셋/키/API/D09/main/배포는 추가하지 않는다.

## Review Focus

1. 다른 컨테이너/환경 설정으로 접속·삭제하는가 — helper ID/name/owner·포트·이미지 가드, ambient secret/config 제거와 실제 종료 증거 확인.
2. canonical과 초기 오류본·별칭 hash를 혼동하는가 — final 포인터/SHA와 full input→DB 대조, replay 조기 반환과 새 hash batch를 구별.
3. 늦은 충돌을 Reader 거부나 이미 존재한 행 재사용으로만 시험하는가 — 초회 전 정렬 마지막 version UUID 충돌·신규44행0·기준선 전체 불변 확인.
4. 새47 SQL을 legacy snapshot 복구·사람 검토/추출47 실적으로 과대 표시하는가 — 기존10 재구성/새 백업 복원·미확인 상태/데이터셋dev3를 분리.
5. 복원·CLI 재실행이 원래 D05 경로/metadata·운영열·공개 상태를 바꾸는가 — 전체16테이블·data SQL·schema와 실제 빈 공개 API 경계·원본 bytes/mode 대조.

### Task 1: 소유권·자식 실행 가드

**Files/Owner:** worker private `src/SourceRegistrationGuards.java`, `src/SourceRegistrationGuardsTest.java`. 부모는 compile classpath·baseline·새 branch/ledger.
**Interfaces:** package `kr.ac.myai.backend`; `INSPECT_FORMAT`은 credential 없는 Docker JSON. `Owner checkOwner(String json,String expectedId,Owner previous)`와 `Map<String,String> cleanEnvironment(Map<String,String>)` 제공. Owner는 id/name/owner/port; 이전 값이 있으면 동일해야 한다.

- [ ] 실제 임의 소유 정보·중복/외부 포트·멈춘/다른 이미지·환경 주입에 대한 작은 실패 시험부터 작성한다. Expected: 동작 누락의 실제 RED, 단순 compile 오류만으로 완료하지 않음.
- [ ] 가드는 helper와 같은 owner/stage/name, mysql:8.4.13·Running·127.0.0.1:임의3306만 허용한다. Expected: 유효 예제 통과·변조 거부·PATH/HOME 보존·DB/Spring/MYAI/OpenAI/Java 주입 제거 GREEN.
- [ ] 부모 `testClasses bootJar --no-daemon` 후 기존 dependency/classpath로 private 가드를 컴파일·실행한다. Expected: 추가 설치/API/DB 없이 자기 점검 PASS.

### Task 2: 실제47 등록·원본 보존·복원

**Files/Owner:** 부모 private `src/NoticeSourceRegistration.java`, 실행/선택/검증 helper·logs/proof/SQL. 제품 코드 수정 없음.
**Interfaces:** Task1 guard, `RecoveryDatabase.start(Path)`/jdbc/dump/dumpData/restore/close, 기존3 selection.json, stage36 final source/root를 소비. 최종 private receipt는 실제 종료·전체 행/schema·원본 hash 대조 뒤에만 성공이다.

- [ ] 기존575파일 manifest·원래199항목·보호 파일·다른 Docker ID 상태를 baseline으로 기록한다. Expected: 현재 hash/mode 모두 일치, local key 미열람.
- [ ] 새 소유 DB에서 원본10 CLI로 V4 기준선을 구성한다. Expected: D03 3/3·D056·D06 3/3·공개4표0, Flyway4; 원래 JSON/AI 기록/uncertain 보존.
- [ ] JDBC 충돌0 확인 뒤 늦은 UUID 충돌44 음성 배치를 실행한다. Expected: Reader 통과·exit3·신규44행0·전체 baseline/Flyway 불변.
- [ ] canonical44 첫 등록·exact replay·다른 source-root 동일 바이트·공백 alias·metadata 충돌·원문 누락을 실행한다. Expected: 첫 delta44/44/1, replay 같은batch/행불변, alias batch만+1, 마지막2개 각각3/2·전체 행불변.
- [ ] 신규44 D03 전체 metadata/상대raw/운영head·원래3/D05/D06/감사/공개/사전/Flyway를 모든 열로 대조한다. Expected: 문서47/버전47·D056·D06 3/3·공개0, 원본 bytes/mode 불변.
- [ ] 같은47 DB의 full/data SQL을 새 blank owned DB에 복원하고 기존10+canonical44를 정확 재실행한다. Expected: 전체16표/data SQL/schema/Flyway 동등·행 추가0·D05경로/원본/상태 유지; raw SQL/diff 보존.
- [ ] source/restore public JAR에서 health200·config/matches503·상세422/404와 DB 불변을 확인하고 자기 프로세스/DB만 정리한다. Expected: 실제 HTTP가 private 자료를 반환하지 않음, 다른 서비스 ID/상태 불변.

### Task 3: 전체 리뷰·PR·통합 인계

**Files/Owner:** 부모 backend/processing README/TASK·private 보고/manifest·GitHub 증거.

- [ ] private 실제 시나리오·가드 자체점검과 npm test/lint/build를 확인한다. Expected: terminal PASS, 미실행/실패를 숨기지 않음. 무거운 검증은 순차·부모만 실행.
- [ ] 작성자 전체 리뷰 후 새 문맥 전체 리뷰1회, 모든 유효 minor 포함 수정·관련 재검증한다. Expected: 유효 미해결0·보류0 전 PR 금지.
- [ ] source CI/자동·새 사람 피드백 확인→develop 병합→통합 CI/리뷰·PR20 기록 갱신. Expected: Java/MySQL336·Python587 등 실제 수치·정확 head/tree gate 확인, main은 사람.
- [ ] 모든 Ruling/비용·원본 불변·실제47 SQL/복원·테스트/리뷰 증거를0700/0600으로 보존하고 이번 scratch만 정리한다. Expected: private manifest 검증·소유 runtime 잔여0·실제 평가/사람/배포는 미완료 유지.
