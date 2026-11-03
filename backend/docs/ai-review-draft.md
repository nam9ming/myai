# AI 원출력에서 숨김 검토 초안 만들기

검증된 D05 실행에서 사람이 검토할 파일을 만들고 기존 local-import로 저장한다. 실제 모델을 호출하지 않으며 기계 검증 통과를 사람 승인으로 바꾸지 않는다. 먼저 [D03 선등록·D05 등록](extraction-run-import.md)을 마친다. 아래 경로·ID·사전 버전은 담당자가 준비한 실제 작업값을 사용한다.

## 생성·저장

저장소 루트, Python3.13에서 실행한다. source는 D03 문서1개·빈 evidence/events의 source-import-v1 파일이다. 제목·게시일·전체 블록·문서 버전·data_kind·전처리 버전이 D05 입력과 같아야 한다. source 파일의 전체 D03 규격·원문 파일은 Java import가 최종 검증한다.

```sh
python3.13 -m processing.extraction draft "$RUN_ID" \
  --root "$ARCHIVE_ROOT" \
  --source data/private/source.json \
  --output data/private/ai-draft.json \
  --area-id "$AREA_ID" \
  --split-group-id "$SPLIT_GROUP_ID" \
  --dictionary-version "$DICTIONARY_VERSION"
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=data/private/ai-draft.json \
  --myai.import.source-root="$SOURCE_ROOT" \
  --myai.import.actor="$ACTOR"
```

ARCHIVE_ROOT는 run_id 폴더의 상위 경로다. 처음 생성할 때 freeze로 별도 읽기 전용 보관본을 만들거나 기존 보관본을 재사용한다. D05 등록 경로·원본은 편집하지 않는다. 원래 archive가 없으면 DB의 raw_ref가 가리키는 보관본의 상위 디렉터리를 사용한다. 새 AI 출처를 저장할 때 Java가 보관본과 등록 행을 다시 대조한다.

출력 파일은 최대8MiB, UTF-8·LF, 새 파일0600·새 디렉터리0700이다. 저장소 안에서는 data/private 아래만 허용하고 외부 경로의 비공개 관리는 실행자가 담당한다. 기존 파일은 동일 바이트일 때만 재사용하며 다른 내용이면 보존하고 충돌로 종료한다. stdout은 run_id·사건ID·출력 SHA-256·review_required의 결과 JSON 한 건이며 본문·실제 경로는 출력하지 않는다.

성공은0, 잘못된 인자/원문 불일치/실패 실행/출력 초과는2, archive 손상·파일 충돌은3, 파일 I/O 실패는5, 내부 오류는1이다. Python 성공은 DB 저장 성공을 뜻하지 않는다. D05는 별도로 등록되어 있어야 한다.

## 초안에 보존하는 것

Java는 저장 전 Python의 동일 변환 함수로 초안 전체를 재구성해 대조한다. 사건 수뿐 아니라 값·근거·연결·ID가 일치해야 하므로 사건이 있는 출력을 빈 배치로 바꾸거나 raw 의미값을 편집해 넣을 수 없다. JSON 공백·키 순서는 대조에서 무시하되 import 배치의 원본 바이트 hash 규칙은 유지한다. 추가 Python 검증은 DB 트랜잭션 밖에서 실행하며 stdin도8MiB로 제한하고 stdout에는 상태·ID·입력 hash만 반환한다.

