# D08 독립 정답표·불변 보관 v1

[D08·평가 기준](../docs/spec/05_시험과인수기준.md)에 따른 비공개 로컬 계약이다. 원문에서 작성한 정답과 다른 담당자의 교차 검토를 기록한다. **검토자 신원·독립 판독·의미 정확성은 제공자의 선언이며 기계 인증이 아니다.** AI 원출력을 실제 정답으로 복사하지 않는다. 합성 시험은 실제 독립 정답 실적으로 집계하지 않는다.

## 정답 입력

UTF-8 JSON 한 건, 최대8MiB·깊이100·중복 키/잘못된 Unicode/추가 키 금지. 모든 키가 필수다.

| 객체 | 키 |
|---|---|
| 최상위 | `schema_version="dataset-gold-v1"`, `gold_version`, `dataset_ref`, `manifest_sha256`, `instructions`, `authorship`, `documents`, `adjudications` |
| instructions | `version`, `normalization_version="gold-exact-v1"`, `text`, `synonyms` |
| synonyms[] | `field`, `canonical`, `variants` |
| authorship | `author`, `reviewer`, `authored_at`, `reviewed_at`, `independent_source_reading`, `cross_reviewed`, `no_unresolved_disagreements` |
| documents[] | `document_version_id`, `input_path`, `output`, `anchors` |
| anchors[] | `slot_id`, `event_id`, `evidence_ids` |
| adjudications[] | `document_version_id`, `slot_id`, `field`, `disagreement`, `resolution`, `reason`, `evidence_ids`, `adjudicated_by`, `adjudicated_at` |

- gold_version·instructions.version은100자 이하 비공백·제어문자 없는 식별자다. dataset_ref/manifest_sha256은 동결 manifest의 값이며 모든 문서 버전을 정확히 한 번 제공한다.
- input_path는 실제 `ai-input-v1` 원본 파일이다. 기존 private-root 정책·파일 symlink/NUL 거부를 적용하며 버전ID·data_kind·원본 바이트 SHA를 manifest와 대조한다.
- output은 **사람이 작성하는** extract-schema-v1 구조다. 형식만 기존 FieldValue/occurrence/location 계약을 재사용한다. 원문 밖 추정·임의 좌표를 넣지 않는다. 미상/null과 명시된 빈 집합을 구별하며 원문 substring·code point·블록 hash를 검사한다.
- 각 item.local_item_id가 독립 사건 slot_id다. anchors는 모든 슬롯에 정확히 하나, 비어 있지 않은 출력 evidence 참조와 manifest의 해당 문서에 연결된 event_id를 갖는다. 한 버전에서 같은 event_id를 두 슬롯에 중복 배정하지 않는다. 빈 문서의 output.items/anchors는 모두 비우고 NO_EVENT_FOUND를 명시한다.
- author/reviewer는 각각128자 이하 식별자이며 NFC·앞뒤 공백·대소문자 정규화 후 달라야 한다. 독립 판독·교차 검토·미해결 의견 없음은 모두 true를 명시한다. authored_at≤reviewed_at, UTC RFC3339·소수초 최대9자리다.
- synonyms.field는 locations/applicability/exceptions 중 하나다. canonical과 비어 있지 않은 variants는 NFC·연속 공백 축약 기준으로 중복/다른 canonical 충돌이 없어야 한다. 공백·사전 승인 동의어 외 의미 추정 정규화는 없다. 판정 지침 전문·버전·승인 동의어를 함께 고정한다.
- adjudications.field는 date_start/date_end/time_start/time_end/locations/types/applicability/exceptions 중 하나다. 슬롯·근거 참조와 작성≤해결≤교차 검토 시각을 검사한다. 같은 버전/슬롯/필드의 최종 해결 기록은 하나다. 의견 차이/최종 판단/이유는 원문에 따라 사람이 작성하며, 텍스트 기록의 의미 일치까지 자동 판정하지 않는다.

## 보관·CLI

check-gold는 실제 파일과 동결 manifest를 읽기 전용 검사한다. freeze-gold는 정답 원본·manifest 원본·각 입력 원본을 별도 묶음에 고정한다. verify-gold는 원래 입력 경로·원래 dataset-root가 없어도 보관한 원본으로 재검증한다.

```sh
python3.13 -m processing.evaluation check-gold --input data/private/gold.json
python3.13 -m processing.evaluation freeze-gold --input data/private/gold.json
python3.13 -m processing.evaluation verify-gold GOLD_REF
```

기본 gold-root는 `data/private/evaluation/gold`; freeze/verify에 `--root`, check/freeze에 `--dataset-root`를 지정할 수 있다. gold_ref는 gold_version UTF-8의 SHA-256이며 같은 버전의 다른 바이트/원본을 덮어쓰지 않는다. 파일0400·디렉터리0500·전체 hash/파일 목록을 검사하고 완성·검증된 staging만 배타 배치한다. 검토/해결 시각은 고정 시각보다 미래일 수 없다. 같은 원본은 기존 frozen_at/receipt를 재사용한다.

stdout은 경로·원문·정답·담당자·판정 지침 없는 요약 JSON, stderr는 고정 코드다. 성공0, 입력2, archive 손상/충돌3, I/O5, 내부1. 키·AI·네트워크·DB를 호출하지 않는다. 기존 macOS/Linux 배타 rename·POSIX 권한 조건과 관리자 비신뢰/WORM 제외를 유지한다.

**이 단계에서 8필드 점수·실행 선택 동결·최초/재시험·규칙 기준선을 계산하지 않는다.** 후속 평가는 gold_ref/원본 hash/고정 시각과 선택한 실행을 함께 잠그고 최초 실행 이전 동결 여부를 대조해야 한다. 이미 실행한 실제 개발3건에 사후 정답을 붙여 독립 최초 성능이나 blind holdout으로 표시하지 않는다.
