# 로컬 관리 HTTP API

B05/I10/I11의 문서·AI 실행 등록, 검토 수정/승인, 공개 미리보기·공개·복구를 HTTP로 연결한다. 기존 [파일 import](reviewed-import.md)·[AI 실행 등록](extraction-run-import.md)·[사람 인계](human-handoff-import.md)·[승인·공개](review-publication.md)의 JSON과 서비스를 사용한다. 현재 검증 상태는 [구현 계획](../../docs/superpowers/plans/2026-11-04-local-management-api.md)을 따른다.

## 실행 준비

Java21·MySQL8.4와 [백엔드 실행 설정](../README.md)을 먼저 준비한다. AI 보관본 검증에는 Python3.13과 같은 버전의 `processing/`이 필요하다. Java 관리 서버가 OpenAI를 호출하지는 않는다.

아래는 새 개발 DB와 합성 예제를 위한 설정이다. 실제 자료에서는 원문 상대 경로의 기준과 선택한 추출·사람 인계 보관 root로 바꾼다. root를 바꾸면 기존 등록 자료의 출처를 다시 확인해야 한다.

```bash
# myai 저장소 루트에서 실행
umask 077
export MYAI_LOCAL_API_TOKEN="$(python3.13 -c 'import secrets; print(secrets.token_urlsafe(32))')"
export MYAI_LOCAL_API_ACTOR=local-developer
export MYAI_LOCAL_API_PORT=8081
export MYAI_LOCAL_API_SOURCE_ROOT="$(pwd -P)/backend/examples"
export MYAI_LOCAL_API_EXTRACTION_ROOT="$(pwd -P)/data/private/local-api/extractions"
export MYAI_LOCAL_API_HANDOFF_ROOT="$(pwd -P)/data/private/local-api/handoffs"
export MYAI_LOCAL_API_REQUEST_ROOT="$(pwd -P)/data/private/local-api/requests"
export MYAI_PYTHON_WORKDIR="$(pwd -P)"
export MYAI_PYTHON_EXECUTABLE=python3.13
mkdir -p "$MYAI_LOCAL_API_EXTRACTION_ROOT" "$MYAI_LOCAL_API_HANDOFF_ROOT" "$MYAI_LOCAL_API_REQUEST_ROOT"
chmod 700 "$MYAI_LOCAL_API_EXTRACTION_ROOT" "$MYAI_LOCAL_API_HANDOFF_ROOT" "$MYAI_LOCAL_API_REQUEST_ROOT"
./backend/gradlew -p backend bootJar
java -jar backend/build/libs/myai-backend-0.1.0.jar --spring.profiles.active=local-api &
MYAI_LOCAL_API_PID=$!
```

DB 환경변수는 기존 안내대로 별도 제공한다. `.env` 파일을 작성하는 것만으로 Java 프로세스에 환경변수가 등록되지는 않는다. 필수 `MYAI_LOCAL_API_*` 값은 실제 프로세스 환경으로 제공하며 다른 application property로 대체할 수 없다. 토큰은 실행 전에 새로 만들고 소스·URL·로그·공개 파일에 남기지 않는다. actor는 비어 있지 않은128자 이하이며 제어문자를 허용하지 않는다.

`local-api` 단독 프로필·servlet·127.0.0.1 bind·forwarded-header 처리 NONE만 허용한다. 공개/fixture/CLI 프로필 혼합과 빈 설정은 DB·웹 기동 전에 거부한다. 공개 서버와 별도 프로세스로 실행하며 공개 리버스 프록시에 관리 경로를 연결하지 않는다. 위 백그라운드 실행은 같은 셸에서 `kill "$MYAI_LOCAL_API_PID"`로 종료한다. 다른 프로세스의 PID를 사용하지 않는다.

## 인증과 호출

모든 경로에 Bearer 토큰, 실제 서버 port의 `Origin: http://127.0.0.1:<port>`, 같은 Host가 필요하다. `localhost`·다른 port·누락/`null` Origin·중복 인증 헤더는 허용하지 않는다. 실제 HTTP port80에서만 기본 port 생략과 `:80`을 동등하게 취급한다. forwarded 헤더로 실제 socket·Host 검사를 대체할 수 없다.

같은 셸에서 서버 기동 후 합성 문서만 등록하는 예다. 인증 없는 `/local/documents` 요청의401 응답으로 먼저 기동을 확인할 수 있다. 같은 원문 파일이 준비된 source root와 연결해야 한다.

