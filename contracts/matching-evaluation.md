# D08 매칭 분류·사유 평가 v1

[세 방법 비교 원본](extraction-comparison.md)을 고정하고 독립 수동 기대값과 같은 조건의 C01~C10 계산을 비교하는 비공개 계약이다. 금표를 넣은 엔진 출력도 평가 대상이며 정답으로 복사하지 않는다. 기존 `calc-v1`·추출/gold/evaluation/comparison v1·공개 API·D03/D05·인계 형식은 유지한다. Python3.13 표준 라이브러리만 사용하며 키·AI·네트워크·DB를 호출하지 않는다.

## 선택 입력

UTF-8 JSON 한 건, 최대8MiB·깊이100이다. 중복 키·추가 키·잘못된 Unicode를 거부하며 nullable 키도 생략하지 않는다. `matching-evaluation-v1`의 최상위 키는 다음10개다.

| 키 | 값·검증 |
|---|---|
| `schema_version` | `matching-evaluation-v1` |
| `matching_eval_id` | UUID. UTF-8 SHA-256이 `matching_ref` |
| `phase` | `initial` 또는 `retest`. 원본 extraction-comparison의 회차와 별개 |
| `case_version` | 공백 아닌100자 이하 식별자. retest에서 같은 버전의 dictionary/cases 변경 금지 |
| `comparison` | 정확히 `comparison_ref`, `receipt_sha256`. 동결 comparison의 ref와 canonical receipt SHA-256 |
| `expectations_review` | 아래 수동 기대값 검토 선언 |
| `context_review` | 정확히 `reviewer`, `reviewed_at`, `note`. 지점·구역·사전·출처 조건의 검토 선언 |
| `dictionary` | 정확히 `dictionary_version`, `entries` |
| `cases` | 최소1개 조건 case. 모든 cohort 버전·gold 논리 사건을 포함 |
| `initial` | initial이면 null, retest이면 정확히 `matching_ref`, `receipt_sha256` |

`expectations_review`는 정확히 `author reviewer authored_at reviewed_at basis cross_reviewed no_unresolved_disagreements`를 갖는다. 담당자 두 값은 NFC·앞뒤 공백·대소문자 정규화 후 달라야 하며 작성≤검토≤평가 시각, 마지막 두 선언은 true다. `basis=source_only|model_outputs_seen|engine_outputs_seen|unknown`을 기록하고 사후 작성·노출 경고를 보존한다. 검토자 신원·독립 판독·의미 정확성은 선언이며 기계 인증이 아니다. context 검토 시각도 평가 시각 이하여야 한다.

comparison은 전체 원본을 재검증한다. 같은 gold·manifest·회차·정확한 AI 부모를 가진 rules/ai_auto/human_reviewed와 모든 버전의 입력 바이트를 재사용하며 성공 문서만 선택하지 않는다. gold의 `(document_version_id,slot_id)→event_id` anchors와 각 선택 문서의 `score-links-v1.item_links` 전체로 연결한다. 기존 field_results만으로 duplicate/additional을 복원하지 않는다.

## 조건·사전·출처

case는 정확히 `case_id context point query source_versions area_memberships expected`를 갖는다. `case_id`는 중복 없는 UUID다.

| 객체 | 필수 키·의미 |
|---|---|
| `context` | 기존 calc-v1의 `mode case_id server_now anchor_date reference_instant knowledge_cutoff history_fidelity data_kind window_days radius_m rules_version dictionary_version` |
| `point` | 기존 `point_id longitude latitude` |
| `query` | 기존 `point_id weekly_hours mode case_id types snapshot_id selection sort` |
| `area_memberships[]` | 정확히 `entry_id status`. 공통 dictionary의 모든 entry ID1회, `status=verified|uncertain|outside` |
| `expected[]` | 정확히 `event_id classification reason_codes note`. 모든 gold 논리 사건1회 |

