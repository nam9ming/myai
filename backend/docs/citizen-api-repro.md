# 시민 공개 API 합성 재현 자료

공개 목록·상세·오류·이력의 실제 합성 HTTP 응답을 화면 개발과 반복 검증에 사용한다. GitHub Actions에서 검사한 커밋의 `citizen-api-repro-<checkout SHA>`를 내려받거나 전용 시험 DB에서 같은 시나리오를 다시 실행한다. 요청과 응답은 [시민 API 계약](../../contracts/citizen-api.md)을 따른다.

## 실행과 초기화

Java 21, 저장소 Gradle Wrapper, Spring Boot 3.5.16, MySQL 8.4.13, Python 3.13과 Docker가 필요하다. Java에 `DB_URL`, `DB_USERNAME`, `DB_PASSWORD`를 환경변수로 전달하고 `MYAI_MYSQL_TESTS=true`를 켠다. 전용 DB 이름은 `myai_test` 또는 `myai_citizen_test`이며, 매번 새 빈 DB를 사용한다. 기본 개발용 `myai_dev`와 운영·공용 DB를 이 시험에 연결하지 않는다.

저장소 루트의 Bash에서 실행한다. 예제는 임의 포트와 시험용 임시 암호를 사용한다. 종료 시 이 실행이 만든 컨테이너를 정리한다. JAR 시험은 별도의 `myai_recovery` 컨테이너를 만들고 직접 정리한다.

```bash
(
  set -eu
  export MYSQL_PASSWORD="$(python3.13 -c 'import secrets; print(secrets.token_hex(16))')"
  export MYSQL_ROOT_PASSWORD="$(python3.13 -c 'import secrets; print(secrets.token_hex(16))')"
  export DB_USERNAME=myai_repro DB_PASSWORD="$MYSQL_PASSWORD" MYAI_MYSQL_TESTS=true
  repro_container=$(docker run --rm -d -p 127.0.0.1::3306 \
    -e MYSQL_DATABASE=myai_test -e MYSQL_USER=myai_repro \
    -e MYSQL_PASSWORD -e MYSQL_ROOT_PASSWORD mysql:8.4.13)
  trap 'docker stop "$repro_container" >/dev/null' EXIT
  for ((attempt=0; attempt<90; attempt++)); do
    if docker exec "$repro_container" mysqladmin ping -h 127.0.0.1 --silent; then
      break
    fi
    sleep 1
  done
  test "$attempt" -lt 90
  binding=$(docker port "$repro_container" 3306/tcp)
  export DB_URL="jdbc:mysql://127.0.0.1:${binding##*:}/myai_test?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8"
  ./backend/gradlew -p backend test \
    --tests '*CitizenNoticeMySqlTest' --tests '*CitizenNoticeJarMySqlTest' --no-daemon
)
```

이 시험은 전용 DB에 Flyway를 적용하고 시나리오별 합성 공개본을 만든다. `MYAI_MYSQL_TESTS=true`에서는 Gradle이 시험을 매번 실행한다. 위 명령을 다시 실행하면 새 DB와 새 결과 디렉터리가 생긴다. 서버·DB가 종료된 뒤에도 아래 파일을 읽을 수 있다.

## 확인할 응답

| 시나리오 | 건수 | 기대 결과 |
| --- | ---: | --- |
| `mysql-education`, `mysql-support`, `mysql-culture`, `mysql-construction_traffic`, `mysql-living` | 10 | HTTP 200 목록과 상세의 공개본·공지·출처 일치. 신청기간과 진행일정, 명시 비용과 미기재 비용 보존 |
| `mysql-not-ready` | 1 | HTTP 503 `PUBLIC_DATA_NOT_READY` |
| `mysql-empty-and-retired` | 6 | HTTP 200 빈 목록, HTTP 409 교체본 ID가 있는 이전 목록·상세, HTTP 404 공지/공개본 누락, HTTP 200 복구 상세 |
| `mysql-multi-source` | 1 | HTTP 200 복수 분야·원문·공개 근거 |
| `mysql-history-unavailable` | 1 | HTTP 200 현재 사실·출처, `history.status=unavailable`, `CITIZEN_HISTORY_TOO_LARGE`. 두 공개본의 파일 크기 합이 8MiB를 초과한다. |
| `jar-history` | 5 | SELECT 전용 계정의 실제 JAR에서 목록·상세·두 이력 페이지와 HTTP 422 잘못된 조건 |

Y01에는 분야·복수 분류, Y02에는 목록/상세·0건·오류, Y03~Y05에는 합성 공지의 일정·비용·대상/조건 원문, Y06·Y08에는 확보 이력과 공개 교체·복구, Y10에는 재생성 절차를 제공한다. 시점별 모집 판정, 검색/복합 필터, 개인 설정(Y07), 실제 Flutter 화면(Y09), 팀 인수와 실자료 평가는 후속 확인 항목이다. 전체 기준은 [시험·평가·인수 기준](../../docs/spec/05_시험과인수기준.md)을 따른다.

## 파일로 대조하기

시험 결과는 `backend/build/repro/citizen-api-v1/`의 새 실행 디렉터리에 쓴다. `manifest.json`의 `response_checks=passed`를 확인한 뒤 파일을 사용한다. CI는 전체 시험과 빌드가 성공한 뒤 묶음을 14일간 보관한다.

- `<case>.request.json`은 GET과 상대 URI를 담는다. `<case>.actual.json`에는 수신한 UTF-8 응답 바이트를 그대로 저장한다. HTTP 상태는 manifest의 해당 case에서 확인한다.
- `<case>.expected.json`에는 기대 HTTP 상태와 검증할 JSON Pointer별 값이 있다. 공지·출처와 이력 전후는 공개본·감사 이력에서, 오류와 페이지 조건은 시험 입력과 계약에서 구한다.
- `snapshots/`에는 기존 내보내기 서비스가 저장한 공개 snapshot을 둔다. UUID·SHA-256을 파일명 및 manifest와 비교한다.
- manifest에는 시나리오·실행 버전·응답 상태·공개 ID·상대 경로·크기·SHA-256이 있다. CI에서 실행한 소스는 checkout SHA로 식별한다. 로컬 결과를 전달할 때는 `git rev-parse HEAD`와 로컬 변경 여부를 함께 적는다.

재실행하면 UUID, 공개 시각, `generated_at`과 오류 `request_id`가 달라질 수 있다. 매 실행의 기록끼리 비교한다. 상세 요청에는 목록에서 받은 `snapshot_id`·`event_id`, 이전 이력 요청에는 응답의 `next_before_version`을 사용한다. 새 실패를 전달할 때는 시나리오·커밋·manifest·기대/실제 상태와 비교가 어긋난 JSON Pointer를 함께 적는다.

응답 묶음은 오프라인 연동 검토용이다. 원문 작업본, 로컬 관리 자료, DB 설정값과 로그의 전달 범위는 기존 저장소 규칙을 따른다. [작업·인계 방식](../../CONTRIBUTING.md)
