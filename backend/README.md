# 백엔드 기초

Java 21 / Spring Boot **3.5.16** / Gradle Wrapper **8.14.3** / MySQL **8.4.13**.
`cwmp`, `debate-bff`의 Gradle·controller/service/DTO 분리·생성자 주입·예외 처리·CORS 패턴을 참고했다.
기존 프로젝트는 Java17·Boot3.2.2이므로 빌드 버전과 오류 형식은 myai 명세에 맞췄다.

## 구현 범위

- `/health`: 프로세스 기동을 확인하는 liveness다. DB·Python 준비 완료 여부는 확인하지 않는다.
- `GET /api/v1/config`, `POST /api/v1/matches`, `GET /api/v1/events/{id}?snapshot_id=…`. 기본 `public` 프로필은 실제 공개 snapshot을 조회하고 matches는 Python C01~C10 계산에 연결한다. [공개 조회 안내](docs/public-snapshot-api.md)를 따른다.
- `fixture` 프로필에서 `contracts/examples/`의 합성 응답을 제공한다. Gradle이 필요한 JSON만 JAR에 포함하므로 별도 복사본을 수정하지 않는다.
- fixture matches는 **matches-request.json의 고정 조건만 지원**한다. 동일 snapshot 지정·selection/sort 기본값도 허용하며 다른 조건은 `503 CALCULATOR_NOT_READY`다. public matches는 선택한 공개본의 지점·영업조건·유형·정렬·상태를 실제 Python으로 계산한다.
- fixture의 기준일·generated_at은 예제에 고정된 합성 값이다. 실제 현재 시각 기반 계산·AI 처리 결과가 아니다.
- 요청 검증·공통 오류·32KiB JSON 본문 제한·개발 origin CORS.
- [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)의 13개 기초 테이블, FK·unique·검토 상태 제약, UTC·낙관적 잠금용 열과 Flyway V1.
- `local-import` 일회성 명령은 D03/D04/D06 검토 JSON, 원문/본문 hash, Unicode 근거와 참조를 검증한다. Spring JDBC로 원자적으로 저장하며 동일 파일 재입력, append-only revision, 조건부 작업 포인터 갱신과 감사 기록을 지원한다. `draft/needs_review`·`hidden`만 저장한다.
- `local-publication` 일회성 명령은 승인·반려 revision, 읽기 전용 공개 JSON 미리보기, 불변 snapshot 공개·복구를 처리한다. V2 `publication_audits`에 공개 포인터 변경 이력을 남기며 충돌·실패 시 이전 공개본을 보존한다.
- `local-export`는 이미 공개한 snapshot을 고정 UTF-8/hash 그대로 파일로 내보낸다. 파일 실패는 DB 공개 성공과 분리하고 동일 파일 재실행·충돌 보존을 지원한다. [내보내기 안내](docs/review-publication.md#snapshot-json-내보내기)를 따른다.

`source-import-v1`은 local-import에서 D03만 먼저 등록한다. `local-extraction`은 Python archive를 검증해 D05 성공/실패·nullable 모델·정밀 metadata/receipt 원본을 불변 등록한다. [D03/D05 연결 안내](docs/extraction-run-import.md)를 따른다. V3는 기존 행을 보존하며 검증 정보 없는 legacy를 D06 origin으로 승격하지 않는다.

**미구현:** 관리 UI, 운영 배포·실자료 평가. 저장 계층에는 이미 포함된 Spring JDBC를 사용한다. JPA entity/일반 CRUD와 Java 후보 판정 엔진은 추가하지 않았다. 승인·공개·복구·계산 연결·내보내기는 합성 자료와 전용 DB로 시험하며 실제 자료의 사실성·이용권한 검토를 완료한 상태는 아니다.

## DB 없이 합성 API 실행

JDK21을 준비한 뒤 저장소 루트에서 실행한다.

```bash
cd backend
./gradlew bootRun --args='--spring.profiles.active=fixture'
```

Windows에서는 `gradlew.bat`을 사용한다. macOS에서 여러 JDK를 쓰면 `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`로 선택한다. 기본 포트는 8080이며 `PORT`로 변경한다.

다른 터미널을 열고 **저장소 루트**에서 응답을 확인한다.

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/v1/config
curl -H 'Content-Type: application/json' --data-binary @contracts/examples/matches-request.json http://localhost:8080/api/v1/matches
curl 'http://localhost:8080/api/v1/events/48bb73cf-3cd9-5e4f-895e-9ba9ce62560f?snapshot_id=37d9f0b8-424f-5145-9329-e71ffd6413e3'
```

응답은 `data_kind=synthetic`, null, 원문·대상·예외 필드를 유지한다. 다른 snapshot이나 미등록 사건을 요청하면 404, 잘못된 입력은 422, 본문 크기 초과는 413을 반환한다. 오류 응답에는 `error.{code,message,field_errors,retryable}`와 `request_id`를 담는다. `/local` 라우터는 등록하지 않았다.

## MySQL 기초 실행

실제 DB 프로필에는 Docker 또는 별도 MySQL8.4 서버가 필요하다. 전용 개발 DB만 사용하고 기존 연구실 DB·계정을 연결하지 않는다.

```bash
cd backend
cp .env.example .env
# .env의 DB_PASSWORD와 MYSQL_ROOT_PASSWORD를 직접 설정
docker compose --env-file .env up -d --wait
```

Compose는 `myai_dev`, 전용 사용자와 영구 볼륨을 만들고 MySQL 포트를 127.0.0.1에만 연결한다. 3306이 사용 중이면 `.env`의 `MYSQL_PORT`와 `DB_URL`을 함께 바꾼다. Compose가 읽은 `.env` 값은 Java 프로세스에 전달되지 않는다. 다음처럼 환경변수를 별도로 지정한다.

```bash
export DB_URL='jdbc:mysql://localhost:3306/myai_dev?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8'
export DB_USERNAME=myai
read -rs DB_PASSWORD; export DB_PASSWORD; echo
./gradlew bootRun
```

기본 `public` 프로필은 DB 연결·Flyway 적용 후 기동한다. 공개 전 config는 `503 PUBLIC_DATA_NOT_READY`, 공개 후 config·상세는 고정 snapshot을 조회한다. matches는 snapshot·지점을 검증한 뒤 아래 설정의 Python을 호출한다. fixture로 자동 전환하거나 JSON seed를 넣지 않는다.

스키마 생성은 Flyway만 담당하고 JPA는 `ddl-auto=validate`를 사용한다. canonical JSON은 LONGTEXT 원문과 별도 checksum으로 보존한다. ID/hash는 ASCII 대소문자를 구분한다. JDBC session·Hibernate는 UTC를 사용하고 격리 수준은 REPEATABLE READ로 설정한다. 적용된 V1·V2·V3를 수정하지 말고 변경 사항은 후속 migration으로 추가한다. 개발 DB는 `docker compose stop`으로 종료하며 볼륨을 삭제하지 않는다.

## Python 계산 연결

Python3.13과 같은 배포 버전의 `processing/` 소스가 필요하다. JAR에 Python을 포함하지 않으므로 서버에도 소스를 배치한다. DB 환경변수를 설정한 터미널에서 **저장소 루트 기준**으로 실행한다.

```bash
export MYAI_PYTHON_WORKDIR="$PWD"
export MYAI_PYTHON_EXECUTABLE=python3.13
./backend/gradlew -p backend bootRun
# 또는 java -jar backend/build/libs/myai-backend-0.1.0.jar
```

| 환경변수 | 기본값·조건 |
|---|---|
| `MYAI_PYTHON_WORKDIR` | 필수: `processing/`이 있는 저장소 루트의 절대 경로 |
| `MYAI_PYTHON_EXECUTABLE` | `python3.13`. 가상환경이면 해당 Python 실행 파일 경로 |
| `MYAI_CALC_TIMEOUT_MS` | `5000`. 1~60000ms, stdin 쓰기·프로세스 종료·출력 읽기에 공통 적용 |

Java는 고정 인자 `-m processing.matching`과 JSON stdin만 사용한다. 입력·stdout 각각8MiB, stderr64KiB, 동시 프로세스4개로 제한하며 timeout·interrupt·실패 시 요청별 프로세스와 I/O 작업을 정리한다. 정리에 필요한 짧은 대기 시간이 제한 뒤 추가될 수 있다. 경로·명령·stderr·사용자 조건은 외부 오류에 넣지 않는다.

원본 snapshot checksum과 실제 전송 바이트 hash를 구분하고 ID·버전·응답 형식·사실 필드·참조/집계 일관성을 검사한다. 시간·거리·후보 판정은 Python이 담당한다. 계산 요청은 DB와 사용자 조건을 저장하지 않는다.

계산 입력과 원본 checksum은 짧은 읽기 전용 REPEATABLE READ 트랜잭션에서 함께 확보한다. DB 연결을 반환한 뒤 Python을 실행하며, 실행 중 공개 head가 교체되어도 이미 선택한 고정 사실을 섞지 않는다. 이후 이전본을 다시 요청하면409다.

설정 미준비·기동/비정상 종료·출력 초과는 `503 CALCULATION_UNAVAILABLE`, retryable=false다. timeout·interrupt·실행 한도 초과는 같은 코드와 retryable=true다. 응답 JSON/hash/ID/버전/사실 불일치는 `500 CALCULATION_PROTOCOL_ERROR`, retryable=false다. `health`200은 계산 준비 완료를 뜻하지 않는다. 자세한 입출력은 [CLI 계약](../contracts/calculation-bridge.md)을 따른다.

## 검토 JSON 로컬 import

DB를 준비한 뒤 저장소 루트에서 실행한다.

```bash
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=backend/examples/reviewed-import.json \
  --myai.import.source-root=backend/examples \
  --myai.import.actor=synthetic-reviewer
```

위 파일은 합성 자료이며 원문·검토 예제는 JAR에 넣지 않는다. 실제 작업본은 `data/private/`에 보관하고 해당 경로를 지정한다. HTTP 서버 없이 실행한 뒤 종료하며 결과 JSON은 stdout, 로그는 stderr에 출력한다. 같은 파일을 재입력하면 같은 batch/revision ID를 반환한다. approved/public은 거부하고 공개 데이터는 변경하지 않는다. 입력 규격, 상태 제한, 종료 코드와 원문 보존 책임은 [상세 안내](docs/reviewed-import.md)를 따른다.

## 검증·빌드

승인·미리보기·공개·복구 명령은 [검토 승인·공개 안내](docs/review-publication.md)를 따른다. 공개 조회는 snapshot에 고정된 지점·사건을 사용하며 최신 작업 행을 섞지 않는다. 교체된 공개본은409와 현행 ID를 반환하고, 복구하면 이전본을 다시 조회할 수 있다.

```bash
cd backend
./gradlew test bootJar
java -jar build/libs/myai-backend-0.1.0.jar --spring.profiles.active=fixture
```

일반 `test`도 실제 자식 프로세스·archive 시험에 **Python3.13**이 필요하다. 프로세스와 공개 조회의 검증·오류를 시험하며 DB 없는 fixture API·import·공개 명령 검사도 유지한다. `MySqlFoundationTest`·`ReviewedImportMySqlTest`·`PublicationMySqlTest`·`CalculationMySqlTest`·`ExtractionRunMySqlTest`는 전용 MySQL 테스트 DB와 `MYAI_MYSQL_TESTS=true`일 때 실행한다. 운영·공유 DB에서는 실행하지 않는다. CI는 매 실행 분리된 `myai_test` DB를 준비해 저장·공개·복구·실제 조회와 Python 계산을 검증한다.

`MYAI_MYSQL_TESTS=true`일 때는 외부 DB 상태를 캐시하지 않고 매번 시험을 실행한다. 검토 입력·사실 응답 예제와 실제 호출하는 Python 소스·계산 입력 예제도 Gradle 시험 입력에 포함한다.

CI의 기존 필수 검사 `check`에서 백엔드 시험과 JAR 빌드도 실행한다. 백엔드 시험이나 빌드가 실패하면 필수 검사도 실패한다. 실행 JAR는 별도 artifact로 보관한다. `CORS_ALLOWED_ORIGIN` 기본값은 `http://localhost:5173`이며 credential·임의 origin을 허용하지 않는다.

기준 문서: [기술 구성](../docs/spec/08_기술구성과연결.md), [DB](../docs/spec/09_DB설계와트랜잭션.md), [공개 계약](../contracts/README.md), [Python CLI](../contracts/calculation-bridge.md).
