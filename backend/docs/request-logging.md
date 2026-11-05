# 최소 요청 로그

공개 웹 프로세스는 요청 종료 때 `public_request ` 뒤에 compact JSON 한 건을 INFO로 남긴다. `/health`, 알 수 없는 경로, CORS 거부, 본문 제한 오류도 포함한다. 현재 동기 API 대상이며 로컬 파일 명령에는 웹 필터가 등록되지 않는다.

```json
{"request_id":"37d9f0b8-424f-5145-9329-e71ffd6413e3","error_code":null,"latency_ms":12,"snapshot_id":null,"rules_version":null}
```

| 필드 | 기록 기준 |
| --- | --- |
| `request_id` | 서버가 요청마다 생성한 UUID. `X-Request-ID` 응답 헤더와 오류 본문의 기존 `request_id`가 같다. 클라이언트가 보낸 ID는 사용하지 않는다. |
| `error_code` | 공통 오류 코드. 관찰한 코드 없이 HTTP 오류가 끝나면 `HTTP_403` 같은 상태 코드, 처리 중 예외가 전파되면 `INTERNAL_ERROR`. 정상은 null. |
| `latency_ms` | 필터 진입부터 종료까지 단조 시계로 측정한 밀리초. 기기·네트워크 전체 응답시간이나 성능 합격 판정은 아니다. |
| `snapshot_id` | 실제 검증·선택한 공개본의 canonical UUID. fixture는 응답의 기술 필드만 사용하며, 선택 전 실패는 null. |
| `rules_version` | 선택본에서 확인한 규칙 버전. 없는 값은 null이며 과거 이력·재현 목록·퇴역 오류의 `current_snapshot_id`로 대체하지 않는다. |

오류 응답의 JSON 필드·상태·메시지는 유지한다. 계산 실패에도 이미 확인한 선택본 버전을 남긴다. 상세 응답에 규칙 버전이 없어도 서비스가 확인한 값은 보존한다. Python `calc-v1`의 요청 ID는 계산 응답 대조용으로 별도 유지한다.

본문·URI/query·IP·Origin·User-Agent·영업시간·예외 메시지/stack을 이 로그에 넣지 않는다. 버전은 최대100 UTF-16자이며 비공백 값만 허용한다. 제어문자·줄/문단 구분자·format 문자·잘못된 surrogate가 있으면 null로 기록한다. 정상 Unicode는 유지하고 JSON으로 escape한다. 오류 코드는 최대100자의 대문자·밑줄로 제한한다.

브라우저에서는 허용된 origin에 `Access-Control-Expose-Headers: X-Request-ID`를 제공한다. 허용 origin·메서드·요청 헤더는 기존 CORS 설정을 따른다. 진단 시 응답 ID로 콘솔의 같은 `request_id`를 찾는다. 로그를 보려면 `kr.ac.myai.backend.logging.PublicRequestLogFilter`의 INFO 출력을 유지한다.

요청 저장 테이블·추적 서버·기본 보존 일수는 추가하지 않는다. 운영 로그의 수집 위치·접근 담당·보존/종료 기준과 프록시 access log 정책은 배포 담당자가 확정해야 한다. 이 구현의 합성 시험을 실제 자료 품질·기기 성능·운영 배포 검증으로 집계하지 않는다.
