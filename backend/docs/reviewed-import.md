# 검토본 로컬 import v1

`reviewed-import-v1`은 D03 문서·D04 사건 관계·D06 검토 revision을 전달하는 **새 로컬 파일 규격**이다. 공개 API나 AI 원출력 `extract-schema-v1`과 구분해 사용한다. [합성 JSON](../examples/reviewed-import.json)과 [합성 원문](../examples/synthetic-source.txt)은 실제 공지·실제 검토 실적으로 집계하지 않으며 실행 JAR에도 포함하지 않는다. `contracts/examples/*response.json`은 API 응답 예제이며 import 입력으로 사용할 수 없다.

## 실행

저장소 루트에서 JDK21·전용 개발 MySQL·`DB_URL`/`DB_USERNAME`/`DB_PASSWORD`를 준비한다. DB 설정은 [README](../README.md)를 따른다.

```bash
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=backend/examples/reviewed-import.json \
  --myai.import.source-root=backend/examples \
  --myai.import.actor=synthetic-reviewer
```

명령을 한 번 실행한 뒤 종료하며 HTTP 서버·관리 라우터는 등록하지 않는다. 로그는 stderr에, 결과 JSON 한 건은 stdout에 출력한다. 성공 결과의 `result`에는 `import_id`, `revision_ids`, `document_version_ids`, `already_imported`를 담는다. 같은 입력 바이트를 재입력하면 같은 ID 목록과 `already_imported=true`를 반환한다. 이때 감사 기록도 늘리지 않는다.

종료 코드는 `0` 성공/기존 결과, `2` 입력·설정 검증 실패, `3` ID·버전·동시 수정 충돌, `4` 저장 중 DB 접근 실패다. 예상하지 못한 오류나 Spring/DB 초기 기동 실패는 `1`을 반환한다. 기동 실패는 결과 JSON 없이 stderr에 나타날 수 있다. 오류 결과는 공개 API와 같은 `error`·`request_id` 구조를 사용하며 원문·SQL·비밀번호·절대 경로는 넣지 않는다.

실제 작업본은 Git 제외 `data/private/`에 보관하고 해당 원문 디렉터리를 `source-root`로 지정한다. `raw_asset_path`에는 이 디렉터리를 기준으로 한 상대 경로를 쓴다. 절대 경로·`..` 경로·밖으로 나가는 symlink·일반 파일이 아닌 입력은 거부한다. 입력 JSON과 각 원문은 각각 최대8MiB다. 이 명령은 원문을 복사/이동하지 않으므로 **원문 디렉터리와 검토 JSON은 별도로 보존**해야 한다. DB의 원문 참조는 해당 root를 기준으로 해석하므로 이후 root를 임의로 변경하지 않는다.

합성 원문 `synthetic-source.txt`와 입력 `reviewed-import.json`은 Git에서 LF로 고정한다. `core.autocrlf=true`에서도 원문 SHA-256과 입력 파일 hash가 유지되도록 한 규칙이다. 실제 원문은 수집한 바이트 그대로 보존한다.

## 최상위·문서·근거

모든 객체는 정의한 키만 허용하며 nullable 키도 생략할 수 없다. 중복 JSON 키·후행 JSON·잘못된 UTF-8/Unicode·문자열 숫자·정수 자리에 실수를 거부한다. ID는 소문자 UUID, hash는 소문자 SHA-256 64자리다.

근거가 있는 `known` 빈 목록은 확인된 항목 없음으로 보존하며 미상을 나타내는 null과 구분한다. `precision=unknown`의 부분 날짜·시간도 그대로 보존하되 시작·종료·익일 값이 모두 있는 시간 구간은 모순 여부를 검사한다.

| 필드 | 내용 |
|---|---|
| `schema_version` | 정확히 `reviewed-import-v1` |
| `data_kind` | `synthetic` 또는 `real`; 기존 문서·사건의 종류와 혼합 불가 |
| `documents` | D03 객체 1개 이상. 사건의 모든 `source_version_ids`를 이번 파일에 포함 |
| `evidence` | 근거 객체 1개 이상, `evidence_id`는 파일 안에서 유일 |
| `events` | D04 메타데이터와 D06 revision 객체 1개 이상 |

