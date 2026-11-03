# D09 사용자 비교 평가 기록·분석 v1

[명세03 D09](../docs/spec/03_데이터와AI.md#d09--최소-사용자-평가-기록-공개-db와-분리)·[명세05 C](../docs/spec/05_시험과인수기준.md#c-사용자-비교-평가)·I12의 비공개 로컬 계약이다. 실제 모집·동의·파일럿·수동 정답·현장 측정·사진을 생성하지 않는다. Python3.13 표준 라이브러리만 사용하며 공개 API/DB·calc-v1·D08·Flutter·운영 배포는 변경하지 않는다.

## private pack과 경계

원본을 읽기 전용 검사·분석하고 사용자가 지정한 JSON/CSV만 내보낸다. D09 원본·자료·증빙을 D08식 archive로 자동 복제하거나 영구 등록하지 않는다. 재현에는 운영자가 보존기한 안에 동일 원본을 유지해야 한다. 실제 접근 담당자·보존 종료일·종료 후 처리 기준은 제공받아야 하며 기본 보존 일수·자동 삭제·동의문을 만들지 않는다.

root 기본값은 `data/private/evaluation/user-studies`다. 기존 private-root 정책을 적용하며 저장소 안에서는 `data/private` 아래, 밖에서는 지정한 임시/비공개 경로를 사용한다. root의 group/other 권한은 없어야 한다. 모든 protocol/input/artifact/output 경로는 root 상대 canonical POSIX 경로다. 절대경로·탈출·symlink·비정규 파일을 거부한다. 실제 기록·결과·사진은 Git/공개 snapshot/외부 AI에 넣지 않는다.

프로토콜과 기한을 먼저 검사한다. `retention_deadline`의 **KST 해당일 끝까지** 유효하며 다음 KST 자정부터 check/export를 거부하고 records 파일을 읽지 않는다. 달력 상한9999-12-31도 같은 KST 경계로 지원한다. 출력 직전에도 현재 기한을 다시 확인한다. 만료 원본과 모든 export의 실제 처리·삭제는 접근 담당자의 운영 책임이다.

## 프로토콜: user-study-protocol-v1

정확한 최상위 키는 다음12개다. 키 생략·추가/중복 키·잘못된 UTF-8/Unicode·비유한 수를 거부한다. protocol/records/result는 각각 최대8MiB·깊이100이다.

```text
schema_version study_id protocol_version phase data_kind declared_frozen_at
pilot_review privacy source_set task_sets versions time_limit_seconds
```

| 필드 | 값·검증 |
|---|---|
| `schema_version` | `user-study-protocol-v1` |
| `study_id`, `protocol_version` | UUID, 공백 아닌100자 이하 버전 |
| `phase`, `data_kind` | `pilot|main`, `synthetic|real`. 파일럿을 본 평가 실적으로 합산하지 않음 |
| `declared_frozen_at` | 사전 고정 선언 UTC 시각≤evaluated_at. 실제 고정/독립성 인증 아님 |
| `privacy` | 정확히 `consent_version photo_consent_version access_owner retention_deadline post_study_processing confirmed_at`. photo_consent_version만 nullable. 나머지 실제 값/ID·YYYY-MM-DD·UTC 시각 필수, confirmed_at≤declared_frozen_at |
| `pilot_review` | pilot이면 null. main이면 정확히 `completed_at reviewer excluded_participant_ids note`. 완료≤declared_frozen_at, 최소1개 고유 pilot 가명 UUID, 본 평가 user와 교집합 금지 |
| `versions` | 정확히 `app_version snapshot_id snapshot_checksum rules_version dictionary_version`. UUID snapshot·SHA-256·rules-v1·명시 버전. board에도 같은 실험의 시제품/공개본 버전 연결 |
| `time_limit_seconds` | 사전 제공한 양수. 정확한 나노초 표현 가능, bool/비유한 값/나노초 미만 분수 금지. 기본값 없음 |

100자 제한은 protocol_version에만 적용한다. 다른 제어 label·버전·환경 문자열에 별도100/128자 상한을 추가하지 않으며 전체 JSON8MiB 한도를 적용한다. 각 필드의 타입·비공백·ID/enum 검증은 유지한다.

300초/두 방식30분은 원래 제안값이며 실제 제한시간으로 자동 채우지 않는다. 참여/촬영 동의는 별도 버전과 시각으로 받으며 법적 타당성·가명 실체·실제 동의를 인증하지 않는다. 다른 가명으로 같은 사람이 파일럿/본 평가에 재참여했는지도 인증하지 못한다.

`source_set`은 정확히 `documents board_document_version_ids prototype_document_version_ids location_reference_artifact snapshot_artifact`다. document는 정확히 `document_id document_version_id official_url text_sha256 artifact`, 고유 version·UUID·HTTPS URL·SHA-256을 갖는다. 두 방법의 버전 목록은 중복 없이 **모든 documents 버전을 똑같이** 포함한다. 같은 문서의 여러 버전도 보존한다.

artifact는 정확히 `{path,sha256,size}`이며 size는 실제 int≥0이다. 원문·위치 참고자료·증빙 bytes의 전체 streaming hash/size를 대조한다. raw artifact 파일 hash와 D03의 text_sha256는 구별한다. 원문을 변환·재접속하거나 D03 본문 hash를 복원했다고 표시하지 않는다.

snapshot은 기존 Java local-export로 pack 안에 준비한다. snapshot_artifact bytes SHA=snapshot_checksum이며 기존 snapshot-v1의 정확한27키·study data_kind·snapshot/rules/dictionary·created_at≤declared_frozen_at을 검사한다. sources의 문서/버전/URL/text hash, event/revision ID·source_version_ids·집합/집계를 대조한다. document_count는 고유 document ID 수, event_count는 event_public_payloads/revision_ids 수, event의 source 합집합은 전체 sources다. 이는 **선택 snapshot identity/집합 검사**이며 사건 내용·시간/거리 판정·전체 공개 whitelist·Java 승인/DB 이력 검증을 대신하지 않는다.

`task_sets`는 A/B 객체를 정확히 하나씩 담는 배열이며 순서는 의미가 없다. 각 객체는 정확히 `{set_id,version,items}`다. 각3문항이며 category `customer_guidance|delivery|event_preparation`을 한 번씩 포함한다. item은 정확히 `task_id category prompt expected_event_ids answer_basis_note`, task UUID는 전체에서 고유하다. expected_event_ids는 snapshot 사건의 중복 없는 부분집합이며 빈 집합도 허용한다. 과제·수동 정답·난이도 대조는 제공자의 선언이다. 두 세트의 질문은 달라도 전체 자료·위치 참고자료는 같다.

## 기록: user-study-records-v1

정확한 최상위 키는 다음7개다. study_id와 **실제 protocol bytes SHA**를 대조하고 records_version을 보존한다.

```text
schema_version study_id protocol_sha256 records_version recruitment participants evidence
```

recruitment[]는 정확히 `{participant_id,status}`다. 고유 가명 UUID, `status=invited|declined|no_show|consented|withdrawn`을 기록한다. 동의 전 운영표에는 이 두 값만 남긴다. invited/declined에는 participant 상세가 없어야 하고 consented는 상세 누락을 거부한다. no_show/withdrawn은 상세 없이도 모집/탈락 수에 남길 수 있다. 상세와 시작 기록이 있어도 이를 보존한 채 기본 비교쌍에서 제외하고 전체 비교 조건은 미확인으로 남겨 개선 성공을 확정하지 않는다.

participants[]의 정확한 키는 다음과 같다.

```text
participant_id participant_type participation_role consent photo_consent
assignment_sequence sessions interview observations feedback
```

- participant_type은 `merchant|resident|staff|expert|other`, participation_role은 `user|expert`다. expert type은 expert role이어야 한다. 전문가는 별도 집계하고 M04/M05 user에 더하지 않으며 비상인을 상인 실증으로 표현하지 않는다. 각 participant는 모집표의 consented/no_show/withdrawn과 연결된다.
- consent는 정확히 `{version,consented_at}`, protocol의 consent_version과 같고 실제 기록 시작 전·evaluated_at 이하다. photo_consent는 null 또는 같은2키와 별도 photo_consent_version이다. 실명/연락처 키는 없다. 자유문장에 개인정보가 없거나 선언이 사실이라는 점까지 검사하지 못한다.
- user의 assignment_sequence는 고유 양의 int다. 1 boardA→prototypeB,2 prototypeA→boardB,3 boardB→prototypeA,4 prototypeB→boardA,5/6은1/2 반복한다. 7이상도4순서 주기를 계속하며 빈 순번/불균형을 보고한다.4칸의 배정 수가 하나라도 다르면3명·6명도 불균형 경고를 남기되 새 eligibility gate나 순서 변경을 만들지 않는다. 사후 재번호를 부여하지 않는다. expert는 assignment_sequence=null·sessions=[]다.
- interview는 정확히 `{convenience,usefulness,continued_use}`의 nullable int1~5, observations는 `{needs_check_understood,distance_distinction_understood,source_access_succeeded}`의 nullable bool, feedback은 `{satisfied,required_changes}`의 nullable text다.

user는 board/prototype session을 하나씩 갖는다. session의 정확한 키는 다음과 같다.

```text
method task_set task_set_version device_browser network instruction_seconds
timing_includes_loading source_check records
```

배정된 task_set 또는 task_set_version이 다르면 채점/배정 분모가 달라지므로 입력 오류다. device_browser/network는 필수 문자열로 유지하며 두 방식의 실제 환경/안내시간이 다르거나 timing_includes_loading=false이면 기록을 보존하되 protocol deviation으로 남기고 기본 M05 비교쌍에서 제외한다. instruction_seconds와 timing_includes_loading은 명시 null을 허용하며, 안내시간 미확인은 instruction_ns=null과 미확인 사유를 남긴다. null 두 개를 같다고 비교하거나0/false로 채우지 않고 primary 제외·전체 비교 미확인으로 처리한다.

source_check는 null 또는 `{checked_at,originals_changed}`다. originals_changed도 nullable bool이며 null은 변경 없음이 아니다. 당일(KST)·각 시작 전·변경 없음 조건의 미충족/미확인은 같은 제외·미확인 처리다. 미래 시각·잘못된 타입은 오류이며 실제 접속/원문 불변을 인증하지 않는다. 동의/privacy·필수 버전·환경의 엄격성은 완화하지 않는다.

각 session.records는 배정된3개 task를 정확히 한 번 덮는다. 문항 기록의 정확한 키는 다음과 같다.

```text
task_id started_at ended_at elapsed_seconds outcome date_correct place_correct
target_correct exceptions_correct reported_event_ids missed_event_ids
false_positive_ids out_of_scope_ids assistance_notes answer_feedback_given operation_taken_over
```

| 항목 | 규칙 |
|---|---|
| outcome | `correct|incorrect|timeout|withdrawn|technical_failure|not_started` |
| not_started | 시각/elapsed/4bool/사건 목록 모두 null. 시작 전 withdrawn/technical_failure도 이 null 묶음 허용 |
| 시작한 문항 | start<end≤evaluated_at, elapsed>0이며 end−start의 나노초와 정확히 같음. 시작은 consent/declared_frozen_at 이후. 시각 한쪽 누락 금지 |
| 순서 | 같은 참여자의 시작 기록끼리 비중첩·방식 배정순서 준수. 서로 다른 참여자의 병렬 수행 허용. 문항 내 새 순서는 강제하지 않음 |
| 시간제한 | correct/incorrect 제출은 elapsed<사전 제한, timeout은 elapsed≥제한. 정확히 제한 도달하면 timeout |
| 정답 flag | 4개 모두 nullable 실제 bool. bool을 숫자로 대체 금지 |
| 사건 목록 | nullable·중복 없는 UUID 배열. missed⊆기대, false_positive⊆전체사건−기대, out_of_scope는 전체사건 밖 |
| reported 제공 | 세 사건 집합을 다시 계산해 선언과 정확히 대조. null이면 수동 판정 목록을 선언으로 보존 |
| correct | 4bool 모두true·missed/fp 빈 집합 필수. 올바른 부재도 true. 완전 정답을 incorrect로 표시하지 않음 |
| 도움 | assistance_notes는 nullable text, answer_feedback_given/operation_taken_over는 nullable bool. 위반 또는 null 선언은 기록·사유를 유지하고 기본 비교쌍 제외·전체 비교 미확인 |

실패/중단 시간은 원래 값으로 남기며0·제한시간으로 대체하지 않는다. 로딩·필터·원문 이동 시간도 포함한다. 범위 밖 발견은 별도로 보고하고 채점 집합에 섞지 않는다. 예외 정답 flag는 명세의 전체 정답 기준을 검사하기 위해 새로 구체화한 필드다.

evidence[]는 정확히 `evidence_id artifact kind participant_id captured_at issue_ids change_refs note`다. 고유 UUID, `kind=screen_capture|deidentified_photo`, participant_id nullable, captured_at≤evaluated_at, 중복 없는 비공개 issue ID/변경 참조 문자열 목록과 설명을 갖는다. participant 연결 시 별도 촬영 동의 버전·시각을 검사한다. null은 참여자 정보 없는 자료라는 선언이다. bytes hash 검사는 사진의 비식별·촬영 사실을 인증하지 않는다. 증빙2개 목표와 실제 검증한 artifact 수는 구별한다.

## 분석·목표 판정

모든 모집 상태·유형·역할·배정·시작/완료/중단/실패/미시작과 unknown을 남긴다. phase=pilot은 본 평가 인원/M05 성과에 합산하지 않고 expert도 별도다. M04의6명 목표/최소3명 추진는 real/main의 **실제 시작 user 수**와 비교하며 모집·동의·완료·정확 비교쌍·상인 인원도 따로 보고한다.

기본 비교쌍은 user의 양쪽3문항 전부correct·동일환경/안내/자료확인/도움 조건 준수인 경우뿐이며 모집 상태 no_show/withdrawn은 제외한다. B_i/P_i는 실제 elapsed_ns 합계, 감소율은 `(B_i−P_i)/B_i×100`이며 Fraction으로 정확히 계산한다. 음수·짝수 중앙값을 보존하고 display percent만 float로 바꾼다.20% gate는 정확한 유리수로 비교한다. 유효0명은 null이다. synthetic/pilot은 관측값만 제공하고 실제 목표 판정은 null이다. 유효 비교쌍에 별도 최소3명 gate를 새로 만들지 않는다.

전체 시작 문항을 분모로 정확 완료·4bool 정확도와 unknown 수를 계산한다. 배정 문항·not_started도 별도 분모/건수다. 전체 누락률의 분모는 **모든 배정 문항의 기대 사건 incidence 합계**, 분자는 알려진 missed 합계다. missed=null을0으로 채우지 않고 미확인 incidence로 남겨 전체 누락률은 null로 표시하며 확인 건수/가능 범위를 별도로 낸다.

prototype 정확 완료율이 낮거나 전체 누락률이 높으면 improvement_supported_as_declared=false다. 전체 누락률·모집 후 누락 상세·시작 user의 비교 조건 위반 등으로 전체 비교를 확인할 수 없으면 null이다. 양쪽의 기대 incidence와 확인된 누락 건수가 모두0이면 비율은 null로 유지하면서0건 비교로 누락 증가 없음을 확인할 수 있다. 한쪽 기대 incidence만0이면 누락 비교는 미확인이다. N/A를0%로 바꾸지 않는다. 시간 target 충족만으로 개선을 확정하지 않는다. 전체/유형별 primary 개인값·제외 사유·분모/미확인·모든 실패를 보존한다. 인터뷰는 역할별 응답/미응답·평균·1~5 분포와3관찰을 집계한다. real/main도 제공자의 선언상 결과이며 통계적/전체 상인 효과·신원·실험 진실성 인증이 아니다.

모집 상태 enum·7명 이후 배정 주기·예외 flag/거짓 포함0의 정답 일관성·기대 사건 incidence 분모·KST 기한 종료 경계·명시 export는 **이번 계약의 기술 선택**이다. 기존에 확정된 현장 운영 정책이나 실제 사용자 승인으로 표현하지 않는다. 과제/동의/보존 운영 사실은 실제 제공값으로 별도 고정해야 한다.

## 결과·공개 출력 경계

`user-study-result-v1`의 정확한 최상위 키는 다음13개다.

```text
schema_version study_id protocol_version records_version protocol_sha256 records_sha256
evaluated_at phase data_kind privacy versions summary participants
```

privacy/versions는 protocol의 같은 객체로 private 결과에 보존한다. 상세 participants에는 원기록과 계산한 task 집합·elapsed_ns·개인 합계/감소율/제외 사유를 남기며 raw artifact bytes는 넣지 않는다. session의 instruction_seconds는 instruction_ns(미확인은null), 문항의 elapsed_seconds는 elapsed_ns로 표현하고 원래 seconds 표현은 입력 bytes SHA로 보존한다. 운영 필드의 unknown 사유 코드는 제외 사유/deviations에 보존하며 사실을 추측하지 않는다. 각 문항 결과에 expected_event_ids를 추가한다. participant.analysis의 정확한 키는 `started finished_all all_correct eligible_pair exclusion_reasons board_ns prototype_ns reduction_percent deviations`다.

private 분석 packet의 records_content는 JSON 재시도 재계산에 쓰는 일시적 원입력 bytes다. result/summary/export의 필드가 아니며 별도 파일·archive로 보존하지 않는다.

summary의 protocol_version은 `user-study-summary-v1`, 정확한 공용 키는 `protocol_version data_kind phase recruitment participants m04 methods primary interviews observations evidence warnings generalization_claim`이다. methods는 board/prototype, primary는 `eligible_pairs ineligible_users median_reduction_percent meets_20_percent_as_declared improvement_supported_as_declared comparison_conditions_confirmed`를 제공한다. summary에는 가명ID·담당자·시각·경로·메모·feedback·artifact 참조·개인값을 넣지 않는다. `generalization_claim=false`를 유지한다. 원본 Decimal을 float로 근사하지 않고 파생 비율만 변환하며 결과 행 생성 중에도8MiB 예산을 검사한다.

summary와 이를 담은 receipt도 D09 파생 비공개 자료다. ID 제거·작은 집계가 익명성을 인증하지 않으며 실제 결과를 외부 AI에 보내거나 공개 게시하지 않는다.

## CLI·명시 내보내기

저장소 루트에서 실행한다. `--protocol`, `--input`, `--output`은 모두 `--root` 기준 상대경로이며 root 기본값은 `data/private/evaluation/user-studies`다.

```sh
python3.13 -m processing.evaluation check-study \
  --protocol protocol.json --input records.json
python3.13 -m processing.evaluation export-study \
  --protocol protocol.json --input records.json \
  --output reports/result.json --format json
python3.13 -m processing.evaluation export-study \
  --protocol protocol.json --input records.json \
  --output reports/result.csv --format csv
```

check는 summary JSON 한 건만 stdout에 출력한다. export의 output/format은 필수이며 JSON은 canonical result, CSV는 고정 열의 participant/task 행이다. CSV는 버전/SHA·역할·배정·결과·시간/정확도/누락·개인 감소율과 participant 행의 deviations 사유 코드를 제공하며 자유 서술은 제외해 JSON/원본에 유지한다. spreadsheet formula 접두는 CSV 표시용 escape하고 원본을 바꾸지 않는다. CSV도 비공개 개인자료다.

export는0600 파일·중간 부모를 포함한 모든 새 output 디렉터리0700으로 배타 생성하며 같은 bytes만 재사용한다(기존0400 허용). 동일 입력의 JSON 재시도는 첫 evaluated_at을 재사용할 수 있으나 원래 protocol/records bytes로 전체 재계산한 canonical result가 기존 bytes와 정확히 같고 현재 기한/권한도 유효해야 한다. 다른 입력·거짓 지표·미래/프로토콜 이전 evaluated_at·부분 파일·symlink·경로 탈출·권한 확대는 거부한다. 원입력의 영구 복사나 동결은 없으며 CSV는 같은 bytes일 때만 재사용한다. 이전 출력을 덮지 않는다. receipt의 정확한 키는 `protocol_version status format output_sha256 output_size summary`이며 상대 filename·participant ID도 포함하지 않는다. stdout은 이 safe receipt 한 건, stderr는 고정 코드다. 성공0·입력2·보관 충돌/손상3·I/O5·내부1로 종료한다.

자동 원본 복제/영구 보존/삭제 스케줄·공개 endpoint/DB 테이블은 없다. 실제 접근 담당자·보존 종료일·종료처리 기준은 확인 대기이며 값을 임의로 채우지 않는다. 실제 참여자·동의·파일럿·질문/정답·40문서/holdout·D09 결과·서식4/5·M04/M05 성과는 미완료다. main 병합·운영 배포는 별도 사람 작업이다.
