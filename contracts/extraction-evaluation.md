# D08 실행 선택·8필드 평가 v1

[독립 정답표](gold-archive.md)와 D05 AI 원출력·[규칙 실행 원본](rule-baseline.md)·[사람 수정 원본](human-review.md)의 비공개 평가 계약이다. [평가 기준](../docs/spec/05_시험과인수기준.md) B의 문서 내 사건 슬롯×8필드 단위를 유지한다. 정답·관계·의미 판정의 진실성을 기계 인증하지 않는다. 실제 독립 gold·40문서 평가는 별도로 필요하다.

## 문서 채점

`score_document(input_bytes, gold_bytes, prediction_bytes, annotation_bytes, instructions)`는 검증된 `ai-input-v1`와 독립 gold/예측 `extract-schema-v1`, 고정 판정 지침을 받는다. 상세 field_results/생성 오류·검토 목록은 **비공개 결과**이며 CLI에는 summary만 출력한다.

| 필드 | 값·분모 |
|---|---|
| date_start/date_end | 알려진 YYYY-MM-DD 집합, 각각 슬롯당1개 분모 |
| time_start/time_end | 알려진 시각 집합. HH:mm와HH:mm:00은 동치, 명시 초는 그대로 비교. 종료는 end_day_offset까지 비교 |
| locations | 알려진 name/address/kind 사실·승인 동의어와 occurrence.location_refs의 결합 |
| types | 세 유형 집합 정확 일치, 추가 유형도 오답 |
| applicability | applicability·route_names·stop_names·directions의 알려진 의미 단위 전체 |
| exceptions | 알려진 조건 집합, 명시된 빈집합은 정답 있음, 미기재/null과 구별 |

복수 값이 있어도 한 슬롯의 필드는1개로 센다. 알려진 값 일부가 빠지거나 대응하는 occurrence가 누락되면 해당 필드 오답이다. 미상/모호/해당 없음만 있으면 기본 분모 밖이다. 명시 all_day=true는 양쪽 시간 필드의 알려진 ‘명시 종일’ 답이며 임의 clock을 채우지 않는다. all_day=false만 있고 clock이 미상이면 시간 정답을 만들어내지 않는다.

NFC·연속 공백 축약·미리 승인한 동의어만 텍스트에 적용한다. 가까운 장소·문장 의미를 추측해 동일하게 만들지 않는다. 일정·장소 관계는 알려진 값 집합이 정확히 같은 필드끼리 새로 생긴 최소 불일치 결합을 비교한다. 2개 값 관계가 모두 같아도3개 이상 값의 결합이 다르면 관련 필드 오답이다. 값이나 관계의 순수 누락은 해당 필드와 occurrence 대응에서 오답 처리하며, 부분 교집합이나 빠진 관계를 무관한 필드의 오류로 전파하지 않는다.

이름/주소가 미상이어도 known kind는 장소의 알려진 사실로 분모에 남긴다. 종일 표시와 함께 제공한 clock/offset을 버리지 않는다. clock·명시 종일이 없는 offset/종일 아님 주장만으로 시간 정답 분모를 만들지는 않으며, 부가 주장을 별도 보존해 occurrence별 생성 여부를 검사한다. 알려진 시간 필드의 추가 주장은 의미 검토가 남으면 생성률 N/A이며, 미상 시간에 새 부가 값을 만들면 생성 오류다.

시간 정답 분모 밖에서도 gold의 부가 값과 다른 값(예: offset0→1)은 새 주장으로 생성 오류에 남긴다. unsupported=false 검토로 이를 상쇄할 수 없으며 금표가 잘못됐다면 새 금표 버전으로 재시험한다.

대응을 비워도 검사에서 빠지지 않는다. 미상 시간의 부가 주장을 gold의 알려진 값 전체와 대조하며, 기존 값으로 확인되지 않은 새 값은 자동 생성 오류다. 연결하지 않은 출력 일정의 알려진 주장도 의미 검토에 남긴다. 출력과 가장 잘 맞는 대응을 자동으로 채워 기본 오답을 없애지는 않는다.

