# 같은 원문 버전의 확인·사용권 이력

`local-source-review`는 이미 등록한 D03 문서 버전에 원문 확인 시도와 사용권 결정을 추가한다. 본문이 바뀌면 새 문서 버전을 등록한다. 확인·사용권만 바뀌면 기존 버전에 이력을 남기며 D05 실행이나 사건 revision을 새로 만들 필요는 없다. Java21·기존 Spring JDBC·MySQL8.4.13을 사용하며 HTTP 관리 API·AI 호출은 추가하지 않는다.

최초 D03의 원본6필드(document_id/document_version_id/version_no/text_sha256/metadata_json/private_content_ref), 원문·블록, 동결 D05·사람 수정 원본과 과거 revision·snapshot은 보존한다. 부모 document_versions의 새 운영 열 source_review_no/source_review_sha256은 이력 추가 때 갱신한다. 기존 import에서 metadata를 편집해 같은 문서 버전 ID로 재입력하면 여전히 충돌이다.

## 합성 예제 실행

JDK21·전용 개발 DB와 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`를 [백엔드 안내](../README.md)에 따라 준비한다. 저장소 루트에서 JAR를 빌드한 뒤 [합성 D03](../examples/source-import.json)을 먼저 등록한다.

```bash
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=backend/examples/source-import.json \
  --myai.import.source-root=backend/examples \
  --myai.import.actor=synthetic-collector
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-source-review \
  --myai.source-review.file=backend/examples/source-review.json \
  --myai.source-review.source-root=backend/examples \
  --myai.source-review.actor=synthetic-reviewer
```

[검토 예제](../examples/source-review.json)는 운영 이력0인 합성 문서용이다. 최초 D03의 확인 목록은 운영 번호에 포함하지 않는다. 같은 예제를 정확히 재실행하면 최초 결과를 반환한다. 다른 검토를 추가할 때는 예제를 별도 작업본에 복사하고 새 `review_id`, 현재 `expected_review_no`, 실제 확인 시각·사용권 선언을 넣는다. 실제 작업본과 원문은 Git 제외 `data/private/`에 보관한다.

| 설정 | 조건 |
|---|---|
| `myai.source-review.file` | 필수. UTF-8 요청 파일 |
| `myai.source-review.actor` | 필수. 공백만 아닌128자 이하 식별자, 제어 문자 금지 |
| `myai.source-review.source-root` | **신규 verified 확인에만 필수.** 최초 D03의 상대 원문 경로를 해석할 디렉터리 |

신규 verified는 기존 D03 검증으로 보존한 원문·본문 hash를 대조한다. 파일 I/O는 쓰기 트랜잭션 밖에서 수행한다. changed/unreachable/uncertain 확인과 권한만 바꾸는 요청은 원문 파일이 없어도 기록할 수 있다. 같은 ID·바이트의 정확한 재실행에도 원문 디렉터리는 필요하지 않다.

명령은 HTTP 서버 없이 한 번 실행한 뒤 종료한다. stdout은 안전한 JSON 한 건, 로그는 stderr다. 성공은 `status=succeeded`이며 `result`에는 `review_id`, `document_version_id`, `review_no`, `record_sha256`, `already_recorded`만 넣는다. 원문·경로·actor·검토 메모는 출력하지 않는다.

`local-source-review`, `local-import`, `local-extraction`, `local-publication`, `local-export`는 하나씩 활성화한다. source-review와 다른 local/public/fixture 프로필 혼합, 웹 모드 강제는 DB 시작 전에 종료2로 거부한다. source-review는 이력 INSERT와 migration에 필요한 쓰기 권한을 가진 전용 DB 계정으로 실행한다.

## 요청 파일

최상위는 다음 **9키**를 모두 포함한다. 추가·중복 키, 후행 JSON, 잘못된 UTF-8/Unicode, 문자열 숫자·실수형 정수·잘못된 scalar를 거부한다. ID는 소문자 UUID, hash는 소문자 SHA-256 64자리다.

| 키 | 값 |
|---|---|
| `schema_version` | 정확히 `source-review-v1` |
| `review_id` | 새 검토 UUID. 정확한 재실행은 원래 ID 유지 |
| `document_version_id` | 등록된 D03 버전 UUID |
| `expected_review_no` | 현재 운영 번호인0 이상64비트 정수. 자동 보충하지 않음 |
| `expected_text_sha256` | 등록된 D03의 본문 hash |
| `check` | null 또는 아래4키 객체. 권한만 갱신할 때 null |
| `use_review` | pending/allowed/restricted |
| `use_note` | 공백만 아닌 사용권 메모 |
| `reason` | 공백만 아닌 이번 결정 사유 |

`check` 객체는 `checked_at`, `result`, `text_sha256`, `note`의 정확한4키다. result는 verified/changed/unreachable/uncertain이다. verified hash는 `expected_text_sha256` 및 등록된 본문 hash와 같아야 한다. `check_id=review_id`, `reviewer_id=actor`로 기록하므로 별도 check ID·검토자 키는 받지 않는다.

`checked_at`은 UTC `Z`, 최대6자리 소수, MySQL1000~9999년 범위다. 이전 확인보다 엄격히 늦고 서버의 이번 `recorded_at` 이하여야 한다. 서버 등록 시각도 마이크로초로 보존하며 이전 운영 기록보다 앞설 수 없다. `check.note`는 공백만 아닌 문자열이고 UTF-8 기준65535바이트 이하로 제한한다. 메모·사유의 실제 앞뒤 공백·줄바꿈은 임의로 자르지 않는다.

권한만 갱신하면 확인 시도·성공 시각을 만들지 않는다. check=null이면서 현재 `use_review`와 `use_note`까지 같으면 무변경 요청으로 거부한다. 실패 확인은 이전 성공 시각을 지우지 않으며 최신 시도·결과만 바뀐다.

현재 번호와 본문 hash는 다음처럼 조회할 수 있다. 예시 UUID는 합성 문서이며 실제 작업 시 대상 ID로 바꾼다.

```sql
SELECT document_version_id, text_sha256,
       source_review_no AS current_review_no,
       source_review_sha256 AS current_record_sha256
