# 사람 수정후 추출 원본 v1

동일 문서의 AI 자동값과 사람 수정값을 구분해 보관하는 비공개 계약이다. 기존 `extract-schema-v1`의 FieldValue·근거 검증과 frozen D05 전체 원본을 재사용한다. D06의 일부 필드는 개별 knowledge를 평탄화하므로 D06만 보고 추출값을 역변환하지 않는다. 사람 수정값을 독립 gold나 AI 자동 성능으로 표시하지 않는다.

## 입력

UTF-8 JSON의 최상위 키는 다음6개다. 전체8MiB·깊이100 한도를 적용하며 중복 키·추가 키·잘못된 Unicode는 거부한다.

| 키 | 내용 |
|---|---|
| schema_version | `human-review-v1` |
| review_id | 새 UUID. 수정 검토마다 별도 ID를 사용한다. |
| source | `run_id`, `snapshot_ref`, `receipt_sha256` |
| review | `reviewed_by`, `started_at`, `finished_at`, `basis`, `note` |
| output | 동일 원본 입력에 대해 검증되는 수정후 `extract-schema-v1` 출력 전체 |
| changes | 아래 형식의 실제 전후 변경 기록 배열 |

source는 D05의 UUID 또는 `registered/HASH/UUID` 참조다. 정확한 canonical receipt SHA·등록 경로의 HASH·실제 파일/권한을 대조하며 API/수동 D05의 성공/실패 원본을 모두 보존한다. 규칙 원본을 D05로 취급하지 않는다. 원본 데이터 구분(real/synthetic)과 모델·실행 모드·실패 상태는 변경하지 않는다.

검토 시각은 UTC `...Z`, 소수점 최대9자리다. 원본 기록 시각과 알려진 실행 종료 ≤ 검토 시작 ≤ 종료 ≤ 검사/보관 시각이어야 한다. `basis`는 `source_only`, `gold_feedback`, `unknown` 중 실제 상황을 선언하고 note에 설명한다. 원문만 봤다는 선언도 비노출·독립성을 인증하지 않는다. 검토자/시각을 자동 생성하지 않으며, 선언한 소요시간은 나노초 정수로 계산한다. 같은 시각의 검토는0이다.

## 변경 기록

각 changes 항목은 `field_path`, `before`, `after`, `reason`, `evidence_ids`, `reviewer`, `time`이다. 예를 들어 `field_path="output.items"`이면 before/after에 실제 이전/새 items 배열 전체를 넣는다. 전체 출력은 `output`, 근거/경고 배열은 `output.evidence`/`output.warnings`를 사용한다. 배열 인덱스나 local ID를 자동 대응하지 않는다.

- 실제 전후 값·JSON 타입·검토자·종료 시각이 기록과 같아야 한다. `false`와0을 같은 값으로 보지 않는다.
- reason은 비어 있을 수 없고 evidence_ids는 이전/새 유효 출력의 근거 ID만 참조한다. 의미를 뒷받침하는지는 사람이 확인한다.
- 바뀐 부분이 모두 기록되어야 한다. 누락·허위·무변경·중복·서로 겹치는 경로는 거부한다. `output` 전체를 기록했다면 하위 변경을 중복 기록하지 않는다.
- 정상 AI 값을 그대로 검토했다면 `changes=[]`다. 실패한 D05에는 유효한 이전 출력이 없으므로 `field_path="output"`, `before=null`, `after=새 출력 전체`의 기록이 필요하다. 실패 원출력은 원래 파일로 보존한다.
- 잘못 추출한 사건을 모두 제거할 수도 있다. 이때 수정후 출력의 `items=[]`·`warnings`의 `NO_EVENT_FOUND`와 전후 변경 기록이 필요하다.

## 명령·보관

사람이 별도로 작성한 비공개 review.json을 준비한다. 값/근거는 원문과 대조하고 source 참조는 기존 D05 freeze 결과를 사용한다. 다음 명령은 저장소 루트에서 실행한다.

```sh
python3.13 -m processing.evaluation check-review \
  --input data/private/review.json --run-root data/private/extraction-runs
python3.13 -m processing.evaluation freeze-review \
  --input data/private/review.json --run-root data/private/extraction-runs
python3.13 -m processing.evaluation verify-review "$REVIEW_REF"
```

`REVIEW_REF`는 freeze가 반환한 review_ref다. review_id UTF-8의 SHA-256이며 기본 보관 위치는 `data/private/evaluation/human-reviews/REVIEW_REF`다. freeze/verify의 `--root`로 변경할 수 있다. 묶음은 원본 review.json·canonical output.json·`source/SNAPSHOT_REF/`의 D05 전체·identity.json·receipt.json이다. 파일0400·디렉터리0500, 정확한 hash 확인 복사·배타 설치를 사용한다. 원래 경로 없이 재검증·동일 입력 재사용이 가능하며 같은 ID의 다른 바이트·손상/부분 목적지는 덮어쓰지 않는다.

stdout은 ID/hash/data_kind·상태·건수·선언 소요시간 요약 또는 receipt JSON 한 건이다. 실제 수정값·검토자·검토 시각·이유·절대 경로는 비공개 파일에만 둔다. 성공0, 입력 오류2, 보관 손상/충돌3, I/O5, 내부 오류1이다. 오류 시 stdout은 비어 있고 stderr에는 고정 코드만 쓴다. 키·AI·네트워크·DB 호출과 새 의존성은 없다.

## 현재 범위

`declared_reviewed`/`human_verification=declared_only`는 제공된 선언·참조·형식을 검사했다는 뜻이다. 실제 사람 판독·신원·독립 gold·승인·공개를 인증하지 않는다. 검토 원본 보관은 D06 DB 저장과 별개이며 [D08 평가](extraction-evaluation.md)는 human_reviewed 뷰·최초/재시험·전체 출처 동결과 선언 소요시간을 연결한다. 세 방법의 짝지은 개선/악화·선별 비교와 D06 인계는 후속 작업이다. 실제40문서 평가·blind holdout도 미완료다. POSIX 권한은 WORM이 아니며 Windows·전원 중단 내구성은 미검증이다.