## 사람이 확정하는 대응·생성 판정

annotation은 strict JSON `score-links-v1`: 정확히 `schema_version`, `item_links`, `generation_reviews`를 갖는다.

- item_links[]: `slot_id`, `local_item_id`, `kind`, `occurrence_links`.
- kind=`match|duplicate|additional`. 모든 예측 item을 정확히 한 번 분류한다. 정규 match는 gold 슬롯당 하나만 허용한다. duplicate는 기존 slot_id, additional은 slot_id=null. 정답에 없는 추가/중복 사건은 기본 gold 분모를 늘리지 않고 별도 센다.
- match의 occurrence_links[]: `gold_occurrence_id`, `local_occurrence_id`. 두 쪽 모두 해당 item의 ID이며 각각 재사용을 금지한다. 알려진 gold occurrence를 연결하지 않으면 그 occurrence의 정답 있는 필드를 오답 처리한다. duplicate/additional은 빈 occurrence_links를 제공한다.
- 대응은 독립 원문 anchor로 사람이 판정하며 값이 가장 잘 맞는 자동 정렬/병합은 하지 않는다. source JSON 배열 순서나 AI local ID 자체를 사건의 정답 identity로 취급하지 않는다.
- generation_reviews[]: `local_item_id`, `field`(8종), `unsupported`(bool), `reason`. 동일 item/필드 판정은 하나다. 검토자·시각은 평가 기록 review에 별도로 보존한다.

gold 비기재/모호 셀에 알려진 값을 넣거나 대응한 미상 occurrence를 채운 것은 생성 오류다. 명시 빈집합도 값이다. 기본 gold 분모 밖이어도 전체 예측 item×8필드 대비 생성 오류에 집계한다. 알려진 필드의 새 주장·추가 사건·잘못된 결합 등 의미 판단이 필요한 경우 검토 목록을 남긴다. 미확정 판정이 있거나 raw가 구조 실패이면 생성률은 N/A다. unsupported=true로 검토한 필드는 기본 정답이 있는 경우 오답으로도 기록한다. unsupported=false가 값 불일치를 정답으로 바꾸지는 않는다.

전체 값·관계 집합이 같아도 사람이 지정한 occurrence 대응에서 알려진 값끼리 다르면 생성 여부의 별도 검토를 요구한다. 검토 결과가 unsupported=false여도 기본 필드 오답은 유지한다. 순수 누락만 있는 경우를 새 주장으로 만들지는 않는다.

생성 판정은 날짜·시각·종류/예외 목록의 개별 값·대상 구성요소·장소의 함께 제시된 name/address/kind 사실을 사용한다. 일정 하나나 알려진 목록/장소 성분/offset의 일부만 빠지면 기본 오답을 유지하고 생성 검토를 만들지 않는다. 기존 한 장소의 사실 부분집합과, 서로 다른 장소의 성분을 섞은 새 주장은 구별한다. 명시 빈 목록은 ‘없음’ 주장으로 유지하며 자유문장의 의미를 부분집합으로 추측하지 않는다.

`맞은 정답 필드 / 정답 있는 필드 ×100`과 필드별 분모/맞음, 문서 실패·사건 누락/중복/추가·결합 오류·생성 오류 수/미확정 수/전체 출력 필드 수를 함께 반환한다. 분모0을100%로 표시하지 않는다. 실패 예측은 정답 있는 필드 분모를 유지하고 모두 오답이며 파싱하지 못한 생성 내용은 미확정으로 남긴다. 실패 raw에는 대응/판정 배열을 모두 비워 둔다.

## 실행·보관 계약

평가 입력 `extraction-evaluation-v1`은 다음 원본을 고정한다. 연결/보관 구현은 이 문서와 같은 판정을 사용한다.

