# 수동 AI 결과 파일 업로드 계약

I10의 결과 파일5MiB 업로드를 기존 [수동 실행 보관](extraction-run.md)·D05 등록에 연결한다. `local-api` 전용이며 인증·loopback·Origin/Host·공통 오류/request_id는 [로컬 관리 계약](local-management-api.md)을 따른다. 자동 AI 호출·사건 생성·사람 승인·공개는 수행하지 않는다. 기존 JSON `/local/extractions/import`는 유지한다.

## 요청·한도

| 요청 | 정확한 입력 |
| --- | --- |
| POST `/local/extractions/uploads` | multipart `control`, `metadata`, `input` 각각 하나 |
| PUT `/local/extractions/uploads/{run_id}/attempts/{attempt}/{artifact}` | multipart `file` 하나. attempt=1..3, artifact=prompt 또는 output |
| POST `/local/extractions/uploads/{run_id}/finalize` | application/json의 기존3키 control |

| 입력 | MIME·개별 한도 |
| --- | --- |
| control·metadata part | application/json·각64KiB |
| input file | application/json·8MiB |
| prompt file | application/octet-stream 또는 text/plain·20MiB |
| output file | application/octet-stream 또는 text/plain·5MiB |
| finalize JSON | application/json·64KiB |

charset을 선언하면 UTF-8만 허용한다. 각 multipart 전체는21MiB다. 중복·추가·누락 part는 거부하고 파일명은 경로·ID로 사용하거나 응답/로그에 반사하지 않는다. input/metadata/control은 빈 파일을 거부한다. prompt/output은 빈 파일·잘못된 UTF-8·잘못된 결과 JSON도 원래 bytes로 받을 수 있다. 수신 단계에서 결과를 고쳐 쓰거나 검증 실패 출력을 버리지 않는다.

control/finalize는 정확히 아래3키다. run_id는 명시 UUID, expected_input_hash는 **제출한 input 원래 bytes**의64자리 소문자 SHA-256이다. finalize의 URL UUID도 같아야 한다.

```json
{
  "schema_version": "extraction-import-request-v1",
  "run_id": "71fb66f0-e610-4f9c-8f26-4bb77655ee8c",
  "expected_input_hash": "<input 원래 bytes의 소문자 SHA-256>"
}
```

위 hash 표시는 실제 값으로 바꿀 자리다. metadata는 [기존17키 예제](../processing/examples/extraction-metadata.json)를 따르며 `execution_mode=manual_import`, 같은 run_id, attempts=1..3이어야 한다. 도구·모델·버전·실제 실행 시각/사용량/비용은 제공값만 기록한다. 미상/null·미상 사유 규칙은 기존 계약을 유지하고 모델 시각을 서버 현재 시각으로 채우지 않는다.

input은 등록된 D03와 같은5키 입력·전체 블록·전처리 버전이어야 한다. Java는 초기 연결·전송 한도만 확인하며17키 의미·input/output 검증은 최종 Python import가 수행한다. `staged`를 의미 검증 통과로 해석하지 않는다. API wire archive를 수동 결과로 위장하거나 api/v2 완료 실행을 manual로 바꾸지 않는다.

## 응답·finalize

staging 성공200은 정확히6키다.

| 필드 | 값 |
| --- | --- |
| schema_version | extraction-upload-result-v1 |
| run_id | 제출한 실행 UUID |
| expected_input_hash | input 원래 bytes의 SHA-256 |
| state | staged |
| received_files | 확인한 고정 파일명의 name·size_bytes·sha256 목록 |
| review_required | true |

received_files의 이름은 control.json·metadata.json·input.json·attempt-N.prompt/output이다. multipart framing·파일명·인증 헤더를 보관했다는 뜻은 아니다. 원본·서버 경로·자식 stderr는 반환하지 않는다.

초기 metadata의 N 밖 slot을 받지 않으며 finalize는 실제 순서1..N의 prompt/output 쌍 전부를 요구한다. Python이 원본 전체를 보관·검증한 뒤 기존 freeze·D03 대조·D05 등록을 사용한다. finalize 성공200은 기존 `local-management-result-v1`이다. 원출력 검증이 실패했어도 정상 보관·등록됐다면200의 `data.status=failed`, `review_required=true`이며 성공 출력으로 바꾸지 않는다.

## 정확 재실행·중단 복구

staging은 request root의 `extraction-uploads/`에 원래 control/input/metadata와 각 slot을 보관한다. root/디렉터리0700·파일0600이며 링크·권한/내용 충돌은 거부한다. 같은 초기 bytes·같은 slot bytes는 재사용하고 다른 bytes는409다. 최초 HTTP control의 공백도 그대로 유지한다.

완료 canonical UUID는 검증된 기존 원본과 metadata/input·시도 수·모든 prompt/output의 size/SHA가 같은 재전송만 허용한다. 새 시도 추가·교체는409이며 새 실행 기록에는 새 UUID가 필요하다. canonical 검증 실패를 부재로 바꾸거나 HTTP 파일로 덮어쓰지 않는다.

동일 HTTP staging이 이미 있고 선언한 쌍이 모두 준비됐다면 중단 finalize를 재시도할 수 있다. identity 설치 전 빈 canonical 디렉터리나 Python이 설치 도중 남긴 정상 비공개 임시 파일만 있는 경우도 포함한다. 임의 payload·잘못된 권한·symlink를 자동 정리하지 않으며, identity/receipt 없이 payload만 남은 상태는422다. HTTP staging이 없는 외부 CLI 미완료 실행도422로 거부하고 기존 CLI의 정확 원본 복구/재개가 필요하다.

파일 보관과 DB commit은 별개다. DB 실패 뒤에는 동일 UUID·hash·원래 파일로 finalize를 다시 호출한다. 기존 archive·D05를 재사용하며 새 모델 호출이나 UUID를 만들지 않는다. 상태조회·취소·자동 만료·자동재시도는 제공하지 않는다.

## 오류·기존 경계

한도413, 입력/미완료·무효 archive422, 부재404, 충돌409, MIME/charset415, 실행/DB 미준비503, 예상하지 못한 I/O500을 공통 JSON/request_id로 구분한다. transport 초과413은 미수신 전체 파일을 보존했다는 뜻이 아니다.

새 HTTP metadata64KiB/prompt20MiB/output5MiB는 기존 CLI metadata8MiB·manual prompt 무제한·큰 실패 출력 전체 stream 보존을 바꾸지 않는다. 기존 관리 JSON·AI 입력8MiB, 원문 업로드 file20MiB/request21MiB도 유지한다.

S10의 AI artifact8MiB·전체 JSON/HTML64MiB는 유지한다. 업로드/D05 등록 성공이 보고서 성공을 보장하지 않으며, 초과 원본을 생략해 보고서를 성공 처리하지 않는다. 원본을 보존하고 별도 검토가 필요하다.

source root·request root의 기존 준비본과 extraction-uploads·canonical/봉인본이 있는 extraction root·DB를 함께 백업하고 같은 경로에 복원한다. [복구 안내](../backend/docs/backup-recovery.md)를 따른다. 접근·보존·용량 관리와 운영 내구성은 별도 책임이다.

합성 기능 검증과 실제 사람 검토·개인정보/권리 확인·독립 gold/40문서/90% 평가·운영 인수를 구분한다. 새 HTTP의 전체 검증·리뷰·통합 완료 여부는 [구현 계획](../docs/superpowers/plans/2026-11-05-extraction-result-upload.md)의 증거를 따른다.
