# 사람 수정 원본의 D06 사실 투영·인계 이미지 v1

[human-review-v1](human-review.md)의 수정값을 D06의 사실 구조로 투영하고 전체 검토/부모 원본과 함께 보관한다. **현재 Java local-import 입력이 아니다.** summary는 status=projection_only, backend_import_supported=false, review_required=true를 반환한다. 실제 D06 저장·revision 연결·승인/공개는 다음 Java 연결 단계에 남는다.

## 선택 입력

human-handoff-v1은 아래8개 키만 받는다. source에는 D03 문서1개·빈 evidence/events의 source-import-v1 JSON 객체를 그대로 넣는다.

| 키 | 값 |
|---|---|
| schema_version | human-handoff-v1 |
| handoff_id | 새 UUID; 다른 선택/구역/사전은 다른 ID 사용 |
| review_ref | review_id UTF-8의 SHA-256 |
| review_receipt_sha256 | 선택한 frozen review의 canonical receipt.json SHA-256 |
| source | source-import-v1 객체 |
| area_id / split_group_id | 명시한 UUID; 지역을 확정했다는 뜻은 아님 |
| dictionary_version | 100자 이하, 제어문자 없는 명시 버전 |

review 이미지와 내부 D05 전체를 재검증하고 실제 receipt hash를 대조한다. source의 data_kind·문서 버전·제목·게시일·전체 블록은 부모 입력, 전처리는 부모 metadata와 같아야 한다. 제공한 cleaned_text는 자체 text_sha256과 부모 블록 포함 여부를 검사한다. 등록 D03의 전체 본문/hash 연결은 다음 Java 단계에서 대조한다. 부모는 api/manual_import·validated/failed의 실제 상태를 보존한다. 실패를 성공 D05로 다시 등록하지 않는다. projected_at은 review frozen_at 이후여야 한다.

D03의 원문 asset 파일은 이 이미지에 포함하지 않는다. raw_asset_path/hash 등 metadata는 source에 보존하며 원문 파일·이용권한·전체 D03 검증은 별도 source-root를 사용하는 Java 연결 단계가 맡는다. 투영 성공을 DB 저장 가능 판정으로 사용하지 않는다.

## 투영과 원본

projection.json의 schema_version은 human-handoff-projection-v1이다. handoff_id/ref·projected_at, review_id/ref/receipt, 부모 run_id/receipt/status/execution_mode, data_kind, 명시 context(area_id/split_group_id/dictionary_version), documents/evidence/events를 담는다. 빈 사건에서도 context와 미사용 근거를 보존한다.

events는 event_id·구역/문서 연결/관계/분할 정보와 facts를 담는다. facts는 D06 의미값·시간/장소/대상/예외/노선·실제 원문/실행 참조·규칙/사전 필드다. event/location/occurrence/evidence UUID5는 기존 부모 run namespace와 로컬 ID를 사용한다. 배열 순서로 사건을 합치거나 최적 대응을 추정하지 않는다.

실제 DB 상태를 모르는 투영에서는 revision_id/no·expected_revision_no·origin·review_status·reviewer_id/at·publication_intent·human_overrides를 생성하지 않는다. 실제 추출 수정의 전후 값·JSON 타입·이유·근거·검토자/시각은 함께 보관한 review.json에 그대로 남는다. D06의 실제 전후 값과 변경 기록은 Java 연결 때 검증해야 한다.

기존 AI 초안의 사실 투영을 재사용하되 사람 수정 output.json을 입력으로 사용한다. 부분 시간·명시 초·반복/모호 관계·중복 문자열·장소 대응 미상·빈 사건을 보존하며 시간/장소를 임의 확정하지 않는다. 장소 geometry/확인자/시각은 null, coverage는 unknown, 지역은 uncertain이다. 투영에서 평탄화되는 title/types/location.kind의 knowledge·사유와 warnings는 원래 output.json에 보존한다. facts만으로 원래 knowledge를 복원한다고 가정하지 않는다.

같은 부모의 다른 review는 같은 사건 ID를 가질 수 있다. 실제 revision 배치·현재 검토본과 충돌/병합·과거 수정 보존은 Java 연결 단계가 처리한다. 현재 reader는 이 투영 schema를 거부하며 approved/public 상태를 만들지 않는다.

## 명령·보관

```sh
python3.13 -m processing.evaluation check-handoff \
  --input data/private/evaluation/handoff.json
python3.13 -m processing.evaluation freeze-handoff \
  --input data/private/evaluation/handoff.json
python3.13 -m processing.evaluation verify-handoff HANDOFF_REF
```

`--review-root`의 기본값은 `data/private/evaluation/human-reviews`, freeze/verify의 `--root`는 `data/private/evaluation/handoffs`다. check는 summary, freeze/verify는 receipt만 stdout JSON 한 건으로 반환한다. 검토자·본문·실제 경로는 출력하지 않는다. 성공0·입력2·보관본 손상/충돌3·파일 I/O5·내부 오류1이다. stderr는 고정 코드만 사용하며 source/출력 검증에는 공통 DRAFT_SOURCE_MISMATCH·DRAFT_SOURCE_INVALID·DRAFT_OUTPUT_TOO_LARGE도 사용한다.

handoff_ref는 handoff_id UTF-8의 SHA-256이다. human-handoff-archive-v1은 selection.json(입력 바이트 그대로), projection.json, identity.json, receipt.json 및 review/REVIEW_REF 아래 전체 사람 수정 이미지·부모 D05를 담는다. 실패/과다 응답도 저장된 원본 크기 그대로 복사한다. JSON 제한은8MiB/깊이100이며 실패 원본은 수신 당시의 보관 범위를 유지한다.

파일0400·디렉터리0500, hash 대조 복사·전체 staging 재검증·배타 rename을 사용한다. 원래 경로 없이 저장한 projected_at으로 재계산하고 모든 파일/hash/권한을 대조한다. 같은 ID/입력은 원래 시각·바이트를 재사용하고 다른 입력은 충돌로 보존한다. 동시 설치·복사 중 변경·symlink/추가/누락·권한 확대·손상을 차단하며 실패 시 자체 임시 이미지만 정리한다. 다른 이미지나 기존 부분 목적지를 교체하지 않는다.

키·AI·외부 네트워크·DB·새 의존성을 쓰지 않는다. 원문 asset과 Java 연결·실제 사람 판독/신원·독립 gold/40건 성능·운영 배포는 별도다. 추가 저장 공간과 POSIX 배타 rename 지원이 필요하며 관리자 교체를 막는 WORM·Windows·전원 중단 내구성은 보증하지 않는다. 합성 시험을 실제 인계·사람 승인·성능 실적으로 세지 않는다.
