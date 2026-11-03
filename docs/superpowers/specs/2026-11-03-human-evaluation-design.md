# 사람 수정후 D08 평가 연결 설계

## 목적·접근

동일 독립 gold/정규화 계약으로 사람 수정후 값을 채점하고 최초/재시험 전체 출처를 보존한다. AI가 정한 구현은 기존 records/scorer/evaluation_storage 재사용이다. 사람 값을 AI/규칙의 first_raw/final_auto나 D05 실행으로 꾸미지 않고 method=human_reviewed·단일 human_reviewed 뷰·review_id/review_ids를 쓴다. 기존 AI/규칙 결과/보관 바이트는 유지한다. 사용자 자율 단계 구현 승인에 따라 설계 선택을 공개하고 연속 진행한다.

## 선택·출처

최상위 extraction-evaluation-v1/review/phase/gold는 기존과 같다. human 정책은 schema_version=extract-schema-v1, review_schema_version=human-review-v1 두 키다. documents는 document_version_id/review_id/review_ref/receipt_sha256/annotation이며 모든 gold 버전을 정확히 한 번 명시한다. review_ref는 review_id UTF-8 SHA-256, receipt_sha256은 실제 human-review archive receipt다. annotation은 기존 score-links-v1의 수동 사건/일정 대응·생성 판정이다. 누락 문서를 조용히 제외하지 않는다.

verify_review로 전체 원본·수정 이력을 재검증하고 문서ID/data_kind·parent input 바이트를 gold 입력과 대조한다. 검증한 output.json을 같은8필드 scorer에 보낸다. 실제 review/parent D05의 ID·receipt hash·원래 모드/실패 상태와 선언 duration/basis를 보존하며 가짜 attempt/model/metadata를 만들지 않는다. 같은 평가 안에서 parent source_run_id도 버전마다 유일해야 하며 같은 ID의 상이한 원본을 최초 선택 전에 거부한다. 실패 parent를 사람이 수정한 점수는 AI 자동 성공이 아니다. 빈 검토 출력도 gold 분모를 유지한다.

## 시간·재시험

사람 평가에는 parent D05의 시작/종료가 알려져 있어야 한다. parent 시작≤종료≤기록≤검토 시작≤종료≤평가자의 reviewed_at≤평가, 검토 종료≤검토 archive 동결≤평가를 검사한다. initial은 gold 동결<parent 시작, basis=source_only다. unknown/시각 미상 source는 원본 보관을 유지하되 최초 성능 자료로 사용하지 않는다. retest의 gold_feedback은 semantic_feedback_used=true/exposure_status=exposed가 필요하며 unknown/feedback은 경고를 남긴다.

retest는 같은 cohort/정규화 지침/방법의 frozen initial만 받는다. 같은 review_id는 최초 receipt SHA와 같아야 하며 새 review는 initial 동결 뒤 시작한다. 같은 parent run_id의 다른 receipt도 거부한다. 기존 parent에 새 검토를 추가할 수 있다. gold 수정에는 새 버전을 사용하며 기존 검토 재사용·점수 차이와 최초 이미지를 보존한다. retest를 initial로 다시 참조하지 않는다.

## 결과·보관

primary_view=human_reviewed, summary.views/splits와 initial_comparison은 이 뷰를 쓴다. 사람 결과에는 review_ids·문서별 review_id/ref/receipt_sha256·원래 source_run_id/source_receipt_sha256/source_execution_mode/source_status·review_duration_ns/review_basis가 있고 가짜 run_ids/attempt_count/source_attempt는 없다. field_results에는 review_id를 붙인다. summary.human_review_time은 declared_only 상태·review_count/total_duration_ns·dev/holdout 합계다. AI M02는 항상 N/A이며 관측 점수/분모·실패/누락·생성 판정은 유지한다. 신원·의미 정확성·독립성은 선언으로만 다룬다.

기존 CLI 명령/종료 코드와 동결기를 사용한다. 기본 run root만 human_reviewed에서 data/private/evaluation/human-reviews로 선택하며 명시한 --run-root/보관본 내부 runs 경로가 우선한다. gold/전체 human-review 이미지(내부 D05 포함)/initial을0400/0500·정확한 hash·배타 설치로 보존한다. 키/AI/네트워크/DB/새 의존성 없음, JSON8MiB/깊이100. 사용자.gitignore/기존 AGENTS 보존, 영어 Conventional Commit·한국어 문서, PR develop/main·배포 사람 전용.

## 완료·후속

수정 전 합성 AI4·규칙 성공/실패/재시험3종 결과/최초 이미지를 고정해 호환 비교한다. 새 연결/원본 혼동/시간/노출/분모/M02/소요시간과 동결/원래 경로 제거/재시험/동시/실제CLI/오류를 시험하고 전체 회귀·한 번의 독립 리뷰·PR CI/AI/사람 리뷰를 확인한다. 실제 사람 검토·독립 gold/40문서/holdout·세 방법 개선/악화/검토시간 비교·선별 평가·D06 인계/승인/공개는 전체 목표에 남긴다. POSIX는 WORM이 아니며 Windows/전원 중단 내구성은 미검증이다.
