# 사람 수정본의 Java D06 저장 연결

## 목적·범위

동결한 human-handoff-archive-v1을 실제 비공개 D06 revision에 저장하고 이후 수정·승인·미리보기·공개에서 같은 출처를 재검증한다. 기존 TASK의 사람 수정본 전달을 끝내기 위한 연결이다. Python 사실 투영만으로 DB 전달 완료를 주장하지 않는다.

사용자가 승인한 Java/Python 단계별 개발·리뷰와 병렬 에이전트 실행을 따른다. 아래 형식·저장 방법은 AI의 구현 판단이며 사용자가 개별 스키마를 지정한 것은 아니다. 기존 checkout의 새 기능 브랜치에서 진행하고 사용자 .gitignore 변경은 보존한다.

Java21·Spring Boot3.5.16·Gradle8.14.3·MySQL8.4.13·Python3.13 표준 라이브러리를 유지한다. 새 의존성·Flutter/UI·AI 호출·키 읽기·기존 서비스/DB 변경·main 병합·운영 배포는 이번 코드 범위에 넣지 않는다. 실제 자료·독립 gold/40건·사람 신원/사실성 평가는 전체 목표에 그대로 남는다.

## 입력과 저장

기존 local-import에서 schema_version=human-handoff-import-v1을 선택한다. 입력은 handoff_ref·receipt_sha256·reason·revisions를 포함하고 다른 키는 거부한다. revisions는 투영 사건 각각의 event_id·새 revision_id·expected_revision_no를 정확히 한 번 지정한다. 현재 번호를 자동 채우거나 목록 순서로 대응하지 않는다. 빈 투영에는 빈 배열을 사용한다. myai.import.handoff-root와 source-root는 명시한 절대 경로다.

Python verify-handoff로 전체 이미지를 재검증하고 Java는 반환 receipt와 디스크 receipt/projection/review의 바이트·hash·ID·형식을 대조한다. 원래 source 경로 없이 보관본을 검사하되 실제 DB D05의 raw_ref는 기존 등록 경로를 유지한다. 중첩 복사본으로 원래 D05 부재를 우회하지 않는다.

private payload의 human_handoffs 배열은 directory·handoff_ref·receipt_sha256의 정확한 참조를 보존한다. 이전 배열은 순서/내용 그대로 유지하고 새 참조만 덧붙인다. 빈 사건도 import_batches.result_refs_json에 전체 참조와 source run을 기록한다. 새 테이블 없이 기존 불변 JSON·배치 트랜잭션을 재사용한다. 일반 reviewed-import-v1은 기존 사건의 참조를 전달·보존할 수 있지만 참조가 있는 새 사건을 만들 수 없다.

투영의 사실을 임의 보완하지 않는다. 새 D06은 ai_reviewed·needs_review·hidden이다. D06 reviewer/time은 CLI 담당자와 실제 인계 실행 시각(MICROS)이며 원래 추출 검토자의 판독/승인 시각이 아니다. 원래 검토자·나노초 시각·knowledge·사유·warnings·실제 extract 변경은 전체 이미지에 손실 없이 남는다.

## 이전 revision·감사 기록

새 사건 또는 아직 보정하지 않은 raw AI 초안, 이전 인계 투영과 사실이 같은 비공개 needs_review 사건만 전용 adapter로 받는다. 기존 사람이 보정한 좌표/구역/사실, 승인·반려 상태와 충돌하면 IMPORT_CONFLICT로 보존한다. 필요한 수정은 일반 reviewed-import에서 실제 이전/다음 값을 명시한다. 묵시적 병합·좌표 재추정은 하지 않는다.

실제 DB 이전 payload와 다음 payload를 비교해 D06 필드 단위 before/after를 기록한다. 배열은 전체를 비교하고 과거 human_overrides를 그대로 보존한다. extract의 output.* 변경 경로를 D06 감사 기록으로 복사하지 않는다. 명시 expected revision과 repository CAS가 읽기 이후 경합을 차단한다.

미상·중복·부분 시간·근거0은 검증한 출처를 가진 비공개 저장에서 보존한다. 새 빈근거 감사 기록은 전용 adapter가 실제 DB 차이로 생성한 경우만 허용한다. 일반 수동 수정은 기존 빈근거 기록만 그대로 보존할 수 있다. 새 기록의 인용은 실제 이전/다음 근거에 속해야 하고, 과거 인용은 이미 검증한 정확한 역사 기록으로 보존한다. 과거 근거가 현재 배열에서 빠져도 evidence 전체 before/after를 잃지 않는다.

빈 사건 인계는 기존 사건을 삭제·반려하지 않고 가짜 사건도 만들지 않는다. 필요하면 별도 명시 반려를 사용한다.

## 출처와 트랜잭션

모든 handoff 참조를 매번 검사하고 사건별 event_id·부모 run·문서 연결을 확인한다. run ID 캐시를 재사용하기 전에 사건별 권한을 확인하여 다른 사건의 증거를 재사용하지 못하게 한다.

기존 validated-only D05 경로는 유지한다. 검증한 handoff 타입을 받는 별도 경로에서만 failed 부모를 허용하며 실제 status/mode/receipt와 기존 등록 행 전체를 대조한다. 실패를 validated로 바꾸지 않는다.

등록 D03의 전체 metadata·cleaned_text/hash·private_ref를 투영 source와 대조한다. source-root에서 원문 asset/hash·이용권한 필드도 기존 reader로 검증한다. Python/파일 읽기는 DB 트랜잭션 밖에서 수행한다. 쓰기·배치 재사용·중복 복구 모두 FOR SHARE로 D03/D05 전체 행 fingerprint를 다시 대조한다.

후속 수동 수정·approve·preview·publish는 private 참조를 보존하고 같은 검증을 수행한다. 승인 시 사실 검증은 기존 strict 규칙을 유지하며 partial 완화를 적용하지 않는다. 반려·이미 공개한 불변 snapshot 복구의 기존 원본 부재 허용은 유지한다. 공개 API/snapshot/export에 실제 경로·사람 검토 선언·원출력을 넣지 않는다.

## 완료 조건

성공/실패/수동 부모·미상/중복/부분 시간/빈 사건, 실제 CLI·재사용/동시 충돌/늦은 실패 rollback, 원본/DB 행 변조·경로/권한/누락, 과거 audit/proof·인용 보존과 보호된 좌표 충돌을 검증한다. 승인 전후 재검증·보완 후 공개·원본 부재 반려/불변 복구·공개 비노출을 확인한다.

격리 MySQL8.4.13과 실제 Java21/Python3.13/JAR로 실행하고 Python 전체·Java 전체·Node·계약·lint/build를 통과시킨다. 자체 전체 리뷰→별도 전체 리뷰→모든 유효 지적 수정→정확한 head CI/자동/도착한 사람 리뷰를 확인한다. main은 사람이 병합한다.
