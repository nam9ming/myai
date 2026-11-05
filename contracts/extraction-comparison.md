# D08 세 방법의 짝지은 비교 v1

같은 [독립 gold](gold-archive.md)에 대한 [규칙·AI·사람 수정후 평가](extraction-evaluation.md)를 비교한다. 기존 점수·원출력을 고치지 않고 필드별 개선·악화와 선언 검토 시간을 별도 기록한다. [시험 명세05 B](../docs/spec/05_시험과인수기준.md)의 비교 도구이며 실제 독립 정답·사람 판독·40건 성능을 인증하지 않는다.

## 선택 입력

`extraction-comparison-v1`은 아래 세 키만 받는다. 자리표시자는 실제 UUID·동결 평가 ref·canonical receipt의 SHA-256으로 바꾼다.

```json
{
  "schema_version": "extraction-comparison-v1",
  "comparison_id": "COMPARISON_UUID",
  "evaluations": {
    "rules": {"evaluation_ref": "RULE_EVALUATION_REF", "receipt_sha256": "RULE_RECEIPT_SHA256"},
    "ai_auto": {"evaluation_ref": "AI_EVALUATION_REF", "receipt_sha256": "AI_RECEIPT_SHA256"},
    "human_reviewed": {"evaluation_ref": "HUMAN_EVALUATION_REF", "receipt_sha256": "HUMAN_RECEIPT_SHA256"}
  }
}
```

각 ref는 해당 extraction_eval_id UTF-8의 SHA-256이며 각 방법을 정확히 하나씩 지정한다. 세 원본은 같은 evaluation root 아래 둔다. `verify_evaluation`으로 전체 gold/input/source/initial·저장된 결과를 재검증하고 선택한 방법·receipt hash를 대조한다. 비교 시각은 모든 평가의 frozen_at 이후여야 한다.

세 평가의 phase(initial/retest)·scorer_version·gold_ref/sha/receipt·manifest_sha256·instructions_sha256이 모두 같아야 한다. 모든 문서 버전/document_id/split·gold 슬롯/필드 집합도 같아야 하며 일부만 골라 비교하지 않는다. 입력 바이트 동일성은 같은 gold 이미지 재검증에 포함된다.

사람 결과의 source_run_id와 source_receipt_sha256은 같은 문서의 선택 AI 실행과 정확히 같아야 한다. UUID가 같아도 원본이 다르면 거부한다. 방법별 정책 SHA·피드백/노출 선언·최초 평가 참조는 각각 유지한다. 서로 다른 선언을 동일 조건이나 비노출로 바꾸지 않는다.

## 필드와 집계

비교 뷰는 rules.final_auto / ai_auto.final_auto / human_reviewed.human_reviewed다. document_version_id/slot_id/field를 기준으로 대응하며 AI의 로컬 ID·배열 순서나 자동 최적 대응을 정답 identity로 쓰지 않는다. 세 쌍은 rules_to_ai, ai_to_human, rules_to_human이다.

| 상태 | 의미 |
|---|---|
| improved | 이전 오답 → 이후 정답 |
| worsened | 이전 정답 → 이후 오답 |
| unchanged_correct | 두 방법 모두 정답 |
| unchanged_incorrect | 두 방법 모두 오답 |
| not_scored | gold 미상으로 기본 일치율 분모 밖 |

private result.json의 field_results에는 문서/사건/gold 슬롯/필드·각 방법의 local_item_id/정답 여부/오류 코드·세 전이가 남는다. 상세 정답/추출값은 원본 평가 이미지에 보존한다.

summary.pairs와 summary.splits.dev/holdout은 전체·필드별 total_fields/known_fields·각 상태 수·delta_percent를 제공한다. `delta_percent=(improved-worsened)/known_fields×100`은 일치율의 백분율포인트(pp) 차이다. 분모0이면 null(N/A)이다. 개선과 악화를 서로 지워 단일 점수로만 표시하지 않는다.

summary.methods는 각 방법의 primary_view, 첫 raw/최종 자동 또는 사람 views와 splits를 포함한다. 정답 분모·맞음·실패·누락·중복·추가·결합·생성 오류/미확정·비율을 기존 평가와 같은 방식으로 합산한다. 생성 검토가 남으면 생성률 N/A를 유지한다. M02는 원래 AI 자동의 선언상 조건을 유지하고 규칙/사람은 N/A다. 비교 자체가 새 M02 목표나 실제 성능을 인증하지 않는다.

최상위 holdout_warnings는 세 방법에서 같은 manifest의 그룹/노출 경고다. 방법별 노출·재시험·규칙 프로필 basis·사람 검토 basis 경고는 `summary.methods.METHOD.m02.warnings`에 원래 목록 그대로 남긴다. 관측 결과도 이 경고와 함께 해석한다.

human_review_time은 status=declared_only, 문서별 review_count/total_duration_ns 및 dev/holdout 합계다. 겹치는 검토 구간을 사람별 순작업 시간으로 추정하지 않으며 재사용 검토의 기존 시간을 새 재시험 노동으로 세지 않는다. generalization_claim은 항상 false다. 방법별 노출·retest·자료 부족 경고와 원래 cohort 수/분포를 함께 보존한다.

## 실행·불변 보관

```sh
python3.13 -m processing.evaluation check-comparison \
  --input data/private/evaluation/comparison.json
python3.13 -m processing.evaluation freeze-comparison \
  --input data/private/evaluation/comparison.json
python3.13 -m processing.evaluation verify-comparison COMPARISON_REF
```

`--evaluation-root`의 기본값은 `data/private/evaluation/extractions`다. freeze/verify의 `--root` 기본값은 `data/private/evaluation/comparisons`다. check는 summary만, freeze/verify는 receipt만 stdout JSON 한 건으로 내보낸다. 상세 값·검토자·원래 경로를 출력하지 않는다. 성공0·입력2·보관본 손상/충돌3·I/O5·내부 오류1이며 stderr는 고정 코드만 사용한다.

comparison_ref는 comparison_id UTF-8의 SHA-256이다. `extraction-comparison-archive-v1` 이미지에는 selection.json(입력 바이트 그대로), result.json, identity.json, receipt.json과 `evaluations/EVALUATION_REF/` 세 묶음이 들어간다. 각 평가의 gold·입력·실행/검토·실패 원본·retest의 initial도 전부 복사한다. 원래 경로 없이 저장한 compared_at으로 재계산하고 결과 바이트·전체 파일/hash/권한을 대조한다. 같은 ID의 다른 입력은 충돌이며 기존 원본을 덮어쓰지 않는다.

파일0400·디렉터리0500, hash 대조 복사·staging 재검증·배타 rename을 사용한다. 동시 같은 입력은 같은 이미지로 수렴하고 다른 입력은 충돌한다. 복사 중 변경·symlink·추가/누락·권한 확대·손상을 거부하며 실패 시 자체 임시 이미지만 정리한다. 기존 부분 목적지는 교체하지 않는다.

키·AI·네트워크·DB·새 의존성·공개 endpoint를 사용하지 않는다. JSON8MiB/깊이100·잘못된 Unicode/중복·추가 키 거부를 유지한다. 세 전체 평가 복사에 추가 공간이 필요하다. POSIX 권한은 관리자 교체를 막는 WORM이 아니며 Windows·전원 중단 내구성은 미검증이다. 실제40건·독립 gold·사람 검토·선별 엔진 평가·D06 인계·main 병합/배포는 별도 작업이다.
