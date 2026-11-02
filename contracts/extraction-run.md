# AI 추출 검증·수동 실행 기록

Python3.13 표준 라이브러리로 실행합니다. 현재 지원은 `manual_import`이며 실제 모델·네트워크·DB 호출은 없습니다. 계산 CLI와 공개 API도 호출하지 않습니다. 입력·원출력·프롬프트·메타데이터는 비공개 기록이며, 공개 snapshot으로 직접 전달하지 않습니다.

## 입력·검증

- 입력은 [ai-input-v1.json](schemas/ai-input-v1.json)의 정확한5키입니다. `data_kind`는 로컬 합성/실제 구분이며 모델 자료에는 넣지 않습니다. 제목·블록은 NFC·LF 전처리가 끝난 텍스트여야 합니다. 게시일 미상은 null이며 현재 시각으로 채우지 않습니다.
- 출력은 [extract-schema-v1.json](schemas/extract-schema-v1.json)을 따릅니다. 두 스키마는 `processing/extraction/schema.py`에서 생성하며 시험에서 일치를 확인합니다. JSON Schema의 구조 검사와 별도로 실제 날짜·문서 일치·문서 내 ID 유일성·근거 참조·경고·시간 순서를 Python이 검증합니다. wire 정수는 boolean·소수 표기를 허용하지 않습니다.
- 모든 의미 값은 `value/knowledge/evidence_ids/reason`을 유지합니다. 미상 값을 채우거나 offset을 자동 보정하지 않습니다. 근거의 `text_sha256`는 **해당 블록 UTF-8 hash**, 위치는 Python code point의 `[start,end)`입니다. D06의 문서 전체 `cleaned_text` hash와 대상이 다르므로 후속 변환에서 각각 검증해야 합니다.
- JSON 입력·메타데이터·검증용 출력은 각각8MiB·깊이100 이하입니다. 중복 키·비정상 UTF-8/Unicode·비유한 수를 거부합니다. 과다 원출력도 파일 전체를 stream 복사해 보존하고 검증 실패로 기록합니다.
- `validated`는 기계 검증 통과입니다. 인용이 의미값을 뒷받침하는지, 종일/예외/취소 판단이 옳은지, 이용권한이 있는지는 사람이 확인합니다. 성공·실패 모두 `review_required=true`입니다.

## 실행

저장소 루트에서 실행합니다. 예제는 모두 합성이며 실제 도구 실행 실적이 아닙니다.

```sh
python3.13 -m processing.extraction prepare \
  --input contracts/examples/ai-input.json
```

기본 위치 `data/private/extraction-runs/prepared/<input_sha256>/`에 입력 원본과 `prompt.json`을 생성합니다. 고정 `prompt-v1`은 지시·전체 스키마·문서/블록/hash 제약·원문4키만 포함합니다. 현재 날짜·사용자 영업조건·정답표는 생성하지 않습니다. 수동 도구에 실제로 제공한 프롬프트 전문을 별도 파일로 보관합니다. 도구 입력 한도·개인정보 제거는 사용 전에 확인합니다.

[메타데이터 예제](../processing/examples/extraction-metadata.json)를 복사해 새 `run_id` UUID, 문서 버전, 실제 도구 표시값·버전·전처리/프롬프트 버전을 기록합니다. 알 수 없는 provider/model_label/model_version은 null과 `unavailable_reasons`를 사용합니다. 실제 시작/종료 시각·사용량·비용·통화를 모르면 null로 유지합니다. 비용은 추정하지 않으며 원본 JSON의 소수 정밀도를 보존합니다. `recorded_at`은 로컬 보관 시각으로 실제 모델 시각과 구분합니다. 예제의 고정 run_id를 실제 실행에 재사용하지 않습니다.

```sh
python3.13 -m processing.extraction import \
  --input data/private/input.json \
  --metadata data/private/metadata.json \
  --attempt data/private/actual-prompt.txt data/private/raw-output.txt
python3.13 -m processing.extraction verify 71fb66f0-e610-4f9c-8f26-4bb77655ee8c
```

`--attempt PROMPT OUTPUT`은 실제 시도 순서대로1~3회 지정하며 metadata.attempts와 같아야 합니다. 명령이 자동 재시도하지는 않습니다. 모든 시도 원본·검증 실패를 남기고 **마지막 출력**의 검증 상태를 실행 상태로 사용합니다. `retryable`은 후속 API 단계의 구조 오류 분류이며 수동 명령의 재호출 지시가 아닙니다. 근거 불일치·문서/위치 참조·확정된 시간 모순은 review 오류로 남깁니다. 실제 API의 전송/구조 오류 최대3시도 정책은 아직 미구현입니다.

## 파일·재실행·인계

`--root` 기본값은 Git 제외 `data/private/extraction-runs`입니다. 저장소 안에서는 `data/private/` 아래만 허용하며, 저장소 밖에서는 운영자가 지정한 비공개 디렉터리를 사용합니다. 새 디렉터리는0700, 파일은0600입니다. 기존 상위 디렉터리 권한·백업·공유 여부는 운영자가 관리합니다. 원본은 닫힌 일반 파일이어야 하며 symlink·FIFO는 거부합니다.

실행 폴더 `<run_id>/`에는 `identity.json`, `input.json`, `metadata.json`, `attempt-N.prompt`, `attempt-N.output`, `receipt.json`이 있습니다. identity가 원본 전체의 크기·SHA-256과 실행을 고정합니다. 복사 중 원본 변경은 거부하고, 완성 임시 파일의 배타 hard link로 원본 덮어쓰기를 막습니다. 같은 ID·같은 원본은 재사용하며, 다른 원본은 충돌입니다. 중단 후 동일 원본으로 다시 실행하면 누락 파일을 채웁니다. 완료 receipt는 마지막에 기록합니다. `verify`는 모든 원본 hash·메타데이터·검증 결과를 다시 확인하며, 미완료·손상을 성공으로 바꾸지 않습니다. hash는 우발 손상 검증이며 관리자가 원본과 기록 전체를 바꾸는 공격의 전자서명은 아닙니다.

stdout은 ID·상태·hash·고정 상대 파일명·안전한 오류 코드/필드 경로를 담은 JSON 한 건입니다. 본문·임의 키 이름·실제 경로는 내보내지 않습니다. 오류 stderr도 고정 코드만 사용합니다.

| 종료 코드 | 의미 |
|---|---|
| 0 | prepared 또는 validated |
| 2 | 입력·설정·메타데이터 오류 |
| 3 | 충돌·손상·미완료 |
| 4 | 원출력 보존 완료, 최종 검증 failed |
| 5 | 파일 I/O 실패 |
| 1 | 내부 오류 |

Java `local-extraction`은 [D03/D05 연결 안내](../backend/docs/extraction-run-import.md)에 따라 검증된 archive의 성공/실패·nullable metadata 원본을 등록한다. 같은 전체 D03 입력·전처리 버전이 필요하며 원본 경로를 유지한다. 검증 정보가 없는 legacy와 failed는 D06 AI origin으로 사용할 수 없다. D06 자동 초안 변환·실제 모델/API 실행·실자료 평가·공개 승인·운영 배포는 후속 작업이다.
