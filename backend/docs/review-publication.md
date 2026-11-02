# 검토 승인·공개·복구

검토본 import 이후의 작업을 `local-publication` 일회성 명령으로 실행한다. 기존 Java21·Spring Boot·MySQL 구성을 사용하며 HTTP 관리 API는 추가하지 않는다. 공개 API는 DB snapshot을 조회하며 matches는 Python 계산에 연결한다.

## 작업 흐름

1. [검토본 import](reviewed-import.md)로 `draft/needs_review`·`hidden` revision을 저장한다.
2. 사람이 원문·근거·수정값을 대조한 뒤 `approve` 또는 `reject`를 실행한다. 새 revision·검토자·시각·이유·감사 기록을 저장하며 이전 revision은 보존한다.
3. `preview`로 공개 예정 JSON을 확인한다. DB에는 저장하지 않는다. 확인 후 `publish`로 승인된 현행 revision과 검토 지점 5개를 불변 snapshot으로 묶고 공개 포인터를 전환한다.
4. 문제가 생기면 `rollback`으로 같은 채널에서 공개했던 snapshot을 다시 선택한다. 복구 이력도 남긴다.
5. 파일 전달이 필요하면 별도 `local-export`로 이미 공개한 snapshot을 내보낸다. DB 공개 성공과 파일 저장 성공은 별개다.

승인은 `approved/public`, 반려는 `rejected/hidden`인 새 작업 revision을 만든다. 여기서 public은 공개 후보 자격이다. **승인·반려만으로 기존 공개본을 바꾸지 않는다.** 이미 공개한 사건을 반려한 경우에도 새 snapshot 공개 또는 포인터 복구를 별도로 수행해야 한다.

## 실행

전용 개발 DB와 `DB_URL`·`DB_USERNAME`·`DB_PASSWORD`를 준비한 뒤 저장소 루트에서 실행한다. V1은 유지하며 V2가 `publication_audits`를 추가한다.

```bash
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-publication \
  --myai.publication.file=backend/examples/approve.json \
  --myai.publication.source-root=backend/examples \
  --myai.publication.actor=synthetic-reviewer
```

이 예제는 먼저 `backend/examples/reviewed-import.json`을 import한 합성 자료용이다. 실제 작업본은 Git 제외 `data/private/`에 보관한다. `source-root`는 import 때 사용한 원문 디렉터리이며 승인·공개 때 원문 hash를 다시 대조한다. 반려·복구에는 원문 디렉터리가 필요하지 않다.

`myai.publication.file`을 [publish.json](../examples/publish.json) 또는 [rollback.json](../examples/rollback.json) 작업본으로 바꾸면 같은 명령으로 공개·복구할 수 있다. 공개 작업본의 action을 preview로 바꿔 먼저 확인하고 publish로 바꿔 실행한다. **예제의 revision/snapshot ID는 실제 명령 결과로 교체해야 한다.** 공개 예제의 `revision_ids`에는 approve 결과의 `revision_id`를 넣는다. 예제를 복사해 수정하며 원본 파일을 실제 작업 데이터로 덮어쓰지 않는다.

명령은 HTTP 서버 없이 한 번 실행하고 종료한다. 결과 JSON은 stdout, 로그는 stderr에 출력한다. `result`의 `action`, `event_id`, `revision_id`, `snapshot_id`, `checksum`, `head_version` 중 해당 작업에 필요한 값만 채워진다. preview는 `result.preview`에 공개 예정 내용을 반환한다. 이때 ID·생성 시각·checksum은 미리보기용이며 실제 공개 결과와 구분한다. 성공은 종료 코드 `0`, 입력 오류·미등록 ID는 `2`, 버전 충돌은 `3`, DB 접근 실패는 `4`다. 예상하지 못한 오류 또는 Spring/DB 초기 기동 실패는 `1`이며 기동 실패에는 결과 JSON이 없을 수 있다. 오류 응답에는 원문·SQL·비밀값·절대 경로를 담지 않는다.

`local-import`, `local-publication`, `local-export`는 하나씩 활성화한다. 혼합하면 작업을 거부한다. 별도 가입·복잡한 역할 체계는 만들지 않았으며 로컬 실행 권한을 가진 단일 관리자가 운영하는 기존 S10 가정을 따른다. actor는 감사용 팀원 식별자이고 인증 토큰이 아니다.

## 명령 파일 규격

최상위 `schema_version`은 `publication-command-v1`이다. 모든 키를 포함하고 nullable 값도 생략하지 않는다. 추가/중복 키·문자열 숫자·정수 자리에 실수·잘못된 UTF-8/Unicode를 거부한다. 파일은 최대8MiB다.

| action | 필드 |
|---|---|
| approve/reject | `schema_version`, `action`, `reason`, `event_id`, `expected_revision_no`, `evidence_ids` |
| preview/publish | 위 공통값 중 schema/action/reason과 `mode`, `case_id`, `anchor_date`, `reference_instant`, `knowledge_cutoff`, `history_fidelity`, `data_kind`, `area`, `rules_version`, `dictionary_version`, `revision_ids`, `points`, `expected_head_version` |
| rollback | `schema_version`, `action`, `reason`, `mode`, `case_id`, `snapshot_id`, `expected_head_version` |

