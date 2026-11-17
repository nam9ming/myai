# Citizen Human Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 사용자 지시로 파일 소유권을 나눠 agents로 구현하며, 독립 전체 리뷰는 마지막 정확히1회다.

**Goal:** 봉인한 시민 사람 수정본을 전체 출처와 함께 Java의 숨김 D06 revision으로 인계하고 별도 승인·공개·보고·복구 경로에 연결한다.

**Architecture:** 기존 review/handoff 보관·명시 revision/CAS·수정 감사·트랜잭션·공개 allowlist를 재사용한다. 새 selection/projection/import family를 명시하고 검증한 부모 metadata와 대조한다. 기존 형식·DB migration·원본 bytes를 바꾸지 않는다.

**Tech Stack:** Python3.13 표준 라이브러리, Java21·Spring Boot3.5.x·MySQL8.4, 기존 unittest·JUnit·Gradle·Node 도구.

**Spec:** `docs/spec/00_목차.md`, `docs/spec/01_제품요구사항.md`, `docs/spec/07_결정사항과자체점검.md`, `contracts/citizen-extraction.md`, `contracts/human-handoff.md`, `backend/docs/citizen-review.md`, `backend/docs/citizen-publication.md`. 기술 이름과 형식은 작성자 구현안이며 실제 팀원·Flutter 합의가 아니다.

## Global Constraints

- G4 PR56 source16a18f0의 CI44182663051·실제 자동 코멘트·사람 미해결0 확인 후 develop e4a3dea에 병합·tree 검증·본인 브랜치 정리를 완료했다. 전체 Java/Python goal을 이 계획으로 축소하지 않는다.
- Java21·Spring Boot3.5.x·MySQL8.4·Python3.13·현행 의존성 유지. V1~V6·과거 공개본·기존 추출/수정/실패 원본은 불변이다.
- 신청/진행·지역/장소/거주·비용 미상/무료·자격/관심과12개 원문 사실을 보존한다. 날짜·정규화·자격·관계·평가 분모를 추정하지 않는다.
- 실제 키/비공개 자료/독립 정답/D09를 읽거나 provider를 호출하지 않는다. 합성 시험·검토 선언은 실제 품질·신원·승인이 아니다.
- 공개 조회 중 AI/Python 호출0, 새 인증·계정·알림0. loopback/Bearer/Host/Origin·8MiB 관리 요청·고정 오류와 로그 경계를 유지한다.
- AGENTS.md·사용자 .gitignore·타인 브랜치·worktree scratch를 보존한다. Gradle은 주 작업자만 실행한다.
- 영어 Conventional Commits·명령형·50자 이내, 문서/PR 한국어. 유효 Minor까지 수정한다. 정확 head CI·실제 자동/도착한 사람 지적0 후 develop에 병합하며 main/배포는 수행하지 않는다.
- 미확정 자료원·실제 group·담당·정책은 `backend/docs/citizen-open-items.md`에 남기고 답변을 요구하지 않는다.

## Files and Interfaces

