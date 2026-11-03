# AI 추출 검증·수동 실행 기록

Python3.13 표준 라이브러리로 `manual_import`와 OpenAI `api` 실행을 지원합니다. 네트워크 호출은 명시적인 `run`만 수행하며 `verify/freeze/draft/check-draft`와 계산 CLI·Java 공개 조회는 AI를 호출하지 않습니다. Python은 DB를 쓰지 않습니다. 입력·원출력·프롬프트·메타데이터는 비공개 기록이며, 공개 snapshot으로 직접 전달하지 않습니다.

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

`--attempt PROMPT OUTPUT`은 실제 시도 순서대로1~3회 지정하며 metadata.attempts와 같아야 합니다. 수동 명령은 자동 재시도하지 않습니다. 모든 시도 원본·검증 실패를 남기고 **마지막 출력**의 검증 상태를 실행 상태로 사용합니다. `retryable`은 구조 오류 분류이며 수동 명령의 재호출 지시가 아닙니다. 근거 불일치·문서/위치 참조·확정된 시간 모순은 review 오류로 남깁니다.

## OpenAI API 실행

`run --input FILE --preprocessing-version VERSION [--run-id UUID] [--model MODEL] [--root ROOT]`는 `OPENAI_API_KEY`를 헤더에서만 사용합니다. 모델 선택은 `--model`→`OPENAI_MODEL`→현재 리뷰 기본값 `gpt-6.1-sol` 순서입니다. 개발 키 재사용은 사용자 결정이며 실제 자료의 검토·비식별화 책임을 대신하지 않습니다.

