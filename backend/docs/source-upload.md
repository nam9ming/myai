# 원문 파일 업로드·텍스트 준비

기존 [로컬 관리 서버](local-management-api.md)에 txt/pdf/json 원문을 제출한다. 파일을 비공개 보존하고 D03와 Python 입력을 준비한다. 실제 AI 실행·사람 검토·승인/공개는 별도다. 요청·응답 필드는 [계약](../../contracts/source-upload.md)을 따른다.

## 실행 준비

기존6개 `MYAI_LOCAL_API_*` 필수 환경변수와 전용 MySQL·Java21을 준비한다. source/request root는 실제 절대 경로·0700이며 경로 중간에 symlink가 없어야 한다. 기존 원본과 다른 위치를 정했다면 관련 원문·준비본을 함께 관리한다.

PDF는 Poppler의 `pdftotext`가 필요하다. 로컬 기능 시험은25.04.0으로 수행했으며 실제 사용 버전을 각 준비본에 기록한다. Ubuntu는 poppler-utils, macOS의 기존 Homebrew 설치는 `/opt/homebrew/bin/pdftotext` 등을 확인한다. Maven/Python 라이브러리는 추가하지 않는다.

```bash
export MYAI_LOCAL_API_PDFTOTEXT=/usr/bin/pdftotext
"$MYAI_LOCAL_API_PDFTOTEXT" -v
java -jar backend/build/libs/myai-backend-0.1.0.jar --spring.profiles.active=local-api
```

PDF 경로가 없거나 도구를 읽지 못하면 PDF 요청만503이다. txt/json·기존 JSON 관리 경로는 사용할 수 있다. `server.tomcat.max-http-form-post-size=21MB`를 포함한 수신 한도는 기동 때 검사하며 metadata는 실제 part 읽기부터64KiB로 제한한다. 입력/출력 제한·프로필 설정을 완화해 실행하는 방식은 지원하지 않는다.

## 요청

합성 예제 metadata.json은 계약의14키를 따른다. 파일은 Git 제외 private 경로에 둔다. 아래는 기존 실행 토큰을 pipe로 전달하는 호출 예다. 실제 토큰을 문서·URL·채팅에 넣지 않는다.

```bash
printf 'Authorization: Bearer %s\n' "$MYAI_LOCAL_API_TOKEN" |
  curl --fail-with-body --noproxy '*' --header @- \
    --header "Origin: http://127.0.0.1:${MYAI_LOCAL_API_PORT:-8081}" \
    --form 'metadata=@data/private/upload/metadata.json;type=application/json' \
    --form 'file=@data/private/upload/notice.txt;type=text/plain' \
    "http://127.0.0.1:${MYAI_LOCAL_API_PORT:-8081}/local/documents"
```

PDF는 format=pdf·file part application/pdf, JSON은 format=json·application/json이다. JSON 파일 내용은 `{"schema_version":"text-body-v1","text":"본문"}`이다. 기존 source-import JSON은 기존 application/json API로 제출한다.

| 한도 | 값 |
| --- | --- |
| metadata / 원문 / 전체 multipart | 64KiB / 20MiB / 21MiB |
| 최종 cleaned_text / 블록 | 200,000 / 2,000 Unicode code point |
| 기존 관리 JSON·CLI·AI입력 | 8MiB 유지 |

제목은 NFC를 사용한다. 본문은 LF/NFC로 정리하며 고정 전화/이메일만 치환한다. 블록을 결합하며 추가한 LF도 최종 한도에 포함하므로200,000자 한 행은 분할 후 초과할 수 있다. 초과 자료를 잘라 성공 처리하지 않는다.

빈 줄·공백 블록을 제거한 뒤 실제 보관되는 본문으로 한도를 검사한다. 제거될 공백이 많아도 최종 본문이 한도 이하면 받을 수 있으며, 블록 안에 남는 공백·치환 표시·결합 LF는 한도에 포함한다.

## 준비본·재실행·실패

성공의 문서/버전ID와 hash를 보관한다. 업로드는 항상 pending/unchecked다. PDF는 내장 텍스트만 추출하고 text_review_required=true이며 텍스트 없는 페이지가 있으면 전체 등록을 중단한다. OCR층·그림·표·원문 누락, 연락처 이외 개인정보는 실제 검토가 필요하다.

변환 stderr에 진단이 있으면 exit0이어도422로 중단해 손상 stream의 부분 본문을 등록하지 않는다. 무해한 경고도 별도 검토 대상이며 진단 원문은 응답·로그에 넣지 않는다. 정확 재실행으로 이전 준비본을 받은 것은 새 변환 검사 통과가 아니다.

request root의 `uploads/<document_version_id>.json`에서 bundle_id를 읽으면 `uploads/bundles/<bundle_id>/input.json`이 기존5키 Python 입력이다. 같은 디렉터리에 metadata·source-import·receipt가 있다. metadata/file의 원래 bytes, 도구/전처리 버전과 전체 hash를 보존한다. 파일명은 저장경로로 사용하지 않는다.

정확한 재실행은 첫 준비본을 재사용하고 기존 import 결과의 already_imported가true일 수 있다. 같은 버전의 다른 metadata/file은409다. PDF 도구 버전이 바뀌어도 기존 준비본을 다시 변환하지 않는다. 원문이나 준비본이 손상되면 덮어써 복구하지 말고 검증된 백업을 복원한다.

알려진 변환/DB 실패의 비공개 원본이 남을 수 있다. 파일 보관 성공이 DB 등록 성공을 뜻하지 않는다. [백업·복구 안내](backup-recovery.md)에 따라 source/request 전체와 DB를 함께 보존하고 운영자가 접근·보존·삭제 정책을 정한다.

## 확인 범위

합성 자료의 실제 HTTP/MySQL/JAR·원문/hash·재시도·충돌·rollback·S10·선택 파일 복구를 시험한다. 전체 검증·PR 상태는 [구현 계획](../../docs/superpowers/plans/2026-11-05-document-upload.md)을 따른다. 실제 PDF 완전성·개인정보/권리 검토·사람 승인·독립 평가·운영 배포 완료로 해석하지 않는다.