- Python `human_handoff._header/project_handoff`: 새 selection `citizen-human-handoff-v1`의6키=`schema_version handoff_id review_ref review_receipt_sha256 source split_group_id`. 기존8키/오류 순서/bytes 유지. 시민 projection=`citizen-human-handoff-projection-v1`, context=`{split_group_id}`.
- `draft._source_document(source)->dict`: D03 shape/문서 UUID 검사를 분리하고 기존 `_context`의 context 우선 검증은 유지한다. `_source(source,doc,document,metadata)`는 재사용한다.
- 신규 `evaluation/citizen_handoff.project_output(run_id,source,extracted,split_group_id)->dict`: `{data_kind,documents,evidence,events}` 반환. 기존 UUID5 방식·근거 연결을 사용하고12사실의 evidence ID만 치환한다. title/categories가 known·유효 값·근거를 충족하지 않으면 `HANDOFF_CITIZEN_FACTS_UNRESOLVED`다.
- wrapper `human-handoff-archive-v1`, summary-v1, HandoffReference3키, check/freeze/verify-handoff·동결/재생성 검증은 유지한다. summary는 projection_only/backend_import_supported=false/review_required=true다. split은 명시 D06 관계 group이며 D08 배정을 뜻하지 않는다.
- Java `HumanHandoffArchiveReader.read(HandoffReference)`/`read(String,String,Path)` 유지. 새 projection/context와 embedded review/output/parent metadata·receipt를 결합한다. 새 시민은 manual_import/archive-v1만 허용하며 Python은 executeKeyless로 실행한다.
- `HumanHandoffImportService.importFile(Path,Path,Path,String)`/`importBytes(byte[],Path,Path,String)` 유지. 새 request=`citizen-human-handoff-import-v1`, 동일5키·명시 revisions mapping·expected_revision_no. 전용 경로가 `citizen-reviewed-import-v1` envelope를 만들고 `ReviewedImportReader.prepareHandoff(JsonNode,Path,String,String)`가 새 batch schema를 반환한다.
- 새 시민 revision은 기존 marker citizen-revision-v1·ai_reviewed/needs_review/hidden·원 run/source/proof를 보존한다. 일반 import의 최초 AI proof 추가는 막고 기존 proof 뒤 감사된 수정은 허용한다. legacy의 기존 감사된 최초 proof 첨부는 유지한다.
- `ExtractionRunRepository.handoffParentDirectory/verifiedHandoffParent`만 검증한 시민 family를 허용한다. direct referenceDirectory의 기존 validated legacy 경계는 유지한다. `ExtractionImportService`의 사건별 proof·등록 D03/D05·fingerprint/잠금은 완화하지 않는다.
- 기존 local-import/POST reviews/import/PUT event review로 dispatch한다. S10 두 family·빈 인계·전체 실패/수정을 판독한다. 기존 시민 approve→preview/publish→export/rollback을 재사용하며 자동 승인은 없다.

## Review Focus

1. 새/기존 family 교차·parent/review/request 불일치·일반 JSON의 최초 시민 proof 위조는 저장 전에 거부한다(Task1/2).
2. 성공/실패 부모·미상·known[]·Unicode·12사실·제공 prompt 라벨·전체 수정은 손실 없이 보존되고 미상 제목/분야는 인계 실패다(Task1/2).
3. 봉인 원래 경로 유실·잘못된 권한/추가 파일·충돌/재실행·검증 중 변경에서 원본을 복구/덮어쓰지 않는다(Task1/2).
4. stale CAS·동시 인계·늦은 감사 실패·이전 proof/근거 삭제·실패 부모 다른 사건 도용은 원자 거부한다(Task2).
5. 실제 JAR/HTTP·SELECT S10·승인/공개/복구에서 미승인/권리 미확인 자료와 비공개 proof가 공개되지 않으며 과거본 bytes가 불변이다(Task2/3).

---

### Task 1: Python 시민 사실 투영·전체 인계 보관

**Files:** 수정 `processing/evaluation/human_handoff.py`, `processing/extraction/draft.py`; 신규 `processing/evaluation/citizen_handoff.py`, `processing/tests/test_citizen_handoff.py`, 필요 공개 합성 호환 fixture. Python worker 단독 소유, 타인 수정은 되돌리지 않는다.

**Interfaces:** 위 Python selection/projection/함수 서명을 생산한다. Task2는 같은 projection과 wrapper를 소비한다. 원본 review·source 전체는 기존 보관기가 복사한다.

- [x] **Step 1:** 현재 G4 고정 시민 review와 새6키 selection을 실제 check-handoff CLI로 전달하는 시험을 작성한다. 기대 exit0/projection_only인데 기존 header가 거부하는 행동 RED를 기록한다. 누락 모듈/컴파일 실패는 RED가 아니다.
- [x] **Step 2:** 명시 schema 분기·D03 helper 분리·최소 raw 사실 투영을 구현한다. metadata로 검증기를 선택하고 old 요청의 시민 거부와 D08 unsupported를 유지한다. unknown title/categories 거부·known[]/배열 순서·5분야·stable ID·실패 부모 상태를 검사한다.
- [x] **Step 3:** 실제 freeze/verify-handoff·빈 사건·전체 큰 실패 bytes·원래 review/run 경로 삭제 뒤 검증·old/new ID 충돌·잘못된 family/hash/권한/링크·부분 설치·CLI 비공개 로그 경계를 확인한다. 원래13pin/39파일 및 G4 고정76파일을 현재 코드로 읽고 bytes/mode 불변을 대조한다. expected는 재생성하지 않는다.
- [x] **Step 4:** Run `python3.13 -B -m unittest discover -s processing/tests -p 'test_citizen*.py' -v` 및 기존 handoff/review 시험. Expected: 새 성공/실패와 기존 고정 호환 모두 통과. 커밋 `feat: project citizen human handoffs`.

