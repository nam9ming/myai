# AI 추출 검증·비공개 원출력 기록 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자 Goal에 따라 native 구현·검증 후 한 번의 별도 전체 리뷰를 수행한다. main은 사람 병합, 다른 PR은 최신 CI·유효 미해결0 후 병합한다.

**Goal:** 기존 extract-schema-v1을 기계 검증하고 수동 도구의 입력·프롬프트·시도별 원출력·실패·D05 metadata를 불변 비공개 파일로 기록한다. 실제 API 추출·D05 DB import·D06 사람 검토 연결은 전체 Goal에 유지한다.

**Architecture:** stdlib 전용 `processing/extraction/`을 추가한다. 동일 필드 정의에서 JSON Schema를 만들고 계약 전용 validator로 구조·knowledge·참조·근거·시간을 확인한다. 별도 CLI의 prepare/import/verify는 네트워크·DB·계산기를 호출하지 않는다. 기록한 bytes/hash를 검증하며 사람 승인이나 사실성 검증을 대신하지 않는다.

**Tech Stack:** Python3.13, unittest, json/hashlib/decimal/pathlib/os/tempfile. 새 의존성 없음.

**Spec:** `docs/spec/03_데이터와AI.md` D05·AI 입력/출력·검증/재시도, `processing/TASK.md`, `contracts/examples/ai-input.json`, `ai-extraction.json`.

## Global Constraints

- 기준85eb53dd754c1152c0c4491d04847274b0dcde06. Java/Python 범위이며 공개 API·D06/D07 필드·matching 계산 규칙은 변경하지 않는다.
- 기존 AI 입력5키와 출력 extract-schema-v1을 그대로 따른다. 알 수 없는 값은 null+knowledge/reason이며 좌표·거리·영업영향·평가 정답을 추가하지 않는다.
- 입력 JSON·metadata 검증은 UTF-8 원본8MiB·깊이100, 중복 키/비정상 Unicode/비유한 수 거부. 검증용 출력 크기도8MiB이며 더 큰 원출력은 stream으로 전부 보존하고 실패로 기록한다.
- D05 evidence.text_sha256는 기존 예제 검증과 같은 **블록 UTF-8 hash**다. D06의 문서 cleaned_text hash로 임의 대체하지 않는다. 이후 전달 변환에서 각 hash의 대상을 분리해 검증한다.
- 오류는 고정 코드·알려진 필드/배열 인덱스 경로만 노출한다. 원문·unknown key 문자열·인증정보·실제 경로를 stdout/stderr에 넣지 않는다.
- `validated`는 구조·근거 위치/참조 검증 상태다. 원문 의미·이용권한·승인은 별도이며 `review_required=true`를 유지한다.
- manual_import는 실제 도구 호출을 수행하지 않는다. metadata의 run_id·attempts1~3과 같은 수의 실제 prompt/output 쌍을 받는다. 시도별 결과를 모두 보존하고 마지막 출력의 기계 상태를 기록한다. 자동 API 재시도는 후속 API 단계에서 schema/transport만 최대3회로 구현한다.
- provider/model/version·usage/cost는 수동 기록의 제공값이며 미확인 값은 null+해당 사유다. 현재 시각을 AI 실행 시각으로 꾸미지 않고 local recorded_at과 제공된 started_at/finished_at을 분리한다.
- 기본 archive root는 Git 제외 data/private/extraction-runs. 저장소 안 다른 경로를 거부하고 바깥 private root는 허용한다. 새 디렉터리0700·파일0600, 같은 run_id의 원본을 덮어쓰지 않는다.

## Review Focus

1. 잘못된 UTF-8/중복키/boolean 정수/NaN/깊은 JSON·추가 비공개 필드가 기계 검증을 우회하거나 로그로 새지 않는가.
2. 여러 블록·여러 사건·emoji의 offset/hash·중복 local ID·다른 사건의 위치 참조가 정확히 분리되는가.
3. 날짜 미상·부분 시각·명시 익일·다른 종료 날짜·all_day를 추정으로 채우거나 서로 모순된 known을 통과시키지 않는가.
4. 실패/과다 원출력도 bytes/hash 그대로 보존하며, source 변경·동시/재실행·같은 run_id 충돌·파일 실패에서 validated를 거짓 기록하지 않는가.
5. prepare가 현재시각·data_kind·사용자 조건·정답을 모델 자료에 섞지 않고, raw/metadata/receipt 손상이 verify·후속 소비자에게 차단되는가.

### Task 1: 스키마·입출력 검증

**Files:** Create `processing/extraction/__init__.py`, `schema.py`, `validation.py`; `contracts/schemas/ai-input-v1.json`, `extract-schema-v1.json`; `processing/tests/test_extraction_validation.py`.

**Interfaces:** `parse_input(bytes)->dict`, `parse_output(bytes,input)->dict`, `ExtractionError(code,path,kind)`; `input_schema()/output_schema()->dict`. kind=input/schema/review이며 schema만 자동 재시도 가능하다.

