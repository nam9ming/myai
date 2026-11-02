# Spring → Python 계산 CLI 계약 v1

담당: 김윤기(계산 함수·CLI), 강명묵(Java adapter), 남규민(통합 확인). 공개 API I01~I03의 필드·응답은 변경하지 않습니다. Python `rules-v1` 계산 CLI를 구현했으며 Java adapter는 후속 작업입니다. 실제 실행·시험은 [processing 안내](../processing/README.md)를 따릅니다.

## 경계

Spring은 요청을 검증하고 DB의 승인된 불변 snapshot·지점·원문 확인 상태를 선택합니다. Python은 C01~C10에 따라 계산한 후 public matches 응답의 data를 반환합니다. AI 호출·DB 조회/쓰기·임의 URL 요청·사용자 조건 영구 저장은 계산기에 없습니다. Java와 Dart는 별도 판정 엔진을 만들지 않습니다.

초기 연결은 한 요청에 하나의 CLI 프로세스로 단순화합니다. 실행 비용과 응답 시간을 실제로 측정하고, 추후 지속 프로세스가 필요하면 프로토콜을 유지한 별도 변경으로 기록합니다. 현재 방식으로 성능 목표가 달성됐다고 가정하지 않습니다.

## 실행

설정된 Python3.13 실행 파일로 저장소 루트에서 `-m processing.matching`을 실행합니다. Java ProcessBuilder의 인자 배열을 사용하고 shell·사용자 입력으로 실행 명령/경로를 구성하지 않습니다. Python 실행 경로·workdir은 서버 설정으로 고정합니다.

stdin은 UTF-8 JSON 객체 한 건 후 EOF, stdout은 UTF-8 JSON 객체 한 건입니다. Java는 stdout/stderr를 함께 배출해 파이프 대기를 방지하고 크기 제한·timeout·종료 코드·응답 스키마를 확인합니다. timeout 기본5초(설정값), 입력/출력 각각8MiB이며 변경하면 시험을 갱신합니다. 초과·시간초과 시 자식 프로세스를 종료하고 현재 공개 데이터는 변경하지 않습니다. CLI 종료 코드는 성공0, 입력 오류2, 출력 초과3, 런타임 실패1입니다. 실패 시 stdout은 비어 있고 stderr에는 각각 `CALCULATION_INPUT_INVALID`, `CALCULATION_OUTPUT_TOO_LARGE`, `CALCULATION_FAILED`만 남깁니다.

## 입력 객체

| 필드 | 계약 |
|---|---|
| protocol_version | `calc-v1` |
| request_id | Spring이 만든 요청 ID |
| snapshot_id, snapshot_checksum | 선택한 D07의 ID·정규화 JSON SHA-256 |
| context | `mode`, `case_id`, `server_now`, `anchor_date`, `reference_instant`, `knowledge_cutoff`, `history_fidelity`, `data_kind`, `window_days=14`, `radius_m=500`, `rules_version`, `dictionary_version` |
| point | `point_id`, 검토된 WGS84 `longitude`, `latitude`. 이용자 좌표 문자열로 대체하지 않음 |
| query | 공개 matches-request와 같은 D02 객체. Spring이 검증·정규화한 값 |
| events | 선택 snapshot의 D06 계산용 사건 revision 목록. occurrences·locations의 geometry/coverage·근거·lifecycle·source_version_ids를 포함 |
| source_versions | D03의 공개 출처 정보와 해당 버전의 마지막 성공 확인·이후 check_result 등 C08 판정에 필요한 기록 |

current 기준일은 server_now의 Asia/Seoul 날짜이며 Java가 계산해 context.anchor_date에 전달하고 Python이 일치 여부를 검증합니다. current의 case/reference/cutoff/history_fidelity는 null입니다. replay는 D07의 고정 anchor/reference/cutoff/history_fidelity를 사용합니다. data_kind도 D07에서 전달합니다. UTC 시각은 소수9자리까지 검증하며 최신성 비교에서 나노초를 버리지 않습니다. 조회창·전날을 표현할 수 없는 날짜는 거부합니다. client 제공 날짜를 현재 기준일로 신뢰하지 않습니다. query의 mode·case·point는 선택 context와 같아야 하며 snapshot_id는 null 또는 선택 ID입니다. query의 selection/sort 기본값은 Java가 명시적으로 전달합니다.

