# 로컬 원문 업로드 계약

`POST /local/documents`에 `multipart/form-data`를 추가한다. 기존 `application/json`의 source-import-v1·8MiB 입력은 유지한다. 인증·Origin/Host·공개 분리는 [로컬 관리 계약](local-management-api.md)을 따른다. 업로드는 외부 AI·사건 생성·승인·공개를 실행하지 않는다.

## 입력

part는 정확히 두 개다. 중복·추가·누락은422다.

| part | 형식·한도 |
| --- | --- |
| metadata | application/json·UTF-8·64KiB. 아래14키가 모두 있어야 한다. |
| file | txt=text/plain, pdf=application/pdf, json=application/json. 최대20MiB. 파일명은 저장경로·ID로 사용하지 않는다. |

전체 multipart는21MiB다. charset을 선언하면 UTF-8이어야 한다. 제목은 NFC이며 CR을 포함하지 않는다. 중복/추가키·후행 JSON·잘못된 Unicode를 거부한다.

아래는 합성 예제다. ID·버전·실제 수집 시각은 수집·준비 도구에서 고정해 전달한다. 같은 게시물 수정본은 같은 document_id와 다음 version_no를 사용한다. URL을 수집하거나 문서를 자동 병합하지 않는다.

```json
{
  "schema_version": "source-upload-v1",
  "format": "txt",
  "data_kind": "synthetic",
  "document_id": "44444444-4444-4444-8444-444444444444",
  "document_version_id": "55555555-5555-4555-8555-555555555555",
  "version_no": 1,
  "publisher": "합성 기관",
  "official_url": "https://example.invalid/notices/1",
  "title": "합성 공지",
  "official_number": null,
  "published_date": null,
  "collected_at": "2026-11-02T00:00:00Z",
  "collection_method": "synthetic fixture",
  "use_note": "합성 예제이며 공개 검토 전"
}
```

JSON 파일은 정확히 `{"schema_version":"text-body-v1","text":"본문"}`이다. 기존5키 AI입력이나 source-import를 추측해 변환하지 않는다. source-import는 원래 application/json 경로로 제출한다.

## 텍스트와 검토 상태

txt/json은 엄격한 UTF-8, PDF는 설정한 Poppler의 내장 텍스트를 사용한다. LF/NFC·고정 전화/이메일 치환 후 최대2,000 code point 블록으로 만든다. PDF 페이지 번호를 보존하고 블록 text를 LF로 결합한다. 최종 본문200,000 code point를 넘으면413이며 자르지 않는다. 긴 한 행의 분할 LF도 한도에 포함한다.

PDF는 `text_scope=embedded_text_only`, `text_review_required=true`다. 텍스트 없는 페이지는 전체422 `PDF_PAGE_REVIEW_REQUIRED`이며, 마지막 form-feed 종료 표식은 새 페이지가 아니다. 기존 OCR층은 내장 텍스트로 읽을 수 있지만 OCR을 실행하지 않는다. 그림·표·머리말만 추출된 페이지의 완전성은 사람이 대조해야 한다. txt/json의 `provided_text`·false도 개인정보/사실 검토 완료를 뜻하지 않는다.

모든 신규 D03은 use_review=pending·check_result=unchecked·checks=[]·확인 시각null이다. 고정 연락처 치환은 모든 개인정보 제거를 보증하지 않는다. 외부 AI 전송 전 실제 비식별·원문 검토가 필요하다.

redaction_log는 치환 전 LF/NFC 본문의0기반 Unicode code point 범위 `[start,end)`를 기록한다. PDF는 페이지별 `page:N:codepoints:start-end`, txt/json은 `codepoints:start-end`이며 치환된 본문의 offset과 구별한다. 제거한 연락처 값은 로그에 넣지 않는다.

## 성공·원본·재시도

성공200의 schema_version은 `source-upload-result-v1`이다. document_id/document_version_id/version_no, use_review/check_result, raw_sha256/text_sha256/input_hash, preprocessing_version/text_scope/text_review_required와 기존 import 결과 `data`를 반환한다. data.already_imported는 첫 등록false·재실행true일 수 있다. 같은 입력의 ID/hash와 준비본은 유지한다.

`upload_sha256`은 ASCII `source-upload-v1\n<metadata SHA-256>\n<raw SHA-256>`의 SHA-256이다. metadata와 file part의 원래 bytes를 각각 보존하며 multipart 전체·파일명·인증 헤더를 보관했다고 주장하지 않는다. metadata의 공백만 바뀌어도 같은 버전의 다른 원본으로409다.

- 원문: source root의 `uploads/<raw_sha256>.<format>`.
- 준비본: request root의 `uploads/bundles/<server UUID>/`에 metadata.json·source-import.json·input.json·receipt.json 네 파일.
- 완료 index: request root의 `uploads/<document_version_id>.json`. 준비본 전체를 검증한 뒤 배타 hard link로 설치한다.

root/디렉터리0700·파일0600, 링크·기존 다른 내용·권한/전체 hash 충돌은 거부한다. 같은 버전의 정확한 재실행은 첫 준비본을 사용하고 PDF를 다시 변환하지 않는다. DB 실패 뒤에도 원문·완료 준비본이 남아 재시도할 수 있다. 파일 저장과 DB commit은 별개다. 기존 D03를 새 경로·전처리로 덮어쓰지 않는다.

## 오류·설정·남은 범위

공통 오류/request_id 형식이다. 한도413, 형식422, MIME415, 원본/버전 충돌409, PDF 도구 미준비503, 저장 I/O500과 기존 DB 오류를 구분한다. 원문·토큰·경로·자식stderr를 오류/로그에 반사하지 않는다.

multipart는 전역 off·local-api에서만 on이다. 기동 때 파일20MiB·요청21MiB·Tomcat form-post21MiB·메모리 threshold21MiB 이상/int 범위·lazy parsing을 검사한다. metadata는 실제 part 읽기부터64KiB로 제한한다. 이 조건을 풀면 기동을 거부한다. PDF는 공통10초 deadline·stdout4MiB/stderr64KiB·키 없는 환경이며 종료 정리에 최대600ms가 추가될 수 있다. OS 메모리 격리·전원 중단 내구성은 보증하지 않는다.

기존 JSON/CLI/AI입력8MiB·D05 원출력/장문 보관 규약을 유지한다. S10 raw20MiB 전체 embed·AI artifact8MiB·전체 JSON/HTML64MiB다. AI 결과 파일5MiB 업로드, 관리 UI·실자료 사람 검토·독립 gold/40문서/90%·사용자 평가·운영 배포는 후속 범위다.
