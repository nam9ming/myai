# D09 사용자 비교 평가 기록·분석 설계

## 목적·경계

명세03 D09·05 C·I12의 비공개 사용자 기록을 검사하고 M04/M05·실패/정확도/누락·인터뷰를 재현 가능한 로컬 JSON/CSV로 계산한다. 실제 모집·동의·파일럿·수동 정답·현장 측정·사진은 생성하지 않는다. 현재 실제 접근 담당자·보존 종료일·종료 후 처리 기준은 사용자에게 문의했으며 미정 값을 만들지 않는다. 이 단계는 도구 구현이며 실제 사용자 성과 완료가 아니다.

Python3.13 표준 라이브러리·기존 strict JSON/파일/나노초 helper를 재사용한다. Java 공개 서버·DB·calc-v1·D08·Flutter·운영 배포·실자료·키·AI 호출은 변경하지 않는다. 기존 AGENTS와 사용자 .gitignore 두 줄을 보존한다. 커밋 제목/본문은 영어 Conventional Commits(제목50자 이내), 문서/PR/주석은 한국어다. 기존 위임에 따라 현재 체크아웃·병렬 소유자·부모 Git·마지막 독립 전체 리뷰1회와 develop만의 병합을 적용한다. 설계의 새 선택은 작성자 판단이며 사용자 승인으로 표현하지 않는다.

## 접근 방식

공개 API/DB 수집은 비공개 분리 요구에 맞지 않고, D08식 전체 D09 동결 복제는 철회/보존 종료 처리와 충돌한다. **읽기 전용 private pack 검증·분석 + 명시한 private 결과 내보내기**를 선택한다. 프로토콜/기록/자료/증빙 파일을 자동 복사하거나 영구 archive로 등록하지 않는다. 입력 원본·version·SHA와 계산 기준을 결과에 남기며 재현에는 운영자가 기한 내 동일 원본을 보관해야 한다. 자동 삭제·보존 일수·동의문·실제 신원 인증을 만들지 않는다.

CLI pack root는 기존 `_root`의 private 경로 정책을 따른다(저장소 안 data/private, 밖 임시 경로). root에는 group/other 권한이 없어야 한다. 모든 protocol/input/artifact/output 경로는 root 상대 canonical POSIX 경로이고 symlink·탈출·비정규 파일을 거부한다. 공개 snapshot은 기존 Java local-export로 pack 안에 준비한다. 해시와 필요한 identity/집합만 대조하며 전체 Java 공개 게이트·DB 승인·원문의 진실성을 대신 검증했다고 주장하지 않는다.

## 프로토콜 — user-study-protocol-v1

정확한 최상위 키는 `schema_version study_id protocol_version phase data_kind declared_frozen_at pilot_review privacy source_set task_sets versions time_limit_seconds`다. UUID study_id,100자 이내 version, phase pilot/main, data_kind synthetic/real. declared_frozen_at≤evaluated_at이며 JSON 최대8MiB/깊이100·추가/중복키/잘못된 Unicode/비유한 수를 거부한다.

- `privacy`: 정확히 `consent_version photo_consent_version access_owner retention_deadline post_study_processing confirmed_at`. photo_consent_version만 nullable. 나머지는 실제 제공된 공백 아닌 값/ID·YYYY-MM-DD·UTC시각이며 confirmed_at≤declared_frozen_at. 기한은 KST 해당일 종료까지다. 그 다음 KST 자정부터 check/export를 거부한다. CLI는 프로토콜과 기한을 먼저 검사해 만료 때 records 파일을 읽지 않는다. 동의/보존 선언의 법적 타당성을 인증하지 않는다.
- `pilot_review`: pilot이면 null, main이면 정확히 `completed_at reviewer excluded_participant_ids note`. 완료≤declared_frozen_at, 최소1개 고유 pilot 가명 UUID. 본 평가 user와 교집합 금지. 다른 가명으로 같은 사람이 재참여했는지는 인증할 수 없다.
- `versions`: 정확히 `app_version snapshot_id snapshot_checksum rules_version dictionary_version`. UUID snapshot·SHA-256, rules-v1, 공백 아닌 버전. board에도 같은 실험의 시제품/공개본 버전을 연결하며 게시판이 앱을 실행했다는 의미가 아니다.
- `source_set`: 정확히 `documents board_document_version_ids prototype_document_version_ids location_reference_artifact snapshot_artifact`. 각 document는 `document_id document_version_id official_url text_sha256 artifact`. 고유 version·유효 UUID/HTTPS URL/SHA. board/prototype 목록은 중복 없이 **모든** version을 똑같이 포함한다. artifact는 정확히 `{path,sha256,size}`(size 실제 int≥0)이며 전체 streaming hash/size를 대조한다. 원문 artifact의 파일 hash와 D03 text_sha256는 구별한다.
- snapshot_artifact bytes SHA는 snapshot_checksum과 같아야 한다. snapshot-v1의 정확한27개 top-level 키를 검사하고 study data_kind·snapshot/rules/dictionary, created_at≤declared_frozen_at, sources의 문서/버전/URL/text hash, event/revision ID·source_version_ids와 집합/집계를 대조한다. document_count는 고유 document ID 수, event_count는 event_public_payloads/revision_ids 수이며 event의 source 합집합은 전체 sources다. 위치 참고 자료와 raw source bytes도 hash만 검사한다. 사건 내용·시간/거리 판정·전체 공개 whitelist/DB 이력 검증을 재구현하지 않는다.
- `task_sets`: A/B 각각 정확히 `{set_id,version,items}`. 각3문항, category customer_guidance/delivery/event_preparation 한 번씩. 각 item은 `task_id category prompt expected_event_ids answer_basis_note`; task UUID는 전체에서 고유, expected는 snapshot 사건 집합의 중복 없는 부분집합이며 빈 집합도 허용한다. 수동 정답/난이도 검토 설명은 선언이다. 두 세트의 문항은 달라도 자료 전체와 위치 참고 자료는 같다.
- `time_limit_seconds`: 사전 제공된 양수, 정확한 나노초로 표현 가능. 300초/30분은 제안값이지 강제 기본값이 아니다. bool/비유한 값/나노초 미만 분수를 거부한다.

