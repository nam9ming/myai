# D08 실행 선택·8필드 평가 v1

[독립 정답표](gold-archive.md)와 D05 원출력의 비공개 평가 계약이다. [평가 기준](../docs/spec/05_시험과인수기준.md) B의 문서 내 사건 슬롯×8필드 단위를 유지한다. 정답·관계·의미 판정의 진실성을 기계 인증하지 않는다. 실제 독립 gold·40문서 평가는 별도로 필요하다.

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
| policy | `provider`, `model_label`, `prompt_version`, `schema_version`, `retry_policy_version` |
| documents[] | `document_version_id`, `run_id`, `snapshot_ref`, `receipt_sha256`, `first_annotation`, `final_annotation` |

이번 AI 실행 연결은 method=ai_auto와 기존 api D05의 구조 재시도 정책만 지원한다. retry_policy_version=`api-structure-retry-v1`. provider/model_label/prompt_version/schema_version은 선택한 모든 실행과 일치해야 한다. preprocessing_version은 실행별 원본을 보존한다. 모든 gold 버전을 한 번씩, 버전마다 한 D05를 명시한다. 성공 실행을 자동 선택하지 않는다. 첫 raw와 마지막 자동 결과를 모두 기록하고 기본 view는 final_auto다. manual_import를 AI 자동 성능으로 표시하지 않는다.

phase=initial은 initial_ref=null, gold 동결<실행 시작≤종료≤검토≤평가≤보관 시각과 실행 종료≤D05 기록≤평가를 검사하며 의미 정답 피드백 사용을 허용하지 않는다. retest는 같은 cohort 입력/manifest·정규화 지침·방법의 동결 initial을 참조한다. gold 자체 수정은 이전/새 버전과 점수 차이를 보존하며 최초 기록을 덮어쓰지 않는다. 모델/프롬프트 정책 변경은 허용하되 policy_changed로 보고한다. 새 run_id는 initial 동결 이후 시작해야 하며 금표 수정만 재채점할 때는 이전 run_id를 유지할 수 있다. retest를 initial_ref로 다시 참조할 수 없다. retest나 노출/불확실 자료는 새 일반화·blind holdout 증거가 아니다. review의 신원/노출 상태도 제공자의 선언이다.

기존 run_id 재사용은 최초 평가가 선택한 receipt SHA와 정확히 같아야 한다. 같은 gold_ref의 다른 gold 원본은 거부하며 금표 수정에는 새 gold_version을 사용한다. 다른 저장 위치에서도 같은 ID를 다른 원본으로 바꿔 재시험 이력을 우회할 수 없다.

키·AI·네트워크·DB를 호출하지 않는다. JSON8MiB·깊이100·중복 키/추가 키/잘못된 Unicode 금지. 선택·결과·독립 gold/입력·D05 전체 요청/응답/실패 원본과 retest의 initial을 별도0400/0500 묶음으로 보관한다. 같은 extraction_eval_id의 다른 원본을 덮어쓰지 않는다. stdout은 요약 JSON, 상세 정답/출력/근거·검토자·경로는 private 파일에만 둔다. main 병합·배포·단순 규칙 기준선·사람 수정값 연결·실제 평가 수행은 별도다.

평가 ID의 UTF-8 SHA-256을 evaluation_ref로 사용한다. 기본 저장소는 `data/private/evaluation/extractions`이며 각 묶음에 selection.json(입력 바이트 그대로)·result.json(상세 채점)·identity.json·receipt.json과 `gold/GOLD_REF/`, `runs/SNAPSHOT_REF/`, retest의 `initial/INITIAL_REF/`를 둔다. 하위 묶음의 identity/receipt·실패/부분 응답도 모두 보존한다. root identity의 artifact hash, 정확한 파일/디렉터리 집합·권한, 각 gold/D05/initial 원본, 저장한 evaluated_at을 사용한 재채점 결과를 검사한다. 원래 경로 없이 검사하며 같은 입력 재사용은 원래 시각·바이트를 유지한다. 검증한 staging을 기존 배타 rename으로 설치한다. 관리자에 의한 전체 묶음 교체·삭제를 막는 WORM이나 전원 중단 내구성을 보장하지 않는다.

요약은 전체/개발/확인별 첫 raw·최종 자동의 분모·맞음·실패·누락·중복·추가·생성 수/미확정·필드별 점수, cohort의 유형/특성 분포와 부족분을 제공한다. M02 기본값은 확인용 final_auto이며 real 선언·40/20/20 목표·문서당1버전·비노출/그룹 검토 선언·initial·확인용 정답 분모가 갖춰져야 수치를 제공한다. 미달이면 M02는 N/A이고 관측 점수는 각 view에 남긴다. generalization_claim은 항상 false이며 선언만으로 실제 자료·독립성·일반화 성능을 인증하지 않는다.
