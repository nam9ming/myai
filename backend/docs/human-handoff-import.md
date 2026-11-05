# 사람 수정본의 D06 저장

동결한 [인계 이미지](../../contracts/human-handoff.md)를 읽어 실제 비공개 D06 revision에 저장한다. 투영 JSON을 직접 import하지 않고 local-import의 human-handoff-import-v1 요청으로 선택한다. 원래 사람 검토/D05 이미지와 DB의 등록 D03·D05가 필요하다.

## 요청·실행

요청의 키는 schema_version·handoff_ref·receipt_sha256·reason·revisions 다섯 개다. handoff_ref는 인계 ID의 SHA-256, receipt_sha256은 선택한 이미지 receipt.json 원본 바이트의 SHA-256이다. revisions는 투영의 모든 사건에 대해 event_id·새 revision_id·expected_revision_no를 정확히 한 번 지정한다. 새 사건은0, 후속 수정은 실제 이전 번호를 명시한다. 빈 투영은 빈 배열로 기록한다.

예시는 형식 설명용 합성 값이다. 실제 ref/hash·사건·새 revision ID로 교체하고 최신 검토 상태를 확인한다.

```json
{
  "schema_version": "human-handoff-import-v1",
  "handoff_ref": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "receipt_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "reason": "원문과 수정 원본을 대조한 D06 인계",
  "revisions": [{
    "event_id": "00000000-0000-4000-8000-000000000001",
    "revision_id": "00000000-0000-4000-8000-000000000002",
    "expected_revision_no": 0
  }]
}
```

Java21·MySQL·Python3.13과 동일 processing 소스를 준비한다. 설정은 [README](../README.md)의 DB/Python 연결을 따른다. source-root에는 실제 원문 asset 파일을 두고 handoff-root에는 동결 ref 디렉터리들을 둔다. 보관 root는 symlink가 없는 정규화한 실제 절대 경로를 사용한다.

```sh
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=data/private/handoff-import.json \
  --myai.import.source-root=/absolute/private/sources \
  --myai.import.handoff-root=/absolute/private/handoffs \
  --myai.import.actor=review-operator
```

stdout은 기존 import 결과 JSON 한 건이다. 같은 요청 바이트와 보관 경로는 같은 배치/revision을 반환한다. 입력·원본/실행 검증 실패2, revision·경합 충돌3, DB 미준비4, 내부 오류1이며 원문·검토자·실제 경로를 오류에 넣지 않는다. 다른 로컬 명령·웹 시작과 혼합하지 않는다.

## 상태·기존 수정 보호

새 revision은 ai_reviewed·needs_review·hidden이다. reviewer_id/reviewed_at은 인계 작업을 실행한 담당자와 서버 시각(MICROS)이다. 원래 사람이 현재 DB의 좌표를 검토했거나 공개를 승인했다는 뜻이 아니다. 원래 검토자·나노초 시각·추출 변경/사유·knowledge·warnings는 전체 이미지에 그대로 남는다.

기존 raw 초안 또는 이전 인계 사실과 같은 비공개 needs_review만 전용 adapter로 갱신한다. 사람이 보정한 좌표/구역/사실, 승인·반려 상태는 충돌로 보존한다. 필요한 병합은 [일반 검토 import](reviewed-import.md)에서 실제 변경을 명시한다. 현재 번호를 자동 채우거나 좌표를 추정하지 않는다. 빈 사건 인계는 기존 사건을 지우거나 반려하지 않는다.

실제 이전/다음 D06 차이는 필드·배열 전체 before/after로 기록한다. 이전 human_overrides와 human_handoffs는 순서/내용 그대로 보존한다. 새 빈근거 기록은 전용 adapter가 생성한 실제 차이에만 허용하며 일반 수정은 이미 있던 기록만 유지할 수 있다. 과거 인용이 현재 근거 배열에서 제거돼도 역사 기록은 남는다.

## 원본·승인·공개

Python이 전체 인계 이미지와 내부 사람/D05 원본을 재검증한다. Java는 receipt·projection·부모 hash와 실제 DB 등록 행, 전체 D03 metadata·본문/hash·원문 asset을 대조한다. failed 부모는 검증한 인계와 해당 사건 연결이 있을 때만 허용하고 원래 상태를 바꾸지 않는다. D05는 기존 raw_ref에서 재검증하며 중첩 복사본으로 원래 경로 부재를 대체하지 않는다.

Python/파일 검증 후 쓰기·재사용·중복 복구 모두 트랜잭션에서 D03/D05 행 fingerprint를 다시 대조한다. 후속 수정·승인·미리보기·공개도 private human_handoffs 참조를 보존해야 한다. 일반 입력에서는 최상위 human_handoffs 배열을 기존 payload 값 그대로 전달한다. 각 원소는 directory·handoff_ref·receipt_sha256만 포함한다.

미상·중복·부분 시간은 비공개로 보존하며 승인 때는 기존 strict 사실 검증을 통과해야 한다. 빈근거 사건도 원본 없이 명시 반려할 수 있다. 이미 공개한 불변 snapshot의 복구는 기존 원본 부재 허용을 유지한다. 공개 snapshot/API/export에는 인계 경로·검토 선언·원출력을 넣지 않는다.

합성 시험과 실제 자료 인계 실적은 구분한다. stable 경로·POSIX 권한·원본 백업이 필요하며 관리자 전체 교체·WORM·Windows·전원 중단 내구성을 보증하지 않는다. 이 명령은 실제 사람 신원·사실성·금표/성능·운영 배포를 인증하지 않는다.