FROM document_versions
WHERE document_version_id = '10000000-0000-4000-8000-000000000002';
```

이 조회는 부모 행에 저장한 운영 번호·해시를 보여 주며 전체 이력 검증을 대신하지 않는다. 명령은 전체 이력의 끝과 이 두 열이 일치하는지도 검사한다. 조회 이후 다른 기록이 추가되면 예상 번호가 오래되어 충돌한다. 최신 이력과 의도한 변경을 확인한 뒤 새 요청을 준비하며, 실패를 피하려고 번호를 자동으로 덮어쓰지 않는다.

## 저장·정확한 재실행

V4는 `source_reviews`와 부모 `document_versions`의 운영 두 열을 추가한다. 이력에는 `review_id` PK, 문서 버전 FK, `UNIQUE(document_version_id,review_no)`, `JSON_VALID(record_json)`을 적용한다. 부모의 `source_review_no`는 BIGINT NOT NULL DEFAULT 0, `source_review_sha256`은 nullable CHAR(64)이며 CHECK로 0/null 또는 양수/non-null 조합만 허용한다. 기존·신규 문서의 운영 초기값은0/null이고 이력 번호는1부터 연속해서 증가한다. 별도 head 테이블은 만들지 않는다. V1~V3 migration과 원본6필드 값은 보존하며, 부모 행을 잠근 뒤 운영 두 열·전체 이력·명시한 예상 번호를 대조한다.

`record_json`은 `record_version`, `review_id`, `document_version_id`, `review_no`, `document_sha256`, `previous_record_sha256`, `input_json`, `input_sha256`, `actor`, `recorded_at`의 정확한10키다. record_version은 `source-review-record-v1`이다. 원본 D03 전체 fingerprint, 정확한 요청 UTF-8 문자열·바이트 hash, 이전 기록 hash와 최초 actor·서버 등록 시각을 보존한다. 읽을 때 번호·hash·행 대응·원본 prefix·각 기록 당시의 확인 순서를 다시 검증한다. 누락·손상을 초기 상태로 조용히 대체하지 않는다.

새 check가 있으면 기존 `source_checks`에도 INSERT하고 직전 성공 check 참조를 연결한다. 새 `source_reviews` 기록과 check INSERT 뒤 부모의 운영 번호·해시를 같은 트랜잭션으로 갱신하며, 어느 단계든 실패하면 세 변경을 함께 rollback한다. 초기 metadata의 확인 목록과 SQL 행을 기준선으로 유지하고, 운영 확인까지 전체 대조한다. 권한·확인 상태는 별도 `SourceView`로 합성하여 승인·공개에 사용한다. D05·사람 인계와 일반 import가 읽는 원래 D03 metadata는 바뀌지 않으며 legacy에 없는 필드를 만들어 채우지 않는다.

일반 조회는 같은 읽기 snapshot에서, append·공유 잠금 재검증은 현재 읽기로 부모 운영 두 열과 전체 기록의 마지막 번호·해시를 대조한다. check를 만들지 않는 마지막 권한 제한 행이 유실돼도 부모의 끝과 맞지 않아 충돌하며 이전 allowed 상태로 조용히 돌아가지 않는다. 원본 보존은 기존6필드와 D05·사람 인계 원본으로 확인하고, `SELECT *` 전체가 불변이라고 주장하지 않는다. 새 운영 두 열의 변경은 기록 끝과 별도로 대조한다.

같은 `review_id`와 **같은 요청 바이트**는 후속 이력이 생겨도 최초 결과와 `already_recorded=true`를 반환한다. 최초 actor·등록 시각도 유지한다. 먼저 원본·운영 이력·SQL 대응을 검증한 뒤 재사용하며, 신규 확인이 아니므로 verified였어도 원문 파일 재검증을 생략한다. 같은 ID의 다른 공백·줄바꿈 등 다른 바이트, 다른 ID의 오래된 예상 번호·본문 hash는 충돌이다.

요청, JSON escaping 후 개별 기록, 문서별 전체 `record_json` 누적, 유효 metadata에 각각8MiB를 적용한다. 초과 요청은 INSERT 전에 거부하고 기존 원본·이력·입력 파일을 보존한다. 오래된 이력을 자르거나 자동 백업·별도 보관본을 만들지 않는다. 한도에 이른 이력의 확장·백업은 별도 운영 작업이다. 이 검사는 부모 운영 두 열과 이력을 신뢰하는 저장 경계 안에서 일부 유실·불일치를 감지한다. 관리자에게까지 불변성을 보장하는 WORM·전자서명이 아니며, 기록과 부모 두 열을 함께 바꾸는 관리자 변조나 DB 전체의 과거 복원을 탐지한다고 보증하지 않는다.

## 승인·공개·과거 재현

approve/preview/publish는 현재 운영 상태의 `use_review=allowed`와 성공 확인 기록을 검사한다. 최신 실패 뒤에도 이전 성공은 남고 기존 최신성 판정은 유지한다. 같은 공개 작업에서 같은 문서 버전은 하나의 조회 상태를 사용하며, 쓰기 직전 원본과 운영 번호·hash를 현재 읽기로 다시 대조한다. 확인·권한 변경만으로 사건을 승인하거나 공개하지 않는다.

replay도 **현재 사용권**을 검사한다. 역사 확인 목록에는 `checked_at <= knowledge_cutoff`인 확인만 넣고, 추가 운영 확인은 `recorded_at <= knowledge_cutoff`까지 만족해야 한다. 나중 등록한 과거 시각의 확인을 당시 verified_snapshot 근거로 소급하지 않는다. 원래 확인 목록의 cutoff 처리와 collected_at 제한은 유지하며 `current_*`에는 현재 전체 확인 상태를 남긴다.

이미 공개한 snapshot·조회·export·rollback은 고정된 기존 바이트를 사용한다. 나중의 restricted 기록이 과거 공개본을 자동 철회하지 않는다. 공개 전환·복구 절차는 [승인·공개 안내](review-publication.md)를 따른다.

preview는 DB 쓰기 없이 원본·운영 이력을 읽고 공유 잠금으로 다시 확인하므로 SELECT 전용 계정으로 사용할 수 있다. 먼저 쓰기 계정으로 V4까지 적용한 DB를 준비하고, publish 요청 작업본의 action을 preview로 바꿔 다음처럼 실행한다. 원문 및 D05·사람 인계 보관본의 읽기 조건도 그대로 필요하다.

```bash
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-publication \
  --spring.flyway.enabled=false \
  --myai.publication.file=data/private/preview.json \
  --myai.publication.source-root="$SOURCE_ROOT" \
  --myai.publication.actor=synthetic-reviewer
