# 검토 JSON import 구현 계획

**목표:** 검토 JSON을 MySQL에 원자적으로 저장한다. 중복 재입력이나 충돌·실패가 발생해도 기존 자료를 보존한다.

**구조:** 로컬 `local-import` 프로필의 일회성 명령에서 파일과 근거를 검증한 뒤 Spring 서비스 트랜잭션으로 기존 V1 테이블에 저장한다. 이미 포함된 Spring JDBC를 사용하며 공개 HTTP 라우터는 추가하지 않는다.

**기술 구성:** Java21, Spring Boot3.5.16, MySQL8.4.13, Gradle8.14.3. 새 의존성은 추가하지 않는다.

**기준 명세:** `docs/spec/03_데이터와AI.md` D03~D06, `docs/spec/09_DB설계와트랜잭션.md` import·수정 트랜잭션 및 DB02~DB04/DB07.

## 제약과 범위

- D03/D04/D06을 담는 로컬 전송 규격 `reviewed-import-v1`을 문서화한다. 기존 공개 API·Python 계약은 변경하지 않는다.
- 원문·cleaned text SHA-256, Unicode code point 근거와 필드·참조·날짜·좌표·검토 상태를 검증한다. 입력/원문 파일은 각각 최대8MiB로 제한하며 원문 경로는 설정한 source root 내부의 일반 파일만 허용한다.
- `draft`/`needs_review` 및 `hidden`만 import한다. 승인·snapshot 생성·공개 전환은 후속 단계이며 이 명령이 수행하지 않는다.
- 원본 바이트·schema·source kind가 같으면 기존 결과를 반환한다. revision은 append-only로 보존하며 예상 revision과 조건부 포인터 갱신으로 동시 변경을 차단한다.
- 원문 읽기·hash 검증은 DB 트랜잭션 밖에서 수행한다. 배치·문서·원문 확인·revision·감사 기록은 하나의 트랜잭션으로 저장한다.
- PR #4 위 후속 브랜치에서 직접 구현한다. 기존 V1 migration·공개 fixture 응답은 유지한다.

## 중점 검토 항목

1. emoji 앞뒤의 code point offset과 근거 hash 불일치 → 거부.
2. 원문 경로 이탈·symlink 이탈·중복 JSON 키·추가 필드·8MiB 초과 → 거부.
3. 동일 파일 동시 import → 동일 batch/revision, 중복 없음.
4. 배치 후반 revision 충돌 → 선행 문서·사건·감사·batch까지 rollback.
5. 다른 내용으로 같은 문서/revision ID 재사용·동시 수정 →409 성격의 충돌, 이전본 유지.

## 작업 1. 입력 계약과 검증

대상 파일: `backend/examples/`, `backend/src/main/java/kr/ac/myai/backend/importing/ReviewedImportReader.java`, `ReviewedBatch.java`, `ImportException.java`, `backend/src/test/java/kr/ac/myai/backend/ReviewedImportReaderTest.java`, `backend/docs/reviewed-import.md`.

인터페이스: `ReviewedImportReader.read(Path file, Path sourceRoot)`는 검증된 불변 `ReviewedBatch`를 반환한다. 입력 hash는 실제 UTF-8 파일 바이트로 계산하고 payload는 정보 손실 없이 보존한다.

- [x] 합성 D03/D04/D06 예제와 독립 기대값으로 실패 시험 작성·실행.
- [x] strict JSON/shape·hash·code point·참조·필드 의미 검증 구현.
- [x] 단위 시험 전체 통과.

## 작업 2. 원자적 저장과 재입력

대상 파일: `backend/src/main/java/kr/ac/myai/backend/repository/ReviewedImportRepository.java`, `service/ReviewedImportService.java`, `backend/src/test/java/kr/ac/myai/backend/ReviewedImportMySqlTest.java`.

인터페이스: `ReviewedImportService.importBatch(ReviewedBatch batch, String actor)`는 batch ID, revision ID 목록과 기존 결과 여부를 반환한다. repository는 V1 테이블만 사용한다.

- [x] 실제 MySQL의 중복·새 revision·문서 충돌·배치 rollback·동시 import/수정 시험을 먼저 작성·실행.
- [x] parameterized SQL·서비스 트랜잭션·조건부 포인터 갱신·감사 기록 구현.
- [x] 이전 revision·공개 snapshot 보존과 미공개 API503 확인.

## 작업 3. 로컬 명령과 인계

대상 파일: `importing/LocalImportCommand.java`, `MyaiBackendApplication.java`, `application-local-import.yml`, 관련 시험, `backend/README.md`, `backend/TASK.md`, 루트 README.

- [x] 일회성 명령의 성공·재입력·검증 실패·비정상 종료 코드 및 공개 라우터 미등록 확인.
- [x] JAR에 원문/검토 예제가 포함되지 않도록 확인하고 실행법·상태 제한·원문 보존 책임 문서화.
- [x] 전체 Java/MySQL·Node·계약 시험과 빌드 실행, 후속 PR 생성 및 1차 CI/자동 리뷰 확인.

## 검증 기록

로컬 MySQL8.4.13 전용 컨테이너에서 Java 시험 35개를 모두 실행·통과했다. Node 시험 15개와 계약 예제 8개, lint·build도 통과했다. 실행 JAR의 정상/재입력/검증 실패/충돌 종료 코드 0/0/2/3과 예제 미포함을 확인했다. 검토 과정에서 찾은 `known` 빈 목록 처리, 미상 날짜의 시간 구간, 중첩 객체 키의 Unicode, 소수 정밀도 오류는 각각 회귀 시험 실패를 확인한 뒤 수정했다. 부분 날짜·시간과 소수 정밀도를 보존하며 모순된 완전 구간은 거부한다. backend Markdown 전체와 이 계획서는 한국어 윤문 후 기술 토큰·명령어·수치 보존을 검사했다.

후속 PR은 #5이며 PR #4를 기반으로 한다. CI와 OpenAI 자동 리뷰 결과는 PR 검사와 리뷰 댓글에서 확인한다. 승인·공개·Python 계산·운영 배포는 후속 작업이다.
