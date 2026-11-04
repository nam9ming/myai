# 수동 AI 결과 파일 업로드

실제로 사용한 input·metadata·시도별 prompt/output을 비공개 staging에 올리고 finalize로 D05를 등록한다. [로컬 관리 서버](local-management-api.md)의 기존6개 필수 환경변수·Java21·전용 MySQL·Python3.13을 사용한다. 새 AI 키나 외부 호출은 필요하지 않다. 필드·오류·한도는 [계약](../../contracts/extraction-upload.md)을 따른다.

source/request/extraction root는0700의 비공개 절대 경로를 사용한다. Python 실행 파일·`processing/` 작업 경로는 기존 `MYAI_PYTHON_EXECUTABLE`·`MYAI_PYTHON_WORKDIR`로 설정하며 [D05 실행 안내](extraction-run-import.md)를 따른다.

## 준비

먼저 대응 D03를 등록한다. input.json은 [원문 업로드 준비본](source-upload.md)의 원래5키 입력 또는 기존 D03와 정확히 같은 입력이다. metadata의 document_version_id·전처리 버전도 D03와 같아야 한다.

[기존17키 metadata 예제](../../processing/examples/extraction-metadata.json)를 참고해 metadata.json을 준비한다. `manual_import`·명시 run UUID·실제 시도 수1..3을 고정하고 실제 도구 표시값·미상/null을 유지한다. prompt는 실제 도구에 제공한 전문, output은 각 시도의 원출력이다. 생성 프롬프트를 실제 사용한 기록으로 대신하지 않는다. 기존 `processing.extraction prepare`는 [수동 실행 안내](../../contracts/extraction-run.md)에 따라 입력 준비에 사용할 수 있다.

아래는 합성 ID와 파일명을 사용한 전송 예시다. 같은 input에 대응하는 D03가 선등록돼 있고 합성 파일4종이 준비됐다고 가정한다. 실제 AI 실행·HTTP 검증 완료 실적을 뜻하지 않는다. 실제 처리에는 해당 실행의 UUID와 원본을 사용한다.

```bash
umask 077
UPLOAD_ORIGIN="http://127.0.0.1:${MYAI_LOCAL_API_PORT:-8081}"
UPLOAD_DIR="data/private/synthetic-extraction-upload"
UPLOAD_RUN_ID="71fb66f0-e610-4f9c-8f26-4bb77655ee8c"
```

이 private 디렉터리에 input.json·metadata.json·prompt-1.txt·output-1.json을 준비한다. 아래 control 작성은 최초 한 번만 수행하며 기존 파일을 덮어쓰지 않는다. input의 실제 bytes로 hash를 계산하고 정확한3키 JSON을 저장한다.

```bash
python3.13 - "$UPLOAD_DIR/input.json" "$UPLOAD_RUN_ID" "$UPLOAD_DIR/control.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
value = {
    "schema_version": "extraction-import-request-v1",
    "run_id": sys.argv[2],
    "expected_input_hash": hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(),
}
with Path(sys.argv[3]).open("x", encoding="utf-8") as target:
    json.dump(value, target, separators=(",", ":"))
    target.write("\n")
PY
```

## 초기 파일·시도·finalize

기존 실행 토큰은 표시하지 않고 curl의 stdin header로 전달한다. `--noproxy '*'`로 로컬 요청의 프록시 사용을 막는다.

```bash
printf 'Authorization: Bearer %s\n' "$MYAI_LOCAL_API_TOKEN" |
  curl --fail-with-body --noproxy '*' --header @- \
    --header "Origin: $UPLOAD_ORIGIN" \
    --form "control=@${UPLOAD_DIR}/control.json;type=application/json" \
    --form "metadata=@${UPLOAD_DIR}/metadata.json;type=application/json" \
    --form "input=@${UPLOAD_DIR}/input.json;type=application/json" \
    "$UPLOAD_ORIGIN/local/extractions/uploads"
```

각 실제 시도의 prompt/output을 따로 제출한다. metadata.attempts가3이면 실제 순서대로1·2·3의 여섯 파일을 모두 올린 뒤 finalize한다.

```bash
printf 'Authorization: Bearer %s\n' "$MYAI_LOCAL_API_TOKEN" |
  curl --fail-with-body --noproxy '*' --header @- --request PUT \
    --header "Origin: $UPLOAD_ORIGIN" \
    --form "file=@${UPLOAD_DIR}/prompt-1.txt;type=application/octet-stream" \
    "$UPLOAD_ORIGIN/local/extractions/uploads/$UPLOAD_RUN_ID/attempts/1/prompt"

printf 'Authorization: Bearer %s\n' "$MYAI_LOCAL_API_TOKEN" |
  curl --fail-with-body --noproxy '*' --header @- --request PUT \
    --header "Origin: $UPLOAD_ORIGIN" \
    --form "file=@${UPLOAD_DIR}/output-1.json;type=application/octet-stream" \
    "$UPLOAD_ORIGIN/local/extractions/uploads/$UPLOAD_RUN_ID/attempts/1/output"
```