context/point/query의 타입·WGS84·영업시간·KST·시각/참조 검증은 [calc-v1](calculation-bridge.md)을 그대로 따른다. `window_days=14`, `radius_m=500`, `rules_version=rules-v1`이며 dictionary_version은 공통 사전과, data_kind는 gold와 같다. private query.snapshot_id는 null이다. current context.case_id는 null, replay이면 해당 case_id이며 server_now≤evaluated_at이다. 공개 snapshot·실제 등록 revision을 만들었다고 간주하지 않는다. query.selection/sort로 평가 행을 숨기지 않는다.

expected는 엔진 출력과 독립적으로 작성한 사건별 `candidate|needs_check|cancelled|excluded`와 공백 아닌 판단 설명이다. source를 가진 gold 슬롯이 없는 manifest 사건을 추측해 추가하지 않는다. gold 사건0개일 때만 expected가 빈 배열이며 area_memberships는 dictionary.entries가 비었을 때만 빈 배열이다. reason_codes는 다음 기존13개 코드의 중복 없는 집합이며 비교할 때 순서는 의미가 없다.

```text
WINDOW_OUTSIDE BUSINESS_CLOSED TIME_NO_OVERLAP DISTANCE_OUTSIDE
DATE_UNKNOWN TIME_UNKNOWN BUSINESS_UNKNOWN LOCATION_UNKNOWN
AREA_UNCERTAIN SOURCE_STALE SOURCE_UNREACHABLE RELATION_UNCERTAIN CANCELLED
```

dictionary.entries[]의 정확한 키는 `entry_id name name_aliases address address_aliases kind geometry coverage source checked_by checked_at`이다. entry_id는 UUID, name/address는 nullable이며 둘 중 하나는 있어야 한다. 별칭은 각각 중복 없는 문자열 배열이다. kind는 `point|segment|stops|area|unknown`, coverage는 `complete|partial|unknown`, geometry는 nullable이며 기존 calc-v1의 geometry 종류·좌표·구간 제약을 따른다. source/checked_by와 평가 시각 이하의 checked_at을 남긴다. 동일 별칭의 여러 후보는 허용하되 자동 선택하지 않는다.

각 방법 **자신의 알려진** name/address를 NFC·공백 축약·casefold로 같은 필드의 사전 값과 대조한다. 알려진 두 필드가 충돌하거나 후보가 여러 개이거나 known kind가 다르면 geometry 미상이다. 유일하게 연결한 검토 geometry/coverage/kind는 계산용 파생값이며 원출력의 FieldValue를 덮어쓰지 않는다. gold의 장소·시간·유형·event ID로 다른 방법의 미상을 보완하지 않는다. Decimal 좌표는 원래 값의 유한성·범위를 확인한 뒤 계산 경계에서만 float로 바꾼다.

구역도 gold 사건이 아닌 공통 사전 entry의 검토 선언을 사용한다. 해당 출력의 occurrence가 실제 참조한 장소만 자기 값으로 사전에 연결한다. 참조 중 verified entry가 하나라도 있으면 verified, 참조가 비지 않고 모두 해소됐으며 모두 outside이면 outside, 나머지는 uncertain이다. 사용하지 않은 location은 구역을 verified로 올리지 않는다. match/duplicate/additional annotation은 채점 identity만 결정하며 계산 분류·사유에 영향을 주지 않는다. 따라서 gold에 없는 additional도 자신의 장소·조건으로 candidate가 되어 orphan FP로 기록될 수 있다.

source_versions는 모든 cohort 버전을 정확히 한 번 포함하며 기존 calc-v1 출처 객체의 다음 키를 그대로 사용한다.

```text
document_id document_version_id publisher official_url title official_number
published_date collected_at text_sha256 last_verified_at latest_check_attempt_at
check_result current_last_verified_at current_latest_check_attempt_at
current_check_result checks
```

