# D08 실행 선택 동결·8필드 채점 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. 기존 연속 native 실행 지시를 적용하고 마지막에 한 번 fresh 전체 리뷰한다.

**Goal:** 독립 정답표와 명시한 AI 실행/슬롯 대응을 연결해 최초 raw·최종 자동 결과를8필드로 채점하고 initial/retest 평가 원본을 덮어쓰지 않게 보관한다.

**Architecture:** 순수 문서 채점기 → D05/독립 gold 실행 연결·시각 검증 → 별도 불변 평가 묶음/CLI 순서다. 정답·실행·이전 initial 원본과 대응/판정 기록을 함께 고정하며 stdout은 요약, 상세 값은 private 결과에 둔다. 단순 규칙 기준선·사람 수정값 연결·실제40건/선별/사용자 평가는 전체 목표의 후속 단계다.

**Tech Stack:** Python3.13 표준 라이브러리·unittest. 기존 private I/O·배타 rename 재사용, 외부 의존성 없음.

**Spec:** docs/spec/03_데이터와AI.md D05/D08, docs/spec/05_시험과인수기준.md B, contracts/gold-archive.md, contracts/dataset-bindings.md.

## Global Constraints

- 기능 PR 대상 develop, 배포 기준 main은 사람이 병합한다. 영어 Conventional Commits, 한국어 PR. 기존 AGENTS·사용자.gitignore·Java/공개 API/DB/기존 실제 원본은 변경하지 않는다.
- 기본 단위는 문서 내 사건 슬롯×date_start/date_end/time_start/time_end/locations/types/applicability/exceptions8필드다. 복수 일정/장소를 분모에서 세분화하지 않는다. null/누락/실패를 정답 있는 분모에서 빼지 않는다. 분모0은 N/A.
- 사람이 근거 anchor로 확정한 item/occurrence 대응을 받는다. 동일 출력 item/occurrence 재사용·하나의 gold 슬롯에 복수 정규 매칭을 금지하고 추가/중복을 분리한다. 모델에 유리한 자동 최적 매칭은 하지 않는다.
- 날짜는 값 정확 비교, clock은 초0 형식만 동치로 비교하며 end offset을 보존한다. 명시 종일은 독립 시간 답으로 비교하고 미기재와 구별한다. 공백/NFC·승인 동의어 외 의미 추정은 하지 않는다.
- 장소는 name/address/kind의 제공된 사실과 occurrence 참조를 보존한다. 대상은 applicability·route_names·stop_names·directions 전체, 예외는 명시 빈집합/미기재를 구별한다.
- 알려진 값 집합뿐 아니라 일정/장소 관계를 비교한다. 공유된 값의 최소 불일치 관계로 관련 시간/장소 필드를 오답 처리하며, 단일 값 오류가 무관한 필드로 전파되지 않게 시험한다.
- gold 비기재/모호 필드에 제공된 값은 생성 오류로 기록한다. 알려진 필드의 추가 주장·추가 사건 등 의미 판단이 필요한 생성 여부는 별도 검토 기록을 받으며 미확정 비율은 N/A다. 실제 의미/신원·독립성 인증으로 표시하지 않는다.
- method=ai_auto는 검증한 api D05만 지원한다. 최초 raw와 최종 자동을 함께 기록하고 M02 기본 view는 final_auto다. 기존 실제3건의 v1→v2를 동일 정책의 재시도로 합치지 않는다.
- initial은 gold 동결<실행 시작≤종료≤평가 시각을 요구한다. retest는 동일 입력/방법의 동결 initial을 참조하며 금표 변경·노출 이력·점수 차이를 보존하고 새 일반화 결과로 표시하지 않는다.
-8MiB·깊이100·엄격 JSON·safe CLI·정확0400/0500·완성 staging 배타 설치. 키/AI/네트워크/DB 호출 없음. 합성 시험을 실제 평가로 집계하지 않는다.

## Review Focus

