# 공개 snapshot JSON 내보내기 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 체크 항목을 순서대로 구현·검증한다. 사용자 Goal에 따라 단계마다 승인 질문 없이 진행하고 마지막 전체 리뷰는 별도 읽기 전용 reviewer가 수행한다.

**Goal:** 이미 공개 commit된 D07을 원본 UTF-8/hash 그대로 로컬 파일로 내보내고 안전하게 재시도한다.

**Architecture:** 별도 `local-export` 일회성 명령에서 snapshot ID·출력 디렉터리를 받는다. 짧은 읽기 전용 RR에서 공개 감사 기록·원본 checksum·저장 문맥·공개 필드 범위를 검증한 후 DB 연결을 반환하고 파일을 쓴다. 파일 실패는 DB 공개를 취소하지 않으며 HTTP API·DB 스키마를 바꾸지 않는다.

**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4.13·Java NIO. 새 의존성 없음.

**Spec:** `docs/spec/09_DB설계와트랜잭션.md` 11·28·65·69행, `backend/docs/review-publication.md`, `backend/TASK.md`.

## Global Constraints

- 기준 `a2c277b3ffaa0efec1e0fb5575fe2d56c4aa4c0b`; main은 사람 병합, 그 외는 최신 CI·유효 미해결 지적0 후 병합.
- 원본 canonical을 재직렬화하거나 checksum/newline을 추가하지 않는다. 조회 조건·계산 결과·원문·AI 원출력·내부 검토자를 공개 파일에 넣지 않는다.
- 이미 공개했던 retired snapshot도 명시 ID로 내보낼 수 있다. export가 head·revision·감사 기록·공개 파일 전환을 대신하지 않는다.
- 파일명은 `<snapshot_id>-<checksum>.json`. 동일 바이트는 재사용하고 다른 파일·symlink·디렉터리는 덮어쓰지 않는다.
- 같은 디렉터리의 임시 파일을 완성한 뒤 Java NIO hard link로 최종 이름을 배타 생성한다. Linux/macOS의 hard link 지원 파일시스템이 필요하며 지원하지 않으면 안전한 I/O 오류로 종료한다.
- 성공 stdout 한 JSON: `status=succeeded`, `result={snapshot_id,checksum,file_name,already_exported}`. 오류는 기존 `error/request_id` 형태로 경로·SQL·원문을 넣지 않는다.
- 종료0 성공,2 설정/ID/미등록/손상 snapshot,3 기존 파일 충돌,4 DB 오류,5 재시도 가능한 파일 I/O,1 예상치 못한 실패. 초기 DB 기동 실패는 기존 CLI처럼 JSON 없이1일 수 있다.
- 실행 설정 `myai.export.snapshot-id`, `myai.export.directory`. 기존 디렉터리를 명시하며 actor·원문 root·Python은 요구하지 않는다.

## Review Focus

1. 파일 쓰기 실패·재시도에서 공개 DB/head가 유지되고 최종 파일이 부분 내용으로 노출되지 않는가.
2. 동시 export·기존 다른 파일·symlink 충돌에서 덮어쓰기나 임시 파일 잔존이 없는가.
3. checksum이 맞더라도 원문/검토자 등 추가 필드가 canonical에 섞이면 외부로 내보내지 않는가.
4. retired/replay·head 변경 중에도 선택한 동일 ID/hash를 내보내며 현재 mutable 원문을 다시 읽지 않는가.
5. 실제 JAR의 단일 JSON·종료 코드·혼합 프로필·HTTP 차단과 DB 연결 반환이 Spring proxy 밖에서도 유지되는가.

### Task 1: 바이트 보존·안전한 파일 생성

**Files:** Create `backend/src/main/java/kr/ac/myai/backend/service/SnapshotExportService.java`; Test `backend/src/test/java/kr/ac/myai/backend/SnapshotExportTest.java`.

