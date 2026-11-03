# D08 매칭 분류·사유 평가 설계

## 목표·경계

명세03 D08/05 B의 수동 기대 candidate/needs_check/cancelled/excluded·사유와 동일 조건의 금표/규칙/AI/사람 수정후 계산을 비교한다. 기대값은 엔진 출력에서 만들지 않는다. 기존 동결 extraction-comparison을 정확한 receipt로 선택해 같은 gold/cohort·회차·사람의 정확한 AI 부모 검증과 전체 원본을 재사용한다.

Python3.13 표준 라이브러리·기존 C01~C10이 단일 계산 원본이다. calc-v1·추출/gold/evaluation/comparison v1·D03/D05/인계·Java 공개 동작은 보존한다. 새 의존성·AI/키/네트워크/DB·공개 endpoint·실자료/사람/gold 생성·main 병합/배포는 범위 밖이다. 기존 사용자 .gitignore 두 줄과 AGENTS를 수정/커밋하지 않는다. 커밋 제목/본문은 영어 Conventional Commits(제목50자 이내), 문서/PR/주석은 한국어다.

## 선택 입력

`matching-evaluation-v1`의 정확한 키는 `schema_version matching_eval_id phase case_version comparison expectations_review context_review dictionary cases initial`이다.

- matching_eval_id UUID, phase initial/retest, case_version 공백 아닌100자 이하 식별자.
- comparison: `{comparison_ref,receipt_sha256}`. 두 값은 SHA-256이며 ref는 기존 comparison_id의 hash다. 원본 전체를 verify_comparison으로 재검증한다.
- expectations_review: `{author,reviewer,authored_at,reviewed_at,basis,cross_reviewed,no_unresolved_disagreements}`. 서로 다른 정규화 담당자, authored<=reviewed<=evaluated, 마지막 두 값 true. basis는 source_only/model_outputs_seen/engine_outputs_seen/unknown. 선언·사후 작성/노출 경고를 보존하며 신원·독립성 인증으로 간주하지 않는다.
- context_review: `{reviewer,reviewed_at,note}`. 고정 지점·구역·사전·원문 확인 조건의 검토 선언이며 시각은 evaluated_at 이하다.
- dictionary: `{dictionary_version,entries}`. entry는 정확히 `entry_id name name_aliases address address_aliases kind geometry coverage source checked_by checked_at`. UUID, nullable name/address(둘 중 하나 필수), 각각 중복 없는 문자열 별칭, kind point/segment/stops/area/unknown, nullable GeoJSON, coverage complete/partial/unknown, 출처/담당자/검토 시각을 받는다. geometry는 기존 좌표/구간 제약을 따른다. 같은 별칭의 여러 후보는 허용하되 자동 선택하지 않는다.
- cases는 고유 case_id UUID의 배열, 각 정확한 키는 `case_id context point query source_versions area_memberships expected`다. 최소1개 case이며 expected가 비는 것은 gold 사건0개일 때만 가능하다.
- context/point/query는 calc-v1의 해당 객체를 그대로 사용한다. private query.snapshot_id는 null이어야 하며 공개 snapshot을 만들었다고 간주하지 않는다. context.dictionary_version은 공통 dictionary와 일치하고 data_kind는 gold와 같다. current context.case_id=null, replay context.case_id=해당 case_id. 14일/500m/rules-v1/KST·시각/영업/참조 검증을 유지하고 server_now는 evaluated_at 이하여야 한다.
- source_versions는 calc-v1의 원문 상태17필드를 사용하며 모든 cohort 버전을 정확히 한 번 포함한다. document ID/URL은 manifest, title/published_date는 고정 AI 입력과 일치한다. D03 body hash는 이 입력만으로 복원할 수 없으므로 source.text_sha256/checks는 **고정 case의 선언**으로 검사한다. 이를 실제 D03 본문 대조·URL 재접속으로 표시하지 않는다.
- area_memberships는 `{event_id,status}` 배열이며 모든 gold logicalevent를 정확히 덮는다. status verified/uncertain/outside. matched/duplicate에 같은 논리 사건의 선언을 적용하고 추가 orphan은 uncertain이다. outside는 별도 area_filter disposition의 excluded/[]이며 새 C코드를 만들지 않는다.
- expected는 `{event_id,classification,reason_codes,note}` 배열이며 모든 gold logicalevent를 정확히 한 번 포함한다. reason_codes는 명세04의13개 코드 중 중복 없는 집합, note는 공백 아닌 수동 판단 설명이다. source를 가진 gold 슬롯이 없는 manifest 사건을 추측해 새 정답을 만들지 않는다.
- initial은 initial일 때 null, retest일 때 `{matching_ref,receipt_sha256}`다. 명시한 동결 initial만 읽고 현재 ID와 같거나 retest 체인을 initial로 쓰면 거부한다.

## 공통 검증과 private 사실 투영