| 객체 | 필수 키 |
|---|---|
| 최상위 | `schema_version`, `extraction_eval_id`, `gold_ref`, `gold_receipt_sha256`, `method`, `phase`, `initial_ref`, `review`, `policy`, `documents` |
| review | `reviewed_by`, `reviewed_at`, `semantic_feedback_used`, `exposure_status`, `exposure_note` |
| policy(ai_auto) | `provider`, `model_label`, `prompt_version`, `schema_version`, `retry_policy_version` |
| policy(rules) | `rule_version`, `profile_version`, `profile_sha256`, `schema_version`, `retry_policy_version`, `profile_reviewed_by`, `profile_locked_at`, `profile_basis` |
| policy(human_reviewed) | `schema_version`, `review_schema_version` |
| documents[](ai_auto/rules) | `document_version_id`, `run_id`, `snapshot_ref`, `receipt_sha256`, `first_annotation`, `final_annotation` |
| documents[](human_reviewed) | `document_version_id`, `review_id`, `review_ref`, `receipt_sha256`, `annotation` |

method=ai_auto의 기존 `api-structure-retry-v1` 정책은 archive-v1만 받으며 provider/model_label/prompt_version/schema_version이 모든 선택 실행과 일치해야 한다. [장문 분할](chunked-extraction.md)의 `api-document-cycle-v1`은 prompt_version=`prompt-v2-or-v3`을 명시하고 archive-v1/prompt-v2와 archive-v2/prompt-v3을 고정 규칙으로 선택한다. provider/model_label/schema_version 일치는 계속 요구한다. preprocessing_version은 실행별 원본을 보존한다. 모든 gold 버전을 한 번씩, 버전마다 한 D05를 명시한다. 성공 실행을 자동 선택하지 않는다. 첫 raw와 마지막 자동 결과를 모두 기록하고 기본 view는 final_auto다. v2의 first_raw는 첫 전체 문서 cycle의 파생 결과이며, attempt_count/source_attempt도 문서 cycle이다. 실제 HTTP 호출 수는 함께 보관한 원본 receipt.total_calls에서 확인한다. manual_import를 AI 자동 성능으로 표시하지 않는다.

method=rules는 rules-run-v1의 UUID 실행을 선택한다. snapshot_ref도 UUID이며 API registered 경로를 받지 않는다. schema_version=`extract-schema-v1`, retry_policy_version=`rules-single-pass-v1`이다. 모든 선택 실행의 규칙/프로필 버전·정확한 profile.json SHA가 policy와 같아야 한다. 실제6파일·입력 바이트·data_kind·문서ID·receipt SHA를 재검증한다. 원본의 실행 모드·receipt·모델/사용량은 변경하지 않는다.

프로필 검토자·고정 시각은 제공자의 선언이며 신원·사전 검토·실제 고정을 인증하지 않는다. profile_locked_at은 선택한 모든 실행 시작보다 엄격히 이전인 UTC 시각이다. profile_basis는 development_only/holdout_feedback/unknown 중 하나이며 initial은 development_only만 받는다. holdout_feedback이면 review.semantic_feedback_used=true·exposure_status=exposed가 필요하다. retest의 unknown/holdout_feedback은 RULE_PROFILE_BASIS_UNCLEARED 경고를 남긴다.

규칙은1회 실행이므로 first_annotation과 final_annotation이 같아야 한다. first_raw/final_auto는 같은 실제 output.json을 채점한다. final_auto는 해당 방법의 자동 결과이며 규칙 실패도 정답 있는 분모에 남는다. 규칙 관측 점수는 전체/dev/holdout에 표시하고, AI 목표 M02에는 M02_REQUIRES_AI_AUTO 경고와 N/A를 반환한다. 사람 수정후는 아래 별도 뷰를 사용하며 세 방법의 짝지은 개선/악화 비교는 [별도 계약](extraction-comparison.md)을 따른다.

## 사람 수정후 뷰

