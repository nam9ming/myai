# 장문 분할 추출

장문 분할의 `extraction-archive-v2` 계약이다. 기존 [archive-v1](extraction-run.md)·prompt-v1/v2 바이트/재검증은 유지한다. 실제 API 결과·사람 검토 성과를 뜻하지 않는다.

## 실행과 분할 계획

새 API 실행에서 전체 prompt-v2 첫 요청 body가131072bytes 이하이면 기존 v1 경로다. 초과이면 prompt-v3·v2 archive로 분할한다. 입력 ai-input-v1 전체5키·D03 원문과 출력 extract-schema-v1 전체5키는 유지한다. 같은 완료 ID는 저장된 형식으로 검증해 키 없이 재사용하며 중단 ID는 자동 전송하지 않는다.

팀 정책은 `request-bytes-v1`: 요청 body131072bytes·피드백 여유4096bytes·인접 이전 block1개 중복이다. 공급자 token 한도가 아니며 token 수를 환산하지 않는다. 새 실제 API 없이 합성 응답으로 검증한다.

`chunk-plan.json`은 canonical `_json`이며 정확히 다음 키다.

| 키 | 값 |
| --- | --- |
| schema_version / policy_version | extraction-chunk-plan-v1 / request-bytes-v1 |
| input_sha256 / model / prompt_version | 전체 원입력 bytes SHA / 선택 model / prompt-v3 |
| request_limit_bytes / feedback_reserve_bytes / overlap_blocks | 131072 / 4096 / 1 |
| status / error_code | ready/null 또는 requires_review/CHUNK_REQUEST_LIMIT |
| chunks | 원문 순서의 chunk 배열 |

각 chunk의 정확한 키는 `chunk_id,core_start,core_end,context_start,core_block_ids,context_block_ids,request_sha256,request_bytes`다. ID는 `chunk-000001`부터 연속이다. core는 원래 block 순번의 `[start,end)`, 첫 context_start=0·그 밖은 core_start-1이며 context는 직전 block1개다. 전체 core는 빈틈·중복 없이 모든 block을 덮는다. ID/text/page·block 내부 code point offset/hash는 변경하지 않는다. 같은 예산에서 가장 긴 연속 core를 선택한다.

request hash/bytes는 해당 chunk의 v3 첫 요청을 실제 직렬화한 값이며 base body는 limit-reserve 이하다. 단일 core block과 필수 context조차 초과하면 그 core1개를 별도 chunk로 기록하고 나머지 계획도 완성하되 전체 requires_review로 둔다. 이 예외는 API0·문서 실패이며 원문을 자르거나 일반 장문 전체를 거부하는 대안이 아니다.

v3 prompt는 기존 source 부분집합·block_metadata와 `chunk` 객체를 추가한다. chunk 객체는 `chunk_id,core_start,core_end,context_start,core_block_ids,context_block_ids`만 담는다. 부분 문맥임과 `CHUNK_CONTEXT_PARTIAL` 경고를 요구하며, 전송하지 않은 block 인용·문서 전체 not_stated 추정은 거부한다. 각 chunk 출력은 실제 전송한 blocks로 parse_output한 뒤 재귀적인 not_stated 금지·경고를 검사한다. 미관측은 null/ambiguous/reason을 사용한다.

## 문서 cycle와 원출력

metadata는 기존 정확한 키를 유지하고 `attempts=문서 cycle 수(1~3)`, prompt_version=prompt-v3·execution_mode=api다. 각 cycle은 모든 chunk에 최대1요청이며 chunk 내부 재시도는 없다. retryable 실패만 기존1초/2초 뒤 전체 새 cycle로 재시도한다. 이전 성공 chunk도 다시 실행하며 새 cycle의 구조 feedback은 같은 chunk의 직전 schema 오류 경로만 쓴다.

영구 실패면 뒤 chunk는 미시도다. 계획 requires_review이면 cycle1만 기록하고 모든 chunk 미시도/API0이다. 실제 피드백 요청이 body 예산을 넘으면 CHUNK_REQUEST_LIMIT·review·재시도 불가로 보존한다. 어떤 chunk라도 실패/미시도이면 전체 cycle failed이며, 모두 validated이고 전체 결합도 검증될 때만 validated다. 실패 우선순위는 첫 재시도 불가 실패, 없으면 첫 실패다. 미시도는 선행 영구 실패에 딸린 표시이며 별도 재시도 원인을 만들지 않는다.

각 실제 subrequest는 `attempt-N-chunk-000001.prompt/.output/.response/.exchange`다. prompt/response/exchange는 기존 실제 요청 bytes·수신 bytes·5키 exchange와 동일하며 response_complete/부분 응답·실패도 보존한다. output은 실제 check_api_attempt가 돌려준 bytes다. 미시도 subrequest의 파일은 만들지 않는다.

`attempt-N.prompt`는 실제 단일 API 요청이 아닌 canonical 파생 manifest다. 정확한 키는 `schema_version:chunk-cycle-v1,cycle,chunk_plan_sha256,requests`이며 requests의 각 항목은 `chunk_id,attempted,error_path`다. error_path는 실제 전송한 구조 feedback 또는 null이다. `attempt-N.output`은 성공 cycle의 전체 파생 JSON이며 실패 cycle은 빈 bytes다. 부분 성공 원출력은 subrequest 파일에 남으며 빈 정상 JSON/NO_EVENT_FOUND로 바꾸지 않는다.