ID는 소문자 UUID이며 `evidence_ids`는 저장본에 있는 근거 ID 목록이다. reason은 최대4000자, actor는 최대128자다. approve/reject는 현재 revision 번호를 expected로 지정한다. 성공하면 번호가 하나 증가하며 같은 예상 번호를 다시 보내면 충돌한다. 작업 revision과 공개 포인터의 버전은 별개다.

처음 공개하는 채널의 `expected_head_version`은 null이다. 첫 성공 결과는 `head_version=0`이며 다음 공개·복구에는 이 값을 expected로 전달한다. 전환할 때마다 하나 증가한다. null을 기존 채널의 강제 덮어쓰기 값으로 사용할 수 없다. 충돌 시 최신 결과를 확인하고 의도한 변경만 다시 실행한다.

## 승인·공개 검증

승인 때 원문/본문 hash, code point 인용, FieldValue·시간·좌표·참조를 다시 검사한다. 원문의 사용권 검토는 allowed여야 하고 성공 확인 기록이 필요하다. 수집·확인·장소 검토·사람 수정 시각은 미래일 수 없다. 날짜·위치 미상, 근거가 있는 빈 목록, null과 소수 정밀도는 보존한다. 인용의 실제 의미·공식성·이용권한 판단은 사람이 수행한다. 이 명령은 외부 URL이나 AI에 접근하지 않는다.

publish는 승인된 현행 revision의 public intent와 자료 종류·구역·규칙/사전 버전을 확인한다. 승인 후 새 작업 revision이 생겼다면 이전 승인을 그대로 공개할 수 없다. 사건 목록은 빈 배열도 허용하며 이 경우 0건 snapshot을 만든다.

`area`는 `{area_id,name,description}`이다. `points`는 동일 구역의 활성 시험 지점 정확히5개이며 예제의 D01 필드를 모두 포함한다. verified 상태·좌표 근거·검토자/시각·사전 버전이 필요하다. 좌표는 V1 DB 열에 맞춰 소수점 이하 최대7자리로 받으며 조용히 반올림하지 않는다. 새 지점은 version=1, 기존 지점의 변경은 다음 version으로만 허용한다. 같은 버전이면 전체 검토 metadata도 같아야 한다. 과거 snapshot의 지점 정보는 이후 지점 변경으로 바뀌지 않는다.

## 현재·과거 채널

current에서는 case·기준일·reference/cutoff·history_fidelity를 모두 null로 둔다. replay는 등록할 case UUID와 해당 문맥을 모두 지정한다. `knowledge_cutoff <= reference_instant <= 현재시각`이며 reference의 KST 날짜가 anchor_date와 같아야 한다.

verified_snapshot에는 cutoff 이전 수집·성공 확인 기록이 필요하다. reconstructed에서는 당시 수집해 둔 원문을 현재 검토·구조화한 경우처럼 과거 성공 확인이 없는 상태도 표현한다. **두 모드 모두 해당 원문 버전의 collected_at이 cutoff 이하여야 한다.** 게시일만으로 현재 수집본이 당시에도 같은 내용이었다고 단정하지 않는다. cutoff 이후 수집본은 별도 역사 근거 규격을 마련하기 전까지 거부한다.

snapshot의 출처에는 당시 cutoff까지의 `checks`·`last_verified_at`과 현재 확인 상태인 `current_*` 필드를 분리해 보존한다. 과거 자료가 당시 확인되지 않았다면 역사상 확인 시각은 null이다. 현재 원문 확인 시각으로 이를 대신하지 않는다. 24시간 경과와 후보 판정은 이후 Python 연결 경로에서 처리한다.

## 공개 내용·실패·복구

snapshot에는 D07 문맥, 고정 지점, 승인된 사건 사실·FieldValue·근거·문서 관계, 공개 출처와 수집/확인 범위를 담는다. event별 근거 ID 범위를 유지한다. 원문 전체·raw 경로·AI 출력·평가·검토자·수정 전 비공개 값·내부 감사 기록은 제외한다. 공개 JSON은 내부 snapshot 형식이다. [공개 조회 API](public-snapshot-api.md)가 사실·근거를 응답 형식으로 변환하며 계산 완료 결과로 사용하지 않는다.

canonical JSON은 UTF-8 원문과 별도 SHA-256으로 저장한다. checksum은 checksum 필드를 제외한 고정 원문에 대응하며 snapshot은 수정하지 않는다. 쓰기 트랜잭션에서 문서·revision을 다시 확인하고 지점·snapshot·구성 revision·공개 포인터·감사 기록을 함께 commit한다. 한 부분이라도 실패하면 이번 변경 전체를 rollback한다.

