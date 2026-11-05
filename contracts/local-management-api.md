# 로컬 관리 HTTP 계약

B05/I10/I11의 로컬 관리 계약이다. 기존 JSON 관리 경로의 구현·검증 기록은 [관리 API 계획](../docs/superpowers/plans/2026-11-04-local-management-api.md)을 따른다. [txt/pdf/json 업로드 계약](source-upload.md)을 추가했으며 전체 회귀·리뷰·PR/CI·통합 결과는 [업로드 계획](../docs/superpowers/plans/2026-11-05-document-upload.md)에서 추적한다. 기존 CLI·공개 I01~I03은 유지한다.

## 실행 경계

`local-api` 단독 servlet 프로필만 사용한다. bind는127.0.0.1, 기본 port8081이며 다른 port와0번 임시 port를 명시할 수 있다. 공개/fixture/CLI 혼합·외부 bind·forwarded-header 처리·빈 필수 설정을 기동 전에 거부한다. 공개 앱에는 `/local` controller가 없으며, 로컬 앱에는 공개 API controller가 없다.

필수 설정은 `MYAI_LOCAL_API_TOKEN/ACTOR/SOURCE_ROOT/EXTRACTION_ROOT/HANDOFF_ROOT/REQUEST_ROOT`와 선택 `MYAI_LOCAL_API_PORT`다. PDF 업로드는 선택 `MYAI_LOCAL_API_PDFTOTEXT`의 절대 실행 파일을 사용하며 미설정이면 PDF 요청만503이다. token은 실행 전에 새로 준비한32~128자리 `[A-Za-z0-9_-]` 문자열이다. 소스·URL·로그·응답에 넣지 않는다. root는 운영자가 지정한 절대 private 디렉터리이며 client가 임의 root를 전달하지 않는다. 새 업로드의 source/request root는0700·파일0600이며 중간 symlink를 거부한다.