protocol의 context/point/query 검증을 `validate_scenario(context,point,query,snapshot_id=None)->(now,cutoff)`로 추출한다. 공개 validate는 실제 snapshot_id를 전달해 기존 의미를 유지한다. `_source(...,*,evaluation=False)->collected`의 default도 그대로다. private의 literal evaluation=True만 성공 확인 필수라는 출판 gate를 완화하고 collected의 상한을 now로 검사한다. checks의 순서·hash·cutoff, 파생 last/latest/result, current_*와 현재시각/현재모드 일치는 모두 유지한다. 이 옵션은 JSON에서 받지 않는다.

private에서 collected>cutoff이면 unavailable_at_cutoff 행을 보존하고 _classify를 호출하지 않는다. 실패·누락·유형 미상도 excluded로 바꾸지 않는다. source가 unchecked이면 실제 null/빈 checks를 그대로 두고 엔진의 SOURCE_STALE 등을 사용한다. 모드를 reconstructed로 바꿔 검증을 우회하지 않는다.

`draft._project_output`의 기존 시간/장소 대응·미상 처리를 재사용하고 필요한 사실만 꺼낸다. namespace는 명시적으로 계산한 projection UUID이며 실제 run ID가 아니다. 내부 carrier는 manifest document_id·실제 input의 version·평가 블록 `SHA256('\n'.join(block.text))`만 사용한다. 이 hash는 projection_body_sha256이며 원본 D03 text_sha256와 구별한다. ai-draft envelope·workflow·가짜 실행을 외부로 출력/등록하지 않는다. 원래 입력 bytes SHA·FieldValue·근거 hash는 별도 보존한다.

각 방법 자신의 known name/address를 NFC·공백 정규화·casefold 후 공통 사전의 해당 이름/주소 필드와 대조한다. 알려진 두 필드가 충돌하거나 후보가 여러 개, known kind가 불일치하면 geometry 미상이다. 유일하게 연결한 검토 geometry/coverage/kind는 계산용 파생값이고 원출력의 미상 kind 등을 덮어쓰지 않는다. gold slot/event ID나 gold 위치로 AI 좌표를 보완하지 않는다. Decimal 좌표는 원래 수의 finite/범위를 먼저 검사한 뒤 계산 경계에서만 float로 변환하며 원본 bytes는 유지한다.

선택 유형이 있고 raw types 미상이면 not_computable/type_unknown을 남긴다. known 유형 불일치는 excluded/[]와 type_filter disposition이다. 유형 필터가 없으면 유형/제목 미상 자체는 핵심 분류의 blocker가 아니다. `business_hours`·`locate`·`engine._classify`를 재사용하며 None 분류만 excluded로 매핑한다. 공개 selection/sort로 평가 행을 숨기지 않는다. 재현 current_*·reconstructed 경고도 별도 보존한다. 알려진 반복 문구의 날짜 변환 등 기존 projector가 미상으로 남긴 정규화 제한은 표시한다. expected↔gold-engine 불일치는 엔진뿐 아니라 투영/문맥/수동 판단을 조사할 신호이며 확정 엔진 버그로 표시하지 않는다.

## 관측·분모·지표

E=모든 gold 고유 logicalevent, A=모든(document_version_id,slot_id), 예측 관측=(version,local_item_id)다. 모든 case·gold/규칙 first_raw/final_auto·AI first_raw/final_auto·human_reviewed의6개 view를 계산한다. 비교의 item_links 전체와 실제 출력을 사용하며 field_results만으로 복원하지 않는다. 각 A에 정규 match 또는 missing/failed/not_computable/unavailable 행을 반드시 남긴다. duplicate/additional도 별도 원형 보존하며 missing 정규 match를 duplicate로 대체하지 않는다. 모든 문서/버전·실패·빈 출력과 원본을 유지하고 임의 최신 선택·사실 병합·자동 중복 제거를 하지 않는다.

event 분류는 모든 필수 anchor의 정규 match 및 연결 duplicate가 계산 가능하고 분류가 전부 같을 때만 확정한다. 이유도 모든 집합이 같을 때만 확정하고 union하지 않는다. 알려진 linked 분류가 여러 개면 conflict가 우선이다. 그 외 정규 match 계산0이면 primary 상태가 동일할 때 missing/failed/not_computable/unavailable을 유지하고, primary 상태가 서로 다르면 partial이다. 정규 match가 일부라도 계산됐으나 전부 완성되지 않으면 partial이다. 정규 match가 없는 candidate duplicate는 검색 TP가 될 수 있어도 event state는 missing이다. 이유 불일치는 분류 확정을 지우지 않되 reason_codes=null로 남긴다. 새 상태는 classification/C코드가 아닌 별도 state다.

이번 계약은 전체 cohort의 모든 버전을 관측 대상으로 고정한다. 입력에서 임의 버전을 비활성으로 골라 어려운 관측을 제거하는 옵션은 두지 않는다. 과거 취소/새 후보가 함께 있으면 conflict를 보존하며 현재 revision/관계 해석을 대신하지 않는다. 별도 검토된 provenance 범위 선택이 필요하면 다음 계약에서 명시적으로 추가한다.

