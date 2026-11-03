# 사람 수정후 추출 원본 보관 설계

## 목적·접근

동일 문서의 규칙/AI/사람 수정후 비교에 필요한 사람 수정 원본을 먼저 보관한다. 기존 D06은 개별 knowledge를 평탄화하므로 역변환하지 않는다. AI가 정한 접근은 기존 extract-schema-v1의 수정후 출력과 frozen D05 전체를 별도 묶음으로 보존하는 것이다. 새 스키마/DB나 D06 역변환보다 기존 근거 검증·원본 보관 방식을 재사용할 수 있다. 사용자는 단계별 자율 구현을 지시했으며 실제 사람 검토를 수행했다고 간주하지 않는다.

## 입력·검사

human-review-v1 입력은 schema_version, review_id(UUID), source(run_id/snapshot_ref/receipt_sha256), review(reviewed_by/started_at/finished_at/basis/note), output, changes다. source는 frozen D05의 UUID 또는 registered/HASH/UUID이고 정확한 canonical receipt SHA·등록 경로 hash를 대조한다. API와 manual_import의 validated/failed 원본을 모두 받되 규칙 원본을 D05로 취급하지 않는다. 원본 recorded_at과 알려진 finished_at ≤ 검토 시작 ≤ 종료 ≤ 검사/보관 시각을 검사한다. basis는 source_only/gold_feedback/unknown 선언이다. 이 선언은 독립성/신원/실제 판독 인증이 아니다.

output은 동일 원본 input에 대해 기존 parse_output을 통과해야 하며 FieldValue/근거/초/미상을 그대로 보존한다. changes는 기존 D06 기록과 같은 field_path/before/after/reason/evidence_ids/reviewer/time을 사용한다. output을 루트로 점 경로의 object만 탐색하며 배열은 전체 기록한다. 각 기록은 실제 전후 값(숫자와 boolean 구별)·동일 검토자/종료 시각·이전/새 출력의 유효 근거 ID와 일치해야 한다. 누락·중복·겹치는 경로·허위·무변경 기록은 거부한다. 실패 source는 유효한 이전 구조화 출력이 없으므로 before=null의 output 전체 변경 기록이 필요하다. 정상 source의 무수정 검토는 changes=[]로 가능하다. 시각·이유는 사람이 제공하며 자동 채움하지 않는다.

## 보관·CLI

review_ref는 review_id UTF-8의 SHA-256이다. 기본 root는 data/private/evaluation/human-reviews. review.json 원본 바이트, canonical output.json, source/SNAPSHOT_REF/의 D05 전체, identity.json/receipt.json을 보관한다. 기존 hash 확인 복사·POSIX0400/0500·배타 rename을 사용하고 원래 경로 없이 재검증한다. 같은 ID/바이트 재사용은 원래 경로가 없어도 가능하며 다른 입력·부분/손상된 목적지를 덮어쓰지 않는다. 검토 시간은 기존 instant_ns로 계산한 선언 duration_ns로 보존한다.

check-review --input FILE [--run-root ROOT], freeze-review --input FILE [--run-root ROOT] [--root ROOT], verify-review REVIEW_REF [--root ROOT]를 evaluation CLI에 추가한다. stdout은 ID/hash/data_kind/상태/건수/선언 소요시간 요약만, 실제 값/검토자/절대 경로는 비공개 파일에 남긴다. 성공0/입력2/보관 손상·충돌3/I/O5/내부1. JSON8MiB·깊이100·중복 키/비정상 Unicode 금지. 새 의존성·키/AI/네트워크/DB 호출 없음.

## 경계·완료 조건

D08 human_reviewed 채점/최초·재시험 연결, D06 인계 변환, 세 방법의 개선/악화·선별 비교는 다음 단계에 유지한다. 실제 독립 gold·holdout40·실제 검토/승인·운영 배포도 완료로 표시하지 않는다. 이번 완료는 명시한 source/수정 이력/시간 검증, 전체 이미지 동결/복구/충돌/동시성/CLI 오류 시험과 전체 회귀·리뷰·develop PR이다. 기존 AI/규칙 결과/보관본 의미·바이트는 바꾸지 않는다. main 병합·배포는 사람 전용, 사용자 .gitignore 변경 보존, 커밋 영어 Conventional·문서 한국어. POSIX는 WORM이 아니며 Windows/전원 중단은 미검증이다.
