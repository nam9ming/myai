# Matching Evaluation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 독립 수동 기대 분류·사유와 같은 조건의 금표/규칙/AI/사람 관측을 비교·동결해 매칭 오류와 추출 영향을 구별한다.
**Architecture:** 기존 frozen extraction-comparison 전체를 재사용한다. 별도 private projection은 공통 validator와 C01~C10을 호출하고, 고정 E/A·전체 관측으로 검색 존재와 완전 분류를 분리한다. 새 matching storage/CLI는 기존 원본 복사·재계산 보관 패턴을 따른다.
**Tech Stack:** Python3.13 표준 라이브러리, 기존 JUnit/Java21/MySQL8.4.13 bridge 회귀, 새 의존성 없음.
**Spec:** docs/superpowers/specs/2026-11-04-matching-evaluation-design.md

## Global Constraints

- 원본 calc-v1·추출/gold/evaluation/comparison v1·D03/D05/인계·Java 공개 의미 보존. 기존 사용자 .gitignore/AGENTS/다른 작업 보존.
- 키·AI/네트워크/DB 호출·실자료/사람/gold 생성·새 의존성·공개 endpoint·main 병합/배포 없음. develop 기능 PR만 기존 위임대로 병합.
- 입력/결과8MiB·깊이100, raw artifact 전체 보존, unknown/failure/missing/duplicate/additional/availability와 분모 유지.
- 수동 기대값은 gold engine에서 생성하지 않음. 자기 known 장소만 공통 검토 사전 연결, gold 좌표/유형/시간 주입 금지.
- 비교 cohort·gold·source/부모·원래 phase/노출/정책·검토 시간 선언과 원본 전체 보존. 최신 버전/사실 자동 병합 없음.
- 커밋 제목/본문 영어 Conventional Commits(제목50자 이내), 문서/PR/주석 한국어. 부모만 stage/commit.

## Review Focus

1. 같은 logicalevent의 다문서·cancelled/candidate·실패+candidate 및 상충 duplicate가 검색 TP와 완전 판정 성공으로 혼동되는가 — Task2 고정 E/A·consensus/partial/conflict 시험.
2. 미상 types·빈 출력·failed raw·orphan을 필터로 지워 분모/FP/FN이 좋아지는가 — Task1+2 유형필터·전체 annotation/출력·누락/실패/추가 시험.
3. 이름/주소/known kind 충돌·같은 별칭·Decimal 미세 범위 초과에서 gold 좌표가 새거나 거짓 geometry가 확정되는가 — Task1 좌표/자기값/별칭/원본 hash 시험.
4. private source 허용이 공개 출판 gate를 풀거나 replay 과거에 미래 출처/check를 섞는가 — Task1 공개 불변/unchecked/late-collected/future-check/24h+1ns 시험.
5. changed case/gold·retst/초기·원본 교체/복사 실패가 같은 비교·같은 ID로 통과하거나 원본을 덮는가 — Task2+3 회차/hash/전체 보관/오프라인/원자성/크기 시험.

### Task 1: 검증된 private 문맥·사실 투영

**Owner:** projection worker. Files: processing/evaluation/matching_projection.py(신규), processing/matching/protocol.py(공통 검증 추출만), processing/tests/test_matching_projection.py(신규).

**Interfaces:**
- protocol.validate_scenario(context,point,query,snapshot_id=None)->(now:int ns,cutoff:int ns|None); protocol._source(source,context,now,cutoff,*,evaluation=False)->collected:int ns. 공개 호출 default는 기존 그대로.
- matching_projection.validate_dictionary(value,evaluated_at)->검증/계산용 사전 dict.
- matching_projection.prepare_case(case,cohort,dictionary,*,data_kind,evaluated_at)->계산용 case dict. cohort는 version->{document_id,official_url,split,split_group_id,input:parsed AIinput,input_sha256,anchors:{slot:event_id},gold_output}.
- prepared case의 공용 조회 키는 case_id/context/point/query/source_versions(버전별 dict)/source_availability(버전별 bool)/area_memberships(사전 entry_id별 status)다. 그 외 runtime helper 값은 Task1 내부다. cutoff 미확보 버전은 primary state도 unavailable로 남기되 document_failed/빈 출력 사실은 별도로 보존한다.
- matching_projection.classify_output(output:validated extract dict|None,annotation:score-links dict,document:cohort entry,case:prepared dict,dictionary:validated dict,*,projection_id:UUID)->dict local_item_id→{state,classification,reason_codes,disposition,projection_limitations}. None은 실패이며 None 반환. 빈 유효 출력은 {}. 문서 version은 document.input.document_version_id.
- 반환 state는 classified/not_computable/unavailable. classified.classification은4값, 나머지는null; reason_codes는 sorted list 또는null. disposition engine/type_filter/area_filter/type_unknown/not_available_at_cutoff. projection_limitations에는 해석하지 않은 known recurrence 등 정규화 제한만(공개 C코드와 분리).
- 실제 item 결과에는 projection_body_sha256와 source_text_sha256(선언값)을 별도로 남긴다. 원본 D03 hash를 재구성한 것으로 표시하지 않는다.
- matching_projection.CLASSES=(candidate,needs_check,cancelled,excluded), REASONS=명세04의13개 코드, STATES는 위 state 목록.