### Task 2: 검증한 인계의 Java D06·감사·S10 연결

**Files:** archive worker는 `handoff/HumanHandoffArchiveReader.java`, `repository/ExtractionRunRepository.java`, `service/ExtractionImportService.java` 및 대응 단위 시험만 소유한다. 주 작업자는 `importing/ReviewedImportReader.java`, `service/HumanHandoffImportService.java`, `ReviewedImportService.java`, `repository/ReviewedImportRepository.java`, `importing/LocalImportCommand.java`, `local/LocalManagementService.java`, `review/ReviewReportService.java`와 새 `CitizenHumanHandoffMySqlTest`/JAR 시험을 소유한다. 필요 없는 backup/공개 SQL·migration은 수정하지 않는다.

**Interfaces:** Task1 projection을 기존 archive DTO/public signatures로 반환한다. 새 import request/검증한 projection family를 일치시켜 trusted batch를 만들고 동일 source_kind=human_handoff/result_refs로 저장한다. `HumanReviewChanges.record/validate(...,CITIZEN_FIELDS)`를 재사용한다.

- [x] **Step 1:** Task1의 실제 frozen archive를 Java 기존 public reader/import에 전달하는 시험을 작성한다. 새 schema gate의 실제 거부 RED를 주 작업자의 Gradle로 관찰한 뒤 생산 코드를 수정한다.
- [x] **Step 2:** archive 검증/키 없는 subprocess·schema별 trusted 생성·ordinary 최초 proof 방지·명시 mapping/CAS·원래 proof/audit prefix·사건별 D05 검증을 최소 확장한다. 기존 read/import signatures·legacy 최초 첨부 회귀를 유지한다.
- [x] **Step 3:** 전용 DB에서 D03/D05 성공·실패→숨김 D06, 정확 replay·빈 batch·stale/동시 CAS·늦은 감사 rollback·사건/근거/출처/권한 변조·수동 후속 수정의 실제 전후 값을 검증한다. 쓰기 전 시험 소유 UUID 기록·허용 DB 확인, 소유 행만 정리한다.
- [ ] **Step 4:** 실제 JAR CLI/HTTP POST/PUT와 원입력 보관·URL event 불일치·인증/한도·SELECT S10 전체 수정/실패·별도 승인/공개/export/rollback과 private 비노출을 확인한다. 운영·독립 품질 인수로 표현하지 않는다.
- [ ] **Step 5:** Run 주 작업자만 `./gradlew test --tests '*HumanHandoff*' --tests '*ReviewedImport*' --tests '*Citizen*' --tests '*ReviewReport*' bootJar`. Expected: 가능한 local 검증 통과; Docker 부재는 정확 원격 MySQL8.4 전체 CI로 반드시 보완한다. 커밋 `feat: import citizen human handoffs`.

### Task 3: 계약·전체 검증·리뷰·develop 반영

**Files:** 신규 `contracts/citizen-human-handoff.md`; 관련 contracts/README.md·human-handoff.md·human-review.md·citizen-extraction.md, 저장소·backend/processing README/TASK 및 handoff/review/S10/local docs·citizen-open-items.md, G4/G5 계획의 실제 결과만 갱신한다.

**Interfaces:** Task1/2의 실제 버전·명령·제약·합성 재현·검증 결과를 인계한다. 미확정 실제 정책·팀원/Flutter 합의는 open-items다.