events/source_versions는 `PublicationContent`가 생성한 snapshot-v1의 event_public_payloads/sources 구조 그대로입니다. 모든 키는 필수이며 nullable 값도 null 키로 전달합니다. 모르는 키·중복 ID·참조 누락·구역 밖·미지원 규칙 버전은 거부합니다. current는 성공 확인 없는 출처를 거부하고, reconstructed replay에서만 당시 확인 null을 보존합니다. source_version_ids에 선택된 모든 출처의 최신성을 검사하며 다른 사건의 출처는 분류에 사용하지 않습니다. Java가 승인·사용권·원문 hash·snapshot checksum을 검증합니다. Python에는 전체 원문이나 canonical snapshot 바이트가 없으므로 그 검증을 대체하지 않습니다.

exact_time의 다른 종료 날짜는 명시된 datetime 끝이며 같은 날 시각 쌍의24시간 제한을 적용하지 않습니다. 같은 날짜 표기와 recurrence의 날짜에는 end_day_offset을 적용하고 시각+offset의 길이를 검사합니다. 종료 날짜가 이미 익일이면 offset을 이중 적용하지 않습니다. 부분 시간도 명시된 종료 날짜·시각을 넘겨 늘리지 않으며, 같은 날짜 표기의 미상 offset은 가능한 익일 종료를 남깁니다. recurrence_dates=null은 연속 구간, []는 발생 없음입니다. unknown 영업일은 그날 시작할 수 있는 최대24시간 구간의 합집합인 그날00시~다음다음날00시를 가능 범위로만 사용합니다. 알려진 영업이 덮은 부분은 다시 미상으로 계산하지 않습니다.

snapshot 내부에 필요한 좌표·시간·관계가 미상인 경우 원래 unknown을 보존합니다. 정상 값으로 채워넣지 않습니다. 공개 응답 예제 `public-events.json`은 특정 조회 결과를 설명하는 자료이므로 이 입력으로 그대로 사용하지 않습니다. D06 원본 입력은 03 데이터 계약에 맞춰 별도로 조립합니다.

## 출력 객체

| 필드 | 계약 |
|---|---|
| protocol_version, request_id, snapshot_id | 입력과 동일 |
| input_sha256 | 입력 stdin UTF-8 원본 바이트의 SHA-256. Spring이 실제 전송 바이트로 대조 |
| rules_version | 요청한 계산 규칙 버전과 일치 |
| data | matches-response.json의 data와 같은 구조: data_kind·query_context·counts·items·overlap_groups 등 공개 계약 필드 전체 |
| diagnostics | 내부 검증용 제외 사유 등. 개인 조건 원문은 기본 로그에 쓰지 않고 공개 응답에 포함하지 않음 |

data는 계산 결과이며 DB 사실로 영구 덮어쓰지 않습니다. Spring이 ID·hash·규칙 버전·필수 필드를 검증하고 기존 `{schema_version,snapshot_id,generated_at,data}` 응답으로 한 번만 감쌉니다. 이중 envelope를 만들지 않습니다. data의 전체 필드명은 현재 공개 예제를 따르고 임의 새 alias를 만들지 않습니다.

## 실패 매핑

| 상황 | 외부 응답 |
|---|---|
| 공개 사용자 요청이 잘못됨 | Python 실행 전422 VALIDATION_ERROR |
| DB/snapshot 또는 계산 런타임이 미준비 | 503 DATA_NOT_READY / CALCULATION_UNAVAILABLE |
| 계산 timeout·기동 불가·비정상 종료 | 503 CALCULATION_UNAVAILABLE, retryable 여부를 원인에 맞게 지정 |
| 응답 JSON·hash·snapshot·규칙 버전 불일치 | 500 CALCULATION_PROTOCOL_ERROR, 내부 진단만 남김 |
| 공개 snapshot 미등록/폐기 | 기존404/409 계약 적용 |

오류는 contracts/error-response의 envelope를 사용합니다. traceback·명령 전체·로컬 경로·DB 정보·키는 공개하지 않습니다. 계산 실패를 결과0건으로 바꾸거나 고정 fixture를 실제 계산처럼 반환하지 않습니다. fixture 시연은 별도 명시 모드입니다.

## 반드시 확인할 연결 시험

1. 같은 입력·snapshot·버전은 같은 분류·거리·중첩을 반환합니다. 서버 응답 생성 시각은 비교에서 분리합니다.
2. C01~C10의 14일·자정·500m·미상·취소·동시간 묶음 경계를 CLI와 API 양쪽에서 확인합니다.
3. JSON의 한글·emoji·null·숫자 정밀도·근거 문자 offset을 보존합니다.
4. stdout 오염·stderr 대량 출력·timeout·비정상 종료·구버전·snapshot 불일치에서 정해진 오류를 반환합니다.
5. MySQL 사실/공개 snapshot·사용자 조건은 계산 요청으로 인해 변경되지 않습니다.
