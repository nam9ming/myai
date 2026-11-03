# D08 입력·D05 연결 검사 v1

동결 [manifest](dataset-manifest.md)의 입력 hash를 실제 `ai-input-v1` 바이트·[D05 보관본](extraction-run.md)에 대조하는 **비공개 읽기 전용 계약**이다. 원문을 수정하거나 AI·키·네트워크·DB·freeze를 호출하지 않는다.

## 연결 명세

UTF-8 JSON 한 건, 최대8MiB·깊이100. 중복 키·잘못된 Unicode·추가 키를 거부한다. 모든 키가 필수다.

| 객체 | 키 |
|---|---|
| 최상위 | `schema_version="dataset-bindings-v1"`, `dataset_ref`, `manifest_sha256`, `bindings` |
| bindings[] | `document_version_id`, `input_path`, `runs` |
| runs[] | `run_id`, `snapshot_ref`, `receipt_sha256` |

ID는 소문자 UUID, hash는 소문자 SHA-256이다. dataset_ref·manifest_sha256은 `processing.evaluation freeze`의 결과와 같아야 한다. manifest의 **모든 문서 버전**을 정확히 한 번 연결하고 버전마다 한 개 이상 실행을 명시한다. run_id는 전체 명세에서 중복될 수 없다. 성공 실행을 자동 선택하지 않으며 실패 실행도 선택·검증할 수 있다.

input_path는 현재 작업 경로 기준 상대 경로 또는 절대 경로다. 저장소 안에서는 `data/private/` 아래 파일만 허용하고, 외부 작업 디렉터리도 기존 private-root 규칙을 따른다. 빈 값·NUL·파일 symlink를 거부한다. 입력 JSON의 버전ID·data_kind와 원본 **바이트** SHA가 manifest 및 각 실행의 입력 전체와 같아야 한다. 공백·개행만 달라도 다른 입력이다.

snapshot_ref는 extraction `freeze` 결과의 `RUN_ID` 또는 `registered/RECEIPT_SHA/RUN_ID`만 허용한다. run-root를 기준으로 해석하며 `..`·절대 경로·등록 하위 symlink·다른 run_id를 거부한다. receipt_sha256은 고정된 `receipt.json` **원본 바이트** SHA다. registered 경로의 hash도 같아야 한다.

모든 실행을 기존 `verify_run`으로 오프라인 재검증한다. 실패 원출력·최대3시도의 요청/응답을 포함한 전체 artifact hash를 확인하고 파일0400·실행 디렉터리0500·정확한 파일 목록을 요구한다. 변경 가능 원본을 입력하면 검사기가 freeze/chmod로 고치지 않고 거부한다. 준비 단계에서 별도로 `processing.extraction freeze RUN_ID --root ROOT`를 수행한다.

## 실행·출력

```sh
python3.13 -m processing.evaluation check-bindings \
  --input data/private/evaluation/bindings.json \
  --dataset-root data/private/evaluation/datasets \
  --run-root data/private/extraction-runs
```

연결 항목의 형태는 아래와 같다. 자리표시자는 실제 freeze 결과·입력 경로로 바꾼다.

```json
{
  "document_version_id": "e9dc7495-7186-5318-a054-4fc54e9b78cc",
  "input_path": "data/private/evaluation/input.json",
  "runs": [{"run_id": "71fb66f0-e610-4f9c-8f26-4bb77655ee8c", "snapshot_ref": "registered/<receipt_sha256>/<run_id>", "receipt_sha256": "<receipt_sha256>"}]
}
```

stdout은 `dataset-bindings-check-v1` JSON 한 건이다. 연결 명세 원본의 bindings_sha256, 고정 manifest hash, data_kind, 문서/버전/실행/성공/실패 수, holdout 선언·경고를 반환한다. runs에는 ID·receipt hash·실행 방식·시도 수·첫/최종 상태만 넣고 경로·본문·프롬프트·메타데이터 전문은 출력하지 않는다. 복수 버전/실행을 새 문서로 세지 않는다. stderr는 고정 코드, 성공0·명세/참조/동결 조건 오류2·기존 보관본 손상3·파일 I/O5·내부 오류1이다.

이 명령은 연결 명세를 저장/잠그거나 점수를 계산하지 않는다. 후속 불변 평가 기록은 이 명세의 원본 바이트/hash와 금표·판정 지침·선택한 실행을 함께 고정해야 한다. 실제3문서의 v1 실패/v2 성공6실행 연결은 개발용 provenance 확인이며 재시도 정책·사실성·비노출·독립 정답·8필드 정확도·initial/retest 평가를 증명하지 않는다. 사람 검토·공개 승인은 별도다.