checks[]는 기존 `checked_at result text_sha256` 구조다. document ID/URL은 manifest, title/published_date는 고정 AI 입력과 일치해야 한다. source.text_sha256·checks의 hash는 **case 제공자의 고정 선언**이다. 이 입력으로 D03 전체 본문 hash를 복원하거나 실제 D03·URL을 대조했다고 표시하지 않는다. 입력 bytes SHA·근거 block hash도 각각 보존한다.

private 평가에서 성공 확인이 없으면 실제 null/빈 checks를 유지하고 `SOURCE_STALE` 등 기존 판정을 사용한다. checks의 순서·hash·cutoff·파생 last/latest/result·current_* 검증은 유지하며 reconstructed로 바꿔 검증을 우회하지 않는다. replay에서 collected_at>knowledge_cutoff인 버전은 `unavailable_at_cutoff`로 보존하고 분류 함수를 호출하지 않는다. 이는 excluded가 아니며 모든 버전이 미확보이면 event state도 unavailable이다. 공개 calc-v1의 성공 확인·cutoff gate는 완화하지 않는다.

## 투영·관측 상태

기존 추출 projector의 시간/장소·미상 보존과 `business_hours`·`locate`·C01~C10 분류를 재사용한다. 계산용 projection UUID는 실제 run ID가 아니다. `projection_body_sha256=SHA256('\n'.join(block.text))`는 평가 블록 hash이며 선언된 `source_text_sha256`와 분리한다. 원래 D03 hash를 재구성한 것으로 표시하지 않는다. ai-draft envelope·workflow·가짜 실행을 등록하거나 외부에 출력하지 않는다.

| 상태·조건 | 보존할 결과 |
|---|---|
| 정상 계산 | `state=classified`, 기존4분류와 정렬된 reason_codes |
| 선택 types가 있는데 원출력 types 미상 | `state=not_computable`, classification/reason_codes=null, type_unknown disposition |
| 알려진 types 불일치 또는 참조 사전의 구역 집계 outside | `excluded`, reason_codes=[], type_filter/area_filter disposition |
| cutoff 당시 미확보 | `state=unavailable`, classification/reason_codes=null, not_available_at_cutoff disposition |
| 실패/누락 | failed/missing 행 유지. excluded로 바꾸지 않음 |

유형 필터가 없으면 제목/유형 미상 자체를 핵심 분류 blocker로 삼지 않는다. 엔진의 None 분류만 excluded로 대응하며 새 C코드를 만들지 않는다. 알려진 반복 문구처럼 projector가 해석하지 않은 제한·reconstructed/current_* 경고는 별도로 남긴다. expected와 gold engine의 불일치는 투영·문맥·수동 판단·엔진을 조사할 신호이며 확정 엔진 버그 판정이 아니다.

## 고정 분모·6개 뷰

각 case의 E는 모든 gold 고유 logical event, A는 모든 `(document_version_id,slot_id)`다. 뷰는 `gold_engine`, `rules_first_raw`, `rules_final_auto`, `ai_first_raw`, `ai_final_auto`, `human_reviewed`의6개다. 원본 비교의 AI/규칙 첫 raw·최종 자동과 사람 수정 출력 전체를 사용한다.

모든 A에 정규 match 또는 missing/failed/not_computable/unavailable 행을 남긴다. duplicate/additional도 별도 관측으로 보존하며 duplicate로 missing 정규 match를 대체하지 않는다. 실패/빈 출력 사실과 cutoff 상태를 함께 보존한다. 모든 cohort 문서·버전이 대상이며 active/inactive/latest 선택 옵션·사실 병합·자동 중복 제거는 없다. 같은 사건의 과거 취소와 새 후보가 함께 있으면 conflict를 보존하고 현행 revision을 추측하지 않는다.

event 분류는 모든 anchor의 정규 match와 연결 duplicate가 계산 가능하고 분류가 모두 같을 때만 확정한다. duplicate도 상충 검사에 포함하지만 A/E 분모를 늘리지 않는다. 이유 집합도 모두 같을 때만 확정하며 union하지 않는다. 이유만 다르면 분류는 유지하고 reason_codes=null로 남긴다.