**Interfaces:** consumes `PublicSnapshotRepository.published(String)`·`PublicationContent.verifySnapshot`; produces `export(UUID,Path):Result(snapshotId,checksum,fileName,alreadyExported)`.

- [ ] Step1: 원본 bytes/hash·재시도·commit 전 파일 없음, 동시 생성, 다른 파일/링크 충돌 보존, 미등록·checksum/문맥/공개 추가 필드 거부, I/O 실패 후 재시도 unit 시험 작성.
- [ ] Step2: `./backend/gradlew -p backend test --tests '*SnapshotExportTest'` → 새 service 없음으로 RED 확인.
- [ ] Step3: RR read→검증→파일 I/O 구현. 공개 객체 경로별 고정 키 whitelist로 추가 비공개 객체/필드 거부. 임시 파일 완성 후 hard link, 기존 regular file은 bounded read/hash 대조, finally 임시 파일 삭제.
- [ ] Step4: 같은 시험 → GREEN, `git diff --check` →0.
- [ ] Step5: `feat: export immutable public snapshots` 커밋.

### Task 2: 일회성 CLI·실제 DB·JAR

**Files:** Create `publication/LocalSnapshotExportCommand.java`, `resources/application-local-export.yml`, `SnapshotExportCommandTest.java`; Modify `MyaiBackendApplication.java`, `LocalImportCommand.java`, `LocalPublicationCommand.java`, `PublicationMySqlTest.java` (모두 backend 하위).

**Interfaces:** Task1 Result를 stdout JSON으로 반환. 기존 import/publication의 실패·프로필 동작 유지.

- [ ] Step1: CLI 설정/ID/종료코드·공개 HTTP/혼합 profile 거부 RED 시험. 실제 MySQL publish→export 바이트/hash/비공개 제외·실패 후 head 보존·재시도·retired/replay export·전체 DB 불변 시험 작성.
- [ ] Step2: 관련 시험 RED 확인. 전용 MySQL8.4.13만 사용하고 인증정보는 Git 제외 작업공간에 둔다.
- [ ] Step3: CLI·non-web profile·main 종료 처리·세 로컬 profile 상호 배제 구현. 로컬 오류는 구조화 결과만 출력.
- [ ] Step4: 관련 시험 GREEN 후 실제 MySQL 포함 전체 Java·bootJar → 생략0. 실제 JAR import/approve/publish/export/retry·파일 실패/충돌/미등록·혼합 profile을 실행하고 stdout/exit/hash/DB dump 불변 확인.
- [ ] Step5: `feat: add local snapshot export command` 커밋.

### Task 3: 안내·전체 리뷰·PR

**Files:** Modify `backend/README.md`, `backend/TASK.md`, `backend/docs/review-publication.md`, 루트 `README.md`의 현재 범위.

**Interfaces:** 구현된 명령·오류·파일 계약을 설명하며 기존 공개 API 계약은 유지.

- [ ] Step1: 한국어 실행 예·출력 이름/해시 검증·재시도·DB와 파일 성공 분리·hard link 필요·미완료를 기록.
- [ ] Step2: Python 전체·npm lint/test/build, 실제 MySQL 포함 Java 전체·bootJar 결과 확인. fixture/public API 회귀·JAR 원문 제외 유지.
- [ ] Step3: producer/파일 경계/프로필/복구/예외/문서를 자체 리뷰하고 한 번의 별도 전체 리뷰. 유효 지적은 RED→GREEN·전체 시험으로 수정·재검토.
- [ ] Step4: `backend/api-foundation` 대상 PR. 최신 CI·자동 리뷰·사람 지적 유효성 검토→유효 미해결0일 때 expected-head 병합. main PR은 검증·설명만 갱신.
- [ ] Step5: 소유한 테스트 DB·임시 인증정보·이 계획 작업공간만 정리. 실자료·AI 추출·운영 배포를 완료로 표시하지 않는다.