- [x] **Step 1:** 새/기존 family·선행 원문/추출 등록·명시 group/revisions·미상 거부·실패/전후 감사·별도 승인·오류·실행/복구를 문서화한다. G4 PR56의 완료 증빙과 G5 미완료를 구별한다.
- [ ] **Step 2:** Run 전체 Python, 주 작업자 `./gradlew test bootJar`, npm lint/test/build·계약 validator·변경 Markdown 상대 링크·git diff --check. Expected: 회귀/원본 불변·누락0, Docker/JAR/MySQL8.4는 exact remote head에서도 통과한다.
- [x] **Step 3:** 전체 diff·호출자·권한·원본/복구·계약·문서를 자체 검토하고 유효 지적을 RED→GREEN으로 수정한다. fresh 독립 전체 리뷰 정확1회를 수행하고 Minor 포함 유효 지적을 모두 검증·수정한 뒤 전체 자체 검토한다. 커밋 `docs: describe citizen human handoffs`.
- [ ] **Step 4:** 유효 미해결0에서 develop PR을 제출한다. exact head CI·실제 AI 코멘트·도착한 사람 리뷰/threads를 확인하고 지적은 원인 수정·검증한다. 부분 자동 리뷰를 전체로 쓰지 않는다.
- [ ] **Step 5:** green/head 지적0인 non-main PR만 expected head로 병합한다. source/실제 CI 후보/병합/develop tree를 비교·사용자 변경 보존 FF·본인 병합 브랜치 정리·main PR20 증빙 갱신 후 전체 goal의 다음 단계로 진행한다. main은 병합하지 않는다.

## 계획 자체 검토

G4와 G1~G3 기존 계약을 대조했다. Python projection→archive reader→trusted import→기존 승인/공개·S10의 selector를 모두 범위에 포함했다. backup은 전체 DB/파일 이미지와 generic schema 저장을 재사용하며 새 migration이 없다. 실제 자료/평가·프런트·운영 승인과 분리하고5개 Review Focus를 Task1/2 검증에 연결했다. 실행 중 다른 접점이 확인되면 ledger에 근거와 영향 범위를 기록한다.


## 현재 검증·리뷰 기록

- 실제 Python check-handoff의 새 선택 header 거부·Java 새 projection/schema 거부·등록 D03/D05 성공/실패의 새 요청 거부를 관찰한 뒤 확장했다. 테스트용 ref 키 오타로 발생한 사전조건 오류는 행동 RED에서 제외하고 올바른 봉인본으로 다시 확인했다.
- 후속 일반 시민 수정의 inherited proof가 잘못 legacy로 분류되는 문제를14필드 감사 시험으로 확인·수정했다. 기존 CHECK 주입 시험의 오류 코드 가정도 실제 예외 변환과 대조해 수정했고 전체 행 rollback·정상 재시도 검사는 유지했다. 새 예외 정책은 추가하지 않았다.
- 독립 검토 전 첫 검증은 Python 전체690건/326.242초, 관련 Java138건/6클래스·1분42초·실패/오류/생략0이었다. Java는 로컬 MySQL9.6 보충 검증이며 정확8.4 성공으로 쓰지 않는다. 기존 legacy 최초 proof 첨부·인계 전체 회귀를 포함한다.
- 첫 Node46건·lint610파일·계약13JSON·HTML build·변경18문서377개 상대 파일 링크가 통과했다. 독립 검토 지적을 수정한 최종 결과는 아래에 별도로 기록한다.
- 독립 전체 리뷰는 `e4a3dea..3409ac6` 4커밋·117파일에 정확히1회 수행했다. Critical1·Important6·Minor3을 모두 유효 지적으로 채택해 아래와 같이 수정했다. 독립 재리뷰는 추가하지 않으며 수정 후 전체 자체 검토·회귀와 정확 원격 CI를 통과해야 PR/병합 단계를 마친다. main/배포·실제 사람/Flutter·실자료 품질 인수는 별도다.

## 독립 전체 리뷰 지적·조치