| event 관측 | event state·분류 |
|---|---|
| linked 계산 분류가 둘 이상 | conflict 우선, classification=null |
| 정규 match 계산0, primary 상태 모두 같음 | missing/failed/not_computable/unavailable 유지 |
| 정규 match 계산0, primary 상태가 서로 다름 | partial |
| 정규 match 일부 계산 또는 duplicate까지 완성되지 않음 | partial |
| 모든 필수 관측 계산 완료·동일 분류 | classified, 해당 분류 확정 |

missing 정규 match에 candidate duplicate만 있으면 검색 TP는 가능해도 event state는 missing이다. candidate+failed는 partial, candidate+cancelled 또는 상충 duplicate는 conflict다. 이 상태는 classification이나 reason code를 추가하는 것이 아니다.

| 지표 | 단위·분모 |
|---|---|
| `retrieval_presence` | candidate match/duplicate의 event ID를 한 번, candidate additional은 `(version,local_item_id)`별 orphan key로 포함한 집합 P와 수동 기대 candidate 집합 C의 TP/FP/FN·`precision_percent`/`recall_percent` |
| `complete_classification` | 확정 event 분류가 expected와 같은 수 / E 전체. 미해결 상태도 분모에 유지 |
| 분류+사유 정확 일치 | 확정 분류와 확정 reason 집합까지 expected와 같은 수 / E 전체 |
| `target_agreement` | A 전체의 관측과 logical event 수동 target 비교. 역사 원문 자체의 정확도와 구별 |

`TP=|P∩C|`, `FP=|P−C|`, `FN=|C−P|`, `precision_percent=TP/(TP+FP)×100`, `recall_percent=TP/(TP+FN)×100`이다. 두 비율의 단위는 백분율이며 분모0은 null이다. 분모0을100%로 표시하지 않으며 F1·새 백분율 목표는 추가하지 않는다. duplicate 출력 수·candidate duplicate 수는 별도다. orphan candidate는 각각 FP이며 대응을 추측하지 않는다. candidate 검색 TP가 완전 분류 정답을 뜻하지 않는다.

4분류 confusion에는 missing/failed/not_computable/unavailable/partial/conflict 열을 함께 둔다. expected needs_check의 정확 판정·candidate 오확정·누락과 expected cancelled의 누락·candidate 오노출도 건수로 보고한다. duplicate는 별도 관측 비교와 상충에 포함하고 additional은 orphan/출력 상태로 남긴다.

`needs_check.missing`과 `cancelled.missing`은 해당 expected 상태가 **duplicate를 포함한 모든 linked classified 관측에 하나도 없는** 사건 수다. event state가 missing/failed인지와 별개이며 candidate 오확정/오노출과 동시에 집계될 수 있다. expected cancelled에서 candidate+cancelled는 conflict·완전 분류 오답이지만 cancelled.missing=0, candidate_exposure=1이다. missing primary+cancelled duplicate도 event state는 missing이어도 cancelled.missing=0이다. 이는 상태의 관측 존재를 측정하며 완전 분류 정답이나 실제 취소 안내 성공을 뜻하지 않는다.

expected↔gold engine, expected↔각 방법, gold engine↔각 방법을 구별한다. 마지막은 추출 영향 비교이며 gold engine을 정답으로 삼지 않는다. 모든 A의 대응과 비교 불가·추가·누락을 보존하고 양쪽 failure/null을 일치 정답으로 세지 않는다. gold consensus 불가도 표시한다. 전체·case·dev/holdout을 같은 고정 집합으로 합산하며 다른 case의 같은 event를 하나로 합치지 않는다. 원래 부족/노출/basis/정책/시간 선언과 `generalization_claim=false`를 유지한다.

## 최초·재시험과 불변 보관

