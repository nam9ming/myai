# 기존 문서 버전의 확인·사용권 검토 이력

## 목표와 불변 조건

D03의 같은 본문 버전에 원문 확인 시도와 사용권 결정을 추가한다. 최초 수집 metadata·본문/원문 hash·블록·private_ref·D05 동결 원본·사람 인계 이미지는 수정하지 않는다. 확인만 갱신한다고 새 문서 버전·AI 실행·사건을 강제하지 않는다.

Java21·Spring Boot3.5.16·MySQL8.4.13·Python3.13과 기존 JDBC/Jackson/검증 도구를 사용한다. 새 의존성·AI 호출·HTTP 관리 endpoint·Java 계산 엔진·운영 배포는 추가하지 않는다. 실제3건을 사람이 확인한 것처럼 verified/allowed로 바꾸지 않는다. 사용자 .gitignore·AGENTS·원래 자료·다른 작업 공간을 보존하고 main은 사람이 병합한다.

## 로컬 요청과 의미

새 local-source-review 프로필의 일회성 명령은 myai.source-review.file, .actor를 받고 verified 확인에만 .source-root가 필요하다. stdout은 안전한 JSON 한 건, 진단은 stderr다. 결과에는 review_id/document_version_id/review_no/record_sha256/already_recorded만 넣고 본문·경로·사용권 메모·actor는 출력하지 않는다.

source-review-v1 요청은 아래 키를 모두 요구하며 추가 키·중복 키·후행 JSON·잘못된 UTF-8/Unicode·잘못된 scalar·공백만 있는 문자열을 거부한다. actor는128자/제어문자 금지이며 메모·사유는 기존 D03 text의 문자 의미를 보존하고 임의 trim하지 않는다. 새 check.note는 기존 TEXT 열에 맞춰 UTF-8 65535바이트 이하로 제한한다.

```json
{
  "schema_version": "source-review-v1",
  "review_id": "10000000-0000-4000-8000-000000000020",
  "document_version_id": "10000000-0000-4000-8000-000000000002",
  "expected_review_no": 0,
  "expected_text_sha256": "951432927f32fce5ec44844883644e3b11359a5a0b171964ed845c89a52a0b72",
  "check": {
    "checked_at": "2026-11-03T01:00:00Z",
    "result": "verified",
    "text_sha256": "951432927f32fce5ec44844883644e3b11359a5a0b171964ed845c89a52a0b72",
    "note": "합성 원문 확인 시험"
  },
  "use_review": "allowed",
  "use_note": "합성 자료 사용권 시험",
  "reason": "합성 확인·권한 결정"
}
```

- check는 null 또는 위4키다. result는 verified/changed/unreachable/uncertain이며 check_id는 review_id, reviewer_id는 명시한 CLI actor를 사용한다. checked_at은 실제 확인 시각의 선언이며 UTC·최대6자리 소수·MySQL1000~9999년이다. 미래/이전 확인보다 이르거나 같은 시각은 거부한다.
- use_review는 pending/allowed/restricted, use_note/reason은 비어 있지 않은 선언이다. 권한만 갱신하면 확인·성공 시각을 만들지 않는다. 확인 없이 같은 권한/메모를 새 ID로 반복하는 무변경 요청은 거부한다.
- verified는 같은 text hash와 실제 보존 원문을 기존 D03 source 검증으로 대조한다. 파일 I/O는 쓰기 트랜잭션 밖이다. 원문이 없어도 권한 제한·실패 확인을 기록할 수 있다. 기계 검증은 실제 URL 재접속·사람의 사실성/법적 판단·계정 인증을 대신하지 않는다.
- expected_review_no는 운영 이력0부터 시작하며 현재값을 자동 보충하지 않는다. review_id+입력 바이트 hash가 같은 재실행은 나중 이력이 있어도 원래 결과를 재사용하고 최초 actor/시각을 바꾸지 않는다. 같은 ID/다른 바이트·stale expected는 충돌이다.
- 정확 재실행은 DB 원본 fingerprint·운영/SQL 이력·ID/바이트 무결성을 확인한 뒤 기존 결과를 반환한다. 신규 확인이 아니므로 verified였더라도 source-root/파일 재검증을 생략한다. 원문 부재가 새 확인·승인/공개를 허용하는 것은 아니다.
- 성공0, 입력/설정/원문 검증2, ID/CAS/기록 충돌3, DB 의존성 장애4, 내부/프로토콜1. 초기 DB 연결/1044/1045/1049도 안전한 JSON4, 연결 장애만 retryable=true다. 웹/다른 프로필 혼합은 DB 시작 전에2다.

## 저장과 원본·운영 상태

V4 source_reviews는 review_id PK, document_version_id FK, review_no, input_sha256, record_json LONGTEXT/JSON_VALID, record_sha256과 UNIQUE(document_version_id,review_no)를 추가한다. 기존 V1~V3/행은 수정하지 않는다. 별도 head 테이블 없이 기존 document_versions 행을 mutex로 사용한다.