method=human_reviewed의 policy는 schema_version=extract-schema-v1, review_schema_version=human-review-v1이다. review_ref는 review_id UTF-8의 SHA-256이며 receipt_sha256은 실제 human-review archive의 canonical receipt hash다. 모든 gold 버전을 한 번씩 명시하고 기존 score-links-v1 annotation으로 사람의 사건/일정 대응·생성 판정을 제공한다. 일부 검토본만 골라 나머지 문서를 분모에서 제외할 수 없다.

전체 검토 이미지·내부 D05와 정확한 parent 입력 바이트/문서ID/data_kind를 대조한 뒤 검토 output.json을 같은8필드 scorer에 전달한다. 단일 primary_view와 views/splits 키는 human_reviewed다. 사람이 사건을 모두 제거해도 gold 분모와 누락 수를 유지한다. 실패 parent를 사람이 고쳐도 원래 AI 실패 상태는 남으며 AI 자동 성공으로 바꾸지 않는다.

사람 결과에는 review_ids, 문서별 review_id/review_ref/receipt_sha256, 실제 source_run_id/source_receipt_sha256/source_execution_mode/source_status, review_duration_ns/review_basis가 있다. field_results에는 review_id를 붙인다. 사람 검토를 D05 실행/시도로 만들지 않으므로 run_ids·attempt_count·source_attempt·가짜 모델/metadata는 생성하지 않는다.

부모 D05의 시작/종료 시각이 알려져 있어야 한다. parent 시작≤종료≤기록≤검토 시작≤종료≤평가자의 reviewed_at≤평가, 검토 종료≤검토 archive 동결≤평가를 검사한다. initial은 gold 동결<parent 시작·basis=source_only다. 시각 미상 수동 source는 원본 보관을 유지하되 통제된 최초/재시험 평가에는 사용하지 않는다. retest의 gold_feedback은 semantic_feedback_used=true/exposure_status=exposed가 필요하며 unknown/gold_feedback은 HUMAN_REVIEW_BASIS_UNCLEARED 경고를 남긴다.

같은 평가 안에서도 부모 source_run_id는 버전마다 유일해야 한다. 서로 다른 검토 이미지가 같은 부모 ID의 다른 원본을 내장하면 최초 평가 전에 거부한다.

human retest는 같은 방법/cohort/정규화 지침의 frozen initial만 참조한다. 같은 review_id는 최초 receipt SHA와 같아야 하고 새 검토는 initial 동결 뒤 시작한다. 같은 parent run_id의 다른 receipt도 거부한다. 기존 parent에 새 검토를 붙이거나 금표 수정에 기존 검토를 재사용할 수 있으며 원래 이미지·시각을 유지한다. 다른 방법이나 retest를 initial로 참조할 수 없다.

summary.human_review_time은 status=declared_only, review_count, total_duration_ns와 dev/holdout별 같은 합계를 제공한다. 문서별 선언 소요시간의 합으로, 동시/중복 구간을 정리한 사람별 순소요시간은 아니다. 기존 검토를 재사용한 재시험은 원래 시간을 유지하며 이번 회차의 추가 작업시간을 뜻하지 않는다. 검토자·실제 판독·basis 진실성을 인증하지 않는다. 관측 점수는 남기되 AI M02는 M02_REQUIRES_AI_AUTO와 N/A다.

## 공통 최초·재시험·보관

자동 방법의 phase=initial은 initial_ref=null, gold 동결<실행 시작≤종료≤검토≤평가≤보관 시각과 실행 종료≤원본 기록≤평가를 검사하며 의미 정답 피드백 사용을 허용하지 않는다. retest는 같은 cohort 입력/manifest·정규화 지침·방법의 동결 initial을 참조한다. gold 자체 수정은 이전/새 버전과 점수 차이를 보존하며 최초 기록을 덮어쓰지 않는다. 모델/프롬프트 정책 변경은 허용하되 policy_changed로 보고한다. 새 run_id는 initial 동결 이후 시작해야 하며 금표 수정만 재채점할 때는 이전 run_id를 유지할 수 있다. retest를 initial_ref로 다시 참조할 수 없다. retest나 노출/불확실 자료는 새 일반화·blind holdout 증거가 아니다. review의 신원/노출 상태도 제공자의 선언이다.

