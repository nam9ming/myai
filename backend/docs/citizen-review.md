# 시민 공지 수동 입력·검토

시민 5분야의 원문 표현을 검토 revision으로 보관하는 **내부 입력 규격**이다. 기존 소상공인 규격·공개본과 구별하며 최종 Flutter 조회 계약이나 모집·비용·자격 판정 규칙을 확정한 것은 아니다. 작성자가 선택한 필드명·분류 코드는 이후 화면 연동 때 대조한다.

## 보관하는 정보

`citizen-reviewed-import-v1`은 기존 `data_kind/documents/evidence/events` 구조와 D03 원문 파일·hash·code point 근거 검사를 사용한다. 사건 ID·문서 다대다 관계·정정/취소 관계·중복 후보·revision CAS를 유지하며 `area_id/area_membership`·규칙/지명 사전 버전·시험 지점은 요구하지 않는다.

| 분류 코드 | 분야 |
| --- | --- |
| `education` | 교육·배움 |
| `support` | 지원·혜택 |
| `culture` | 행사·문화 |
| `construction_traffic` | 공사·교통 |
| `living` | 생활정보 |

`categories`는 하나 이상이며 중복을 허용하지 않는다. `title`은 원문을 대조한 문자열이다. 아래 필드는 `value/knowledge/evidence_ids/reason` 객체이며, 현재는 원문의 문자열 또는 문자열 배열을 보관한다.

| 필드 | 구별하는 의미 |
| --- | --- |
| `application_period` / `occurrences` | 신청 시작·마감 표현 / 실제 진행 일정 표현 |
| `regions` / `locations` / `residency_requirement` | 정보 적용 지역 / 진행 장소 / 거주 자격 조건 |
| `target` / `eligibility` | 안내 대상 / 신청 자격·조건 |
| `application_method` / `preparation` | 신청 방법 / 준비사항 |
| `cost` / `recruitment` / `lifecycle` | 비용 조건 / 모집 상태 / 진행·취소 상태 |

`known`에는 유효한 근거가 필요하다. `not_stated/ambiguous/not_applicable`은 `value=null`과 이유를 보관한다. 비용 미상을 무료로 바꾸거나 마감일을 진행 종료일로 복사하지 않는다. 시각·통화·금액·모집 가능 여부를 자동 계산하지 않으며 연령·관심사로 자격을 확정하지 않는다.

## 입력·수정·승인

새 일반 수동 입력은 `origin=human`, `originating_run_ids=[]`, `draft/needs_review`·`hidden`이다. [전용 시민 인계](../../contracts/citizen-human-handoff.md)만 검증한 전체 봉인 proof와 등록 D03/D05를 바탕으로 최초 `ai_reviewed/needs_review/hidden`을 만든다. 일반 JSON으로 최초 AI proof를 추가할 수 없으며 후속 수동 수정은 기존 run/source/proof와 실제 전후 감사를 유지한다. 추가/중복 키·잘못된 Unicode·허위 승인 상태·다른 문서의 근거를 거부한다. 저장 payload에만 `schema_version=citizen-revision-v1`을 넣고 기존 payload bytes는 바꾸지 않는다. 동일 사건을 기존 소상공인 계열과 시민 계열 사이에서 전환할 수 없다.

최초 `human_overrides`는 빈 배열이다. 이후 수정은 새 `revision_id`, 증가한 `revision_no`, 직전 번호 `expected_revision_no`, 검토자·시각과 변경 전후/이유/근거가 필요하다. 과거 감사 prefix를 유지하며 제거된 과거 근거도 전후 근거 합집합과 대조한다. 새 원문 버전은 별도 버전으로 등록한다.

`citizen-review-command-v1`은 `approve/reject`만 받는다. 필드는 기존 Decision과 같은 `schema_version/action/reason/event_id/expected_revision_no/evidence_ids`다. 승인 전 원문 사용권·확인 기록·파일 hash·근거를 다시 검사한다. 성공하면 승인/반려 revision과 감사가 추가되며 이전 revision은 보존된다. `approved/public`은 공개 의도이며 **승인만으로 snapshot·공개 head·공개 API를 만들거나 바꾸지 않는다.** 기존 publish/preview/rollback에 시민 revision을 섞을 수 없다.

## 합성 자료로 재현

운영·공유 DB 대신 새 전용 MySQL8.4 시험 DB에 [백엔드 설정](../README.md#mysql-기초-실행)을 적용한다. 다음 명령은 저장소 루트에서 실행하며 예제는 실제 공지·사람의 검수 기록이 아니다.

```bash
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=backend/examples/citizen-reviewed-import.json \
  --myai.import.source-root=backend/examples \
  --myai.import.actor=synthetic-reviewer
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-publication \
  --myai.publication.file=backend/examples/citizen-approve.json \
  --myai.publication.source-root=backend/examples \
  --myai.publication.actor=synthetic-reviewer
```

초기 입력은 숨김 revision1, 같은 원래 bytes 재시도는 같은 import 결과, 승인은 revision2가 기대 결과다. 이미 승인한 뒤 같은 expected1 명령을 재전송하면409/CLI 종료3이며 별도 공개본은 없다. 예제를 초기화하려면 테스트 전용의 새 빈 DB를 사용한다. 기존 DB의 행을 지우거나 실제 자료를 예제 파일에 덮어쓰지 않는다.

HTTP는 기존 [로컬 관리 설정·인증](local-management-api.md)을 그대로 사용한다. `POST /local/reviews/import`는 배치, `PUT /local/events/{id}/review`는 동일 사건1건의 입력 또는 승인/반려를 받는다. Bearer·loopback·Host/Origin·요청 원래 bytes 보관·오류 형식·8MiB 한도를 유지한다. S10 [검토 보고서](review-report.md)는 시민 payload와 감사도 비공개로 대조한다.

## 검증·남은 범위

재현 시험은 `CitizenReviewedImportReaderTest`, `CitizenReviewMySqlTest`, `LocalManagementServiceTest`, `ReviewReportMySqlTest`와 기존 전체 회귀를 따른다. 전용 DB의 `MYAI_MYSQL_TESTS=true` 없이 MySQL 시험 통과를 주장하지 않는다. 환경·실제 결과·리뷰/PR 증빙은 [작업 계획](../../docs/superpowers/plans/2026-11-18-citizen-review.md)과 해당 PR에 기록한다.

`CitizenReviewMySqlTest`의 자동 DB 시험은 연결 전 `DB_URL`의 DB명이 `myai_test` 또는 `myai_citizen_test`인지 확인한다. 운영/공유 DB나 기본 `myai_dev`를 지정하지 않는다. 공개 회귀는 고유 replay 채널을 사용하며 정리는 해당 시험이 만든 snapshot ID로 제한한다. 수동 CLI·앱의 DB명 계약을 변경한 것은 아니다.

[시민 공개본](citizen-publication.md)은 별도 명령과 채널로 미리보기·발행·복구·내보내기를 연결하며 [시민 조회 구현 검토안](../../contracts/citizen-api.md)에서 같은 공개본의 목록·상세·확보 이력을 읽는다. 기존 publication-command-v1의 시민 revision 거부는 유지한다. [수동 추출/사람 인계](../../contracts/citizen-human-handoff.md)는 별도 family로 연결하며 실제 검증·반영은 각 계획을 따른다. 검색·복합 필터·정규화된 일정/비용·새 추출 API 실행·Flutter 연동·실제 팀원 인수·독립 정확도 평가·운영 배포는 후속 단계다. 합성 시험을 실제 자료 정확도나 최종 계약 합의로 표현하지 않는다.