## 기록 — user-study-records-v1

정확한 키는 `schema_version study_id protocol_sha256 records_version recruitment participants evidence`다. study ID/실제 protocol bytes SHA를 대조하고 records_version도 보존한다. 모든 상세는 private 입력/명시 export 안에만 둔다.

`recruitment[]`는 정확히 `{participant_id,status}`이며 고유 가명 UUID와 invited/declined/no_show/consented/withdrawn이다. 동의 전에는 이 두 값만 운영표에 남기며 평가 상세를 붙이지 않는다. participant 없는 consented는 누락으로 거부한다. invited/declined에는 상세가 없어야 한다. no_show/withdrawn은 상세 없이도 모집/탈락 수를 남길 수 있으나 분석 분모가 불완전함을 표시하고 개선 성공은 확정하지 않는다.

`participants[]`의 정확한 키는 `participant_id participant_type participation_role consent photo_consent assignment_sequence sessions interview observations feedback`다.

- participant_type merchant/resident/staff/expert/other; participation_role user/expert. expert type은 expert role이어야 하며 전문가를 M04/M05 사용자에 합산하지 않는다. staff 등 비상인은 유형별로 분리하고 상인 효과로 표현하지 않는다. 각 participant는 모집표의 consented/no_show/withdrawn과 연결된다.
- consent는 정확히 `{version,consented_at}`이며 프로토콜 consent_version과 같다. 실제 기록 시간 이전·evaluated_at 이하여야 한다. photo_consent는 null 또는 같은2키·별도 photo_consent_version이다. 실명/연락처 키는 schema에 없다. 텍스트 의미/가명 실체/실제 동의는 인증 불가하다.
- user의 assignment_sequence는 고유 양의 int. 원래1~6 표를 따르는4순서 주기:1 boardA→prototypeB,2 prototypeA→boardB,3 boardB→prototypeA,4 prototypeB→boardA,5/6은1/2 반복. 7이상도 같은 주기를 계속하는 작성자 선택이다. 순번을 사후 다시 매기지 않으며 빈 순번·불균형을 보고한다. expert는 null·sessions=[]다.
- user는 board/prototype session을 정확히 하나씩 갖는다. session은 `method task_set task_set_version device_browser network instruction_seconds timing_includes_loading source_check records`다. 배정표/과제 버전이 같고 두 방식의 실제 device_browser/network/안내시간이 같아야 한다. 다름은 기록을 잃지 않도록 protocol deviation으로 남기고 기본 M05 비교쌍에서 제외한다. timing_includes_loading은 bool이며 false도 같은 처리다.
- source_check는 null 또는 `{checked_at,originals_changed}`. 당일(KST)·각 시작 전 확인·변경 없음 조건을 만족하지 않으면 기록은 유지하고 기본 비교쌍에서 제외한다. 미래 시각/잘못된 타입은 오류다. 실제 접속·원문 불변의 인증은 아니다.
- 각 session.records는 배정된3개 task를 정확히 한 번 덮는다. 기록의 정확한 키는 `task_id started_at ended_at elapsed_seconds outcome date_correct place_correct target_correct exceptions_correct reported_event_ids missed_event_ids false_positive_ids out_of_scope_ids assistance_notes answer_feedback_given operation_taken_over`다. exceptions_correct는 원래 bool 목록의 기술 공백을 보완해 전체 정답 기준을 검사한다.
- outcome은 correct/incorrect/timeout/withdrawn/technical_failure/not_started. not_started는 시각/elapsed/4bool/사건 목록이 모두 null. 시작 전 withdrawn/technical_failure도 이 null 묶음을 허용한다. 시작했으면 start<end≤evaluated_at, elapsed_seconds>0이고 **end-start의 나노초와 정확히 같아야** 한다. 시각 한쪽만 없거나 bool을 숫자로 준 경우는 거부한다. 시작은 consent/declared_frozen_at 이후다. 참여자 전체의 시작 기록끼리 겹치면 거부하고 방식 순서도 지켜야 한다. 문항 내 순서는 새로 강제하지 않는다.
- correct/incorrect 제출은 elapsed<사전 제한, timeout은 elapsed≥제한이다. 경계 정확히 도달하면 timeout이다. 실패/중단은 원래 시간을 남기며 제한값/0으로 대체하지 않는다.
- 4bool은 nullable 실제 bool, 사건 목록은 nullable 중복 없는 UUID 배열. missed⊆기대, false_positive⊆전체사건−기대, out_of_scope는 전체사건 밖이다. reported_event_ids를 제공하면 이 세 집합을 다시 계산해 선언값과 정확히 대조한다. reported가 null이면 수동 판정 목록을 그대로 선언으로 보존한다. correct에는4bool 모두true·missed/fp 빈 집합이 필요하다(올바른 부재도 해당 기준 true). 완전 정답인 기록을 incorrect로 표시하지 않는다. 범위 밖 발견은 별도로 보고하고 채점 집합에 섞지 않는다.
- assistance_notes는 nullable text, answer_feedback_given/operation_taken_over는 실제 bool. 실제 도움 위반 선언은 기록에 남기고 기본 비교쌍에서 제외하며 텍스트를 AI로 분석하지 않는다.
- interview는 `{convenience,usefulness,continued_use}`의 nullable int1~5, observations는 `{needs_check_understood,distance_distinction_understood,source_access_succeeded}`의 nullable bool이다. feedback은 `{satisfied,required_changes}`의 nullable text. 전문가 응답은 별도 집계한다.