문서는 [D03 필드](../../docs/spec/03_데이터와AI.md#d03--공식-문서원문-버전확인-기록)를 모두 포함한다. `raw_sha256`는 실제 원문 바이트의 hash와, `text_sha256`는 `cleaned_text`의 UTF-8 바이트 hash와 대조한다. `block_index` 항목은 `{block_id,page,text}`이며 page는 null 또는 양의 정수다. block ID는 문서 버전 안에서 유일해야 하고 블록 본문은 cleaned text에 있어야 한다. `redaction_log`에는 `{category,location}` 배열을 넣되 제거한 실제 값은 담지 않는다.

`checks` 항목은 `{check_id,checked_at,result,reviewer_id,text_sha256,note}`다. 시각 순서대로 나열하고 result는 `verified/changed/unreachable/uncertain` 중 하나다. verified hash는 해당 본문과 일치해야 한다. `latest_check_attempt_at`, `last_verified_at`, `check_result`는 이 목록의 최신 시도·마지막 성공·최신 결과와 일치해야 한다. 시도 없음은 null/null/unchecked다. DB 확인 이력은 직전 성공 check 참조를 함께 저장한다.

근거 항목은 `{evidence_id,document_version_id,block_id,quote,start_char,end_char,text_sha256}`다. offset은 블록 안의 **Python Unicode code point `[start,end)`**를 기준으로 하며 인용과 본문 hash를 정확히 대조한다. 이 검사를 통과해도 사람이 근거의 의미를 검토해야 한다. 외부 URL에 접근하거나 AI를 호출하지 않는다.

## 사건·revision

사건 객체는 `event_id`, `area_id`, `area_membership`, `document_links`, `relations`, `suspected_duplicate_ids`, `split_group_id`, `expected_revision_no`, `revision`으로 구성한다.

- `document_links`: `{document_id,role,evidence_ids}`. role은 original/correction/cancellation/repost, 해당 문서의 근거가 필요하다.
- `relations`: `{from_document_id,to_document_id,type,reviewed_by,reason,created_at}`. type은 corrects/cancels/reposts/duplicates, 자기 참조·순환 정정은 거부한다.
- 최초 사건은 expected=0/revision_no=1. 후속 입력은 현재 revision 번호를 expected로 지정하고 다음 번호·새 UUID를 사용한다. 기존 revision을 수정하지 않는다.
- D06 필드는 예제와 [명세](../../docs/spec/03_데이터와AI.md#d06--사람이-검토한-사건-revision)를 따른다. `origin`을 추가해 human(원본에서 수동 작성, run 목록 비움)과 ai_reviewed(등록된 validated 추출 실행 참조)를 구별한다. 이 명령은 AI 원출력·실행을 생성하거나 import하지 않는다.
- 시간·geometry·FieldValue의 knowledge/value·근거·occurrence↔location 참조를 검사한다. 미상은 null과 사유 그대로 보존한다. UTC 시각은 MySQL DATETIME 범위, 최대 마이크로초 정밀도이며 지역 시간은 HH:mm 또는 HH:mm:ss다.
- **이 import 명령은 `review_status=draft/needs_review`, `publication_intent=hidden`만 허용**한다. approved/public을 조용히 낮추지 않고 거부한다. reviewer_id/reviewed_at은 둘 다 null 또는 둘 다 값이 있어야 한다. 승인·공개는 [별도 로컬 명령](review-publication.md)으로 실행한다.

## 저장·재시도 경계

파일과 원문을 검증한 뒤 하나의 Spring 서비스 트랜잭션에서 batch·문서·확인 이력·revision·작업 포인터·감사 기록을 저장한다. V1 스키마를 그대로 사용한다. 기존 Spring JDBC의 parameterized SQL과 조건부 포인터 UPDATE로 저장하며 JPA entity/일반 CRUD는 추가하지 않는다.

같은 문서 버전 ID는 metadata까지 같을 때만 재사용하며 내용이 다르면 충돌로 처리한다. 새 문서 버전은 다음 번호로만 추가한다. 기존 버전에 원문 확인 기록을 별도로 덧붙이는 명령은 아직 없으므로 metadata를 바꾼 재입력은 거부한다. 저장에 실패하면 이번 배치 전체를 rollback하고 기존 revision·snapshot·공개 포인터를 보존한다. 같은 파일을 동시에 import하면 먼저 성공한 결과를 함께 반환하며 같은 사건의 revision을 서로 다르게 수정해 동시에 넣으면 한 건만 성공한다.

입력 hash는 JSON 파일의 **원본 바이트**로 계산한다. 공백·배열 순서가 바뀌면 다른 배치로 취급하므로 동일 revision을 새 배치로 다시 넣으면 충돌할 수 있다. 실패 batch는 별도로 영구 저장하지 않고 종료 코드와 오류 JSON으로 알린다. 사용자 조건·평가 기록·AI 원출력은 이 규격에 포함하지 않는다. import 이후의 승인·공개·복구는 [별도 로컬 명령](review-publication.md)으로 실행한다. 공개 API는 [DB snapshot을 조회](public-snapshot-api.md)하며 matches는 [설정된 Python](../README.md#python-계산-연결)으로 계산한다.
