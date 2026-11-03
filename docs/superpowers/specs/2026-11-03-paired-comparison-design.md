# 세 방법의 짝지은 비교 설계

## 목적과 범위

시험 명세05 B의 규칙 자동/AI 자동/사람 수정후 비교를 구현한다. 같은 독립 gold와 원문에 대한 필드별 개선·악화·동일 정답·동일 오답 및 선언 검토 시간을 보존한다. 실제40건·독립 금표·사람 검토·선별 엔진 평가·D06 인계·main/배포는 전체 목표에 남긴다.

## 구현 선택

기존 동결 평가 세 개를 재검증하고 비교한 뒤 전체 이미지를 별도로 동결한다. 기존 원출력을 다시 선택하는 방식은 평가 선택/annotation/재시험 검증을 중복하므로 쓰지 않는다. 집계 점수만 빼는 방식은 같은 필드의 개선·악화가 상쇄되어 요구를 충족하지 않는다. 이 선택은 AI의 구현 판단이며 사용자가 구체 스키마를 승인했다는 뜻이 아니다.

## 입력과 동일성

`extraction-comparison-v1`은 `comparison_id` UUID와 `evaluations`를 받는다. evaluations는 rules/ai_auto/human_reviewed 각 하나의 evaluation_ref와 receipt_sha256만 포함한다. 동일 평가 root의 불변 원본 전체를 verify_evaluation으로 재검증한다. 각 ref는 SHA256(extraction_eval_id), 방법과 선택 receipt가 일치해야 한다.

세 평가의 phase·scorer_version·gold_ref/sha/receipt·manifest_sha256·instructions_sha256 및 모든 문서 버전/document_id/split·gold 슬롯/필드 집합이 같아야 한다. 입력 바이트는 같은 gold의 재검증으로 보장한다. initial/retest를 섞지 않는다. 사람 결과의 source_run_id/receipt는 해당 문서의 선택 AI 실행과 정확히 같아야 한다. 다른 부모를 고친 검토를 같은 AI의 성과로 비교하지 않는다. 방법별 정책·노출·피드백·초기 평가 참조는 보존하되 서로 같다고 추정하지 않는다.

## 결과

규칙/AI는 final_auto, 사람은 human_reviewed를 짝짓는다. 키는 document_version_id/slot_id/field이며 로컬 출력 ID나 자동 최적 대응을 만들지 않는다. rules_to_ai/ai_to_human/rules_to_human의 각 셀을 improved/worsened/unchanged_correct/unchanged_incorrect로 구분한다. gold 미상 셀은 not_scored로 보존하고 일치율 분모에서 제외한다. 전체·필드별·dev/holdout 집계를 모두 제공하며 분모0은 N/A다.

방법별 첫 raw/최종 자동 또는 사람 뷰의 기존 분모·실패·누락·중복·추가·결합·생성 오류/미확정 수를 같이 집계한다. 검토 시간은 원래 문서별 선언 합계와 dev/holdout이며 실제 노동시간 감소를 추정하지 않는다. 정책/노출 차이·retest를 숨기지 않고 generalization_claim=false를 고정한다. M02는 원래 방법별 판정 그대로 구분하며 비교 자체가 새 목표를 인증하지 않는다.

## 보관과 CLI

비교 selection/result 및 세 평가 전체(각 gold·source·initial 포함)를 `data/private/evaluation/comparisons`에0400/0500으로 동결한다. SHA256(comparison_id)가 comparison_ref이며 원래 경로 없이 재검증한다. 기존 tree/copy/identity/배타 rename helper를 사용한다. 같은 ID의 다른 입력은 충돌이며 기존 원본을 덮어쓰지 않는다. 복사 변경·symlink·추가 파일·손상·경쟁·설치 실패는 차단하고 임시 파일만 정리한다.

`check-comparison --input FILE --evaluation-root ROOT`, `freeze-comparison --input FILE --evaluation-root ROOT --root ROOT`, `verify-comparison REF --root ROOT`를 추가한다. check는 summary만, freeze/verify는 receipt만 stdout JSON 한 건으로 반환한다. 기존 종료0/2/3/5·입출력8MiB/깊이100·안전한 고정 오류 코드를 유지한다. 키·AI·네트워크·DB·새 의존성·공개 endpoint는 추가하지 않는다. 관리자 교체 방지/WORM·Windows·전원 중단 내구성은 보증하지 않는다.