- 새 로컬 규격은 ai-draft-import-v1, DB source_kind와 origin은 ai_draft다. 기존 envelope에 originating_run_id를 추가하고 D04/D06 구조를 재사용하되 상태는 draft/hidden, 검토자·시각은 null, human_overrides는 비어 있다.
- 제목 미상은 null, 유형 미상은 빈 배열이다. 이 예외는 미검토 초안에만 허용하며 일반 reviewed-import-v1에는 적용하지 않는다.
- 원문·data_kind·FieldValue·인용·code point 위치를 보존한다. 블록 hash를 먼저 검증한 뒤 D06 근거에는 문서 전체 cleaned_text hash를 넣는다. AI의 로컬 ID는 run UUID와 종류별 로컬 ID의 UUID5로 변환한다.
- 예외·노선·정류장·방향의 중복 문자열도 초안에 그대로 보존한다. 일반 reviewed 목록은 중복을 허용하지 않으므로 사람 검토 시 정리하고 수정 이유를 기록한다. ID·근거 참조의 유일성은 초안에서도 검사한다.
- 장소 좌표·검토자·확인 시각은 null, coverage는 unknown, 지역 소속은 uncertain이다. 장소 대응이 없으면 독립 unknown 장소에 연결한다. 서로 다른 날짜와 장소를 임의로 묶지 않는다.
- 명확한 시간/종일/날짜만 precision으로 정규화한다. 반복 문구·모호한 반복·부분/모순 시간은 unknown으로 남기며 시간 값을 버리지 않는다. normalization_note에 원래 시간 FieldValue JSON을 보존한다. 여기에 있는 근거 ID는 원래 D05의 로컬 ID다.
- lifecycle 미상은 uncertain이다. title/types/lifecycle/location.kind의 원래 knowledge·사유와 warnings 등 전체 원출력은 D05에서 함께 확인한다.
- NO_EVENT_FOUND이면 사건을 만들지 않고 빈 사건 배치를 저장한다. 이때도 originating_run_id의 성공 D05·원문을 재검증하며 DB 배치 결과 참조에 실행 ID를 남긴다. 같은 실행·원문·설정의 재실행은 같은 파일·ID를 만든다. 다른 AI 실행은 다른 초안 사건ID를 만들므로 사건 통합·중복/정정 관계는 사람이 검토한다.

원본은 별도 보존한다. 보관본에는 POSIX 권한·hard link·원자 rename과 추가 저장 공간이 필요하다. 관리자 삭제·경로 교체·권한 변경을 막는 WORM 보장은 아니므로 경로·권한·백업을 관리한다.

## 사람 검토본으로 넘기기

초안과 D05 원출력, 원문을 함께 대조한다. 초안을 복사해 별도 파일에서 수정하고 AI 원본과 최초 draft revision을 덮어쓰지 않는다.

1. schema_version을 reviewed-import-v1, origin을 ai_reviewed로 바꾸고 최상위 originating_run_id를 제거한다. revision 안의 originating_run_ids와 event_id는 유지한다.
2. expected_revision_no를 현재 번호로, revision_no를 다음 번호로 설정하고 새 revision_id를 발급한다. 최초 초안이면 각각1/2다.
3. 제목·유형·날짜·시간·반복·장소 대응·지역 소속을 확인한다. 좌표를 넣으면 기존 D06의 geometry·coverage·출처·확인자/시각을 채운다. 불명확한 값을 확정하지 않는다.
4. 수정한 의미값은 human_overrides에 field_path·before·after·이유·근거·검토자·시각을 기록한다. reviewer_id와 reviewed_at을 채우고, 기존 source_version_ids와 originating_run_ids를 보존한다.
5. review_status=draft 또는 needs_review, publication_intent=hidden으로 local-import한다. 원본 실행·문서 참조를 잃거나 검토자/시각이 없는 승격은 거부한다.
6. 교차 검토 후 [별도 approve·preview·publish](review-publication.md)를 사용한다. AI 초안은 직접 approve할 수 없고 일반 승인에는 근거1개 이상이 필요하다.

ai_reviewed로 넘긴 뒤의 후속 수정도 기존 originating_run_ids와 source_version_ids를 유지해야 한다. origin을 human으로 바꿔 AI 추적을 지우는 입력은 거부한다. 새 원문·실행을 추가할 수 있지만 기존 참조를 버리지 않으며, 이후 검증에 필요한 예전 실행 보관본도 함께 보존한다.

## 변경 기록 대조