| 번호·심각도 | 원인·수정 | 재현·검증 |
| --- | --- | --- |
| 1 Critical | 문서 전체 근거가 모든 시민 사건에 복사됐다. 항목별14개 FieldValue 참조만 링크/D06/새 공개본에 전달하고 전체 비공개 원본은 유지한다. 후속 인계의 근거 비교도 같은 범위다 | Python5항목·Java reader/과거 저장본 공개의 RED, 실제5사건 중1건만 승인한 snapshot·상세·export와 전체 비공개 원본 보존 GREEN |
| 2 Important | 시민 proof 없는 legacy 실행이 추가 출처로 허용됐다. 시민 run마다 같은 사건의 시민 proof를 요구한다 | 기존 허용 ROOT2사례, 동일 D03에 실제 등록한 validated legacy 실행의 감사된 추가 거부·DB/원본 불변 GREEN |
| 3 Important | 사건 없는 일반 시민 JSON이 최초 proof 저장 검사를 우회했다. 빈 시민 인계는 내부 전용 준비 경로만 허용한다 | reader·실제 빈/비어 있지 않은 투영의 일반 요청 RED→거부 GREEN, 전용 빈 인계 유지 |
| 4 Important | 등록 D05 재검증이 freeze를 실행해 잘못 복원한 권한에서 새 사본을 만들었다. 등록 후 참조는 readSealed만 사용한다 | ROOT2사례, 재실행/새 인계/승인/preview/publish5경로의0700/0600 거부·부모 전체 트리/DB 불변·정상 복원 후 같은 작업 성공 GREEN |
| 5 Important | 과거 proof와 값이 같으면 사람의 되돌리기 수정도 덮을 수 있었다. 현재 revision이 실제 전용 인계 배치에서 생성됐는지 대조한다 | 인계 A→B→수동 A→전용 C의 ROOT 허용→충돌·전체 DB 불변 GREEN |
| 6 Important | 큰 실패 원본 검사 중 교체한 루트 receipt/identity를 마지막에 재검사하지 않았다. 반환 직전 원본 bytes와 파일 식별자를 재대조한다 | 실제 파일 스트림 종료 시 bytes/동일 bytes의 inode를 교체하는 결정적 ROOT4사례→거부·자동 복구 없음 GREEN |
| 7 Important | S10 자식 proof가 invalid여도 revision의 인계 판정은 valid였다. 자식 실패를 상위 상태에 반영한다 | 실제 봉인본 변조 ROOT→자식/상위 invalid·보고서의 DB/파일 무변경 GREEN |
| 8 Minor | autocrlf 변환과 의도한 CRLF가 고정 원본을 훼손했다. G4 original/manifest/verification만 Git 속성으로 고정한다 | 실제 변환 hash 불일치·범위 diff9오류 RED→78파일 원본 bytes 유지·전체 범위 diff 검사 GREEN. expected 재생성0 |
| 9 Minor | Gradle이 고정 G4 자료·시민 예제를 test inputs에 포함하지 않았다. fixture tree와2개 시민 예제를 등록한다 | 실제 Gradle task 입력5경로 누락 RED→실제 등록 GREEN. 시험 비활성화/생략 없음 |
| 10 Minor | review_ref와 receipt hash의 계산 설명을 혼용했다. review_id UTF-8 hash와 receipt 원본 bytes hash를 구별한다 | 실제 reviews.py의 계산과 문서 대조·수정. 동작 변경 없음 |

수정 후 집중 Java223건/8클래스·2분15초·실패/오류/생략0, 전체 Python693건/333.292초가 통과했다. 전체 로컬 Java는1122건 중1111통과·11실패·오류/생략0·6분49초다. 실패11건은 모두 RecoveryDatabase의 Docker 기동 실패이며 새 시민 JAR/HTTP/SELECT S10과 기존 마이그레이션/복구의 해당 내부 시험은 로컬에서 실행하지 못했다. 별도 bootJar는852ms로 성공했다. 로컬 MySQL9.6 보충 검증을8.4·전체 성공으로 표시하지 않는다.

Node46건·lint611파일·계약13JSON·HTML build와 변경 Markdown19개 상대 파일 링크396개, 전체 범위 diff 검사가 통과했다. 고정 G4/legacy 원본을 유지했고 expected 재생성·시험 삭제/생략은 없다. 수정 전체의 호출자·저장/공개·원본/복구·예외·계약·문서를 다시 자체 검토했으며 유효 미해결 지적은0이다. 정확 source의 원격 MySQL8.4/Docker 전체 CI·실제 자동/도착한 사람 리뷰 확인·PR/병합은 다음 gate다.