rollback은 같은 채널에서 실제 공개했던 snapshot인지, canonical checksum과 저장 문맥이 맞는지 확인한다. 원문 파일이나 계산기를 호출하지 않고 공개 포인터와 감사 기록만 바꾼다. DB의 최신 지점 행을 되돌리는 작업이 아니며 복구 시 기준은 snapshot 안에 고정된 지점·사건이다. DB 스키마 복구와도 구분한다.

공개 API의 config·상세는 DB snapshot을 조회한다. matches는 문맥·지점 검증 후 [설정된 Python](../README.md#python-계산-연결)을 호출한다. 관리 UI·운영 서버 배포·실자료 검수는 미완료다. DB 공개 포인터 전환이나 JSON 파일 저장을 운영 서비스 배포 완료로 표현하지 않는다.

공개 포인터가 바뀌면 이전 공개본의 직접 조회는409다. rollback으로 다시 선택한 공개본은 즉시 조회 가능하며, 지점도 해당 snapshot의 고정 값을 사용한다.

## Snapshot JSON 내보내기

DB 설정과 빌드 후 저장소 루트에서 실행한다. `SNAPSHOT_ID`에는 **publish 성공 결과의 실제 ID**를 넣는다. actor·원문 디렉터리·Python은 요구하지 않는다.

```bash
mkdir -p data/public/snapshots
SNAPSHOT_ID=10000000-0000-4000-8000-000000000007 # 예시이며 실제 공개 ID로 교체
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-export \
  --myai.export.snapshot-id="$SNAPSHOT_ID" \
  --myai.export.directory="$PWD/data/public/snapshots"
```

정상 실행은 HTTP 서버 없이 종료하고 stdout에 JSON 한 건을 반환한다. `result`의 `snapshot_id`, `checksum`, `file_name`, `already_exported`를 확인한다. 파일명은 `<snapshot_id>-<checksum>.json`이며 DB의 canonical UTF-8 바이트를 재직렬화·줄바꿈 추가 없이 보존한다. `shasum -a 256 <파일>` 값은 결과 checksum·파일명의 hash와 같아야 한다. 파일 내용은 내부 `snapshot-v1` 형식이며 공개 API 응답이나 계산 결과 fixture를 대신하지 않는다.

이미 공개했던 이전 snapshot·replay도 명시 ID로 내보낼 수 있다. preview·미공개 ID는 거부하며 export가 현재 head나 공개 이력을 바꾸지 않는다. 짧은 읽기 전용 RR에서 ID·checksum·저장 문맥·공개 필드 범위를 확인하고 연결을 반환한 뒤 파일을 쓴다. 이후 head 교체나 원문 파일 삭제로 선택한 고정 내용이 바뀌지 않는다.

`local-export`에서는 Flyway를 실행하지 않는다. DB 스키마는 기존 import·공개·서버 준비 절차에서 먼저 적용해야 한다. 내보내기 명령이 기동 중 대기 migration을 적용하지 않으며, DB 접속 계정도 조회 권한으로 분리할 수 있다.

파일을 완성한 뒤 같은 디렉터리의 hard link로 최종 이름을 배타 생성한다. Linux/macOS의 hard link 지원 파일시스템과 쓰기 가능한 기존 디렉터리가 필요하다. 같은 내용의 regular file은 `already_exported=true`로 재사용한다. 다른 내용·디렉터리·symlink는 보존하고 충돌로 종료한다. 임시 파일의 기본 권한을 상속하므로 별도 서비스 계정에 전달할 때 필요한 읽기 권한은 배포 절차에서 설정한다.

| 종료 코드 | 오류·처리 |
|---|---|
| 0 | 파일 생성 또는 동일 파일 재사용 |
| 2 | EXPORT_VALIDATION_ERROR / EXPORT_NOT_FOUND / EXPORT_INVALID_SNAPSHOT. 설정·공개 ID·저장 무결성 확인 |
| 3 | EXPORT_FILE_CONFLICT. 기존 파일을 덮어쓰지 않음. 다른 디렉터리를 선택하거나 기존 항목을 별도 보존한 뒤 재시도 |
| 4 | EXPORT_DATABASE_UNAVAILABLE. 일시 DB 접속·자원 장애, retryable=true |
| 5 | EXPORT_IO_ERROR. 권한·디렉터리·파일시스템 확인 후 같은 ID로 재시도, retryable=true |
| 1 | 예상치 못한 실패. 초기 DB 기동 실패는 결과 JSON이 없을 수 있음 |

오류 JSON·실행 결과를 운영 기록으로 보관한다. **파일 저장 실패는 이전 DB 공개 성공을 취소하지 않는다.** 실패 시 파일 유무를 추정하지 말고 같은 ID로 재실행한다. 이미 같은 파일이 완성되었다면 재사용한다. 공개 조회의 기준은 계속 DB snapshot이다. 파일 복사·웹 서버 연결·운영 공개 전환은 별도 배포 작업이다.

`local-import`, `local-publication`, `local-export`는 하나씩 실행한다. 혼합 프로필과 웹 서버 강제 실행은 명령 검증에서 거부하며 DB·출력 파일을 변경하지 않는다. 잘못된 혼합 실행에서는 각 명령의 오류 JSON이 나올 수 있다.