```

이 설정은 preview용이며 source-review INSERT나 승인·공개 쓰기에 SELECT 계정을 사용할 수 있다는 뜻은 아니다.

## 오류·검증 범위

| 종료 코드 | 의미 |
|---|---|
| 0 | 새 기록 또는 정확한 재실행 성공 |
| 2 | SOURCE_REVIEW_VALIDATION_ERROR. 설정·요청·actor·확인 시각·원문 대조·용량 경계 확인 |
| 3 | SOURCE_REVIEW_CONFLICT. ID/예상 번호/hash 충돌 또는 저장 이력·SQL 대응 손상 |
| 4 | SOURCE_REVIEW_DATABASE_UNAVAILABLE. 초기 연결·인증·권한·없는 DB 포함 |
| 1 | SOURCE_REVIEW_INTERNAL_ERROR 또는 내부·프로토콜 오류 |

오류 JSON은 `error`·`request_id` 구조이며 원문·SQL·비밀번호·절대 경로는 넣지 않는다. DB 오류의 `retryable=true`는 SQLState `08` 연결 장애에만 사용한다. 인증1045·권한1044·없는 DB1049는 false다. 충돌이면 최신 상태와 원인을 확인하고 재시도하며 기존 데이터를 고치거나 지워 통과시키지 않는다.

최종 리뷰 I1 보완 전 기준으로 Java/MySQL 전체323개와 실제 JAR34항목을 합성 자료로 검증했다. 재실행·초기0·권한만 변경하는 요청·동시 충돌·rollback·원본 보존·승인/공개 경합·recorded cutoff와 SELECT 전용 계정의 미리보기를 확인했다. 부모 운영 두 열을 추가한 I1 보완 후 전체 회귀·JAR 재검증 결과는 별도로 확인하며 코드 리뷰·원격 검증 결과는 관련 PR 기록을 따른다.

actor·checked_at·권한 값은 실행자의 선언이다. 기계 검사는 실제 URL 재접속·사람의 사실성/법적 이용권한 판단·계정 인증을 대신하지 않는다. 실제 개발 공지3건은 pending/uncertain 상태를 유지하며 이번 합성 검증으로 사람 확인·독립 정답·40문서 성능 평가·공개 승인·운영 배포를 완료한 것으로 표시하지 않는다.
