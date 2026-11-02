# 백엔드 기초

Java 21 / Spring Boot **3.5.16** / Gradle Wrapper **8.14.3** / MySQL **8.4.13**.
`cwmp`, `debate-bff`의 Gradle·controller/service/DTO 분리·생성자 주입·예외 처리·CORS 패턴을 참고했다.
기존 프로젝트는 Java17·Boot3.2.2이므로 빌드 버전과 오류 형식은 myai 명세에 맞췄다.

## 구현 범위

- `/health`: 프로세스 기동 확인용 liveness. DB·Python 준비 완료를 뜻하지 않는다.
- `GET /api/v1/config`, `POST /api/v1/matches`, `GET /api/v1/events/{id}?snapshot_id=…`.
- `fixture` 프로필에서 `contracts/examples/`의 합성 응답을 제공한다. Gradle이 필요한 JSON만 JAR에 포함하므로 별도 복사본을 수정하지 않는다.
- matches는 **matches-request.json의 고정 조건만 지원**한다. 동일 snapshot 고정과 selection/sort 기본값은 허용한다. 다른 지점·영업시간·필터·정렬 조건은 실제 계산을 가장하지 않고 `503 CALCULATOR_NOT_READY`를 반환한다.
- fixture의 기준일·generated_at은 예제에 고정된 합성 값이다. 실제 현재 시각 기반 계산·AI 처리 결과가 아니다.
- 요청 검증·공통 오류·32KiB JSON 본문 제한·개발 origin CORS.
- [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)의 13개 기초 테이블, FK·unique·검토 상태 제약, UTC·낙관적 잠금용 열과 Flyway V1.

**미구현:** JPA 도메인·repository, 검토본 import, 승인·공개·복구 트랜잭션, 실제 snapshot 조회, Python CLI adapter. DB 스키마만으로 공개 승인·불변성·충돌 처리 전체를 검증했다고 보지 않는다. Java에 후보 판정 엔진을 만들지 않았다.

## DB 없이 합성 API 실행

JDK21을 준비하고 저장소 루트에서:

```bash
cd backend
./gradlew bootRun --args='--spring.profiles.active=fixture'
```

Windows에서는 `gradlew.bat`을 사용한다. macOS에서 여러 JDK를 쓰면 `export JAVA_HOME=$(/usr/libexec/java_home -v 21)`로 선택한다. 기본 포트는 8080이며 `PORT`로 변경한다.

다른 터미널에서 **저장소 루트** 기준:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/v1/config
curl -H 'Content-Type: application/json' --data-binary @contracts/examples/matches-request.json http://localhost:8080/api/v1/matches
curl 'http://localhost:8080/api/v1/events/48bb73cf-3cd9-5e4f-895e-9ba9ce62560f?snapshot_id=37d9f0b8-424f-5145-9329-e71ffd6413e3'
```

응답의 `data_kind=synthetic`, null, 원문·대상·예외 필드를 유지한다. 다른 snapshot·미등록 사건은404, 잘못된 입력은422, 본문 초과는413이다. 오류는 `error.{code,message,field_errors,retryable}`와 `request_id`를 반환한다. `/local` 라우터는 등록하지 않았다.

## MySQL 기초 실행

실제 DB 프로필에는 Docker 또는 별도 MySQL8.4 서버가 필요하다. 전용 개발 DB만 사용하고 기존 연구실 DB·계정을 연결하지 않는다.

```bash
cd backend
cp .env.example .env
# .env의 DB_PASSWORD와 MYSQL_ROOT_PASSWORD를 직접 설정
docker compose --env-file .env up -d --wait
```

Compose는 `myai_dev`와 전용 사용자, 영구 볼륨을 만들고 MySQL 포트를127.0.0.1에만 연결한다. 3306이 사용 중이면 `.env`의 `MYSQL_PORT`와 `DB_URL`을 함께 바꾼다. Compose가 `.env`를 읽어도 Java 프로세스의 환경변수가 되지는 않으므로 별도로 전달한다:

```bash
export DB_URL='jdbc:mysql://localhost:3306/myai_dev?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8'
export DB_USERNAME=myai
read -rs DB_PASSWORD; export DB_PASSWORD; echo
./gradlew bootRun
```

기본 `public` 프로필은 DB 연결·Flyway 적용 후 기동한다. 공개 데이터·계산 연결 전에는 API가 `503 PUBLIC_DATA_NOT_READY`를 반환하며 fixture로 자동 전환하지 않는다. JSON seed는 넣지 않는다.

Flyway만 스키마를 생성하고 JPA는 `ddl-auto=validate`를 사용한다. canonical JSON은 LONGTEXT 원문과 별도 checksum으로 보존한다. ID/hash는 ASCII 대소문자를 구분하고, JDBC session·Hibernate는 UTC, 격리 수준은 REPEATABLE READ다. 적용된 V1을 수정하지 말고 후속 V2 migration을 추가한다. 개발 DB 종료는 `docker compose stop`이며 볼륨을 삭제하지 않는다.

## 검증·빌드

```bash
cd backend
./gradlew test bootJar
java -jar build/libs/myai-backend-0.1.0.jar --spring.profiles.active=fixture
```

일반 `test`는 DB 없는 API 시험을 수행한다. `MySqlFoundationTest`는 전용 MySQL 테스트 DB를 지정하고 `MYAI_MYSQL_TESTS=true`일 때 실행한다. 운영·공유 DB에서는 실행하지 않는다. CI는 매 실행 분리된 `myai_test` DB를 준비해 migration 재실행·FK·중복 차단·UTF-8 원문·UTC·실제 모드503을 검증한다.

CI의 기존 필수 검사 `check` 안에서 백엔드 시험·JAR 빌드도 실행하므로 백엔드 실패가 필수 검사 실패로 이어진다. 실행 JAR는 별도 artifact로 보관한다. `CORS_ALLOWED_ORIGIN` 기본값은 `http://localhost:5173`이며 credential·임의 origin을 허용하지 않는다.

기준 문서: [기술 구성](../docs/spec/08_기술구성과연결.md), [DB](../docs/spec/09_DB설계와트랜잭션.md), [공개 계약](../contracts/README.md), [Python CLI](../contracts/calculation-bridge.md).