`evidence[]`는 정확히 `evidence_id artifact kind participant_id captured_at issue_ids change_refs note`. 고유 UUID, artifact는 위 경로/hash/size, kind screen_capture/deidentified_photo, participant_id nullable, captured_at≤evaluated_at, 나머지는 중복 없는 비공개 ID/참조 문자열 목록·설명이다. participant 연결 때 별도 촬영 동의 버전·시각을 검사한다. null은 참여자 정보 없는 자료라는 선언이다. 모든 bytes hash를 검사하지만 사진 내용/비식별/촬영 사실은 인증하지 않는다. 증빙2개 목표와 실제 검증된 artifact 수를 따로 보고한다.

## 분석·결과

E/A/D08 점수를 D09 시간으로 재명명하지 않는다. 모든 모집 상태·유형·역할·배정·시작/완료/중단/실패/미시작을 보존한다. phase pilot은 본 평가 인원/M05 성과에 합산하지 않는다. 본 평가 experts도 별도다. M04 목표6·최소3 추진와 실제 모집/참여/정확 완료·상인 인원을 구별한다.

각 user의 양쪽3문항 전부correct이고 환경/안내/자료확인/도움 조건을 지켰을 때만 기본 비교쌍이다. B_i/P_i는 실제 elapsed_ns 합계. 개인 감소율 `(B-P)/B×100`과 중앙값은 Fraction으로 정확히 계산해 음수·짝수 중앙값을 보존한다. display percent만 float이며20% gate는 정확한 유리수로 비교한다. 유효0명이면 null이다. synthetic/pilot에서는 관측값만, 실제 M05 목표 판정은 null이다. real/main도 선언상 결과이며 통계적/전체 상인 효과·신원/실험 진실성 인증이 아니다.

전체 시작 문항을 분모로 정확 완료·4bool 정확도와 unknown 수를 계산한다. 배정 문항·not_started도 별도 분모/건수에 남긴다. ‘같은 전체 과제 기준 누락률’은 **모든 배정 문항의 기대 사건 incidence 합계**를 분모로 하고 알려진 missed 합계를 분자로 한다. 미시작·실패 등의 missed=null은0이 아니라 미확인 incidence로 남기며 전체 누락률은 null, 확인된 건수/가능 범위는 별도로 낸다. 이 기술적 분모 선택을 기존 확정 정책처럼 표현하지 않는다.