기존 run_id 재사용은 최초 평가가 선택한 receipt SHA와 정확히 같아야 한다. 같은 gold_ref의 다른 gold 원본은 거부하며 금표 수정에는 새 gold_version을 사용한다. 다른 저장 위치에서도 같은 ID를 다른 원본으로 바꿔 재시험 이력을 우회할 수 없다.

키·AI·네트워크·DB를 호출하지 않는다. JSON8MiB·깊이100·중복 키/추가 키/잘못된 Unicode 금지. 선택·결과·독립 gold/입력·선택한 D05 전체·규칙6파일 또는 사람 검토 이미지 전체(내부 D05 포함)·실패 원본과 retest의 initial을 별도0400/0500 묶음으로 보관한다. 같은 extraction_eval_id의 다른 원본을 덮어쓰지 않는다. stdout은 요약 JSON, 상세 정답/출력/근거·검토자·프로필 내용·경로는 private 파일에만 둔다. 세 방법 비교는 별도 비교 이미지로 보관한다. main 병합·배포·D06 인계·실제 평가 수행은 별도다.

평가 ID의 UTF-8 SHA-256을 evaluation_ref로 사용한다. 기본 저장소는 `data/private/evaluation/extractions`이며 각 묶음에 selection.json(입력 바이트 그대로)·result.json(상세 채점)·identity.json·receipt.json과 `gold/GOLD_REF/`, `runs/SNAPSHOT_REF/`, retest의 `initial/INITIAL_REF/`를 둔다. 하위 묶음의 identity/receipt·실패/부분 응답도 모두 보존한다. root identity의 artifact hash, 정확한 파일/디렉터리 집합·권한, 각 gold/선택 실행/initial 원본, 저장한 evaluated_at을 사용한 재채점 결과를 검사한다. 원래 경로 없이 검사하며 같은 입력 재사용은 원래 시각·바이트를 유지한다. 검증한 staging을 기존 배타 rename으로 설치한다. 관리자에 의한 전체 묶음 교체·삭제를 막는 WORM이나 전원 중단 내구성을 보장하지 않는다.

평가 명령의 기본 run root는 ai_auto이면 `data/private/extraction-runs`, rules이면 `data/private/rule-runs`, human_reviewed이면 `data/private/evaluation/human-reviews`다. 명시한 `--run-root`가 우선하며 verify는 보관한 runs 경로를 사용한다. check-bindings의 D05 전용 기본 경로는 그대로다. 기존 AI 선택·결과·동결본 형식과 재계산 바이트를 유지한다.

요약은 전체/개발/확인별 첫 raw·최종 자동의 분모·맞음·실패·누락·중복·추가·생성 수/미확정·필드별 점수, cohort의 유형/특성 분포와 부족분을 제공한다. M02는 method=ai_auto의 확인용 final_auto이며 real 선언·40/20/20 목표·문서당1버전·비노출/그룹 검토 선언·initial·확인용 정답 분모가 갖춰져야 수치를 제공한다. 미달 또는 rules/human_reviewed이면 M02는 N/A이고 관측 점수는 각 view에 남긴다. generalization_claim은 항상 false이며 선언만으로 실제 자료·독립성·일반화 성능을 인증하지 않는다.

사람 방법은 앞의 별도 human_reviewed 뷰와 선언 시간 요약을 사용한다. 세 방법 개선/악화 도구는 별도 계약으로 연결하며, 실제 독립 금표·사람 검토·40문서/holdout 및 실제 자료의 세 방법·선별 비교는 아직 수행하지 않았다.