- candidate 검색 집합 P는 candidate인 match/duplicate의 logicalevent를 한 번, candidate additional은 (version,local_item_id)별 orphan key로 포함한다. 기대 candidate 집합 C와 TP/FP/FN·precision/recall을 계산한다. 분모0은 null. 중복 출력 수·candidate 중복 수는 별도로 남긴다.
- 이 지표는 retrieval_presence다. candidate+실패는 TP일 수 있지만 event 판정은 partial, candidate+cancelled는 conflict다. candidate 정답이 모든 사건 판정 정답을 의미하지 않는다.
- complete_classification 정확도와 classification+reason 정확도는 E 전체가 분모다. 미계산/누락/실패/상충도 분모에 남는다. 4분류 confusion에는 별도 미해결 상태 열을 두며 계산 가능한 것만 분모로 삼지 않는다.
- expected needs_check의 정확 판정·candidate 오확정·누락, expected cancelled의 누락·candidate 오노출을 건수로 보고한다. 후보가0개면 precision null, 기대 후보0이면 recall null이다. 새 백분율 목표·F1은 추가하지 않는다.
- A 단위는 target_agreement로 명명해 역사 원문 정확도와 구별한다. duplicate는 비교·상충에는 포함하지만 A/E 분모를 늘리지 않는다. additional은 orphan FP/출력 상태로 남긴다.
- expected↔gold engine(투영/엔진 조사), expected↔각 방법(end-to-end), gold engine↔각 방법(추출 영향)을 분리한다. 양쪽 failure/null을 일치 정답으로 처리하지 않는다. gold consensus 불가도 별도 표시한다.
- 전체·case·dev/holdout을 같은 고정 집합으로 집계한다. 원래 cohort 부족/노출/retest/방법별 basis·정책·시간 선언과 generalization_claim=false를 보존한다. stdout summary에는 상세 사건ID/기대 설명/검토자/원래 경로를 넣지 않는다.

## 회차·보관·CLI

matching phase와 source comparison phase는 별도로 보존한다. retest 추출을 사용한 첫 matching은 원래 source phase와 경고를 유지하고 최초 모델 성능으로 표시하지 않는다. matching retest는 초기 이미지 전체를 선택·동결한다. manifest cohort가 다르면 거부하고 같은 gold_ref의 다른 gold SHA도 거부한다. case_version이 같은데 dictionary/cases 내용이 달라지면 충돌이다. 바뀐 case/context/기대/gold/source와 이전/새 수치를 보존하며 case/context/target이 같은 case만 paired delta를 낸다. 다른 조건을 같은 비교로 둔갑시키지 않는다.

`evaluate_matching(content,comparison_root=COMPARISON_ROOT,initial_root=MATCHING_ROOT,*,evaluated_at=None)`은 `{result,sources}` packet을 반환한다. `matching_ref=SHA256(matching_eval_id)`, matcher_version=matching-evaluation-v1이다. sources는 선택 comparison 전체와 retest initial 전체의 hash/size 원본이다. 복사·재계산 시각을 고정하고 기존 `_collect/_copy/_read_checked/_tree/_sealed/_rename_exclusive`를 재사용한다.

`freeze_matching(input_path,root=MATCHING_ROOT,comparison_root=COMPARISON_ROOT,initial_root=MATCHING_ROOT)`와 `verify_matching(matching_ref,root=MATCHING_ROOT)`를 제공한다. 기본 root는 data/private/evaluation/matching이다. matching-evaluation-archive-v1에는 selection/result/identity/receipt와 comparison/initial 전체를0400/0500으로 보관한다. 같은 ID·다른 bytes, 부분 목적지, symlink/추가/누락/권한 확대/손상을 거부하고 자체 staging만 정리한다. 현재 코드의 재계산과 canonical result bytes를 대조한다. POSIX/원자 rename·추가 공간·안정된 입력이 필요하며 WORM/Windows/전원 중단 내구성은 보장하지 않는다.

CLI `check-matching --input ... [--comparison-root ...] [--initial-root ...]`, `freeze-matching`에 같은 옵션과 `--root`, `verify-matching REF [--root ...]`를 기존 evaluation CLI에 연결한다. check는 summary, freeze/verify는 receipt만 stdout JSON 한 건, stderr 고정 코드, 종료0/2/3/5/1을 유지한다. 입력/결과8MiB·깊이100·strict UTF8/Unicode/중복키/추가키를 유지하고 case×관측을 만들면서 누적 결과 예산을 검사해 과다 요청은 저장 전에 거부한다. 실패 raw artifact는 기존 전체 streaming 복사로 보존한다.

## 완료 증거

TDD로 공개 검증 불변·private 미상/수집cutoff·좌표/사전 누출/날짜경계·6view의 전체 동결 원본·실패/누락/중복/추가/다문서 상충·E/A 분모·P/R0·이유 불일치·source/gold/회차/initial 불일치·동시/충돌/복사실패·권한/변조/오프라인 재계산·CLI 비노출을 검증한다. 기존 Python 전체·계약/Node/lint/build와 Java/MySQL 공개 bridge 회귀를 통과한다. 전체 자체 리뷰·fresh 전체1회·유효 지적 수정 후 source/통합 CI·자동/새 사람 피드백을 확인해 develop만 병합한다. 실제 gold/40문서/사람 검토·D09·배포는 미완료로 유지한다.