record_json의 source-review-record-v1은 record_version/review_id/document_version_id/review_no/document_sha256/previous_record_sha256/input_json/input_sha256/actor/recorded_at의 정확한10키를 가진다. input_json은 원래 요청 UTF-8 문자열, recorded_at은 서버 실제 MICROS 시각이다. 원본 Document 전체 fingerprint·원래 요청 hash·1부터 연속한 번호·이전 record hash·행/JSON 식별/정밀 시각을 재검증한다. 새 checked_at은 recorded_at 이하이고 이전 확인보다 엄격히 증가해야 한다. 과거 기록은 각 recorded_at/이전 기록을 기준으로 검증하며 현재 마지막 확인과 다시 비교하지 않는다. 과거 확인/권한 결정은 이어 붙이고 재작성하지 않는다. 정상 명령은 기록을 수정/삭제하지 않으며 관리자 전체 변조를 막는 WORM은 아니다.

새 check가 있으면 source_checks에도 같은 트랜잭션으로 INSERT하고 직전 성공 check_id를 연결한다. 완전한 reviewer/hash/권한 선언은 source_reviews에 보존하며 정보가 없는 legacy 열을 꾸미지 않는다. 초기 metadata의 checks/권한을 기준선으로 유지한다. SQL source_checks 전체는 초기 prefix와 운영 check의 ID/버전/시각/result/직전 성공/note에 정확히 대응해야 한다. 일반 view 읽기는 짧은 읽기 전용 REPEATABLE READ로 records/checks를 같은 snapshot에서 읽고, 잠금 검증은 현재 읽기를 사용한다.

PublicationRepository.Document6필드는 원본 전용으로 유지한다. 별도 SourceView(original,effectiveMetadata,reviewNo,reviewSha256,checkRecordedAt)만 운영 필드 use_review/use_note/checks/파생 확인 상태를 합친다. 본문/식별/수집/전처리/hash/경로·D05/Handoff full-D03 검증과 일반 import는 원본 경로를 그대로 사용한다. 누락/손상/잘못된 과거 hash·source_checks 불일치는 정상 상태로 조용히 대체하지 않는다. 요청·JSON escaping 후 개별 운영 기록·문서별 누적 운영 기록·유효 metadata 각각8MiB를 적용한다. 초과 candidate는 INSERT 전에 거부하고 기존 원본/기록과 호출자의 입력 파일을 그대로 둔다. 자동 backup을 만든다는 뜻은 아니다. 대규모 이력의 별도 보관/페이지 검증은 한도에 이르면 확장해야 한다.

## 트랜잭션·공개·과거 재현

- append는 원본 D03을 FOR UPDATE로 잠근 뒤 locking current read로 운영 기록·동일 ID를 읽고 원본 fingerprint/재실행/CAS를 확인한다. 새 source_checks와 기록을 원자 INSERT한다. 원문·D05·사건·공개 포인터는 갱신하지 않는다.
- source writer는 D05/event/head를 잠그지 않는다. 기존 공개의 D05→D03→revision/head 순서를 유지하고 정렬한 D03 원본 잠금 후 운영 번호/hash를 locking current read로 다시 대조한다. 0상태 동시 최초 입력은 같은 부모 잠금이 직렬화한다. 기존 transient/deadlock은 안전한 충돌·재시도로 처리하며 deadlock이 없다고 보증하지 않는다.
- 동일 publish의 여러 사건은 versionId별 같은 SourceView를 캐시하여 검증과 snapshot이 다른 상태를 섞지 않는다. approve/preview/publish는 현재 권한 allowed·last_verified_at 존재라는 기존 의미를 유지한다. 최신 실패 시도는 과거 성공을 지우지 않으며 기존 SOURCE_STALE 등의 공개 판정이 그대로 적용된다. 파일/Python 검증은 DB 트랜잭션 밖이며 쓰기 직전에 원본·운영 상태를 다시 확인한다.
- preview는 DB 쓰기 없이 검증한 view를 짧은 읽기/공유 잠금 트랜잭션에서 재확인한다. SELECT 전용 계정과 기존 읽기 전용 의미를 유지한다. 승인/반려·공개를 자동 실행하지 않는다.
- 새 replay 공개도 현재 사용권을 검사한다. 역사 checks는 checked_at<=cutoff와 추가 운영 check의 recorded_at<=cutoff를 모두 요구한다. 뒤늦게 입력한 과거 확인을 verified_snapshot 근거로 소급하지 않는다. current_*에는 현재 전체 상태를 유지하며 original checks의 기존 cutoff 처리·collected_at 제한은 보존한다.
- 이미 공개한 canonical snapshot·조회·내보내기·rollback에는 새 운영 이력을 덧씌우지 않는다. 새로운 restricted가 과거 공개본을 자동 철회한다는 보장은 추가하지 않는다.

## 인수 증거

요청/기록/원본 파서·미상/무변경/Unicode·원본 prefix·failed 시도/직전 성공·recorded cutoff·손상 검증의 RED→GREEN, 실제 격리 MySQL8.4.13에서 상태0·정확재실행/후속·동시충돌·늦은 INSERT rollback·권한변경과 approve/publish/preview 경합·기존 pending D03의 수동 다음revision 승인·D03/D05/Handoff 바이트/행 보존·공개/복구/SELECT전용 preview·실제JAR 안전한 JSON/초기DB/profile오류를 검증한다. 실제 자료/사람 선언/키/API·기존 서비스 변경은 하지 않는다.

전체 자체 리뷰·fresh 전체 리뷰1회와 유효 지적 전부 수정, source/통합 CI·자동/새 사람 리뷰를 확인하고 develop만 병합한다. 보류 minor0을 유지하고 판단/비용과 증거를 보관한 뒤 이번 자원만 정리한다.

