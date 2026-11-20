# Spring 계산 CLI 연결 계획

## 목표·기준

PR #8이 병합된 `b3095ad`를 기준으로, 실제 DB snapshot의 public matches를 Python C01~C10 계산에 연결한다. 현재503 CALCULATOR_NOT_READY는 연결 준비 전 상태다. Python 계산·기존 fixture·I03 사실 조회를 유지하고 Java에 별도 후보 판정을 만들지 않는다.

기준: [계산 연결 계약](../../../contracts/calculation-bridge.md), [백엔드 TASK](../../../backend/TASK.md), [계산 명세](../../spec/04_계산규칙과기술설계.md). 기술은 Java21·Spring Boot3.5.16·MySQL8.4.13·Python3.13이며 새 의존성은 없다. main은 사람 병합, 그 외 PR은 CI·전체 자체 리뷰·AI 리뷰의 유효 미해결 지적0이면 병합한다.

## 연결 경계

- `SnapshotNoticeService.matches`의 모드·snapshot·지점 검증 후, 원본 canonical checksum·고정 사실·출처·검토 좌표와 정규화한 요청을 조립한다. checksum은 재직렬화한 JSON으로 바꾸지 않는다. 공개본/retired 검증과 REPEATABLE_READ 일관성은 짧은 읽기 경계에서 유지하고 DB 명세에 따라 트랜잭션·연결을 반환한 뒤 Python을 호출한다.
- current의 기준 시각은 서버 Clock에서 한 번 정하고 KST anchor를 만든다. replay는 snapshot의 고정 anchor/reference/cutoff/fidelity를 사용한다. data_kind·규칙·사전 버전은 같은 snapshot에서 가져온다.
- Java ProcessBuilder는 서버 설정의 Python 실행 파일·저장소 루트 workdir과 고정 `-m processing.matching`만 사용한다. 사용자 값은 stdin JSON으로만 전달한다. stdout·stderr·stdin 쓰기를 함께 처리하고 공통5초 제한·입출력8MiB·제한된 동시 실행을 적용한다.
- 시작 실패·비정상 종료·과다 출력·timeout·중단에서 생성한 프로세스/스트림/작업을 정리한다. 원문·명령·로컬 경로·사용자 조건·stderr는 공개 응답/로그에 넣지 않는다. retryable은 일시 장애 여부로 구분한다.
- strict UTF-8/JSON·protocol/request/snapshot/hash/rules 일치와 data 필수 구조를 검증한다. 기존 공개 사실 projection을 재사용해 반환 event/revision·사실 필드가 선택 snapshot과 같은지 확인한다. 거리·시간·분류를 Java에서 재계산하지 않는다. diagnostics를 외부 envelope에 넣지 않는다.
- 계산 실패를0건이나 fixture로 바꾸지 않는다. 외부 오류는 CALCULATION_UNAVAILABLE503 / CALCULATION_PROTOCOL_ERROR500, 기존 요청422·snapshot404/409는 계산 전 처리한다. 설정 미준비도 안전하게 처리한다. DB와 사용자 조건을 계산 요청으로 쓰거나 갱신하지 않는다.

## 구현·검증 순서

1. **프로세스 adapter**: 임시 모듈을 실제 Python 자식 프로세스로 실행하는 실패 시험부터 작성한다. 정상·한글·입력 hash·단일 JSON·빈 결과, timeout, stdin 미소비, 대량 stderr/stdout, 비정상 종료, 잘못된 UTF-8/JSON/hash/ID/버전·data 구조를 확인한다. 준비 실패와 overload도 시험한다.
2. **공개 조회 연결**: 실제 snapshot으로 calc-v1 입력을 만들고 실제 Python을 호출한다. 기존 공개 projection·출처/근거·FieldValue를 대조하며 잘못된 point/context/retired 요청은 프로세스 실행 전에 종료한다. Clock을 고정해 자정/24시간/재현을 검증한다.
3. **실제 MySQL·API**: import→승인→공개→matches, 조건 변경·취소·미상·중첩·공개 교체/복구를 실제 Python으로 시험한다. 계산 전후 DB·snapshot·head·감사 기록 불변을 확인한다. fixture와 I03 응답 회귀를 유지한다.
4. **안내·CI·검토**: 실행 파일/workdir 설정과 실제 설치·실행 예, 실패 코드·미완료를 한국어로 갱신한다. Python 전체, Java 전체·실제 MySQL·bootJar, 기존 npm 검사와 실제 JAR HTTP smoke를 실행한다. 전체 producer/소비자/예외/자원 정리를 자체·별도 리뷰하고 유효 지적을 수정·재검증한다.
5. backend/api-foundation 대상 PR을 제출한다. 최신 SHA CI·자동 리뷰·도착한 사람 리뷰의 유효 지적0을 확인하고 병합한다. main PR은 통합 검증·설명만 갱신하고 사람 병합 대기를 유지한다.

## 전체 리뷰 초점

stdin 쓰기 자체의 무한 대기, stdout/stderr 파이프 교착, 공통 deadline·인터럽트·동시 요청·자식 프로세스/스레드 잔존, 원본 checksum과 전송 바이트 hash의 혼동, 자정 시각 고정, RR 도중 head 변경, 악성/손상된 응답의 비공개 필드·오염·잘못된 사실 반영, 선택되지 않은 후보와 overlap 참조, retryable 분류, 실제 Python 부재를 시험 생략으로 숨기는 경로를 직접 확인한다. 실자료 AI·프런트·운영 배포·실사용 성능 평가는 이 연결 시험으로 완료 처리하지 않는다.