matching의 phase와 source comparison의 phase를 각각 남긴다. retest 추출을 쓴 첫 matching도 원래 source phase·경고를 유지하며 최초 모델 성능으로 표시하지 않는다. matching retest는 명시한 동결 **matching initial**만 참조하고 retest 체인·자기 참조·다른 manifest cohort를 거부한다. 같은 gold_ref의 다른 gold SHA도 거부한다.

retest에서 같은 case_version의 dictionary/cases 변경은 충돌이다. 새 case/context/기대/gold/source는 이전·새 값과 수치를 보존하며 case/context/target이 같은 case만 paired delta를 낸다. 조건 변경을 같은 조건의 개선으로 표시하지 않는다. 검토·노출 선언은 실제 독립성·blind holdout·노동 감소 인증이 아니다.

`evaluate_matching(content, comparison_root=COMPARISON_ROOT, initial_root=MATCHING_ROOT, *, evaluated_at=None)`은 `{result,sources}`를 반환한다. `result.schema_version=matching-evaluation-result-v1`, `result.matcher_version=matching-evaluation-v1`, `summary.protocol_version=matching-evaluation-summary-v1`이다. 상세 case의 관측·기대 설명·사건ID·검토자·원래 경로는 private 파일에만 둔다. summary는 고정 분모·비율·cohort·원래 경고·선언 시간만 제공한다.

`matching-evaluation-archive-v1`은 기본 `data/private/evaluation/matching/MATCHING_REF/`에 `selection.json`(입력 바이트 그대로), `result.json`, `identity.json`, `receipt.json`, `comparisons/COMPARISON_REF/` 전체와 retest의 `initial/INITIAL_REF/` 전체를 보관한다. source comparison 안의 gold/input/실패 raw/각 방법 initial도 모두 복사한다.

파일0400·디렉터리0500, 전체 hash 대조 복사·staging 재계산 검증·배타 rename을 사용한다. 같은 ID의 다른 입력 bytes, 부분 목적지·symlink·추가/누락·권한 확대·손상을 거부한다. 같은 입력은 원래 시각/bytes/receipt를 재사용하며 실패 시 자기 임시 이미지만 정리한다. 원래 root 없이 저장된 evaluated_at으로 재계산하고 canonical result bytes까지 대조한다. 입력/결과8MiB·깊이100이며 행 생성 중 누적 결과 예산 초과도 저장 전에 거부한다. 실패 raw는 기존 전체 streaming 복사로 보존한다.

## CLI·한계

저장소 루트에서 실행하며 입력 경로는 사용자가 준비한 private 파일이다.

```sh
python3.13 -m processing.evaluation check-matching \
  --input data/private/evaluation/matching-selection.json
python3.13 -m processing.evaluation freeze-matching \
  --input data/private/evaluation/matching-selection.json
python3.13 -m processing.evaluation verify-matching MATCHING_REF
```

check/freeze는 `--comparison-root`(기본 `data/private/evaluation/comparisons`), `--initial-root`(기본 `data/private/evaluation/matching`)를 받는다. freeze/verify의 `--root` 기본값도 matching root다. check는 summary, freeze/verify는 receipt만 stdout JSON 한 건으로 내보낸다. receipt에는 전체 hash 대조에 필요한 상대 artifact 경로와 실행/버전 참조가 포함되므로 private 자료로 취급한다. 원래 절대 경로·상세 case/event·판단 메모·담당자·원출력 값은 stdout에 넣지 않는다. stderr는 고정 코드이며 성공0·입력2·보관 손상/충돌3·I/O5·내부1이다.

POSIX 권한·원자 rename·전체 복사 공간·안정된 입력이 필요하다. 관리자 교체를 막는 WORM·Windows·전원 중단 내구성은 보장하지 않는다. 합성 도구 검증은 실제 독립 gold·40문서/holdout·사람 검토·D09·공개 snapshot 검증 실적이 아니다. 실제 개발3건의 사람 검토/이용권한은 pending이며 실제 평가·main 병합·운영 배포는 별도 작업이다.
