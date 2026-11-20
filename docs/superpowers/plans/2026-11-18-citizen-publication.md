# 시민 공개본 발행·복구 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자 goal의 agents 분담·계획별 독립 전체 리뷰1회·Minor 포함 수정·정확 head CI/실제 자동 리뷰 후 develop 반영을 적용한다.

**Goal:** 승인한 시민 사실을 지점 없는 불변 공개본으로 미리보기·발행·복구·내보내고 S10에서 대조한다.

**Architecture:** `develop@09099acd62b234ddebad98a7153bd8a6a13f6c39`의 시민 수동 검토를 사용한다. 기존 revision·원문 검증·잠금·head CAS·공개 감사·파일 설치를 재사용하고 시민 producer/validator와 발행 서비스만 분리한다. 기존 `current/replay:*`와 다른 `citizen:current` 채널 및 `citizen-snapshot-v1`을 사용한다. 명칭은 작성자의 내부 구현 선택이며 최종 Flutter·사업 규칙 합의가 아니다.

**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4.13·기존 Jackson/JUnit/Flyway. 새 의존성 없음.

**Spec:** [제품 요구](../../spec/01_제품요구사항.md), [결정 기록](../../spec/07_결정사항과자체점검.md), [입력 규격](../../../backend/docs/citizen-review.md), [기존 공개](../../../backend/docs/review-publication.md), [재사용 조사](../../../backend/docs/citizen-backend-reuse.md).

## Global Constraints

- V1~V4·기존 revision/canonical JSON/hash·AI 원본·실패·gold/D09는 덮거나 읽지 않는다. 이번 자료는 공개 합성 예제뿐이다.
- 3유형·5지점·500m·14일·Python 계산 단일 원본은 그대로 유지한다. 시민 공개에 가짜 구역/규칙/사전 버전을 채우지 않는다.
- 시민 신청/진행·지역/장소/거주 조건·비용/모집/진행 표현과 미상은 현재 FieldValue로 보관한다. 정규화·무료/자격/취소 판정을 만들지 않는다.
- 공개본에는 검토자·human_overrides·AI/run 원본·private path·전체 원문 필드를 넣지 않는다. JSON8MiB·기존 파일 충돌/링크 방어·로컬 Bearer/loopback/Host/Origin 경계를 유지한다.
- 새 테스트는 연결/Flyway 전 전용 DB를 확인하고 소유 ID만 정리한다. 테이블 전체 DELETE·기존 공개 head의 임의 초기화를 추가하지 않는다.
- 사용자 .gitignore·AGENTS·원본 파일·미병합 frontend/integration·worktree 파일을 보존한다. main 병합/push·배포 금지. 모호한 사업 사항은 별도 기록하고 질문하지 않는다.

## Review Focus

- 동일 UUID라도 legacy/citizen schema·canonical·채널·공개 감사가 다른 계열이면 조회/발행/복구/내보내기에서 섞지 않는다.
- 승인 후 원문 권한/hash/운영 확인 또는 현행 revision이 바뀌면 발행을 거부하고 기존 공개본·모든 이전 bytes를 보존한다.
- 미리보기는 DB/요청 파일 쓰기0이며 SELECT 전용 계정에서도 작동한다. 실제 발행은 잠금/CAS/감사를 한 트랜잭션으로 commit한다.
- 새 JSON의 임의 내부 객체·큰 정수 count·근거/출처 불일치는 공개/export에서 통과하지 못한다. 기존 JSON의 검증 의미는 바꾸지 않는다.
- 두 발행의 경합은 한 승자이며 늦은 실패는 snapshot/head/audit 전체 rollback이다. V4→V5가 기존 행·checksum·Flyway 이력을 바꾸지 않는다.

## 내부 계약과 인터페이스