```bash
curl --fail-with-body --noproxy '*' \
  -H "Authorization: Bearer $MYAI_LOCAL_API_TOKEN" \
  -H "Origin: http://127.0.0.1:$MYAI_LOCAL_API_PORT" \
  -H 'Content-Type: application/json' \
  --data-binary @backend/examples/source-import.json \
  "http://127.0.0.1:$MYAI_LOCAL_API_PORT/local/documents"
```

`--data-binary`로 원래 bytes를 보낸다. 성공200은 `schema_version=local-management-result-v1`, `request_sha256`, 기존 서비스의 `data` 결과를 반환한다. 같은 의미의 JSON도 공백이 다르면 요청 hash가 달라진다. 사람 인계도 수신 bytes를 직접 검증해 DB hash를 연결하며 보관 파일의 재읽기로 요청을 바꾸지 않는다. 동일한 bytes의 보관 파일은 덮어쓰지 않는다.

| 경로 | 입력·동작 |
| --- | --- |
| POST `/local/documents` | `source-import-v1`. 문서만 등록하며 사건·공개본을 만들지 않는다. |
| POST `/local/extractions/import` | `extraction-import-request-v1`의 `run_id`·`expected_input_hash`. 지정 root의 전체 보관본과 입력 SHA를 확인한 뒤 D05를 저장한다. 실패 실행도 실패로 보존한다. |
| PUT `/local/events/{id}/review` | 사건1개의 `reviewed-import-v1`/`human-handoff-import-v1`, 또는 `publication-command-v1` approve/reject. URL과 JSON 사건ID가 같아야 한다. |
| POST `/local/reviews/import` | 다중 사건을 포함한 기존 검토/사람 인계 배치 전체. 동결한 인계 이미지를 잘라서 보내지 않는다. |
| POST `/local/publish` | `publication-command-v1` preview/publish/rollback. 기존 revision·head 번호·근거·확인/사용권·공개 조건을 그대로 검사한다. |

승인과 공개는 별도 명령이다. AI 초안을 직접 승인하거나 미검토 자료를 자동 공개하지 않는다. `preview`는 요청 파일과 DB를 변경하지 않는다. 공개 서버에는 `/local`이 없고, 관리 서버에는 `/api/v1`·`/health`가 없다.

## 한도·오류·원본

JSON은 UTF-8·최대8MiB이며 Content-Length 없이 전송해도 실제 stream을 제한한다. 공개 API의32KiB 제한과 기존 CLI 제한은 유지한다. 추가/중복키·후행 JSON·잘못된 ID/상태는 거부한다.

오류는 기존 `error`·`request_id` 형식이다. 인증401, 출처403, 본문 초과413, 요청 media415, 응답 media406, 입력422, 미등록404, 충돌409, DB/실행환경 미준비503, 내부500을 구별한다. JSON을 허용하지 않는 Accept에도406 JSON 오류를 반환한다. 응답의 request_id와 `X-Request-ID`는 같은 서버 ID이며 원문·토큰·절대 경로·SQL·stack은 반사하지 않는다.

알려진 관리 요청의 원본은 request root0700 아래 `<sha256>.json`0600에 배타 설치한다. root 경로의 symlink·공개 권한이나 기존 파일 충돌을 거부한다. 저장 실패면 domain 서비스를 호출하지 않는다. 인증 실패·초과·잘못된 JSON·알 수 없는 schema·preview는 파일을 만들지 않는다. 알려진 요청의 domain 실패 원본은 남을 수 있으며 파일 보관 성공과 DB 저장 성공은 별개다.

source·extraction·handoff·request root를 함께 백업하고 [복구 안내](backup-recovery.md)를 따른다. 관리자는 원본의 접근·보존·삭제 정책을 정해야 한다. POSIX 권한·hard link를 지원하는 파일시스템이 필요하며 전원 중단 내구성을 검증한 결과는 아니다.

## 남은 범위

이 API는 준비된 JSON·원문·보관본을 연결한다. txt/pdf 새 업로드·텍스트화와 제안20MiB/200000문자/AI5MiB 경로, 관리 UI, 실제 사람 검토·독립 정답표·40문서/90% 평가·사용자 평가·운영 배포는 별도 후속 작업이다. `main` 병합·배포는 사람이 진행한다.
