# Source Review History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 D03 버전의 확인·사용권 이력을 원본/D05 변경 없이 추가하고 승인/공개/과거재현 검증에 연결한다.
**Architecture:** V4 append-only source_reviews+기존 source_checks. immutable PublicationRepository.Document와 effective SourceView 분리, 부모 D03 잠금·locking current read로 CAS/공개 경합 검사.
**Tech Stack:** Java21·Spring Boot3.5.16·MySQL8.4.13·Python3.13 stdlib·기존 JDBC/Jackson/JUnit.
**Spec:** docs/superpowers/specs/2026-11-04-source-review-design.md

## Global Constraints

- 원본 D03 metadata/body/private_ref·동결 D05/사람 인계·과거 revision/snapshot·user .gitignore/AGENTS/다른 작업 보존.
- 실제 자료 verified/allowed·실제 사람/정답·AI/API/키·기존 DB/서비스·main 배포 변경 금지.
- 새 의존성·HTTP 관리 API·계산 엔진·V1~V3 수정 없음. 영어 Conventional Commits, 문서/PR/주석 한국어.
- 파일/Python I/O 트랜잭션 밖, 명시 expectedNo/CAS·same-ID exact bytes 재사용, Unicode/정밀 시각·8MiB 안전 경계 유지.
- source 권한은 현재 결정, replay checks는 checked/recorded cutoff 둘 다. 공개된 불변본 rollback 계약 유지.
- 부모만 stage/commit, 작업자별 파일 소유권과 인터페이스를 지킨다.

## Review Focus

1. original/effective metadata 혼용으로 원래 D05/Handoff·정확재실행이 깨지거나 새 확인이 사라지는가 — Task2+3 실제 D05/Handoff/원본 보존 시험.
2. 0상태 첫 INSERT·rights-only·늦은 실패와 공개 경합에서 stale 상태가 통과하는가 — Task2+3 locking current read·동시/rollback/콜백 시험.
3. 같은 문서가 여러 사건에 사용될 때 검증과 snapshot의 운영 버전이 다른가 — Task3 publish별 versionId 캐시 시험.
4. 나중 등록한 backdated check가 과거 verified_snapshot으로 유입되는가 — Task1 visibility·Task3 실제 replay cutoff/기존 snapshot 불변 시험.
5. 원문 없는 restricted/실패 기록·정확재실행·SELECT전용 preview가 정상 사용을 막는가 — Task2+3 실제 파일 부재/재실행/읽기계정 JAR 시험.

## Files and Ownership

- Core worker: backend/.../source/SourceReviewCommandReader.java, SourceReviewException.java, SourceReviewState.java, SourceView.java 및 SourceReviewCommandReaderTest.java/SourceReviewStateTest.java. 필요하면 기존 readBounded의 caller 검색 후 ReviewedImportReader.java의 helper visibility 한 줄만 공개한다(동작 변경 금지).
- Repository/service worker: backend/.../repository/SourceReviewRepository.java, service/SourceReviewService.java, resources/db/migration/V4__add_source_review_history.sql만.
- DB test worker: backend/src/test/.../SourceReviewMySqlTest.java와 필요한 본인 SourceReviewFixtures.java만.
- Coordinator: PublicationContent.java/PublicationService.java, CLI SourceReviewCommand.java·startup guard/Main/기존 guard·spring.factories/profile, SourceReviewStartupTest/기존 기대값·문서/예제/공통 검증·자원/PR.
- 소유권 밖은 부모에게 요청한다. 다른 변경을 되돌리거나 Git/index를 수정하지 않는다.

### Task 1: 요청·불변 운영 기록·SourceView

**Interfaces:**
- SourceReviewCommandReader.read(Path), parse(byte[]) → Request(reviewId:String,documentVersionId:String,expectedReviewNo:long,expectedTextSha256:String,check:Check|null,useReview:String,useNote:String,reason:String,inputJson:String,inputSha256:String).
- Check(checkedAt:Instant,result:String,textSha256:String,note:String). check ID=reviewId/reviewer=CLIactor.
- SourceReviewException(code:String,field:String), (code:String,field:String,retryable:boolean) overload와 code()/field()/retryable(), 기본false. safe message/field, code SOURCE_REVIEW_VALIDATION_ERROR/CONFLICT/DATABASE_UNAVAILABLE/INTERNAL_ERROR. DB 연결 SQL08만 retryable=true, 인증/권한/없는DB는false.
- SourceView(PublicationRepository.Document original,String effectiveMetadata,long reviewNo,String reviewSha256,Map<String,Instant> checkRecordedAt). SourceView(Document) 초기0/default 생성자, immutable map. checkVisible(String checkId,Instant cutoff)는 추가 check의 recordedAt도 검사(원래 check는 기존 checked_at cutoff 경로 유지).
- SourceReviewState.Stored(reviewId:String,documentVersionId:String,reviewNo:long,inputSha256:String,recordJson:String,recordSha256:String).
- SourceReviewState.documentSha(Document), view(Document,List<Stored>)→SourceView, append(SourceView,Request,String actor,Instant recordedAt)→Stored. 생성한 기록도 view로 재검증 후 SQL 사용.

