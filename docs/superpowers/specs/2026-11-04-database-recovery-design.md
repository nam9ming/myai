# B08 개발 DB 백업·복구 검증

## 목적·방식

[WBS B08](../../spec/10_인원별WBS.md)과 [DB 명세](../../spec/09_DB설계와트랜잭션.md)의 스키마·코드 버전·DB 백업·snapshot checksum 동시 기록, 새 전용 DB 복구·재기동 인계를 검증한다. 기존 Java/Python 업무 코드는 유지한다. 사용자가 위임한 자율 설계·에이전트 분담으로 진행하며 아래 선택은 작성자의 판단이다.

새 production 백업 서비스·HTTP API 대신 **MySQL 표준 dump/restore·tar·기존 서비스의 합성 통합 시험과 한국어 runbook**을 추가한다. Compose 볼륨 유지나 공개 포인터 rollback만으로 DB 복구를 검증할 수 없다. 임의 DB를 받는 범용 도구는 불필요하고 실제 서버 자동 복구는 권한/경로/정책이 미확정이다.

## 격리·DB

- 테스트 전용 `RecoveryDatabase`는 매번 UUID 이름·소유 라벨·임시 자격증명으로 MySQL8.4.13 컨테이너를 만든다. localhost 임의 포트·전용 `myai_recovery` schema만 사용하고 기존 DB_URL/서버·컨테이너를 받지 않는다.
- dump/restore/cleanup 전 소유 라벨·이름·ID를 확인한다. 복원 대상 schema의 테이블이 하나라도 있으면 SQL 실행 전 거부한다. 잘못된 SQL은 성공으로 처리하지 않고 부분 대상은 버린다. SQL 전체를 원자적으로 되돌린다고 주장하지 않는다.
- `mysqldump --single-transaction --no-tablespaces --set-gtid-purged=OFF --hex-blob --default-character-set=utf8mb4 --skip-comments --skip-dump-date --order-by-primary`로 단일 schema를 덤프한다. `--databases`/`--all-databases`·system schema·`--force`는 쓰지 않는다. 계정·권한·binlog/PITR는 별도다.
- 애플리케이션과 다른 쓰기·DDL을 멈춘 뒤 DB와 선택 원본을 함께 백업한다. single-transaction만으로 DB·파일의 공동 일관성을 보장하지 않는다. 실제 백업 주기·접근자·보존·RPO/RTO는 정하지 않는다.
- 자격증명은0700 테스트 root의0600 env 파일과 프로세스 환경에서만 쓰고 명령 로그·proof·SQL/파일 백업에 넣지 않는다. stdout/stderr와 stdin은 파일로 연결해 pipe 교착을 피하고 프로세스 제한 시간·자식 정리·자기 컨테이너 보상 정리를 둔다.

## 원본·검증

기존 `SourceReviewFixtures`로 D03·성공/실패 D05·사람 인계 D06·source_reviews·승인/공개/복구 이력을 만든다. 실제 사람·공지·키·외부 AI/API를 사용하지 않는다. D09 pack/사진/출력이나 기존 private 디렉터리를 자동 수집하지 않는다.

DB의 D05 raw_ref·사람 인계 directory는 절대 경로 identity다. 선택한 새 합성 materials root를 표준 tar로 별도 보관하고 파일 bytes·상대경로·POSIX mode를 모두 기록한다. D05 frozen0400/0500·handoff 전체0400/0500을 유지한다. 원본 경로 부재/다른 경로 복원에서는 후속 검증이 거부됨을 확인하고, **같은 실제 절대 경로**에 복원한 뒤 기존 Java/Python reader와 정확 재등록/재import로 검증한다. SQL 문자열 치환·symlink 우회·새 identity 발급은 복구로 세지 않는다.

새 서버에 SQL을 재적재한 뒤 Flyway 이력 포함 schema의 모든 테이블·모든 열/행을 null·Unicode·timestamp·원문 JSON을 보존한 형태로 비교한다. `source_reviews`·부모 운영 번호/hash·실패 D05·canonical snapshot·head/audit도 빠뜨리지 않는다. 같은 조건의 실제 HTTP config/detail/matches와 snapshot export를 재확인한다. 동적 envelope 시각만 명시적으로 정규화하고 계산은 고정 replay 문맥/같은 request ID를 쓴다. 재기동 뒤에도 seed/행이 늘지 않아야 한다.

## 산출물·한계

- test-only Docker/SQL helper와 경계 시험, 별도 합성 애플리케이션 복구 통합 시험.
- Git 제외 `build/recovery-proof/<UUID>` 또는 명시한 `MYAI_RECOVERY_PROOF_ROOT/<UUID>`에 dump·선택 materials tar·schema/code/snapshot/hash/mode·전후 DB/API 증거만 남긴다. 자격증명은 제외한다. CI의 공개 artifact에는 추가하지 않는다.
- `backend/docs/backup-recovery.md`에 환경변수 이름·표준 백업/새 빈 대상 복원·같은 경로/권한·기동/정지·검증·실패/미완료를 안내한다. 기존 전체 DB 테스트는 자료를 지우므로 복원한 DB에 실행하지 않는다.
- 별도 운영 정책·서버 경로·계정 재설정·실자료 승인/40문서/D09·main 병합/배포·Windows/WORM/전원 중단 내구성은 미완료다. 합성 복구를 실제 연구실 재해복구로 표현하지 않는다.

표준 동작 근거: [MySQL8.4 mysqldump](https://dev.mysql.com/doc/refman/8.4/en/mysqldump.html), [단일 schema SQL 복원](https://dev.mysql.com/doc/refman/8.4/en/reloading-sql-format-dumps.html).
