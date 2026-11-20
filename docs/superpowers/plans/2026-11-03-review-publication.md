# 검토 승인·공개 처리 구현 계획

**목표:** 비공개 검토 revision을 승인·반려하고 검증된 불변 snapshot으로 공개 포인터를 전환·복구한다.

**구조:** 기존 Spring JDBC·서비스 트랜잭션·검토본 검증을 재사용한다. `local-publication` 일회성 명령으로만 실행하며 공개 HTTP 라우터는 추가하지 않는다. 원문 읽기·공개 JSON 생성은 쓰기 트랜잭션 밖에서 수행하고, commit 직전 상태를 다시 확인한다.

**기술 구성:** Java21·Spring Boot3.5.16·MySQL8.4.13·Gradle8.14.3. 새 의존성 없음.

**기준 명세:** `docs/spec/03_데이터와AI.md` D01/D03/D06/D07, `docs/spec/09_DB설계와트랜잭션.md` DB04~DB08, `docs/spec/02_화면과모바일UX.md` S10.

## 범위와 제약

- 승인·반려는 새 revision과 감사 기록을 만들며 기존 revision은 수정하지 않는다. 승인된 revision의 public intent는 공개 후보 자격이며 실제 공개 포인터 변경과 구분한다.
- 승인·공개 때 원문 hash·근거·참조·사용권 allowed·성공 확인 기록을 검증한다. 미상 사실을 채워 넣지 않고 원문 확인의 24시간 경과는 추후 계산 경로에서 처리한다.
- publish 입력은 승인 revision 목록, 검토된 동일 구역 5지점, 버전·current/replay 문맥이다. 빈 사건 목록도 허용하며 공개 이력은 V2 `publication_audits`에 남긴다.
- 공개 JSON은 허용 필드만 선택한다. 원문 전체·AI 원출력·평가·검토자·로컬 경로·수정 전 비공개 값은 포함하지 않는다. 상세 API용 계산·분류 결과는 만들지 않는다.
- canonical JSON은 UTF-8 원문과 별도 SHA-256으로 보존한다. 공개 포인터는 expected head version으로 조건부 전환하고 실패하면 snapshot·지점 변경·감사 기록까지 rollback한다.
- rollback은 같은 채널에서 실제 공개한 이전 snapshot만 선택한다. checksum·채널을 검증하고 공개 포인터와 감사 기록만 바꾼다.
- 프런트·Python·공개 API 계약과 기존 V1 migration은 유지한다. 실제 DB 조회 API·계산 adapter·관리 UI·운영 배포·파일 export는 후속 단계다.

## 중점 검토 항목

1. 승인 후 수정/동시 승인 → 예상 revision 충돌, 이전본·공개본 보존.
2. 미승인·사용권 미검토·원문 변경·원문 확인 없음·자료 종류/버전/구역 불일치 → 승인/공개 차단.
3. 공개 JSON의 중첩 private 필드·검토자·경로·원문·소수 정밀도 → whitelist 및 정확한 값 보존.
4. 공개 포인터 전환 후 감사 저장 실패 → 전체 rollback. 동일 head 동시 공개는 한 건만 성공.
5. replay cutoff·지점 버전·복구 checksum/채널 오류 → 이전 공개본 유지. 복구는 재계산/원문 파일 접근 없이 가능.

## 작업 1. 명령 규격·저장본 재검증

대상: `publication/PublicationCommand.java`, `PublicationCommandReader.java`, `PublicationException.java`, 기존 `ReviewedImportReader.java`·`ReviewedBatch.java`·`ReviewedImportRepository.java`, 명령 단위 시험.

인터페이스: `PublicationCommandReader.read(Path)` → approve/reject/publish/rollback 명령. `ReviewedImportReader.validateStored(JsonNode, Path)`는 저장본의 승인 상태까지 검증하되 일반 import의 draft/hidden 제한은 유지한다.

- [x] strict JSON·필수/null·숫자·5지점·문맥 검증 실패 시험 작성·실행.
- [x] 기존 Unicode/hash/근거 검증을 공유하고 명령 규격 구현.
- [x] 기존 import 시험과 새 단위 시험 통과.

## 작업 2. 승인·공개·복구 트랜잭션

대상: `repository/PublicationRepository.java`, `service/PublicationService.java`, `publication/PublicationContent.java`, `V2__add_publication_audits.sql`, `PublicationMySqlTest.java`.

인터페이스: `PublicationService.execute(PublicationCommand, Path sourceRoot, String actor)` → 작업 결과. repository는 기존 revision 저장 경로와 V2 공개 감사 테이블을 사용한다.

- [x] 실제 MySQL에서 새 승인/반려·동시 충돌·공개 차단·공개/복구·late failure rollback 시험을 먼저 작성·실행.
- [x] 공개 준비 → 상태 재확인/잠금 → snapshot/지점/포인터/감사 commit 구현.
- [x] 공개 whitelist·canonical checksum·빈 목록·replay·포인터 동시 변경·이전본 복구 검증.

## 작업 3. 일회성 명령·인계

대상: `publication/LocalPublicationCommand.java`, `application-local-publication.yml`, 기존 main·프로필 보호, `backend/examples/`·`backend/docs/review-publication.md`·README/TASK.

- [x] 명령의 성공·충돌·검증 오류·비웹 실행·혼합 local 프로필 차단 시험.
- [x] 합성 예제로 import → 승인 → 미리보기 → 공개 → 복구를 실행하고 원문·예제 JAR 미포함 확인.
- [ ] 전체 시험·빌드·별도 코드 검토·CI·자동 리뷰를 거쳐 후속 PR 생성. 문서는 한국어로 작성하고 기술 토큰은 보존.

## 검증 기록과 구현 판단

2026-11-03 로컬 MySQL8.4.13 전용 DB에서 Java53개를 전부 실행·통과했다. 생략0개이며 Node15개·공통 계약 예제8개·lint·build·bootJar도 통과했다. 실행 JAR로 import → 승인 → 미리보기(쓰기0건) → 공개 → 0건 공개 → 이전본 복구와 충돌3/검증 오류2 종료 코드를 확인했다. 예제·원문은 JAR에서 제외했다. 별도 독립 코드 검토의 구체적 결함은 없었다.

게시일만으로 원문 버전의 당시 존재를 추정하지 않도록 replay의 collected_at을 cutoff 이하로 제한했다. cutoff 이후 수집본은 별도 역사 근거 규격을 마련한 뒤 지원한다. public JSON 파일 export·실제 API 조회·Python·관리 UI·운영 배포는 이번 단계에서 구현하지 않는다. 기반은 PR #5를 포함한 PR #4의 d58ba0a이며 main 병합은 사람 검토를 따른다.