AI 출처가 있는 기존 사건을 수정할 때는 이전 revision과 바뀐 의미값을 대조한다. 날짜는 Python과 같은1~9999년을 사용하고 공백만 있는 값은 허용하지 않는다. 실제 문자의 앞뒤 공백은 자르지 않는다. 달라진 필드마다 before/after가 실제 전후 값과 같고 reviewer/time이 이번 revision의 reviewer_id/reviewed_at과 같은 기록이 있어야 한다. 수정 이유·근거의 의미는 사람이 확인한다.

- 제목·유형·시간·장소·대상/예외·노선/정류장/방향·lifecycle·근거·문서/실행 참조·규칙/사전 버전을 대조한다. 지역·문서 연결·관계·중복·분할 그룹 변경은 event.area_membership 등 event. 접두사를 쓴다.
- FieldValue 전체는 applicability처럼, 하위 값만 바꾸면 directions.value처럼 점으로 경로를 쓴다. knowledge·reason·evidence_ids도 달라졌으면 각 변경을 기록하거나 FieldValue 전체를 before/after에 넣는다.
- 배열은 위치 이동에 따른 잘못된 대응을 피하려고 전체 배열로 대조한다. 장소 내부를 바꿔도 field_path=locations, before/after=변경 전후 전체 locations다. 근거 인용문·위치·hash·ID를 바꾸면 field_path=evidence로 최상위 evidence 배열 전체를 기록한다. 근거 ID를 유지해도 내용 변경은 기록해야 한다. occurrences·types·참조 배열도 같다.
- revision ID/번호·검토 상태·검토자/시각·origin 등 작업 상태만 바뀌면 의미값 수정 기록은 요구하지 않는다. 이전 수정 기록을 그대로 남겨 둘 수 있다. 새로 넣는 기록은 실제 전후 값이 달라야 하고 그 값과 일치해야 하며, 바뀌지 않은 필드에 허위 수정 기록을 덧붙이는 입력은 거부한다.

다음은 중복 방향 목록을 사람이 정리한 기록의 형식이다. 실제 값·검토자·시각·현재 파일의 근거 ID로 바꾼다.

```json
{
  "field_path": "directions.value",
  "before": ["상행", "상행"],
  "after": ["상행"],
  "reason": "원문 대조 후 중복 항목 정리",
  "evidence_ids": ["현재 파일의 근거 ID"],
  "reviewer": "reviewer-id",
  "time": "2026-11-02T02:00:00Z"
}
```

사람이 검토를 완료했다고 파일에 기입하는 로컬 작업이며 계정 인증을 대신하지 않는다. 사람이 실제로 원문을 확인했는지는 기계가 판정하지 않는다.

반려는 새 rejected/hidden revision을 남긴다. ai_draft의 반려만 evidence_ids=[]를 허용하여 존재하지 않는 인용을 만들지 않게 한다. 일반 검토본의 반려와 모든 승인에는 근거가 필요하다. 반려에는 원본 디렉터리가 필요하지 않으며 기존 초안·AI 원본을 삭제하지 않는다.

실제 추출·D05 등록 현황은 [Python 실행 기록](../../processing/README.md)을 따른다. 실자료 D06 저장·사람 검토·평가·운영 배포는 후속 작업이다. 합성 시험의 성공을 실제 처리·사람 검토 실적으로 집계하지 않는다.

## 동결 사람 수정 원본의 인계 준비

[human-handoff-v1](../../contracts/human-handoff.md)은 수정된 extract-schema 값과 원래 D05를 검증하고 workflow 없는 D06 사실 투영을 별도0400/0500 이미지에 보존한다. status=projection_only·backend_import_supported=false이며 현재 local-import는 투영 schema를 거부한다. raw를 가짜 성공 D05로 재등록하거나 origin=human으로 출처를 지우지 않는다. 별도 [Java 인계 요청](human-handoff-import.md)이 실제 원문 파일·등록 D03/D05/사람 원본 hash·명시 revision/실제 DB 변경 기록·승인/공개 재검증을 연결한다. Python 투영 성공만으로 DB 저장 완료를 표시하지 않는다.
