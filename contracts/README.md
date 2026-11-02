# 연결 규격 초안 v0.1

프런트·백엔드·AI 담당이 같은 필드와 상태를 사용하기 위한 기준입니다. 상세 모델/필드 검증은 [데이터·AI 명세](../docs/spec/03_데이터와AI.md), 시간·거리·중복 규칙은 [계산·API 명세](../docs/spec/04_계산규칙과기술설계.md)를 따릅니다.

**examples는 모두 합성 자료입니다.** 예제의 거리·지점·날짜·근거·확인값은 가상이고 example.org 링크는 실제 공지가 아닙니다. 이 응답은 화면 연결용이며 실제 지명/원문 검토·AI 실행·거리 계산을 완료한 데이터가 아닙니다.

## 세 API

내부 경로는 아래와 같습니다. 외부 하위경로 접두사는 배포 시 별도 설정합니다.

| ID | 요청 | 예제 | 응답 |
|---|---|---|---|
| I01 | GET `/api/v1/config?mode=current` | [config-response.json](examples/config-response.json) | 지점5개·14일/500m·시간대·자료 범위 |
| I02 | POST `/api/v1/matches` | [matches-request.json](examples/matches-request.json) | [matches-response.json](examples/matches-response.json) |
| I03 | GET `/api/v1/events/{event_id}?snapshot_id=…` | matches 항목의 event_id 사용 | [event-response.json](examples/event-response.json) |

JSON 응답의 공통 껍데기는 `schema_version / snapshot_id / generated_at / data`입니다. 실제 구현 시 `schema_version="api-v1"`로 시작하고 호환성에 영향을 주는 변경을 함께 협의합니다. 예제 response의 `data_kind="synthetic"`는 data 안에 있습니다. 실제 공개자료와 가상자료를 구분하는 표시가 UI까지 이어져야 합니다.

### 조건 요청

- `point_id`: config의 활성 지점ID 하나.
- `weekly_hours`: monday~sunday 객체, 각 `state=unknown|open|closed`, `full_day`, `intervals`.
- interval: `start/end` HH:mm, `end_day_offset=0|1`. full_day=true이면 intervals=[].
- `mode=current|replay`, `case_id`: current이면 null, replay이면 등록된 ID 필요.
- `types`: construction/event/traffic의 OR 필터, 빈 배열은 전체.
- `selection=candidate|needs_check|cancelled`, 기본candidate.
- `sort=start|distance`, 기본start.
- `snapshot_id`: 최초 null 허용. 응답의 snapshot_id로 결과를 고정.

요청에 radius/window 기준일을 임의로 받아 의미를 바꾸지 않습니다. KST의 오늘 포함14일·500m를 서버 설정으로 적용합니다. 예제 날짜는2026-11-06으로 고정된 합성 시연입니다.

### 선별 응답

- `counts`: 유형 필터 후 selection 이전의 고유 사건 수. 후보/확인필요/취소를 합쳐 후보 수로 표시하지 않습니다.
- `items`: 선택한 상태의 사건 목록. 예제 request의 selection=candidate와 연결된 예제 response에는 후보2개만 있습니다.
- `query_context`: 실제 적용한 지점·시간창·영업조건·거리기준·모드.
- `overlap_groups`: 확정된 후보 사건 사이 실제 공통 시간 구간과 event_ids. 카드 수에 추가하지 않습니다.
- `classification`: candidate/needs_check/cancelled. excluded는 공개 목록에 넣지 않고 내부 시험 결과에 기록합니다.
- `distance_m`, `time_overlap_minutes`: 모르면 null이며0으로 바꾸지 않습니다.
- 원문 사실·코드 계산 결과·이용자 확인 항목은 UI에서 구분합니다. 근거리라는 이유로 통행/매출 영향을 단정하지 않습니다.

예제 데이터4개 전체는 [public-events.json](examples/public-events.json)에 있습니다. 서로 다른 selection 예제를 만들 때 counts는 동일 필터 기준으로 유지하고 items만 선택합니다.

### 실패

[error-response.json](examples/error-response.json): `error.code / message / field_errors / retryable`, `request_id`. 입력422·미등록404·버전충돌409·미준비503·기타500을 구분합니다. 실제 traceback·비밀키·비공개 원문 경로를 공개하지 않습니다.

## AI → 검토 → 저장

[ai-extraction.json](examples/ai-extraction.json)은 `extract-schema-v1` 형식의 **가상 추출 원출력**입니다. 같은 폴더의 [ai-input.json](examples/ai-input.json)에 대응합니다.

AI 원출력을 공개 API 응답으로 바로 사용하지 않습니다. 사람의 원문 대조·수정·장소 검토·시간 정규화·상태 관계 확정을 거쳐 backend가 관리하는 공개 데이터로 변환합니다. 바뀐 값과 이유·근거·입력/출력 버전은 분리 보존합니다. 예제에 사람 검토가 완료됐다는 실제 실적은 없습니다.

## 확인

Python 표준 라이브러리만 사용합니다.

```text
python contracts/validate_examples.py
```

이 검사는 JSON 예제 사이 ID·상태·counts·기간·근거 인용의 연결을 확인합니다. 앱 구현 시험, 공식자료 정확도나 AI 성능 평가를 대신하지 않습니다. 실제 구현 시 JSON Schema와 요청/응답 모델 검증은 담당자가 추가합니다.
