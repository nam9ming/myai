# 시민 사람 수정본의 D06 인계

[시민 추출](citizen-extraction.md)의 봉인된 [사람 수정본](human-review.md)을 숨김 검토 revision으로 전달하는 작성자 기술 계약이다. 실제 팀원·Flutter 최종 합의나 자료 품질·사람 승인을 뜻하지 않는다. 구현·검증·원격 반영 상태는 [G5 계획](../docs/superpowers/plans/2026-11-18-citizen-human-handoff.md)을 따른다.

## 명시하는 버전과 입력

| 단계 | 시민 버전 | 기존3유형 버전 |
| --- | --- | --- |
| 부모 출력·metadata | `extract-citizen-v1` | `extract-schema-v1` |
| 인계 선택 | `citizen-human-handoff-v1` | `human-handoff-v1` |
| 사실 투영 | `citizen-human-handoff-projection-v1` | `human-handoff-projection-v1` |
| Java 저장 요청 | `citizen-human-handoff-import-v1` | `human-handoff-import-v1` |

선택 JSON은 `schema_version/handoff_id/review_ref/review_receipt_sha256/source/split_group_id`6키만 받는다. ID는 명시 UUID, ref와 receipt hash는 선택한 실제 봉인본의 SHA-256이다. `source`에는 문서1개·빈 evidence/events의 `source-import-v1`을 넣는다. 시민 context는 `split_group_id`만 담으며 구역·지점·사전 버전을 요구하거나 대신 생성하지 않는다. group은 D06 관계 선언이며 D08 개발/확인 자료 배정이 아니다. 실제 group 미정이면 임의 ID로 실자료를 저장하지 않는다.

검증한 부모 metadata로 family를 선택하고 review 출력·부모 receipt·문서/전처리·본문/hash와 대조한다. 새 시민 부모는 `manual_import/extraction-archive-v1`만 허용한다. 기존 요청에 새 출력을 섞거나 출력의 자기 선언으로 검증기를 바꾸지 않는다.

## 보존하는 사실과 원본

`title/categories`는 known·유효한 값·근거가 필요하다. 미해결이면 `HANDOFF_CITIZEN_FACTS_UNRESOLVED`로 전체 인계를 거부하며 항목을 버리거나 제목·분류를 채우지 않는다.12개 사실은 value/knowledge/reason·문자열/배열/명시 빈 배열·순서를 그대로 두고 evidence ID만 결정적 UUID5로 연결한다.

신청 기간과 진행 일정, 적용 지역과 장소·거주 조건, 안내 대상과 자격, 비용 미상과 무료를 구별한다. 날짜·금액·모집/취소 상태·관계를 추론하지 않는다. facts에는 원문 버전과 실제 run 참조를 남기며 legacy 정규화·규칙/사전·500m/14일 계산을 적용하지 않는다.

전체 review·출력·선택·부모 D05·실패 bytes·실제 prompt/metadata 라벨을 [기존 인계 이미지](human-handoff.md)에 보존한다. title/categories의 원래 FieldValue·warnings·블록 hash는 전체 원본에서 확인한다. 실패 부모를 수정해 인계해도 D05는 failed로 남는다. 원문 asset은 별도 source-root에 필요하다.

## 준비·동결·재검증

기존 명령과 root를 재사용한다. 경로·ID는 실제 보관 결과로 바꾼다.

```sh
python3.13 -B -m processing.evaluation check-handoff \
  --input data/private/citizen-handoff.json --review-root /absolute/reviews
python3.13 -B -m processing.evaluation freeze-handoff \
  --input data/private/citizen-handoff.json --review-root /absolute/reviews \
  --root /absolute/handoffs
python3.13 -B -m processing.evaluation verify-handoff HANDOFF_REF \
  --root /absolute/handoffs
```

wrapper는 `human-handoff-archive-v1`, summary는 `projection_only/backend_import_supported=false/review_required=true`다. 투영 JSON 자체는 일반 import 입력이 아니다. 파일0400·디렉터리0500·정확한 파일 집합과 hash를 검사하고 원래 review/run 경로 없이 전체 이미지로 재검증한다. 같은 ID/입력은 재사용, 다른 입력·family는 충돌이다. 손상·추가 파일·잘못된 권한을 자동 복구하지 않는다.8MiB JSON·실패 전체 보존·종료코드는 기존 계약과 같다.

## Java 저장과 후속 검토

Java 요청은 `schema_version/handoff_ref/receipt_sha256/reason/revisions`5키다. `revisions`의 각 항목에는 투영 event_id·새 revision_id·expected_revision_no를 한 번씩 명시한다. 새 사건은0, 후속은 실제 이전 번호, 빈 인계는 빈 배열이다. 기존 [local-import 명령](../backend/docs/human-handoff-import.md)과 로컬 POST reviews/import·PUT 사건 review를 사용한다. 일반 JSON에 신뢰 flag를 넣는 경로는 없다.

등록 D03·원문 asset·D05와 전체 인계 proof를 검사한 전용 경로만 최초 시민 AI proof를 도입한다. 결과는 `citizen-revision-v1`, `ai_reviewed/needs_review/hidden`이다. 인계 실행 담당자/서버 시각과 원래 review 선언은 구별한다. 일반 후속 수동 수정도 기존 run/source 참조와 proof·human_overrides의 순서/내용 prefix, 실제 변경 전후·근거·이유를 보존해야 한다.

명시 CAS·트랜잭션·등록 행 fingerprint/잠금으로 재실행·동시 충돌·늦은 감사 실패를 처리한다. 기존 수동 보정·승인/반려 revision을 전용 인계로 덮지 않는다. 원래 등록 D05 경로는 유지해야 하며 중첩 복사본만으로 등록 원본 부재를 대체하지 않는다.

S10은 성공/실패·전체 수정·빈 인계를 표시한다. 이후 [별도 시민 승인](../backend/docs/citizen-review.md)과 [공개/내보내기/복구](../backend/docs/citizen-publication.md)를 거친다. 승인 전 사용권·확인·원문/근거/proof를 다시 검사하고 공개 snapshot/API/export에는 인계 경로·run·검토자·비공개 전후 값을 넣지 않는다. 공개 조회 중 AI/Python을 호출하지 않는다.

실제 자료원·권리·검토 담당·평가·운영 조건은 [후속 확인 사항](../backend/docs/citizen-open-items.md)에 남긴다. 합성 검증은 실제 품질·사람 인수·운영 배포를 대신하지 않는다.
