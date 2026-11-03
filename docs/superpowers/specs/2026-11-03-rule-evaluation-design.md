# D08 규칙 실행 평가 연결

## 목표·경계

`docs/spec/03_데이터와AI.md` D08과 `05_시험과인수기준.md` B의 단순 규칙 비교를 기존 채점·최초/재시험 보관에 연결한다. `rules-run-v1`을 명시적으로 선택하며 AI D05로 위장하지 않는다. Python3.13 표준 라이브러리만 사용하고 키·AI·네트워크·DB를 호출하지 않는다. 실제 사전 검토·독립 gold·40문서 성능은 만들었다고 가정하지 않는다.

## 선택·출처

- 기존 `extraction-evaluation-v1`의 method에 `rules`를 추가한다. ai_auto의 입력·정책·계산 결과·보관본 바이트 재검증은 유지한다. 공개 API/DB와 출시한 규칙 추출 알고리즘은 변경하지 않는다.
- rules policy는 정확히 `rule_version`, `profile_version`, `profile_sha256`, `schema_version`, `retry_policy_version`, `profile_reviewed_by`, `profile_locked_at`, `profile_basis`를 받는다. schema_version은 extract-schema-v1, retry_policy_version은 rules-single-pass-v1이다.
- 프로필 검토자·고정 시각·basis는 제공자의 선언이다. basis는 development_only/holdout_feedback/unknown이며 initial은 development_only만 허용한다. holdout_feedback은 semantic_feedback_used=true·exposure_status=exposed를 요구한다. 고정 선언 시각은 선택한 모든 규칙 실행의 시작 이전이어야 한다. 도구는 신원·독립 검토·사전 고정의 진실성을 인증하지 않는다.
- 버전마다 한 UUID 실행을 명시한다. rules의 snapshot_ref는 UUID만 허용하며 API registered 경로를 받지 않는다. 실제6파일 보관본을 재검증하고 문서ID·data_kind·입력 바이트·receipt SHA·규칙/프로필 버전·정확한 프로필 SHA를 대조한다. 같은 평가에 서로 다른 프로필을 섞지 않는다.
- 규칙은1회 실행이다. 사람이 제공한 first/final annotation은 같아야 하며 내부 attempt packet으로만 기존 채점 흐름에 맞춘다. 원본 receipt의 형식·모델/사용량은 바꾸지 않는다. RULE_OUTPUT_LIMIT 실패도 raw를 채점해 정답 있는 분모에 남긴다.

## 평가·동결

기존8필드·사건 대응·생성 검토·first_raw/final_auto·dev/holdout 집계를 그대로 사용한다. rules의 final_auto는 규칙 자동 결과이며 AI90% 목표인 M02에는 넣지 않는다. 관측 점수는 표시하고 M02는 N/A와 전용 경고를 반환한다.

initial의 gold 동결<실행 시작≤종료≤검토≤평가, 실행 종료≤원본 기록≤평가를 유지한다. retest는 동일 cohort/판정 지침/방법의 initial을 참조한다. 다른 방법을 initial로 바꾸지 않으며 정책 변경·금표 수정·노출/의미 피드백과 이전/현재 점수는 보존한다. 같은 run_id의 다른 receipt 재사용은 거부한다.

기존 freeze/verify-evaluation에 gold·선택한6파일 규칙 원본·initial 전체를 복사하고0400/0500·전체 hash·재계산·배타 설치를 검증한다. 원래 경로 없이 재검증한다. 기본 run root는 method에 따라 기존 extraction-runs 또는 rule-runs이며 명시한 --run-root와 보관본 내부 경로가 우선한다. stdout에 실제 정답/출력/검토자/프로필 내용/원래 경로를 추가하지 않는다.

## 증거·후속

코드 수정 전에 합성 AI 성공/실패/재시도/재시험 보관본과 기대 결과 바이트를 별도 private fixture로 보존해 수정 후 대조한다. 새 rules 정상/실패·정책/출처 불일치·시간/노출·M02 제외·복구/충돌·실제 CLI를 시험하고 기존 전체 회귀를 실행한다.

사람 수정후 출처 연결, 세 방법의 쌍별 개선/악화·검토 시간·선별 오류 분해, 실제 검토 사전/독립 gold/holdout/40문서 평가는 전체 목표의 다음 단계다. POSIX는 WORM이 아니며 Windows/전원 중단 내구성의 미검증 범위는 유지한다.
