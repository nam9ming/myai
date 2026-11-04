# 로컬 관리 HTTP 계약

B05/I10/I11의 구현 계획용 계약이다. 현재 브랜치의 실제 구현·검증 상태는 [계획](../docs/superpowers/plans/2026-11-04-local-management-api.md)의 체크박스를 따른다. 기존 CLI·공개 I01~I03은 유지한다.

## 실행 경계

`local-api` 단독 servlet 프로필만 사용한다. bind는127.0.0.1, 기본 port8081이며 다른 port와0번 임시 port를 명시할 수 있다. 공개/fixture/CLI 혼합·외부 bind·forwarded-header 처리·빈 필수 설정을 기동 전에 거부한다. 공개 앱에는 `/local` controller가 없으며, 로컬 앱에는 공개 API controller가 없다.

필수 설정은 `MYAI_LOCAL_API_TOKEN/ACTOR/SOURCE_ROOT/EXTRACTION_ROOT/HANDOFF_ROOT/REQUEST_ROOT`와 선택 `MYAI_LOCAL_API_PORT`다. token은 실행 전에 새로 준비한32~128자리 `[A-Za-z0-9_-]` 문자열이다. 소스·URL·로그·응답에 넣지 않는다. root는 운영자가 지정한 절대 private 디렉터리이며 client가 임의 root를 전달하지 않는다.

모든 로컬 HTTP 요청은 `Authorization: Bearer <token>`, `Origin: http://127.0.0.1:<실제 port>`, 같은 Host를 요구한다. 실제 loopback socket·서버 port로 비교하며 forwarded header를 신뢰하지 않는다. 토큰 오류401, origin/host/socket 오류403이며 body를 읽거나 보관·domain 호출하기 전에 거부한다. encoded path·OPTIONS·오류 경로로 우회하지 않는다.

## 요청·결과

JSON 원문은 UTF-8·최대8MiB다. Content-Length 유무와 무관하게 실제 stream에서 검사하고 초과는413, 다른 media는415다. 중복/추가키·후행 JSON·잘못된 타입/ID/상태는 기존 strict reader로 거부한다. 공개 body32KiB와 기존 CLI8MiB를 바꾸지 않는다.

| 경로 | 원본 JSON | 결과·제한 |
| --- | --- | --- |
| POST `/local/documents` | `source-import-v1` | D03만 등록. 기존 문서 버전·원문/hash/검토 상태를 검증한다. |
| POST `/local/extractions/import` | 정확히 `schema_version:extraction-import-request-v1,run_id,expected_input_hash` | 명시 D05의 전체 보관본을 검증하며 input SHA 불일치는 DB 저장 전에 거부한다. 사건/공개를 만들지 않는다. |
| PUT `/local/events/{id}/review` | `reviewed-import-v1`, `human-handoff-import-v1` 또는 `publication-command-v1` approve/reject | 명시 사건1개만 허용하며 URL ID와 events[0]/revisions[0]/event_id가 같아야 한다. expected 번호·근거·AI/사람 수정 원본을 보존한다. |
| POST `/local/reviews/import` | `reviewed-import-v1` 또는 `human-handoff-import-v1` | 기존 다중 사건 배치 전체를 명시적으로 저장한다. 인계 이미지를 임의로 잘라 단일 사건 요청으로 바꾸지 않는다. |
| POST `/local/publish` | `publication-command-v1` preview/publish/rollback | 기존 승인·사용권·원문 확인·5지점·mode·revision/head 검사를 그대로 실행한다. preview는 파일·DB 읽기 전용이다. |

성공200은 `schema_version:local-management-result-v1,request_sha256,data`다. request_sha256은 수신한 원래 bytes의 SHA이며 data는 기존 서비스 결과 record다. 상태를 자동 승인/공개로 보정하지 않는다. 오류는 기존 `error:{code,message,field_errors,retryable},request_id`이며 입력422·미등록404·충돌409·DB/실행환경 미준비503·내부500을 구별한다. 원문·키·SQL·절대 경로·stack은 반사하지 않는다.

## 원본 보관·미완료

인증을 통과한 인식 가능한 관리 요청은 private request root0700의 `<sha256>.json`0600에 원래 bytes로 보관한다. 배타 원자 설치·동일 bytes 무쓰기 재사용·symlink/기존 내용 충돌 거부를 적용한다. 파일 저장 실패면 DB를 호출하지 않는다. 인증/본문 한도/잘못된 JSON·미지원 schema는 보관하지 않으며 preview도 파일을 만들지 않는다.

보관한 요청은 CLI에서 사용자가 보존하던 입력 JSON에 해당한다. 파일 보관과 DB 성공은 별개이며 domain 실패가 성공 batch를 만들지 않는다. 기존 DB의 실패 batch 영구 기록을 추가하지 않는다. 운영자는 source·extraction·handoff·request root를 함께 백업하고 접근·보존 정책을 정한다. 전원 중단 내구성을 시험 완료로 표시하지 않는다.

이번 구현은 준비된 JSON·원문·보관본을 연결한다. txt/pdf 새 업로드·텍스트화와 제안20MiB/200000문자/AI5MiB 경로, 관리 UI·실자료 사람 검토·독립 gold/40문서/90%·실기기·운영 배포/main 인수는 후속 범위다. 합성 HTTP/DB 시험으로 해당 실적을 대신하지 않는다.