- [x] Step1: 기존 예제·unknown/known 빈목록·0건·한글/emoji/다중 block·local ID/ref·타입/누락/추가 키·JSON wire·날짜/시각·근거 변이 시험 작성.
- [x] Step2: unittest의 새 기능 없음 RED 확인.
- [x] Step3: 공유 필드 정의와 표준 JSON Schema 생성, 전용 validator 구현. 값은 수정하지 않고 안전한 오류 경로만 반환.
- [x] Step4: unittest GREEN·기존 Python69개 회귀·schema artifact와 generator 일치 확인.
- [x] Step5: `feat: validate AI extraction contracts` 커밋.

### Task 2: 프롬프트·D05 metadata

**Files:** Create `processing/extraction/prompt.py`, `metadata.py`, 관련 unittest; synthetic metadata 예제.

**Interfaces:** `render_prompt(input)->bytes`; `parse_metadata(bytes,input,attempt_count)->dict`. metadata는 run_id/document_version_id/execution_mode/attempts/provider/model_label/model_version/unavailable_reasons/prompt_version/schema_version/preprocessing_version/started_at/finished_at/usage_in/usage_out/cost/currency의 정확한 키를 갖는다.

- [x] Step1: prompt-v1의 고정 지시·전체 schema·source4키·해당 ID/블록 hash enum binding·결정성, metadata null 사유/정밀 수/시간 순서/불필요 키 거부 RED.
- [x] Step2: 원본 input의 data_kind는 local tag로만 유지. 실제 prompt는 source4키만 포함하고 현재날짜·사용자 조건·gold를 생성하지 않음. metadata 원본 bytes는 보관하며 cost를 계산/추정하지 않음.
- [x] Step3: 관련 시험 GREEN·커밋.

### Task 3: 불변 비공개 archive·CLI

**Files:** Create `processing/extraction/archive.py`, `__main__.py`; 관련 archive/CLI tests; `contracts/extraction-run.md`.

**Interfaces:** `prepare(input_path,root)->summary`, `import_run(input_path,metadata_path,attempt_pairs,root)->summary`, `verify_run(run_id,root)->summary`. CLI prepare/import/verify는 이 함수를 호출하며 raw 값 대신 ID·상태·hash·상대 artifact 이름만 stdout JSON 한 건으로 반환.

- [x] Step1: 원본 bytes/hash·invalid UTF-8/과다 출력 보존·1~3시도·null/unknown·실패와 review_required·동일 ID 재실행/동시/충돌·변조/공개root/파일 실패·실제 subprocess RED.
- [x] Step2: metadata의 고정 run_id로 private 디렉터리를 만든다. input/metadata/prompt 원본과 output 전체를 보존하고 fingerprint로 identity를 고정한다. 완성 임시 파일→배타 hard link로 같은 파일 재사용/다른 bytes 충돌을 처리한다. 정상 완료 receipt를 마지막에 기록하고 incomplete는 verify 성공으로 간주하지 않는다.
- [x] Step3: 검증은 archive에 보존한 출력에 대응한다. failed 원출력도 삭제하지 않으며, resume/verify에서 모든 bytes/hash·최종 검증 상태를 확인한다. 상대 고정 파일명만 소비하고 symlink를 거부한다.
- [x] Step4: CLI 종료0 정상 준비/validated,2 입력·설정,3 archive 충돌/무결성/미완료,4 원출력 보존 후 failed·사람 확인 필요,5 I/O,1 내부오류. 오류에 원문/경로를 포함하지 않음.
- [x] Step5: 전체 Python·실제 CLI·npm lint/test/build GREEN. Java에 직접 호출부 변경 없음은 diff/CI로 확인. `feat: archive manual AI extraction runs` 커밋.

### Task 4: 전체 검토·PR

- [ ] README/TASK·archive 계약·실행/미완료를 한국어로 갱신하고 예제는 합성/실제 미호출 표시.
- [ ] 전체 producer/validator/artifact/consumer·실패/참조/파일/문서를 자체 리뷰한 뒤 별도 전체 리뷰. 지적은 재현·수정·재검증 후0으로 닫음.
- [ ] backend/api-foundation 대상 PR·최신 CI/AI/사람 지적 검토. 유효 미해결0과 CI 성공이면 expected-head 병합. main은 사람 대기.
- [ ] 본 계획의 private 테스트 자료만 정리. 실제 AI 실행·자료 수집/인수·D05 DB 등록·D06 전달·평가/배포를 이번 단계 완료로 표시하지 않는다.

## 구현 검증 기록

- Python97개·Node29개·JSON 예제9개·lint/build 통과. 실제 CLI prepare/import/verify/재실행을 합성으로 확인했으며 원출력 실패·과다 출력·중단 재개·동시 실행·충돌·손상을 시험했다.
- 별도 전체 리뷰의 유효 P2 2건(Decimal 극단 지수 예외, 반복 블록 재해싱)은 각각 RED→GREEN 회귀와 전체 재검증으로 수정했다. 검증 성공도 사람 검토가 필요하며 실제 모델 호출·D05 DB 등록·D06 전달·실자료 평가는 후속 단계다.