결합은 모든 chunk의 local item/occurrence/location/evidence ID와 참조를 결정적으로 namespace하고 원문 전체로 다시 검증한다. 같은 제목·날짜·주소·근거만으로 사건/occurrence를 융합·삭제하지 않는다. 전체 warning에는 `CHUNK_RELATIONS_REQUIRE_REVIEW`를 남긴다. 일부 chunk의 NO_EVENT_FOUND는 다른 chunk에 item이 있으면 전체 warning에서 제거하며, 모든 coverage가 성공하고 모두 사건0개일 때만 전체 NO_EVENT_FOUND를 남긴다. 원래 chunk output bytes는 변경하지 않는다.

원출력은 파일별 hash를 대조해 순차로 결합하고, 각 chunk 뒤 최종 warning을 포함한 canonical 전체 결과8MiB를 검사한다. 초과는 CHUNK_OUTPUT_LIMIT·review·재시도 불가인 문서 실패다. 이미 실행한 모든 chunk의 원출력은 보존하며 전체 실패 output은 빈 bytes로 남긴다. 일부 성공을 완성 문서로 내보내거나, 모든 chunk의 decoded 출력 객체를 무제한 메모리에 쌓지 않는다.

실제 호출 전체의 공급자 usage를 합산하고 한 호출이라도 미상이면 합계null이다. 호출0이면 usage0/0이며 실제 시작/종료 시각을 남긴다. 모델 세부버전·금액·통화는 추정하지 않는다. exchange 시각 순서·metadata 시작/끝·요청/응답·결합 결과를 오프라인으로 재계산한다.

## v2 archive exact 구조

identity의 키는 기존7키와 같으며 format_version만 extraction-archive-v2다. receipt는 기존12키에 `chunk_plan_sha256,total_calls`를 더한다. total_calls는 모든 cycle에서 실제 attempted=true인 HTTP 전송 시도 수이며 서버 수신·과금 완료를 인증하지 않는다. receipt.attempts는1~3개이며 각 항목은 기존 `attempt,status,error_code,error_path,failure_kind,retryable`에 `chunks`를 더한다.

각 chunks 항목은 정확히 `chunk_id,attempted,status,error_code,error_path,failure_kind,retryable`다. attempted=false는 status=not_attempted, error_code=CHUNK_REQUEST_LIMIT(계획 불가) 또는 CHUNK_NOT_ATTEMPTED(선행 영구 실패), error_path=null, failure_kind=review,retryable=false다. 실제 요청 body 초과도 attempted=false·CHUNK_REQUEST_LIMIT이다. attempted=true 결과5키는 실제 검사에서 재계산한다.

artifact 집합은 정확히 input.json·metadata.json·chunk-plan.json, 각 cycle의 attempt-N.prompt/output, 각 attempted subrequest의4파일이다. 전체 파일의 size/SHA·canonical identity/receipt·순서·계획·cycle 결과를 재검증하며 누락/추가/변조를 거부한다. 기존 freeze/봉인·읽기 전용 verify-sealed를 그대로 사용하고 archive-v1 검사를 완화하지 않는다. 입력·metadata·검증 출력/전체 파생 결과는8MiB다. 파생 plan은 유효한 입력보다 커질 수 있어 전체 canonical 계획을 재생성하고 실제 파일의 전체 size/SHA를 stream 대조한다. 보고서의 파일당8MiB·전체64MiB 초과는 기존 명시 오류이며 원본을 잘라 성공으로 표시하지 않는다.

파생 cycle manifest·receipt도 입력보다 커질 수 있으므로 재계산한 canonical bytes의 전체 size/SHA를 실제 파일과 대조한다. Python 생성→verify→freeze→재사용과 D08 bindings/자동·사람 수정 평가·사람 검토/인계는 receipt의8MiB 접두부를 읽어 비교하지 않는다. identity는 기존8MiB decode 한도를 유지하며 v2는 공백·키 순서를 포함한 canonical bytes도 요구한다. 기존 v1 identity 허용 범위는 바꾸지 않는다.

## Java·사람 검토·평가

Java는 v1/v2 exact 이름을 구분하고 마지막 attempt-N.output hash를 전체 파생 결과로 저장한다. metadata attempts1~3과 기존 DB 제약은 유지한다. report는 모든 subrequest와 파생 cycle을 구별해 표시한다. source 전체 D03·receipt·metadata·사용권·승인 재검증을 유지한다.

Java 연결은 기존 Python 자식 프로세스 stdout8MiB·최대60초 및 saved receipt8MiB 한도를 유지한다. Python 단독으로 보관·평가 가능한 큰 receipt도 이 한도를 넘으면 Java 등록/인계 대상이 아니며 별도 검토가 필요하다. D03의 제목·block ID 등 기존 Java 입력 제약과 S10 파일8MiB/전체64MiB 한도도 그대로다. 큰 Python 합성 입력의 보관 성공을 Java 등록·보고서 성공으로 집계하지 않는다.

v2 직접 ai-draft/check-draft는 CHUNK_DRAFT_REVIEW_REQUIRED로 거부한다. 실제 사람 검토자가 전체 원문·모든 chunk·교차 chunk 관계를 확인한 human-review/handoff는 기존 경로로 저장할 수 있다. 사람 결과를 자동 결과에 끼워 넣지 않는다.

D08 새 `api-document-cycle-v1` policy는 prompt_version을 `prompt-v2-or-v3`으로 명시하고, v1의 prompt-v2 단일 요청/v2의 prompt-v3 분할을 고정된 선택 규칙으로 평가한다. 다른 provider/model/schema는 기존처럼 정확히 일치해야 한다. 기존 api-structure-retry-v1은 v1만 허용한다. first_raw 이름은 기존 인터페이스이며 v2에서 첫 cycle의 파생 결과임을 명시한다. 전체 실패/미시도·누락·중복 분모와 최초/재시험·원본을 유지한다. 실제 독립 gold·40문서/20·20/90%·사람/권리/기기/D09·운영/main 인수는 별도다.