- `citizen-publication-command-v1`: `preview/publish`는 `schema_version/action/reason/data_kind/revision_ids/expected_head_version`, `rollback`은 `schema_version/action/reason/snapshot_id/expected_head_version`. 키 생략/추가 금지, UTF-8/중복키/UUID/범위는 기존 reader를 재사용한다. 공개 목록은0~1000개·중복 없는 UUID이며 새 head는 expected=null, 기존 head/rollback은 실제 번호를 사용한다.
- `PublicationCommand.CitizenPublish`와 `.CitizenRollback`은 기존 sealed interface를 구현한다. publish expected는 nullable Long, rollback은 non-null Long, 공통 reason4000자·expected0~Long.MAX_VALUE-1 규칙을 따른다.
- `CitizenPublicationContent.SCHEMA_VERSION="citizen-snapshot-v1"`, `.CHANNEL="citizen:current"`. 생성 메서드는 `snapshot(CitizenPublish, List<PublicationRepository.Revision>, Map<String, SourceView>, String id, Instant createdAt) -> PublicationRepository.Snapshot`, 검증은 `verifySnapshot(Snapshot, String dbSchema, Instant dbCreatedAt) -> void`다.
- 새 canonical root의 폐쇄 키: `schema_version snapshot_id created_at data_kind mode case_id channel_key timezone revision_ids notices sources notice_count`. mode=current·case_id=null·timezone=Asia/Seoul이며 지점·반경·구역·규칙/사전 필드는 없다.
- notices는 사건 ID순이다. 공개 키는 `event_id revision_id title categories`와 입력의12개 사실 FieldValue, `source_version_ids document_links relations evidence`다. 문서 관계에서는 reviewed_by를 제외한다. 내부 감사/AI/run/중복 후보/원문 경로는 선택하지 않는다.
- sources는 사용한 문서 버전 ID순이며 `document_id document_version_id publisher official_url title official_number published_date collected_at text_sha256 last_verified_at latest_check_attempt_at check_result checks`만 포함한다. checks에는 `checked_at/result/text_sha256`만 보관한다. 모두 공개본 생성 시의 고정값이며 실시간 재확인값이 아니다.
- public FieldValue의 value는 문자열/문자열 배열 또는 미상 null이다. 폐쇄 키와 evidence/source 참조·원문 hash·ID 유일성·count 정수 범위를 대조한다. 원문 의미 정확성을 기계 검사로 인증하지 않는다.
- `CitizenPublicationService.execute(PublicationCommand, Path root, String actor) -> PublicationService.Result`는 새 publish/rollback만 처리한다. 기존 PublicationService가 actor/예외 변환을 유지하며 위임한다. 공통 원문 `PublicationContent.validate`·D05 참조·행 잠금·head CAS·감사를 사용한다.
- `PublicationRepository.insertSnapshot(Snapshot,List<Revision>,Instant,String schema)` overload 추가, 기존3인자는 snapshot-v1에 위임한다. Snapshot record의 기존8인자는 유지한다. 새 `PublicSnapshotRepository.citizenPublished(String id) -> Optional<Published>`는 DB schema/current/case/channel/audit를 결합한다. 기존 published는 시민 계열만 제외하여 legacy의 손상 schema 오류 의미도 보존한다.
- V5에서 snapshot rules_version/dictionary_version만 nullable로 바꾸고 named CHECK로 시민은 두 값 null, 그 외 기존 계열은 두 값 non-null을 요구한다. 기존 행/캐노니컬 UPDATE 및 적용 migration 수정은 없다.

## 파일·소유권

| 소유자 | 책임·파일 |
| --- | --- |
| 공개 내용 worker | 새 `publication/CitizenPublicationContent.java`, 새 `CitizenPublicationContentTest.java`: 공개 투영·정확 allowlist·형식/참조/hash/metadata 검증 |
| 발행 worker | 새 `service/CitizenPublicationService.java`, 새 `CitizenPublicationMySqlTest.java`: 원문/승인 재검사·읽기 전용 preview·원자 발행·rollback·경합·소유 데이터 보존 |
| 주 작업자 | PublicationCommand/Reader·기존 PublicationService 위임·PublicationRepository/PublicSnapshotRepository·V5/이전 보존 시험·LocalManagementService·SnapshotExportService·ReviewReportService/Repository·영향받는 시험/예제/문서·전체 검증·PR/정리 |

다른 작업자도 같은 worktree에 있으므로 소유 파일만 수정하고 타인 변경을 되돌리지 않는다. 공유 인터페이스는 위 이름/형식으로 고정한다. Gradle은 주 작업자가 전담한다.

### Task 1: 명령·저장·계열 경계

**Files:** 기존 Command/Reader, PublicationRepository/PublicSnapshotRepository, 새 V5, 관련 명령/DB 시험.

**Interfaces:** 위 DTO·insertSnapshot overload·citizenPublished. 기존 Decision·Snapshot·Published·legacy parser 호출 형식은 유지한다.

- [x] 새 명령과 실제 시민 발행의 실패 시험을 먼저 작성·실행한다. approve/reject·가짜 points/rules·미지원 action을 새 publication schema로 받지 않는다.
- [x] DTO/reader·schema 인자 저장·계열별 공개 조회를 연결한다. V5와 V4→V5 이전/원본 보존 시험을 추가한다.
- [ ] 같은 DB에서 old rule/dictionary non-null 제약·시민 null·모든 기존 canonical/hash/행과 V1~V4 checksum 보존을 확인한다.

### Task 2: 공개 투영·무결성

**Files:** 공개 내용 worker 소유 파일.

**Interfaces:** `snapshot(...)`는 기존8인자 Snapshot을 반환하며 versions=null이다. `verifySnapshot(...)`은 DB schema/createdAt·canonical/checksum·current/null case·고정 채널을 결합하고 공개 폐쇄 형식을 검사한다.

