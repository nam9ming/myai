# 시민 공지 수동 검토 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자가 지정한 agents 분담과 계획별 독립 전체 리뷰 1회를 적용한다. Minor도 모두 수정한다.

**Goal:** 시민 5분야의 원문 근거가 있는 사실을 숨김 revision으로 입력·수정하고 명시적으로 승인/반려한다.

**Architecture:** 기존 D03 문서·근거 검사, D06 불변 revision·CAS·감사, 로컬 관리 보안과 승인 트랜잭션을 재사용한다. 새 내부 입력 버전과 payload 식별자를 추가하며 기존 JSON·행·공개 snapshot bytes는 바꾸지 않는다. 새 공개 snapshot·시민 조회·Python 추출은 다음 계획이다.

**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4·기존 Jackson/JUnit. 새 의존성 없음.

**Spec:** [현재 요구](../../spec/01_제품요구사항.md), [결정 기록](../../spec/07_결정사항과자체점검.md), [재사용 조사](../../../backend/docs/citizen-backend-reuse.md). 2026-11-18 사용자의 추가 질문 없이 확정 범위 진행 지시를 적용한다. 아래 JSON 이름은 작성자의 내부 구현 선택이며 프런트 최종 합의를 뜻하지 않는다.

## Global Constraints

- 원문·AI 원출력·실패·사람 수정 revision·승인·불변 공개 snapshot을 보존한다. 적용된 Flyway V1~V4를 수정하지 않는다.
- 기존 3유형 API·5지점·500m·14일 계산과 Python 단일 원본을 보존한다. 시민 입력에 가짜 구역·사전·좌표를 넣지 않는다.
- 공개 조회 중 AI 미호출과 로컬 관리의 Bearer·loopback·Host/Origin·8MiB JSON/20MiB 원문 경계를 유지한다.
- 비밀값·비공개 원문·독립 정답·실제 사용자 기록을 읽거나 공개하지 않는다. 합성 자료만 사용한다.
- 기존 worktree와 사용자 `.gitignore`·AGENTS·미병합 frontend 브랜치를 보존한다. `main` 병합·push·운영 배포를 하지 않는다.
- 모르는 사업 규칙은 별도 기록하며 질문하지 않는다. 내부 원문 표현 보관을 최종 검색·모집·비용 판정 계약으로 주장하지 않는다.

## Review Focus

- 잘못된 family 명령·동일 사건의 family 교체는 승인과 반려 모두 거부하고 기존 행을 보존한다.
- 이전 근거를 제거한 수정도 전후 값·과거/현재 근거의 합집합으로 감사하고 과거 기록 변조는 거부한다.
- 신청 기간과 진행 일정, 장소/적용 지역/거주 자격, 비용 미상과 무료를 다른 필드로 보관한다.
- pending/restricted 원문·실제 원문 hash 변조·미래 확인 시각은 승인에서 차단한다.
- 동시 수정·늦은 실패는 한 승자 또는 전부 rollback이며 승인만으로 공개 head/snapshot을 생성하지 않는다.

## 내부 입력 계약

- 새 envelope `citizen-reviewed-import-v1`: 기존 최상위 `schema_version/data_kind/documents/evidence/events`와 문서/근거 형식을 재사용한다. human 전용이다.
- 새 payload에만 `schema_version=citizen-revision-v1`을 둔다. 기존 payload의 식별자 부재는 legacy이며 다른 식별자는 거부한다.
- 사건은 기존 형식에서 `area_id/area_membership`만 제외한다. document_links·relations·suspected_duplicate_ids·split_group_id·예상 revision을 유지한다.
- revision은 `revision_id event_id revision_no title categories application_period occurrences regions locations residency_requirement target eligibility application_method preparation cost recruitment lifecycle human_overrides review_status reviewer_id reviewed_at publication_intent origin source_version_ids originating_run_ids`의 폐쇄 객체다.
- `categories`는 중복 없는 비어 있지 않은 배열: `education/support/culture/construction_traffic/living` = 교육·배움/지원·혜택/행사·문화/공사·교통/생활정보. 자동 추론하지 않는다.
- `title`은 원문을 대조한 문자열이다. categories 이후의 12개 사실 필드는 기존 `value/knowledge/evidence_ids/reason` 형식의 FieldValue다. known이면 근거와 문자열 또는 문자열 배열, 그 외는 null과 이유가 필요하다. 날짜·비용·자격을 자동 정규화하거나 판단하지 않는다.
- 새 입력은 `origin=human`, `originating_run_ids=[]`, draft/needs_review·hidden만 허용한다. 최초 human_overrides는 빈 배열이다. 후속 수정은 이전 감사 prefix와 실제 변경 전후·검토자·시각을 보존한다.
- `citizen-review-command-v1`은 기존 Decision DTO의 approve/reject만 지원한다. 상태 approved/public은 공개 **의도**이며 이 단계에서는 공개본을 만들지 않는다. 기존 publish/preview/rollback은 시민 revision을 거부한다.

## 파일·분담

