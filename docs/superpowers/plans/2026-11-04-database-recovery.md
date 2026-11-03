# Database Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** B08의 DB·선택 원본 백업→새 전용 DB/동일 경로 복구·재기동·운영 인계를 합성 검증한다.
**Architecture:** test-only Docker helper가 소유한 새 MySQL을 만들고 표준 dump/restore를 수행한다. 별도 통합 시험은 기존 Java/Python fixture/서비스·HTTP를 재사용하며 docs는 실제 정책과 합성 결과를 구분한다. production API/DB migration/백업 서비스는 추가하지 않는다.
**Tech Stack:** Java21·JUnit5/Spring·MySQL8.4.13·Docker CLI·tar·기존 Python3.13 표준 라이브러리.
**Spec:** docs/superpowers/specs/2026-11-04-database-recovery-design.md

## Global Constraints

- 실제 DB/자료·제공 로컬 키·D09 수집·연구실 서비스·main 변경 없음. 사용자.gitignore·AGENTS 보존, 부모만Git.
- 새 소유 컨테이너만 생성/삭제, 임의 DB_URL 입력 없음. 복원 대상은 새 빈 schema만, SQL 실패는 부분 대상 폐기.
- D03·성공/실패 D05·handoff·운영/공개 이력의 bytes/path/mode/행 보존. DB+파일 백업 전에 모든 쓰기/DDL 중지, 동일 실제 절대 경로 복원.
- 영어 Conventional Commit 제목/본문·제목50자 이내, 문서/주석/PR한국어. 새 의존성·production 인터페이스 없음.
- 파일0600/부모0700의 비공개 합성 proof, credential/env 미포함. 공개 CI artifact 추가 없음.

## Review Focus

1. 잘못된 대상·재실행이 기존 DB/컨테이너/파일을 지우는가 — 소유 ID/라벨/이름·빈 schema 검사와 기존 행 불변 시험.
2. DB만 복원되거나 raw_ref가 다른 경로여도 성공으로 보이는가 — 원래 경로 부재/다른 경로의 거부, 같은 경로·bytes·modes 재검증.
3. 부분 SQL 실패·pipe 교착·시작 실패에 성공 proof/남은 소유 리소스가 생기는가 — 실제 잘못된 SQL·bounded file I/O·finally cleanup 확인.
4. 일부 테이블·실패 D05·null/Unicode/정밀 원문·source_reviews/공개 이력이 빠져도 비교가 통과하는가 — 전체 schema/행·파일 manifest·실제 API/export 및 재기동 대조.
5. dump와 원본 시점·코드/schema 버전이 달라지거나 D09/자격증명이 섞이는가 — quiesced seed·명시 선택 자료·버전/checksum receipt·proof 파일 목록 검사.

### Task 1: 소유 전용 MySQL dump/restore helper

**Owner/Files:** DB helper worker: `backend/src/test/java/kr/ac/myai/backend/RecoveryDatabase.java`, `RecoveryDatabaseTest.java` 신규만.
**Interfaces:** package-private `RecoveryDatabase implements AutoCloseable`; `static start(Path privateRoot)`→새 컨테이너; `JdbcTemplate jdbc()`; `String url()/username()/password()/id()`; `void dump(Path newFile)`; `void dumpData(Path newFile)`(동일 옵션+--no-create-info --skip-triggers); `void restore(Path existingDump)`; `close()`→검증한 소유 컨테이너/볼륨·임시 env만 정리. 호출자는 증거에password를 쓰지 않는다. dump는 새 파일에만 설치하고 restore는 schema 비었는지 먼저 검사한다. root는 호출자0700 임시 디렉터리.

- [x] 먼저 helper contract 경계 시험을 작성하고 부재/잘못된 동작 RED를 기록한다. test-only helper이며 production 변경으로 보고하지 않는다.
- [x] 실제 Docker 두 DB에 작은 Unicode/emoji/null 행을 dump→restore하고 전후 같음, 이미 찬 대상 재복원 거부·행 불변을 검증한다. 새 DB의 일부 DDL 뒤 잘못된 SQL 실패를 성공으로 처리하지 않는 별도 시험을 둔다.
- [x] 제한시간·파일 redirect·소유 확인·시작 실패 보상/finally 정리·0600 env/proof를 최소 구현한다. 임의 외부 대상 옵션 없음.
- [x] `./backend/gradlew -p backend test --tests '*RecoveryDatabaseTest' --no-daemon`를 MYAI_MYSQL_TESTS=true/JAVA_HOME21로 실행, Expected: 소유 시험 모두 PASS/실패·생략0 및 남은 소유 컨테이너0. 부모 커밋 `test: isolate recovery database operations`.