모든 로컬 HTTP 요청은 `Authorization: Bearer <token>`, `Origin: http://127.0.0.1:<실제 port>`, 같은 Host를 요구한다. 실제 HTTP port80에서만 `http://127.0.0.1`/`127.0.0.1`의 기본 port 생략과 `:80` 명시를 동등하게 허용한다([Origin 직렬화 규칙](https://www.rfc-editor.org/rfc/rfc6454#section-6.2)). 실제 loopback socket·서버 port로 비교하며 forwarded header를 신뢰하지 않는다. 토큰 오류401, origin/host/socket 오류403이며 body를 읽거나 보관·domain 호출하기 전에 거부한다. encoded path·OPTIONS·오류 경로로 우회하지 않는다.

## 요청·결과

기존 JSON 관리 요청은 `application/json`·UTF-8·최대8MiB다. 새 추출 업로드의 finalize JSON만64KiB다. Content-Length 유무와 무관하게 실제 stream에서 검사하고 초과는413, 지원하지 않는 media는415다. 중복/추가키·후행 JSON·잘못된 타입/ID/상태는 기존 strict reader로 거부한다. 공개 body32KiB·기존 CLI/AI입력8MiB를 바꾸지 않는다. `/local/documents` multipart는 metadata64KiB·원문20MiB·최종 본문200,000 Unicode code point다. [수동 추출 업로드](extraction-upload.md)는 control/metadata64KiB·input8MiB·prompt20MiB·output5MiB이며 각 multipart 전체는21MiB다.

| 경로 | 입력 | 결과·제한 |
| --- | --- | --- |
| POST `/local/documents` | `source-import-v1` | D03만 등록. 기존 문서 버전·원문/hash/검토 상태를 검증한다. |
| POST `/local/documents` | `multipart/form-data`: metadata/file 두 part | [원문 업로드](source-upload.md). txt/pdf/json 원문·metadata bytes를 보존하고 pending/unchecked D03와 기존5키 Python 입력을 준비한다. 자동 AI·사건·승인·공개는 없다. |
| POST `/local/extractions/import` | 정확히 `schema_version:extraction-import-request-v1,run_id,expected_input_hash` | 명시 D05의 전체 보관본을 검증하며 input SHA 불일치는 DB 저장 전에 거부한다. 사건/공개를 만들지 않는다. |
| POST `/local/extractions/uploads` | multipart control/metadata/input 각각 하나 | [수동 추출 업로드](extraction-upload.md)의 초기 원본을 보존한다. staged는 의미 검증 통과가 아니다. |
| PUT `/local/extractions/uploads/{run_id}/attempts/{attempt}/{artifact}` | multipart file 하나 | 명시1..3시도의 prompt/output 원본을 보존한다. 빈/비정상 출력도 보존하고 다른 bytes 재전송은409다. |
| POST `/local/extractions/uploads/{run_id}/finalize` | 기존3키 control JSON·64KiB | 완성한 모든 시도를 Python import/freeze·D03 대조·D05 등록에 연결한다. 정상 보관한 실패 결과도200이며 data.status로 구별한다. |
| PUT `/local/events/{id}/review` | `reviewed-import-v1`, `human-handoff-import-v1` 또는 `publication-command-v1` approve/reject | 명시 사건1개만 허용하며 URL ID와 events[0]/revisions[0]/event_id가 같아야 한다. expected 번호·근거·AI/사람 수정 원본을 보존한다. |
| POST `/local/reviews/import` | `reviewed-import-v1` 또는 `human-handoff-import-v1` | 기존 다중 사건 배치 전체를 명시적으로 저장한다. 인계 이미지를 임의로 잘라 단일 사건 요청으로 바꾸지 않는다. |
| POST `/local/publish` | `publication-command-v1` preview/publish/rollback | 기존 승인·사용권·원문 확인·5지점·mode·revision/head 검사를 그대로 실행한다. preview는 파일·DB 읽기 전용이다. |

기존 JSON 관리 성공200은 `schema_version:local-management-result-v1,request_sha256,data`다. request_sha256은 수신한 원래 bytes의 SHA이며 data는 기존 서비스 결과 record다. multipart 성공은 별도 `source-upload-result-v1`이며 문서/버전·원문/본문/AI입력 hash·전처리/검토 범위·기존 import 결과를 반환한다. multipart 전체 bytes의 SHA를 반환한 것으로 해석하지 않는다. 상태를 자동 승인/공개로 보정하지 않는다. 오류는 기존 `error:{code,message,field_errors,retryable},request_id`이며 입력422·미등록404·충돌409·응답 media406·DB/실행환경 미준비503·내부500을 구별한다. JSON을 허용하지 않는 Accept도406 JSON 오류로 반환한다. 원문·키·SQL·절대 경로·stack은 반사하지 않는다.

## 원본 보관·미완료

추출 초기/slot 성공은 별도 `extraction-upload-result-v1`의6키이며 고정 파일명·size/hash만 제공한다. finalize는 기존 `local-management-result-v1`과 수신 control 원bytes hash를 반환한다. request root의 `extraction-uploads/`에는 초기 원본·slot·불변 index와 size/hash 기록을 함께 보존한다. 기존 flat JSON과 구별하며 [정확 재시도·중단 복구 계약](extraction-upload.md)을 따른다.

인증을 통과한 인식 가능한 기존 JSON 관리 요청은 private request root0700의 `<sha256>.json`0600에 원래 bytes로 보관한다. 배타 원자 설치·동일 bytes 무쓰기 재사용·symlink/기존 내용 충돌 거부를 적용한다. 파일 저장 실패면 DB를 호출하지 않는다. 인증/본문 한도/잘못된 JSON·미지원 schema는 보관하지 않으며 preview도 파일을 만들지 않는다.

보관한 요청은 CLI에서 사용자가 보존하던 입력 JSON에 해당한다. 파일 보관과 DB 성공은 별개이며 domain 실패가 성공 batch를 만들지 않는다. 기존 DB의 실패 batch 영구 기록을 추가하지 않는다. 운영자는 source·extraction·handoff·request root를 함께 백업하고 접근·보존 정책을 정한다. 전원 중단 내구성을 시험 완료로 표시하지 않는다.

업로드는 source root의 `uploads/<raw_sha256>.<format>`, request root의 `uploads/bundles/<server UUID>/` 네 파일(metadata.json·source-import.json·input.json·receipt.json), `uploads/<document_version_id>.json` 완료 index와 기존 flat metadata/source-import SHA JSON을 함께 보존한다. 검증을 마친 묶음만 index hard link로 배타 설치하며 DB 실패 뒤에도 raw·완료 준비본은 재시도에 사용한다. 정확한 재요청은 PDF를 다시 변환하지 않고 첫 준비본을 재사용하며 다른 metadata/file bytes는409다. [백업 안내](../backend/docs/backup-recovery.md)에 따라 두 root와 DB를 함께 같은 원래 경로로 복원한다. S10은 raw20MiB 전체·AI artifact8MiB·총 JSON/HTML64MiB 한도를 적용한다.

준비된 JSON·원문·보관본 연결과 txt/pdf/json 업로드·텍스트화는 구현했으며, 원문 업로드의 전체 회귀·리뷰·PR/CI·통합 결과는 [계획](../docs/superpowers/plans/2026-11-05-document-upload.md)에서 추적한다. 수동 추출 업로드의 실제 DB/JAR·복구·전체 회귀·리뷰/통합은 [별도 계획](../docs/superpowers/plans/2026-11-05-extraction-result-upload.md)을 따른다. 관리 UI·실제 AI 품질/PDF 완전성·개인정보/사용권·사람 검토/승인·독립 gold/40문서/90%·실기기·운영 배포/main 인수는 후속 범위다. 합성 HTTP/DB 시험으로 해당 실적을 대신하지 않는다.