1. 미상/부분 미상/명시 빈값·실패가 분모나 생성 오류율을 유리하게 바꾸지 않아야 한다.
2. 같은 주변 값 집합에서 date/time/place 결합을 뒤섞거나 동일 슬롯을 중복 추출해도 정상8필드로 통과하지 않아야 한다.
3. 초/익일 offset/명시 종일·추가 유형·방향/노선·예외·동의어를 정확히 비교하고 단일 오류를 무관 필드로 확장하지 않아야 한다.
4. 실패 raw→최종 성공·gold 사후 작성·manual D05·다른 버전/입력/phase·retst source 변경을 안전하게 거부/분리해야 한다.
5. 원본 경로 부재·동시 충돌·부분 설치·변조/권한/하위 symlink에서도 initial과 기존 원본을 보존해야 한다.

### Task 1: 순수8필드 채점

**Files:** Create processing/evaluation/scoring.py, processing/tests/test_scoring.py, contracts/extraction-evaluation.md. Modify processing/evaluation/gold.py to share existing instructions validation.

**Interfaces:** `score_document(input_bytes, gold_bytes, prediction_bytes, annotation_bytes, instructions:dict)->dict` returns private field_results + safe summary; annotation schema score-links-v1 has item_links/generation_reviews. item link keys slot_id/local_item_id/kind/occurrence_links, kind match/duplicate/additional, occurrence link keys gold_occurrence_id/local_occurrence_id. Generation review keys local_item_id/field/unsupported/reason.

- [x] 합성 source/gold/prediction과 독립 기대값으로8/8·누락/실패0/N·unknown/N/A·명시 빈값·중복/추가·wrong offset/all-day·뒤섞인 연결·단일 오류·pending generation·승인 동의어 시험 RED.
- [x] 기존 FieldValue/근거 검증과 판정 지침을 재사용해 최소 집합/대응/관계 채점 구현. Expected: 대상 시험 GREEN.
- [x] 전체 Python·npm lint/test/build 성공 후 feat: score eight extraction fields 커밋.

### Task 2: 실행·정답 연결과 최초/재시험

**Files:** Create processing/evaluation/records.py, processing/tests/test_evaluation_records.py.

**Interfaces:** `evaluate_record(content:bytes,gold_root,run_root,initial_root)->dict` loads verified sources and returns result/artifact sources for storage. Input extraction-evaluation-v1 fixes extraction_eval_id/gold_ref/gold_receipt_sha256/method/phase/initial_ref/review/documents. Each document selects version/run/snapshot_ref/receipt_sha256 and separate first/final annotations. No automatic successful-run selection.

- [ ] 합성 실제 API archive(전송 fake, 실제 키/네트워크 없음)로 raw실패/final성공·문서/버전/hash·api전용·시각·initial/retest/금표 변경·비노출 선언·정답 없는 분모 시험 RED.
- [ ] 원본 재검증·exact coverage·같은 입력·gold-before-run·phase/오염 기록·view별 전체/분할 요약 구현. Expected: 최초/최종 결과와 실패/누락/중복/생성 수 보존, synthetic은 실제 M02 성과로 표시하지 않음.
- [ ] 전체 회귀 성공 후 feat: bind extraction evaluation records 커밋.

### Task 3: 평가 묶음 불변 보관·CLI

**Files:** Create processing/evaluation/evaluation_storage.py, processing/tests/test_evaluation_storage.py. Modify processing/evaluation/__main__.py, processing/README.md, processing/TASK.md, contracts/README.md, docs/spec/03_데이터와AI.md.

**Interfaces:** `freeze_evaluation(input_path,root,gold_root,run_root,initial_root)->dict`; `verify_evaluation(evaluation_ref,root)->dict`; CLI check-evaluation/freeze-evaluation/verify-evaluation. eval_ref is SHA256(extraction_eval_id UTF-8).

- [ ] 바이트 보존·원래 경로 부재·동일/충돌 동시 실행·재시험의 최초 기록 보존·권한/파일/symlink/손상·I/O cleanup·실제 CLI safe JSON/exit tests RED.
- [ ] selection·result·gold/선택한 D05 전체 원본·retest의 initial 묶음을 복사·재검증한 뒤 배타 설치. Expected: 원본 불변, 같은 ID 다른 입력 충돌, 재사용은 고정 시각 유지, 무관 파일 보존.
- [ ] 전체 자체 리뷰·한 번 fresh 전체 리뷰·유효 지적 수정·정확한 head CI/자동 리뷰 지적0 확인 후 feat: freeze extraction evaluations 커밋/PR. develop만 병합, PR20 설명/통합 검증 갱신.