- [x] 5분야·문자열 배열·미상·신청/진행 분리·다대다 출처·정확 공개 필드의 실패 시험을 작성한다.
- [x] 기존 select/parse/payload·원문 검증 결과를 재사용해 새 producer/validator만 구현한다. 기존 producer/old payload를 재직렬화하지 않는다.
- [x] 내부 필드 주입·범위를 넘는 count·근거/source 불일치·누락/중복·잘못된 schema/channel/hash/DB 시각의 거부와8MiB 한도를 검증한다.

### Task 3: 미리보기·발행·복구

**Files:** 발행 worker 소유 파일, 주 작업자의 기존 PublicationService 위임.

**Interfaces:** 새 Service는 공통 Result를 사용한다. preview는 새 ID/checksum만 반환하고 DB/파일에 쓰지 않는다. publish는 승인된 현행 시민 revision·동일 data_kind만 선택한다. rollback은 같은 시민 채널에서 실제 공개한 불변 row만 사용하며 원문/계산기를 호출하지 않는다.

- [x] 기존 공개 head와 무관한 시민 preview/publish/rollback 실패 시험을 먼저 실행한다.
- [x] 원문 사용권·파일/hash·근거·현재 revision·AI 참조를 기존 경계로 재검사하고 쓰기 직전 잠금/CAS/감사를 적용한다.
- [x] SELECT 전용 preview, 승인/원문 변경, 미승인/legacy 혼입, 빈 공개,0→다음 head, 동시 한 승자·늦은 실패 rollback·과거 bytes 보존을 실제 전용 DB에서 검증한다.

### Task 4: 호출자·export·보고서·인계

**Files:** 주 작업자의 LocalManagementService·SnapshotExportService·ReviewReportService/Repository·기존 생성자 호출 시험·합성 예제·문서.

**Interfaces:** `/local/publish`와 local-publication CLI에 새 schema를 연결한다. export의 파일명/원문 bytes/읽기 전용·충돌 보존을 유지하며 시민 validator를 선택한다. S10의 공개 이력 검증/명시 preview/기준 head 비교는 시민 채널을 사용한다. 변경 집계는 event_id→revision_id의 실제 차이이며 정규화되지 않은 취소 수는 null로 표시한다.

- [x] 실제 로컬 dispatch·시민 export exact bytes·보고서 검증/preview의 실패 시험을 먼저 추가한다. 기존 public events/config/matches에서 시민 UUID를 legacy로 읽지 않음을 검증한다.
- [x] 호출자·오류·형식 분기를 연결하고 기존 legacy allowlist·기록·변경 집계 의미를 보존한다.
- [x] Java/DB/계약·Node 검증·필요한 Python 회귀·실제 JAR/SELECT 계정·이전 데이터 보존을 실행하고 전체 변경 자체 검토를 반복한다.
- [ ] 계획별 독립 전체 리뷰1회와 모든 유효 지적 수정을 마친 뒤 영어 Conventional Commit·한국어 develop PR을 제출한다. 정확 head의 실제 CI/자동/도착한 사람 의견이 유효 미해결0이면 반영·동일 tree 확인·본인 branch만 정리한다.

## 인수·다음 작업

이번 단계는 시민 불변 공개·내보내기·복구의 기반이다. 시민 목록/상세·검색/필터·Python 시민 추출/사람 인계·Flutter 실제 연결·실자료/독립 평가·운영 배포는 후속이며 전체 goal을 완료 처리하지 않는다. PR20 main 검토용 통합 CI는 별도 추적하고 기존 신뢰 경계/부분 자동 검토 기록을 보존한다.

## 구현·로컬 검증 기록

2026-11-18 기준 시민 명령·별도 공개/복구·export/S10·V5와 호출자/예제/문서를 구현했다. 최초66개 중 신규27개 RED 후, 최종 관련124개는 실패/생략0이다. 전체 Java955개/66클래스 중939개 통과·16개 환경 실패·생략0이며, Docker 부재9개와 로컬 root/빈 비밀번호 조건7개를 구분했다. 후자7개를 포함한4클래스30개는 전용 제한 계정으로 재실행해 실패/생략0이다. Docker8.4.13의 최종 전체 실행은 정확 head 원격 CI에서 확인한다.

Python3.13 전체632개/323.859초·Node34개·계약9개·린트440파일·정적 빌드·변경 Markdown 로컬 링크167개를 통과했다. 실제 JAR8단계에서는 SELECT 전용 preview/export/S10의 DB 무쓰기와 원문 삭제 뒤 canonical/hash 복구·head2·기존 head0을 확인했다. 이 로컬 MySQL9.6 보충 증거를8.4 실제 Flyway 이전·Docker 시험 증거로 바꾸지 않는다.

독립 전체 리뷰1회는 tracked21+신규11개와 관련 호출자를 검토해 확정 지적0이었다. 자체 검토도 유효 미해결0이며, 원격 CI·실제 AI 코멘트·도착한 사람 의견과 병합/정리는 PR에 추가 기록한다.