staging 응답은 `extraction-upload-result-v1`의 run_id·expected_input_hash·state=staged·received_files·review_required=true다. received_files의 고정 이름·size_bytes·sha256를 확인한다. 이 응답은 metadata/input/output의 Python 의미 검증 통과나 D05 등록 완료가 아니다.

```bash
printf 'Authorization: Bearer %s\n' "$MYAI_LOCAL_API_TOKEN" |
  curl --fail-with-body --noproxy '*' --header @- --request POST \
    --header "Origin: $UPLOAD_ORIGIN" \
    --header 'Content-Type: application/json' \
    --data-binary "@${UPLOAD_DIR}/control.json" \
    "$UPLOAD_ORIGIN/local/extractions/uploads/$UPLOAD_RUN_ID/finalize"
```

finalize는 기존 `local-management-result-v1`을 반환한다. HTTP200이어도 `data.status=failed`일 수 있다. 이는 잘못된 JSON·빈/비정상 UTF-8 출력까지 원본으로 보관·D05 등록한 결과이며 사람 검토가 필요하다. 검증 실패 출력을 고쳐 성공 원본으로 덮어쓰지 않는다.

| 입력 | 새 HTTP 한도 |
| --- | --- |
| control·metadata·finalize JSON | 각각64KiB |
| input / prompt / output | 8MiB / 20MiB / 5MiB |
| 각 multipart 요청 전체 | 21MiB |

JSON part/input은 application/json, prompt/output은 text/plain 또는 application/octet-stream이다. charset 선언은UTF-8만 허용하지만 file bytes를 변환하지 않는다. prompt/output의 빈 파일과 누락 part는 다르다. 새 한도는 기존 CLI metadata8MiB·manual prompt 무제한·큰 실패 출력 전체 보존 정책을 바꾸지 않는다.413은 분할/별도 검토가 필요하며 미수신 전체 파일 보존을 의미하지 않는다.

## 재시도·복구·보고서

- 전송 중단: 저장된 control·metadata·input을 유지하고 누락된 slot의 같은 원본을 다시 제출한다. 같은 slot의 다른 bytes는409다.
- 완료 run UUID: 동일 metadata/input·전체 시도 원본만 재사용한다. 새 시도 추가·교체는409이며 다른 실행에는 새 UUID를 사용한다.
- finalize/DB 실패: 같은 UUID·hash·원래 파일로 finalize를 다시 호출한다. 파일 보관과 DB 성공은 별개이며 기존 D05가 이미 등록됐다면 `already_registered=true`일 수 있다.
- 중단 canonical: 완성된 동일 HTTP staging이 있으면 identity 설치 전 빈 디렉터리·정상 비공개 Python 임시 파일만 남은 경우도 재시도 대상이다. 임의 payload·권한/링크 문제는 자동 정리하지 않는다. HTTP staging 없는 외부 CLI 미완료나 identity/receipt 없이 payload만 남은 상태는422이며 원본 확인·정확 CLI 재개/백업 복원이 필요하다.

request root의 `extraction-uploads/`는 전송 원본이며 extraction root의 canonical/봉인본·D05 등록과 구별한다. source root의 D03 원문, request root의 기존 준비본과 새 staging, extraction root 전체와 DB를 함께 백업하고 같은 경로에 복원한다. [백업·복구 안내](backup-recovery.md)를 따른다. 자동 만료·삭제·재시도 기능은 없으므로 운영자가 접근·보존·용량을 관리한다.

S10은 AI artifact8MiB·전체 JSON/HTML64MiB를 유지한다. 예를 들어20MiB prompt가 정상 등록돼도 보고서는 한도 초과로 거부될 수 있다. 원본 일부를 생략해 성공 보고서를 만들지 않으며 원본을 보존하고 별도 검토한다.

새 HTTP의 실제 검증·리뷰·CI·통합 상태는 [구현 계획](../../docs/superpowers/plans/2026-11-05-extraction-result-upload.md)을 따른다. 이 안내는 검증 통과 선언이 아니다. 합성 코드 시험과 실제 사람 검토·개인정보/권리 확인·독립 평가·운영 인수를 구분한다.