- [ ] 새 parser/상태 부재 RED 및 엄격 scalar/shape/duplicate/UTF8/Unicode·actor/time/overflow·no-op·verifiedhash·초기 prefix/권한-only·과거 성공/failed 이력·정확한 기록/hash/이전연결/8MiB 손상·cutoff 시험을 작성/관찰한다.
- [ ] 기존 json parser/제한/UTC/sha helper를 재사용한다. 요청은 한 번 읽은 제한된 바이트로 hash와 원문을 보존한다. 원래 source metadata는 deep copy 후 운영 필드만 수정한다.
- [ ] 기록은 spec10키·실제MICROS·actor·원래inputJson·부모fingerprint·이전hash를 보존한다. 모든 과거 번호/hash/행대응과 시간/원래prefix를 검사한다. future check와 순서 위반/no-op·check.note UTF8 TEXT65535·개별/누적8MiB 초과를 거부한다.
- [ ] 기존 PublicationContent 테스트는 부모가 SourceView로 적응한다. 새 단위 시험과 기존 reader/시간/출처 단위 시험 GREEN을 확인한다.

### Task 2: append 저장·출처 검증·실제 MySQL

**Interfaces:**
- SourceReviewService.review(Path file,Path sourceRoot|null,String actor) → Result(reviewId:String,documentVersionId:String,reviewNo:long,recordSha256:String,alreadyRecorded:boolean).
- SourceReviewRepository.view(PublicationRepository.Document)→SourceView; lockView(SourceView) 원본 FOR SHARE+전체 운영 locking current read 대조, SELECT 전용도 지원.
- Repository/service 내부 append 시 document_versions FOR UPDATE→전체 source_reviews locking current read→동일id/bytes 재실행→명시CAS→source_checks+source_reviews INSERT. new head table 없음. 세부 private helper는 담당자가 정하되 부모 문서/공개 caller 인터페이스를 바꾸지 않는다.
- view는 원본/운영기록/source_checks를 짧은 읽기전용 RR에서 같은 snapshot으로 대조한다. lockView는 FOR SHARE 현재읽기만 사용하고 baseline+운영SQL 전체 일치를 검사한다. source_checks의 원래prefix/새운영check 저장열을 모두 대조한다.

- [ ] DB test worker가 실제 missing service/schema RED를 먼저 관찰한 후 repository/service 구현을 시작한다.
- [ ] V4 새 테이블/unique/FK/JSON_VALID를 추가한다. 기존 document/source_checks/D05 값은 초기 migration으로 재작성하지 않는다.
- [ ] 서비스는 기존 PublicationRepository.Document 원본을 확보한다. verified 확인만 source-root와 기존 source-import/validateStored 검증으로 실제 원문/hash를 트랜잭션 밖에서 대조한다. 실패/권한제한은 원문 없어도 기록한다.
- [ ] 동일ID/hash를 CAS/verified 파일I/O보다 먼저 재사용하고 최초actor/시각 유지. 신규verified만 원문 검증한다. 다른ID stale expected/기존ID 다른바이트 충돌, 새 check/권한 결정 원자성·전체기록 및 source_checks 대응 검증·안전한 오류를 구현한다.
- [ ] 실제 격리8.4.13에서 초기0/후속/rights-only/원문없음·정확재실행/동시동일/상충·변조/실패rollback·새check의직전성공·원본/D05/Handoff 보존·안전한 오류 시험 GREEN. 기존 DB 시험도 유지한다.

### Task 3: 승인·공개·CLI·전체 검증

**Interfaces:** PublicationContent.validate(JsonNode,List<SourceView>,Path)와 snapshot(Publish,List<Revision>,Map<String,SourceView>,String,Instant). SourceReviewRepository.view/lockView를 PublicationService가 주입 받아 publish별 같은 versionId view를 캐시한다. 기존 Document6필드와 D05/Handoff 검증은 그대로다.

- [ ] pending 원본+운영 allowed/verified로 수동 다음revision 승인, restriction/block·동일문서다사건 캐시·writer/approve/publish/preview 경합·backdated check/recorded cutoff·과거 snapshot/rollback 불변·SELECT전용 preview의 실패 시험을 먼저 추가/관찰한다.
- [ ] content의 identity/hash/private_ref는 original, 권한/checks는 effective로 검사하고 snapshot과 같은 view를 사용한다. current_*는 전체상태, historicalchecks는 두 cutoff. 검증 단계 원문/Python은 트랜잭션 밖, final preview/write는 원본/운영 상태를 짧게 다시 확인한다.
- [ ] 새 local-source-review CLI/profile/초기 guard/Main 오류 JSON·종료코드·one stdout를 기존 형태로 연결한다. 기존 guard/CLI 혼합 목록·System.exit·factory·Flyway 기대개수/cleanup caller를 모두 갱신한다.
- [ ] 실제 JAR 정상/정확재실행/거부/DBcold1044/1045/1049/연결·profile/web guard/SELECT preview/기존 공개·복구·출처 보존을 확인한다. 합성만 쓰며 기존 실제3건은 미검토 유지한다.
- [ ] backend/README/TASK·실행 규격/합성 예제·관련 D03/DB 설계/계약과 processing 안내의 기존제한을 실제 구현과 일치시킨다.
- [ ] 전체 native Java/실제MySQL/Python·Node/JSON/lint/build, 전체 자체 리뷰→fresh전체1회→유효 지적 모두 RED/GREEN/전체 회귀. 정확 source CI/AI/새사람리뷰→develop 병합·통합 검증, main은 사람.
- [ ] ledger 모든 판단/비용·검증/보고를 private evidence로 보존하고 이번 container/credential/workspace만 정리한다.

## Plan Self-Review

원본/운영 분리·권한/확인 독립·0state locking/CAS/replay·recorded cutoff·새운영행 source_checks 원자성·D05/Handoff·다사건캐시·preview SELECT/불변snapshot·오류/profile/전체caller를 각 task의 시험에 연결했다. 구체 SQL helper와 보관 구현은 기존 JDBC 패턴으로 정하며 새 판단은 비용과 함께 ledger에 남긴다.