`https://api.openai.com/v1/responses`만 호출하며 리다이렉트를 따라가지 않습니다. [공식 Responses 안내](https://developers.openai.com/api/docs/guides/migrate-to-responses)에 따라 `store=false`, 지시와 원문 입력을 전달합니다. 도구·검색·평가 정답·사용자 조건을 요청하지 않습니다. 매 시도 원문과 해당 실행의 고정 프롬프트 버전 전체 계약을 다시 보내고 구조 오류 피드백은 경로만 전달합니다.

요청별120초·최대3시도·출력8192토큰입니다. timeout/전송·HTTP408/429/5xx와 구조 오류만1초·2초 간격으로 재시도합니다. 인증/다른4xx/리다이렉트·거절·근거/시간 모순은 중단합니다. 실패도 완료 receipt를 보관하며 종료4입니다. 클라이언트 요청 시작/종료 시각과 공급자가 제공한 모든 시도의 token 사용량만 기록합니다. 어떤 시도라도 사용량이 미상이면 그 합계는 null입니다. 상세 모델 버전·요금·통화는 추정하지 않고 raw 응답의 표시값을 남깁니다.

HTTP 전송은 고정 내부 프로세스에서 수행하고 부모가 요청 전체 deadline에 종료합니다. DNS·느린 헤더·chunk framing도 같은 제한을 적용하며 짧은 종료 정리에 최대1초가 추가될 수 있습니다. 이미 받은 재시도 불가 HTTP 상태는 부분 본문 전송 오류보다 우선합니다. 내부 파이프는 상태 숫자 한 줄과 수신 본문만 전달하며 키는 자식 환경변수와 HTTPS 헤더에서만 사용합니다.

content_filter로 중단된 응답은 거절·검토 오류로 보관하고 다시 요청하지 않습니다. 토큰 한도로 불완전해진 응답은 최대3시도 정책을 적용합니다. API의 마지막 시도가 재시도 가능 실패이면3회가 모두 남아야 완료 archive로 인정하며,1~2회만 남은 조기 종료 기록은 거부합니다. 수동 가져오기의1~3회 허용은 유지합니다.

API 실행은 시도별 `attempt-N.prompt`(실제 HTTP JSON body, 헤더 제외), `.response`(수신 응답 본문), `.exchange`(HTTP 상태·전송 오류·완전 수신 여부·시각), `.output`(응답의 추출 텍스트)를 보관합니다. 수신 한도8MiB+1의 초과/중단은 prefix와 불완전 상태를 남기며, 정상 전체 응답으로 처리하지 않습니다. 입력8MiB·출력 검증8MiB는 유지합니다. JSON 인코딩으로 커진 요청은 원본 전체 fingerprint와 재구성한 요청을 대조하므로 조용히 잘라내지 않습니다.

`.output`은 완료 응답의 assistant 텍스트를 추출한 파생 파일입니다. 토큰 한도 등으로 미완료된 응답은 부분 텍스트를 포함한 `.response` 원본을 그대로 보존하고 `.output`은 비워 둡니다. 원본 유실이나 검증 성공으로 처리하지 않으며 `verify`·`freeze`에서도 같은 규칙을 확인합니다.

오프라인 `verify`는 모든 파일 hash, 원문/요청 일치, 응답→추출 텍스트, 실패/재시도 정책, 시각·사용량을 다시 계산합니다. 수동 receipt 형식은 유지하며 API는 `execution_mode=api`와 추가 artifact를 구분합니다. Java는 두 방식 모두 같은 freeze·DB 등록·재검증·초안 경계를 적용합니다.

새 API 실행은 `prompt-v2`로 블록 ID별 `block_metadata.{id}.{text_sha256,length}`를 제공합니다. 길이는 Unicode code point 수이며 전체 블록 인용 시 시작0·끝length를 복사하도록 안내합니다. 출력의 hash·위치·인용을 자동 보정하지 않고 기존 검증을 그대로 적용합니다. 수동 `prepare` 기본값과 원래 `prompt-v1` 바이트는 유지합니다. API archive는 metadata의 v1/v2에 맞는 원래 요청으로 재검증하며 기존 완료 ID를 다시 실행해도 새 버전으로 유료 호출하지 않습니다. 미지원 버전이나 요청과 다른 버전은 거부합니다.

완료 run_id는 동일 입력 바이트·모델·전처리 버전일 때 재사용하며 새 네트워크 호출이 없습니다. 디렉터리 배타 생성으로 동시 중복 호출을 차단합니다. 중단한 실행은 미완료로 남깁니다. 이미 처리됐을 수 있는 요청의 중복 과금을 피하도록 자동 재전송하지 않습니다. 원본을 확인한 뒤 별도 run_id를 사용합니다.

## 파일·재실행·인계

Java 등록은 `python3.13 -m processing.extraction freeze RUN_ID --root ROOT`로 별도 읽기 전용 실행 보관본을 만든다. `extraction-registration-v1` 응답은 `protocol_version/snapshot_ref/receipt`의3키이며 snapshot_ref는 `registered/<receipt_sha256>/<run_id>` 또는 이미 읽기 전용인 현재 run_id의 상대 경로다. 전체 원본을 hash 대조 복사·검증하고 파일0400/실행 디렉터리0500으로 설정한 뒤 원자적으로 내놓는다. 같은 보관본은 재사용하며 원래 archive를 덮어쓰지 않는다. 실패/과다 출력도 그대로 보존하고 종료0/4는 receipt.status에 대응한다. 추가 저장 공간과 POSIX 권한 지원이 필요하다. 관리자 권한 변경·이동·삭제를 방어하는 WORM 보장은 아니다.

`--root` 기본값은 Git 제외 `data/private/extraction-runs`입니다. 저장소 안에서는 `data/private/` 아래만 허용하며, 저장소 밖에서는 운영자가 지정한 비공개 디렉터리를 사용합니다. 새 디렉터리는0700, 파일은0600입니다. 기존 상위 디렉터리 권한·백업·공유 여부는 운영자가 관리합니다. 원본은 닫힌 일반 파일이어야 하며 symlink·FIFO는 거부합니다.

실행 폴더 `<run_id>/`에는 `identity.json`, `input.json`, `metadata.json`, `attempt-N.prompt`, `attempt-N.output`, `receipt.json`이 있습니다. identity가 원본 전체의 크기·SHA-256과 실행을 고정합니다. 복사 중 원본 변경은 거부하고, 완성 임시 파일의 배타 hard link로 원본 덮어쓰기를 막습니다. 같은 ID·같은 원본은 재사용하며, 다른 원본은 충돌입니다. 수동 가져오기는 중단 후 동일 원본으로 다시 실행하면 누락 파일을 채웁니다. API 실행은 미완료 ID의 자동 재전송을 거부합니다. 완료 receipt는 마지막에 기록합니다. `verify`는 모든 원본 hash·메타데이터·검증 결과를 다시 확인하며, 미완료·손상을 성공으로 바꾸지 않습니다. hash는 우발 손상 검증이며 관리자가 원본과 기록 전체를 바꾸는 공격의 전자서명은 아닙니다.

stdout은 ID·상태·hash·고정 상대 파일명·안전한 오류 코드/필드 경로를 담은 JSON 한 건입니다. 본문·임의 키 이름·실제 경로는 내보내지 않습니다. 오류 stderr도 고정 코드만 사용합니다.

| 종료 코드 | 의미 |
|---|---|
| 0 | prepared 또는 validated |
| 2 | 입력·설정·메타데이터 오류 |
| 3 | 충돌·손상·미완료 |
| 4 | 원출력 보존 완료, 최종 검증 failed |
| 5 | 파일 I/O 실패 |
| 1 | 내부 오류 |

Java `local-extraction`은 [D03/D05 연결 안내](../backend/docs/extraction-run-import.md)에 따라 검증된 archive의 성공/실패·nullable metadata 원본을 등록한다. 같은 전체 D03 입력·전처리 버전이 필요하며 원본 경로를 유지한다. 일반 D06 AI 경로는 검증 정보가 없는 legacy와 failed를 거부한다. failed는 별도 [사람 수정본 인계](../backend/docs/human-handoff-import.md)의 전체 증거·사건 연결을 검증한 경우만 제한적으로 허용하며 실제 상태는 바꾸지 않는다. import·승인·미리보기·공개 때 archive 원본과 DB 등록 기록을 다시 대조하며 Python 검증 중 DB 트랜잭션을 유지하지 않는다. D06 숨김 초안 변환·저장·사람 검토 다음 revision 연결은 [초안 안내](../backend/docs/ai-review-draft.md)를 따른다. 개발용 실제3건은 v2 기계 검증과 전용 시험 DB의 D03·D05·후보 연결 D06 숨김 초안 저장을 확인했다. 원문은 pending/uncertain, 지역 소속은 uncertain이며 사람 검토·독립 정답/40건 평가·공개 승인·운영 배포는 후속 작업이다.

같은 D03의 확인·사용권 갱신은 Java [local-source-review](../backend/docs/source-review.md)의 별도 이력이다. 최초 source metadata·본문/원문 hash·전체 블록과 동결 D05·사람 인계 이미지는 수정하지 않으며 기존 입력·전처리 대조와 정확한 재실행을 유지한다. 승인·공개만 현재 운영 상태를 합쳐 검사한다. 새 확인을 이유로 AI 실행을 재생성하거나 legacy/failed를 성공으로 바꾸지 않는다.

## Java의 초안 전체 대조

Java local-import는 AI 초안에만 내부 명령 `python3.13 -m processing.extraction check-draft RUN_ID --root ROOT`를 사용한다. stdin은 ai-draft-import-v1 JSON 한 건이며 최대8MiB다. Python은 기존 생성 함수를 재사용해 등록 보관본의 최종 출력에서 기대 초안을 만들고 JSON 키 순서·공백을 제외한 전체 값·ID·근거·연결을 대조한다. 빈 사건도 실제 NO_EVENT_FOUND 출력이어야 하며 raw 파일을 사람 수정본으로 사용하지 않는다.

stdout은 정확히 `protocol_version/status/run_id/input_sha256`의4키다. 버전은 ai-draft-check-v1, 성공 상태는 validated이며 hash는 받은 stdin UTF-8 바이트의 SHA-256이다. Java는 이 ID/hash·응답 형식을 대조한다. 원문·AI 출력·실제 경로는 반환하지 않는다. 불일치2·archive 오류3·파일 오류5·내부 오류1이며 성공0도 사람 승인은 아니다. Java가 DB 트랜잭션 밖에서 제한된 Python 프로세스로 실행하므로 추가 검증 I/O가 발생한다. D03 전체 규격·원문 파일은 Java가 별도로 검증한다.