### Task 2: 애플리케이션 DB·원본·HTTP 복구 통합

**Owner/Files:** recovery worker: `backend/src/test/java/kr/ac/myai/backend/DatabaseRecoveryTest.java` 신규만. 기존 fixture 변경 필요 시 부모에게 알림.
**Interfaces:** Task1의 helper만 DB를 만든다. SpringApplicationBuilder는 명시 datasource 인자·public profile·localhost/port0·PythonProbe.PYTHON/REPO로 실행하여 환경의 기존 DB_URL과 분리한다. SourceReviewFixtures/root·기존 서비스·public HTTP 재사용. proofRoot=MYAI_RECOVERY_PROOF_ROOT 또는 backend작업경로의 build/recovery-proof, 새 UUID하위0700만 생성.

- [ ] 독립 seed로 D03·성공/실패 D05·handoff D06·source_reviews·공개/head/audit를 채우고 원본/DB/HTTP/snapshot/export 기준값을 저장한다. production 변경 없음; 새 복구 시험의 누락 탐지력은 실제 restore 호출을 뺀 한정 RED 대조군으로 확인하고 원래 시험을 복원한다.
- [ ] source 앱 종료→DB dump/표준 tar 백업→새 빈 target DB restore→기존 경로 부재/다른 경로의 후속 검증 거부를 확인한다. symlink·SQL 경로 치환 없음.
- [ ] tar를 같은 실제 절대 경로에 복원하고 모든 bytes/modes/SQL rows/schema/Flyway/code/snapshot을 대조한다. Java/Python 정확 재등록·handoff 재사용으로 private 경로를 검증하고 실제 HTTP config/detail/matches·export를 같은 문맥에서 비교한다.
- [ ] 행 전용 SQL은 실제 bytes/SHA를 대조하고 전체 raw SQL/DDL 차이는 원형 그대로 보존한다. target 앱 재기동 후 행/seed/응답 보존, fullschema 목록의 source_reviews 포함을 확인한다. proof는 선택 합성 dump/tar/manifests/응답/메타데이터만, 자격증명/전체temp/D09 없음.
- [ ] `./backend/gradlew -p backend test --tests '*DatabaseRecoveryTest' --no-daemon`, Expected: PASS/실패·생략0·소유 컨테이너0, private proof 생성. 부모 커밋 `test: verify application recovery`.

### Task 3: 인계 문서·전체 gate

**Owner/Files:** docs worker `backend/docs/backup-recovery.md` 신규, backend/README.md·TASK.md 링크/상태만. 부모 design/plan/ledger·전체 gate/Git/PR.

- [ ] 비밀값 없는 환경/코드/schema/checksum·쓰기 중지·선택 파일 백업·새 빈 대상/같은 경로 복원·기동/정지·실패 폐기·검증과 실제 미완료를 기록한다. 표준 CLI 실제 시험과 문법 검사·운영 미검증을 구별한다.
- [ ] 현재 전체 Python587·Java/MySQL기존329+새 복구 시험·Node29/JSON9/lint/build/JAR를 실행한다. Python/Java 무거운 전체 시험은 순차, 문서/한정 네이티브 검증은 병렬.
- [ ] 작성자 전체 검토→새 전체 리뷰1회→모든 유효 minor 포함 수정/RED→GREEN/전체회귀→정확 source CI/AI/새 피드백→develop 병합→통합 gate/PR20 기록. main은 사람.
- [ ] 모든 Ruling/비용·시험 원형/private proof를 evidence에 보관·hash 대조 후 이번 소유 컨테이너·credential·workspace만 정리. 실제 사람/gold40/D09/main/배포로 전체 goal을 완료 처리하지 않는다.

## Pre-flight

Task1의 start/jdbc/dump/restore/close가 Task2에 직접 소비된다. DB helper는 입력 대상 선택을 제공하지 않고 Task2는 SQL 주입/임의 global DELETE로 복원하지 않는다. proof root는 Task1 credential root와 별개다. docs의 일반 수동 백업 인계는 자동시험이 운영 복구를 수행했다고 표현하지 않는다.
