# 사람 수정 원본의 D06 투영·인계 이미지 설계

## 목적과 단계 경계

TASK의 사람 수정본→공통 D06 인계를 두 검증 가능한 단계로 진행한다. 이번 단계는 frozen human-review의 수정값을 D06 사실 구조로 투영하고 원본 전체와 함께 동결한다. 다음 단계는 Java의 등록 D05/수정 원본 참조·실제 revision CAS·승인/공개 재검증에 연결한다. Java 연결은 전체 목표에 남으며 이번 투영을 기존 local-import 입력으로 취급하지 않는다.

## 구현 판단

기존 draft.py의 검증·사실 투영을 분리해 재사용한다. 원출력을 가짜 성공 D05로 다시 등록하거나 D06의 평탄화 값을 extract-schema로 역추측하지 않는다. 인계 도구가 실제 DB revision 번호·승인·좌표·행정구역 확정을 만들지 않도록 workflow 없는 사실 투영을 선택했다. 이는 AI 구현 판단이며 사용자가 구체 스키마를 승인했다는 뜻은 아니다.

## 선택과 투영

입력 human-handoff-v1은 schema_version, handoff_id(UUID), review_ref, review_receipt_sha256, source(source-import-v1 객체), area_id, split_group_id, dictionary_version만 받는다. 정확한 frozen review receipt/전체 이미지·실제 부모 D05를 재검증한다. source의 data_kind/문서버전/제목/게시일/블록은 부모 입력, 전처리는 부모 metadata와 같아야 한다. 제공한 cleaned_text는 자체 text_sha256과 부모 블록 포함 여부를 검사한다. 등록 D03의 전체 본문/hash·원문 파일·이용권한 등 전체 백엔드 연결 검증은 다음 단계가 맡는다.

부모가 api/manual_import·validated/failed인 실제 상태를 그대로 보존한다. 사람 수정 output.json으로 기존 D06 시간/장소/근거·UUID5 규칙을 적용하고 원출력은 바꾸지 않는다. 정상·부분 미상·중복·빈 사건·반복/명시 초·장소 대응 미상도 보존한다. event/location/occurrence/evidence UUID는 부모 run namespace를 유지한다.

projection.json의 human-handoff-projection-v1은 handoff_id/ref·projected_at·정확한 review/parent 출처·data_kind·명시 context·documents/evidence/events를 담는다. events의 facts는 기존 D06 의미값/원문·실행 참조/규칙·사전 필드다. revision_id/no, expected_revision_no, origin, review_status, reviewer_id/at, publication_intent, human_overrides는 만들지 않는다. 실제 추출 변경·검토자/시각·knowledge/reason/warnings는 함께 보관하는 review.json/output.json에 그대로 남는다. 인계 단계의 D06 변경 기록을 실제 DB 전후 값 없이 꾸미지 않는다. 근거 없는 장소 geometry/확인자·지역 확정도 만들지 않는다.

서로 다른 review의 같은 로컬 item은 같은 부모 event ID를 가질 수 있다. 실제 revision·병합/동시 충돌·과거 검토 보존은 다음 Java 연결 단계가 결정한다. 이 파일의 schema는 기존 ai-draft-import-v1/reviewed-import-v1과 다르므로 현재 Java reader가 거부한다.

## 보관·CLI·제한

selection.json·projection.json·review/REVIEW_REF 아래 사람 수정 이미지 전체(부모 D05 포함)를 handoff archive로 보관한다. 기본 data/private/evaluation/handoffs, SHA256(handoff_id) 참조, 파일0400/디렉터리0500·hash 대조 복사·전체 staging 재검증·배타 rename·같은 ID 다른 입력 충돌을 적용한다. 원래 경로 없이 저장한 projected_at으로 재계산하며 실패 시 자체 임시 이미지만 정리한다.

check-handoff/freeze-handoff/verify-handoff를 evaluation CLI에 추가한다. summary/receipt만 stdout JSON 한 건, 안전한 고정 stderr와 종료0/2/3/5를 유지한다. status=projection_only, backend_import_supported=false, review_required=true를 명시한다. 검토자·원문·경로는 stdout에 내보내지 않는다. JSON8MiB/깊이100·키/AI/외부 네트워크/DB/새 의존성 없음.

AI draft 바이트·공개 API·Java/DB/승인 정책은 이번 단계에서 바꾸지 않는다. 실제 사람/신원·독립 gold·실제40건·성능·D06 DB 전달 완료를 합성 검증으로 인증하지 않는다. POSIX/WORM·Windows·전원 중단 내구성의 기존 제한을 유지한다.
