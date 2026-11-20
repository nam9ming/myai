# 시민 공개본 미리보기·발행·복구

[시민 수동 검토](citizen-review.md)에서 승인한 원문 표현을 별도 불변 공개용 기록으로 묶는다. `citizen:current` 채널과 `citizen-snapshot-v1`을 사용하며 기존 소상공인 `current/replay:*`·5지점·500m·14일·공개 JSON을 보존한다. [시민 목록·상세 구현 검토안](../../contracts/citizen-api.md)에서 이 공개본과 확보 이력을 읽는다. 최종 Flutter 계약 대조·검색/복합 필터·Python 시민 추출은 후속 단계다.

## 입력과 실행

전용 개발 DB·Java21·MySQL8.4와 원문 디렉터리를 준비한다. 먼저 [입력·승인](citizen-review.md#합성-자료로-재현)을 실행하고 **승인 결과의 실제 revision_id**를 확보한다. 예제의 고정 ID는 아직 승인하지 않은 최초 revision의 자리표시자다. 원본 예제를 덮지 말고 Git 제외 작업본에 복사해 수정한다.

```bash
# 저장소 루트에서 실행. 작업본의 revision_ids를 실제 승인 결과로 바꾼다.
mkdir -p data/private/citizen-publication
cp backend/examples/citizen-publish.json data/private/citizen-publication/preview.json
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-publication \
  --myai.publication.file=data/private/citizen-publication/preview.json \
  --myai.publication.source-root=backend/examples \
  --myai.publication.actor=synthetic-reviewer
```

새 schema는 `citizen-publication-command-v1`이다. `preview/publish`의 폐쇄 키는 `schema_version/action/reason/data_kind/revision_ids/expected_head_version`이다. 같은 사건을 중복 선택하지 않으며 승인된 현행 시민 revision만0~1000개 받는다. `area/points/rules_version/dictionary_version/mode/case_id`를 새 명령에 넣지 않는다. reason은4000자 이하다.

미리보기는 새 ID/checksum을 포함한 예정 JSON을 반환하며 DB·공개 head·요청 파일을 쓰지 않는다. 확인한 작업본의 action을 publish로 바꿔 별도 실행한다. 최초 시민 head의 expected는 null, 이후에는 직전 성공 결과의 실제 `head_version`이다. 승인은 공개와 별개이며 preview의 ID/checksum을 실제 공개 결과로 사용하지 않는다.

HTTP는 기존 [로컬 관리 인증·한도](local-management-api.md)를 그대로 적용한 `POST /local/publish`를 사용한다. 잘못된 계열·문자열 숫자·중복 키·추가 키·초과 본문은 거부한다. 입력/자료 검증422, stale revision/head409, DB 미준비503 등 기존 오류 규격을 유지한다.

## 발행·복구의 경계

발행 전 원문 사용권·확인 시각·파일 hash·근거와 승인된 현행 revision을 다시 확인한다. 쓰기 직전 원문·운영 확인·revision을 잠그고 snapshot·구성 revision·시민 head CAS·공개 감사를 한 트랜잭션으로 저장한다. 일부 실패나 경합에서는 이번 변경 전체가 rollback된다. 기존 소상공인 head·지점은 변경하지 않는다.

`revision_ids=[]` 공개는 시민 목록 전체를 비우는 명시적 작업이다. 이를 미검토 자료의 자동 공개나 검색 결과 없음과 혼동하지 않는다. 자료 종류 synthetic/real을 명시하고 합성 결과를 실제 자료 성과로 집계하지 않는다.

복구는 [복구 예제](../examples/citizen-rollback.json)의 `snapshot_id/expected_head_version`을 실제 값으로 바꾼다. 키는 `schema_version/action/reason/snapshot_id/expected_head_version`이며 source-root는 필요하지 않다. 같은 시민 채널에서 실제 발행한 기록만 선택하고 고정 bytes·checksum·DB schema/시각을 확인한 뒤 head와 감사만 바꾼다. 원문 파일·Python·최신 검토 상태로 과거 공개본을 재작성하지 않는다. DB 스키마의 되돌리기나 운영 배포도 아니다.

## 공개 JSON·출처

root는 `schema_version/snapshot_id/created_at/data_kind/mode/case_id/channel_key/timezone/revision_ids/notices/sources/notice_count`만 가진다. `mode=current`, `case_id=null`, `timezone=Asia/Seoul`이다. 사건·출처는 ID순이며 문서 다대다 관계와 근거를 보존한다.

notices는 제목·5분야·12개 사실 FieldValue·출처/문서 관계·근거다. 신청 기간과 진행 일정, 적용 지역/진행 장소/거주 자격, 비용 미상과 무료를 구별하며 날짜·금액·모집/자격/취소를 자동 판정하지 않는다. sources의 확인 이력은 생성 시 확보한 고정 기록이다. 후속 실패는 이전 성공 시점을 지우지 않으며 verified 외 확인의 다른 hash도 보존한다. 요청 시점의 실시간 재확인으로 표시하지 않는다.

공개 allowlist에는 원문 전체 필드·private 경로·AI/run 원본·검토자·사람 수정 전후 감사가 없다. 공개 인용의 실제 원문 대조는 발행 전 기존 원문 검증을 사용한다. 원문 없는 export/rollback에서는 공개 JSON 형식·참조·인용 길이·hash·고정 metadata를 검사하며 의미 정확성을 인증하지 않는다.

## 읽기 전용 검토·파일 전달

V5를 먼저 적용한 개발 DB에서 SELECT 전용 계정을 사용할 경우 미리보기 명령에 `--spring.flyway.enabled=false`를 추가한다. 원문·관련 보관본의 파일 읽기 권한은 필요하다. 발행/복구는 쓰기 계정을 사용하며 앱이 새 DB 계정이나 권한을 자동 생성하지 않는다.

`local-export`는 기존과 같은 명령으로 시민 공개본도 내보낸다. 공개했던 이전본도 가능하며 `<snapshot_id>-<checksum>.json`의 원래 UTF-8 bytes를 보존한다. 유효한 JSON의 공백을 제거하거나 재직렬화하지 않는다.8MiB 한도와 기존 파일/디렉터리/링크 충돌 보존은 그대로다.

[S10 보고서](review-report.md)는 시민 공개 이력과 명시 preview를 검증하고 실제 event_id→revision_id 기준의 추가/변경/제거를 비교한다. 원문 표현의 취소 상태를 정규화하지 않았으므로 `cancelled_events=null`이다. 빈 시민 preview는 선택 문서가 현재 시민 공개본에 연결된 경우만 허용한다. 관련 없는 문서로 전체 삭제 preview를 요청하면 거부한다. 보고서는 비공개 산출물이다.

## V5·재현 검증

V5는 기존 snapshots의 두 버전 열만 nullable로 바꾸고, 시민 schema는 rules/dictionary 둘 다 null, 기존 계열은 둘 다 non-null인 CHECK를 추가한다. V1~V4·기존 행·canonical JSON·checksum은 변경하지 않는다. 기존 V4 백업은 그대로 보관하며 [백업·복구](backup-recovery.md)의 새 빈 DB 복원 절차와 V5 적용을 구분한다.

시험은 `CitizenPublicationContentTest`, `CitizenPublicationMySqlTest`, `CitizenSnapshotMigrationTest`, `CitizenPublicationJarMySqlTest`와 기존 전체 회귀다. 자동 DB 시험은 전용 DB와 `MYAI_MYSQL_TESTS=true`를 사용한다. source/환경/명령·실제 결과·리뷰·원격 CI는 [작업 계획](../../docs/superpowers/plans/2026-11-18-citizen-publication.md)과 해당 PR을 따른다. 합성·MySQL9.6 보충 검증을 실제 MySQL8.4/Flyway·공식자료 품질·사람 인수·Flutter·배포 완료로 보고하지 않는다.