- [ ] **RED:** 새 모듈·private source 경로 부재, 공개 unchecked/late source 거부 불변, 4분류/미상 제목·유형·시간/빈refs·실패/빈출력, 이름/주소/kind 충돌·별칭 중복·골드 위치 누출, Decimal bounds/bool/형, source 해시/순서/future/cutoff/24h+1ns·replay 불변 시험. Run `python3.13 -B -m unittest discover -s processing/tests -p test_matching_projection.py -v`; Expected missing API/의도한 차이 실패를 관찰.
- [ ] **GREEN:** 기존 validate 블록·source default 의미를 보존하고 private literal 옵션만 추가한다. 각 방법 자신의 값으로 사전 연결·기존 projector/business_hours/locate/_classify를 사용한다. 내부 projection hash를 실제 D03 hash로 표시하지 않는다.
- [ ] **Author design-fix RED/GREEN:** 같은 raw item을 match/duplicate/additional 또는 다른 gold slot으로 대응해도7개 계산 결과는 같아야 한다. 사전 entry_id의 구역 상태만 사용하고 occurrence 참조 장소만 집계해 orphan 후보 FP가 정답 대응 유무로 차단되지 않음을 확인한다.
- [ ] **Verify:** 새 projection + 기존 protocol/engine/intervals/geometry/draft/handoff 관련 시험. Expected 실패/생략0, 원래 공개 입력 허용/거부 그대로, 원본 bytes/dict 불변.
- [ ] **Commit:** 부모가 `feat: project matching evaluation facts` 영어 제목/본문으로 소유 파일만 커밋.

### Task 2: 원본 연결·고정 분모·6view 평가

**Owner:** evaluation worker. Files: processing/evaluation/matching.py(신규), processing/tests/test_matching_evaluation.py(신규 fixture 포함). Task1 파일 수정 금지.

**Interfaces:** matching.py MATCHING_ROOT='data/private/evaluation/matching', COMPARISON_ROOT 기존 상수, MATCHER_VERSION='matching-evaluation-v1'. `_header(content)->dict`는 spec의10키/기초 shape·phase/initial을 검사한다. `evaluate_matching(content,comparison_root=COMPARISON_ROOT,initial_root=MATCHING_ROOT,*,evaluated_at=None)->{result,sources}`. sources는 기존 `_collect` 형태 name→(Path,{sha256,size}). retest initial은 matching_storage._verify_directory(...,initial_only=True)를 함수 내부 import해 검증하며 result/receipt/전체 sources를 읽는다.

공유 tests API: `MatchingEvaluationFixture(PairedComparisonFixture)`는 비교 원본을 실제 freeze하고 self.comparison_root/self.matching_root/self.matching_selection을 제공한다. 기존 self.selection/self.control은 덮어쓰지 않는다. `write_matching(selection=None)->Path`, `matching(selection=None,*,at=MATCHING_AT,root=None)->packet`을 제공한다. MATCHING_AT은 고정 case.server_now 이후의 UTC 시각이며 기대분류/코드는 fixture에서 독립 리터럴로 지정한다. 부모 storage 시험이 이 fixture를 사용한다.

result 정확한 최상위 키: `schema_version matching_eval_id matching_ref matcher_version selection_sha256 evaluated_at phase case_version comparison gold_ref gold_sha256 manifest_sha256 initial_comparison cases summary`.
case 결과: `case_id observations event_results target_agreement extraction_effects summary`. observations/view에는 모든 A primary 행+모든 duplicate/additional, event_results/view에는 모든 E를 보존한다. view 이름은 gold_engine/rules_first_raw/rules_final_auto/ai_first_raw/ai_final_auto/human_reviewed. primary 행 kind=match|missing|failed, extra kind=duplicate|additional, sourceversion/slot/localitem/event/split·state/class/reasons/disposition를 남긴다.
summary는 data_kind/phase/source_phase/case_version/matcher_version/case_count/코호트 수·부족·분포·holdout 경고/방법별 노출·정책·initial 경고/선언 시간/generalization_claim=false와 views·splits를 포함한다. 상세 ID/사유/담당자/경로는 summary 밖 private cases에만 둔다. 비율은 정수 분모에서 다시 계산하고 Decimal 사실값을 근사 변환하지 않는다.