| 소유자 | 파일·책임 |
| --- | --- |
| 입력 worker | `ReviewedImportReader.java`, 새 `CitizenReviewedImportReaderTest.java`: 명시 schema dispatch·사실/근거/관계 검증·기존 bytes 회귀 |
| 저장/승인 worker | `HumanReviewChanges.java`, `ReviewedImportRepository.java`, `PublicationCommandReader.java`, `PublicationContent.java`, `PublicationService.java`, 새 `CitizenReviewMySqlTest.java`, 기존 관련 단위 시험: family·수정 감사·승인/반려·원자성 |
| 주 작업자 | 합성 예제·문서·이 계획, `LocalManagementService.java`·관련 시험, `ReviewReportService.java`·관련 시험: 실제 진입점·보고서·재현 안내·통합 검증 |

다른 작업자가 같은 worktree에 있으므로 소유 파일만 수정하고 타인의 변경을 되돌리지 않는다. 공유 인터페이스는 `ReviewedImportReader.CITIZEN_IMPORT_VERSION`, `.CITIZEN_PAYLOAD_VERSION`, `.CITIZEN_FIELDS`, `schemaForPayload(JsonNode)`로 고정한다. 마지막 함수는 legacy/citizen import 버전을 반환하며 미지원 식별자는 ImportException으로 거부한다.

### Task 1: 시민 원문 사실 입력

**Interfaces:** 기존 `read(byte[], Path)`·`read(Path, Path)`·`validateStored(JsonNode, Path)` → 기존 `ReviewedBatch`; 기존 문서/근거/관계 검증 재사용. `CITIZEN_FIELDS`는 title/categories와 12개 사실·source_version_ids/originating_run_ids를 포함하는 감사 목록이다.

- [ ] 합성 `backend/examples/citizen-reviewed-import.json`·`citizen-source.txt`를 고정한다.
- [ ] 각 분야 입력, 신청/진행 및 미상 비용 보존의 실패 시험을 작성한다. 기존 reader의 schema_version 거부 실패를 확인한다.
- [ ] strict 새 형식과 payload 식별자를 구현한다. 여분 키·잘못된 근거/출처·중복 분류·허위 승인·AI origin·가짜 area/rules를 거부한다.
- [ ] `./backend/gradlew -p backend test --tests '*CitizenReviewedImportReaderTest' --tests '*ReviewedImportReaderTest'` → 모두 통과.

### Task 2: 수정 감사·명시 승인/반려

**Interfaces:** `HumanReviewChanges.record(..., List<String> fields)`와 `validate(..., boolean generatedHandoff, List<String> fields)` 추가, 기존 overload는 기존 목록을 유지한다. 기존 Decision/Result·DB 저장 서비스·row lock·source 검증을 사용한다.

- [ ] 새 승인 명령·family 교체 차단·시민 수정 감사에 대한 단위 실패 시험을 먼저 실행한다.
- [ ] 새 계열의 import는 모든 실제 사실 변경을 감사 검증한다. 같은 event의 legacy↔citizen 변경을 공통 append에서 차단한다.
- [ ] 새 명령은 승인/반려만 허용하고 명령 family를 저장 payload에 대조한다. 승인 시 원문 권한·파일 hash·근거·시각·CAS를 재검사한다. 기존 공개 명령은 시민 revision을 받지 않는다.
- [ ] `MYAI_MYSQL_TESTS=true` 전용 MySQL8.4 시험에서 5분야 입력→수정→승인/반려, 중복 재시도, 교차 계열, 잘못된 감사, 동시 수정, 배치 후반 실패의 원자성·기존 bytes 보존을 검증한다.

### Task 3: 실제 로컬 진입점·검토 보고서·인계

**Interfaces:** 기존 `/local/reviews/import`, `/local/events/{id}/review`·`local-import`/`local-publication` CLI·S10 보고서에 새 schema를 연결한다. URL 사건 일치·원래 요청 bytes 보관·기존 오류 계약을 유지한다.

- [ ] 새 입력의 로컬 연결 실패 시험과 시민 revision의 보고서 검증 실패 시험을 먼저 확인한다.
- [ ] 로컬 dispatch와 보고서 envelope 선택을 연결한다. 새 승인만으로 공개 snapshot/head를 만들지 않는지 시험한다.
- [ ] 새 내부 규격·curl/CLI·데이터 초기화·분야별 기대 결과·미완료를 한국어로 문서화한다. 실제 팀원/공식자료 평가 완료를 주장하지 않는다.
- [ ] Node24 lint/test/build·계약 예제·Python 전체·Java 전체/bootJar·전용 MySQL8.4 시험을 실행한다. 전체 diff 자체 검토와 계획별 독립 전체 리뷰1회 후 모든 유효 지적을 수정·관련 재검증한다.
- [ ] 영어 Conventional Commit으로 기록하고 `develop` 대상 PR을 제출한다. 정확 head의 CI·실제 AI/사람 의견을 확인해 유효 미해결0일 때만 병합·병합 결과 검증·본인 작업 브랜치 정리. 결과는 PR 본문에 남긴다.

## 후속 단계

시민용 불변 snapshot·독립 head·preview/publish/rollback·export/report 호환을 다음 계획으로 수행한다. 그 뒤 시민 목록/상세와 확정된 검색·필터·Python 인계·같은 공개본의 5분야 수직 인수로 진행한다. 현재 계획 완료를 전체 백엔드·Flutter·실자료 평가·운영 완료로 표현하지 않는다.