prototype 정확 완료율이 낮거나 전체 누락률이 높으면 improvement_supported_as_declared=false다. 전체 누락률/모집 후 누락 상세/시작한 사용자의 비교 조건 위반 등으로 전체 비교를 확인할 수 없으면 null이다. 시간 target 충족만으로 개선을 확정하지 않는다. M05의20%는 유효 비교쌍이1개 이상일 때 계산하며 별도 최소3개 gate를 새로 만들지 않는다. M04의6명/최소3명은 real/main의 실제 시작 user 수와 비교하고 전체 동의·완료·정확 비교쌍 수를 따로 보고한다. primary 개인값·제외 사유·시작/배정/미확인 분모·모든 실패를 전체/유형별로 보존한다. survey는 역할별 응답/미응답·평균·개별1~5 분포와3관찰을 집계한다.

result는 `user-study-result-v1`이며 정확한 top keys `schema_version study_id protocol_version records_version protocol_sha256 records_sha256 evaluated_at phase data_kind privacy versions summary participants`다. privacy/versions는 프로토콜의 같은 객체로 export의 보존 책임·버전 연결을 유지한다. 상세 participants에는 입력의 상세/기록과 계산된 task 집합·elapsed_ns·개인 합계/감소율/제외 사유를 남기되 raw artifact bytes는 넣지 않는다. session의 instruction_seconds와 record의 elapsed_seconds는 정확한 instruction_ns/elapsed_ns로 표현하고 원래 seconds 표현은 input bytes SHA로 보존한다. 각 task 결과에 expected_event_ids를 추가한다. participant.analysis는 `started finished_all all_correct eligible_pair exclusion_reasons board_ns prototype_ns reduction_percent deviations`를 갖는다. summary는 `user-study-summary-v1`, counts/denominators/지표/경고/목표만 포함하며 가명ID·담당자·시간·경로·메모·feedback·artifact refs는 넣지 않는다. summary의 공용 키는 protocol_version/data_kind/phase/recruitment/participants/m04/methods/primary/interviews/observations/evidence/warnings/generalization_claim이다. methods는 board/prototype, primary는 eligible_pairs/ineligible_users/median_reduction_percent/meets_20_percent_as_declared/improvement_supported_as_declared/comparison_conditions_confirmed를 제공한다. individual 값·ID는 summary 밖에만 둔다. 입력/결과 최대8MiB·행 생성 중 예산 검사를 한다. 원본 Decimal을 float로 바꾸지 않으며 파생 비율만 변환한다.

## CLI·내보내기

`check-study --root ROOT --protocol protocol.json --input records.json`은 summary JSON 한 건만 stdout에 출력한다. `export-study`는 같은 검증 뒤 `--output reports/result.json|csv --format json|csv`에 private 결과를 배타 생성하고 safe receipt만 출력한다. root 기본은 data/private/evaluation/user-studies. export JSON은 canonical result, CSV는 participant·task 행(고정 열)으로 version/SHA·역할·배정·결과·시간/정확도/누락·개인 감소율을 제공한다. 자유 서술은 CSV에 넣지 않고 JSON/원본에 보존한다. 문자열의 spreadsheet formula 접두는 CSV 표시용 escape하며 원본은 유지한다.

export는0600 파일·0700 새 디렉터리, 같은 bytes만 재사용하고 다른 내용·부분 파일·symlink·경로 탈출·권한 확대를 거부한다. 재사용 파일은 더 제한적인0400도 허용한다. 재사용 때 이전 JSON/CSV bytes를 덮지 않는다. 출력 직전에 현재 기한을 다시 검사한다. 자동 원본 복제/영구 보존/삭제 스케줄·공개 endpoint/DB 테이블은 없다. 만료 파일과 모든 export의 실제 처리·삭제는 정해진 접근 담당자의 운영 책임이다. 성공0·입력2·보관 충돌/손상3·I/O5·내부1, stderr 고정 코드만 사용한다.

## 검증·완료 조건

실제 RED→GREEN으로 strict schema/consent/retention 선검사·기한경계·자료전체/해시/버전/집합·탈출/symlink·배정표/전문가/파일럿·동일조건/시간나노초·전부정답 비교쌍·음수/짝수median/20%정확경계·누락미상/실패/정확도 방어·survey·크기·JSON/CSV/배타파일/안전CLI를 검증한다. 전체 Python·Java/MySQL bridge·Node/JSON/lint/build를 실행하고 작성자 전체 리뷰·마지막 독립 전체1회·모든 유효 minor 포함 수정 후 source/통합 CI·AI·새 사람 피드백을 확인한다. develop만 병합하고 main/배포는 사람이다. 실제 모집/동의/실증·공식 서식 작성·M04/M05 성과는 여전히 별도 완료 조건이다.