- [ ] **RED:** PairedComparisonFixture로 실제 frozen comparison+독립 manual target fixture를 만들고 새 evaluate API 부재를 관찰한다. `python3.13 -B -m unittest discover -s processing/tests -p test_matching_evaluation.py -v` Expected missing module/API.
- [ ] **Implement:** verify_comparison/checked reads와 기존 records._load_sources를 재사용해 full gold/input/run/annotation을 로드한다. field_results로 예측을 복원하지 않는다. 모든 cohort/E/A와6view를 평가하고 실패·빈 출력·불가·cutoff·중복/추가를 그대로 둔다. 타입/구역 private filter는 새 C코드 없이 구별한다.
- [ ] **Metrics RED/GREEN:** unique candidate 존재 TP/FP/FN/P/R0null, E 전체분모 완전판정/사유·4분류 confusion+미해결열, needs_check 오확정/누락·취소 누락/후보오노출, A targetagreement, method-vs-gold 비교불가/추가/누락, duplicate상충·누락 primary+candidate duplicate·candidate+실패·old/new문서상충·orphan 후보·빈gold·개발/확인 분할을 시험한다. 원문/선언/금표를 계산으로 덮지 않는다.
- [ ] **Round/size RED/GREEN:** 비교/receipt/정확 부모/코호트·시간 불일치, retest 최초전체·같은case_version 다른내용 충돌·changedcase의paired차이금지·상태노출경고 유지·행생성중8MiB초과거부를 검증한다. Expected 전체 관련 GREEN, goldengine를 정답으로 사용한 코드 없음.
- [ ] **Commit:** 부모가 `feat: evaluate matching classifications` 영어 제목/본문으로 커밋.

### Task 3: 불변 보관·CLI·문서·전체 gate

**Owner:** coordinator. Files: processing/evaluation/matching_storage.py, processing/evaluation/__main__.py, processing/tests/test_matching_evaluation_storage.py, contracts/matching-evaluation.md, processing/README.md/TASK.md, contracts/README.md, docs/spec/03_데이터와AI.md/05_시험과인수기준.md 및 필요한 합성 예제만.

**Interfaces:** `_verify_directory(directory,reference,*,initial_only=False)->receipt`; verify_matching(matching_ref,root=MATCHING_ROOT); freeze_matching(input_path,root=MATCHING_ROOT,comparison_root=COMPARISON_ROOT,initial_root=MATCHING_ROOT). archive format matching-evaluation-archive-v1, identity 키 `format_version matching_ref artifacts recorded_at`. receipt 키는 format_version/status/matching_ref/frozen_at/artifacts/summary. result 재계산은 저장된 evaluated_at, retest 최초는 directory/initial, source comparison은 directory/comparisons에서 수행한다.

- [ ] **RED:** 실제 comparison/expectation fixture로 freeze/verify/CLI API 부재를 관찰한다. Expected missing module/command.
- [ ] **GREEN:** 기존 comparison_storage와 같은 checked copy·원본 bytes·identity/receipt·0400/0500·staging 전체 verify·exclusive rename·동일입력 재사용·충돌 보존·자기임시폴더 정리. retest 초기 이미지 전체를 보관한다.
- [ ] **Boundary RED/GREEN:** 원래 root 제거 후 verify/reuse, concurrent same/different input, raw큰실패원본/원자복사중변경, hash재작성거짓result, symlink/추가/누락/권한확대, partial destination, CLI0/2/3/5/1·한JSON/비노출·입출력8MiB 경계를 시험한다.
- [ ] 한국어 계약/README/TASK·D08·인수 설명을 실제 구현에 맞춘다. 실제 사람/gold/40문서/배포를 미완료로 유지한다. 기존 공개 계약 변경 없음.
- [ ] Native 전체 Python·Node/JSON/lint/build·Java/MySQL bridge와 실제 eval CLI→freeze→원본경로제거→verify·retest·거부 매트릭스를 실행한다. 실제 데이터/키 없이 합성만 사용한다.
- [ ] 전체 자체 리뷰·fresh전체1회, 유효 지적 모두 수정/재검증. source head CI·자동/새사람피드백0→develop 병합·통합 gate. main은 사람.
- [ ] 모든 Ruling/비용·최종보고·proof/checksum을 private evidence로 보존한 뒤 이번 소유 workspace/container/credential만 정리한다. 기존 archive/실자료/다른 작업은 보존한다.

## Plan Self-Review

독립 target·기존 원본/공개 엄격성·미상/필터/시간·사전좌표 누출·fixedE/A/6view·다문서/중복·initial/retest·전체 보관/오프라인·오류/CLI·회귀/원격을 각 Task 시험에 연결했다. Case/helper/packet/storage 인터페이스와 실제 파일 소유권을 위에 고정한다. 새 판단은 ledger Ruling과 비용으로 기록하며 실제 성과를 추정하지 않는다.
