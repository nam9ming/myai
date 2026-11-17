# 시민 원문 추출·수동 보관 v1

`extract-citizen-v1`은 시민5분야의 원문 표현을 보관하는 별도 추출 계약이다. 작성자의 호환성 구현안이며 실제 팀원·Flutter 최종 합의나 새 평가 기준을 뜻하지 않는다. 기존 `extract-schema-v1`·3유형·8필드 평가·계산 계약과 원본은 유지한다.

입력은 기존 [ai-input-v1](schemas/ai-input-v1.json)의 `data_kind/document_version_id/title/published_date/blocks`다. [합성 입력](examples/citizen-ai-input.json)과 [합성 출력](examples/citizen-ai-extraction.json)은 설명·기계 시험용이며 실제 공지 처리나 사람 검토 실적이 아니다. 출력 구조는 [extract-citizen-v1.json](schemas/extract-citizen-v1.json), 구현은 `processing/extraction/citizen.py`다.

## 출력·근거

root의 폐쇄 키는 `schema_version/document_version_id/items/evidence/warnings`다. schema_version은 `extract-citizen-v1`이며 입력의 문서 버전과 일치해야 한다. item은 유일한 `local_item_id`, `title/categories`와 아래12개 사실만 가진다.

| 필드 | 원문에서 구별할 정보 |
| --- | --- |
| `application_period` / `occurrences` | 신청 기간 / 실제 진행 일정 |
| `regions` / `locations` / `residency_requirement` | 적용 지역 / 진행 장소 / 거주 조건 |
| `target` / `eligibility` | 안내 대상 / 신청 자격·조건 |
| `application_method` / `preparation` | 신청 방법 / 준비사항 |
| `cost` / `recruitment` / `lifecycle` | 비용 / 모집 표현 / 진행·취소 표현 |

title·categories·12개 사실은 모두 `value/knowledge/evidence_ids/reason`의 폐쇄 FieldValue다.

- title의 known 값은 비어 있지 않은 문자열이다.
- categories의 known 값은 `education/support/culture/construction_traffic/living` 중 하나 이상의 중복 없는 배열이다. 분류 미상은 `value=null`, `knowledge=ambiguous`, 비어 있지 않은 reason으로 남긴다.
- 12개 사실의 known 값은 원문 문자열 또는 중복 없는 문자열 배열이다. 알려진 빈 배열은 명시적인 없음 표현이며 미기재와 구별한다.
- known은 기존 근거 ID를 하나 이상 참조한다. 그 밖의 `not_stated/ambiguous/not_applicable`은 value=null과 reason이 필요하다. 미상 title도 같은 규칙을 따른다.

evidence는 `evidence_id/block_id/quote/start_char/end_char/text_sha256`만 가진다. ID는 문서 내 유일하고 block_id는 실제 입력 블록이어야 한다. quote는 Unicode code point 기준 `[start_char,end_char)`의 정확한 부분문자열, text_sha256은 해당 블록의 UTF-8 SHA-256이다. 문서 전체 cleaned_text hash와 혼용하지 않는다. 정수 위치에 boolean·소수를 받지 않으며 근거·문서 불일치도 거부한다. 사건이 없으면 `items=[]`와 `NO_EVENT_FOUND` 경고를 함께 남긴다.

기존 JSON8MiB·깊이100·중복/추가 키·잘못된 UTF-8/Unicode 거부를 재사용한다. 인용 일치가 값의 의미 정확성을 인증하지는 않는다. 날짜·금액·무료 여부·신청 자격·모집/취소 상태·일정 대응을 추론하거나 정규화하지 않는다. 원출력을 공개/승인 상태로 만들지 않는다.

## 준비·수동 원본 보관

저장소 루트에서 실행하는 준비 예시다. 준비는 프롬프트 생성이며 AI를 호출하지 않는다.

```sh
python3.13 -B -m processing.extraction prepare \
  --input contracts/examples/citizen-ai-input.json \
  --schema-version extract-citizen-v1
```

기본 root의 `prepared/extract-citizen-v1/<input_sha256>/input.json,prompt.json`에 기록한다. `--schema-version`은 prepare에만 있으며 생략 시 기존 `extract-schema-v1`·`prepared/<input_sha256>/`·prompt-v1 bytes를 유지한다. 미지원 버전은 준비 root에 쓰기 전에 거부한다.

생성 템플릿은 `citizen-prompt-v1`이며 지시·schema·문서/블록과 블록별 hash/code point 길이를 담는다. 실제 수동 도구에 준 프롬프트와 같았다는 인증은 아니다. [metadata 예제](../processing/examples/extraction-metadata.json)의 전체 키를 유지해 새 run_id·문서 버전, `schema_version=extract-citizen-v1`, `execution_mode=manual_import`를 기록한다. prompt_version은 실제 사용한 도구/템플릿의 비어 있지 않은100자 이하 선언 라벨을 그대로 적는다. 생성 템플릿을 쓰지 않았다면 citizen-prompt-v1로 바꾸지 않는다. 알 수 없는 도구·모델·시각·사용량·비용을 생성하지 않고 기존 null/unavailable_reasons 규칙을 따른다.

```sh
python3.13 -B -m processing.extraction import \
  --input contracts/examples/citizen-ai-input.json \
  --metadata data/private/citizen-metadata.json \
  --attempt data/private/actual-prompt.txt data/private/citizen-raw-output.txt
python3.13 -B -m processing.extraction verify RUN_ID
python3.13 -B -m processing.extraction freeze RUN_ID
python3.13 -B -m processing.extraction verify-sealed RUN_ID --root PARENT_OF_SEALED_RUN
```

RUN_ID·봉인 부모 경로와 private 파일은 실제 결과로 바꾼다. import에는 schema 선택 옵션이 없으며 제공 metadata의 명시 family로 parser를 선택한다. 출력의 자기 선언으로 parser를 바꾸지 않는다. 시민은 `manual_import`·`extraction-archive-v1`만 지원한다. 새 provider/API 실행·archive-v2·chunk·규칙 실행을 추가하지 않는다.

[기존 archive-v1](extraction-run.md)의 파일 집합·identity/receipt·1~3시도·정확 재실행·충돌·symlink 방어·0400/0500 봉인을 유지한다. 실제 prompt/metadata/output 원래 bytes와 모든 실패를 보관하고, 마지막 출력의 기계 검증 상태를 실행 상태로 쓴다. 검증용 JSON8MiB 초과·비UTF-8 실패도 원출력 전체를 보존한다. 성공도 `review_required=true`다. CLI manual prompt의 기존 한도와 [HTTP 업로드](../backend/docs/extraction-upload.md)의 metadata64KiB/prompt20MiB/output5MiB 한도를 구별한다. 봉인은 전자서명·WORM·실제 사람 승인이 아니다.

시민 봉인본의 파일 집합은 receipt의 artifacts와 `identity.json/receipt.json`뿐이며 디렉터리0500·일반 파일0400을 정확히 요구한다. 재사용·verify-sealed·Java 판독·사람 수정 부모가 같은 조건을 적용한다. 봉인 전 canonical은 같은 파일 집합의0700/0600만 허용한다. 다른 권한이나 추가 파일/디렉터리/링크가 있으면 원본을 chmod하거나 항목을 버려 복구하지 않고 오류로 남긴다. 기존 family의 봉인 판정은 변경하지 않는다.

## 사람 수정·Java 연결·기존 평가 격리

[human-review-v1](human-review.md)은 부모 metadata의 family로 이전/수정후 출력 전체를 검사한다. 전체 changes 감사·원래 review bytes·부모 D05 전체·실패 상태를 유지한다. 실패 부모는 `before=null`, `after=수정후 전체 출력` 기록이 필요하며 새 family로 바꿔 수정할 수 없다. 검토자·basis·시각은 제공자의 선언이다. 합성 check-review CLI 시험의600초는 `review_duration_ns=600000000000`, `human_verification=declared_only`이며 실제 사람 작업시간 측정이 아니다.

이 시민 사람 수정 연결은 **Python 별도 보관본까지**다. Java D05/S10은 새 수동 archive의 원출력·실패·metadata를 판독한다. Java의 시민 human-review 표시/저장·D06 인계·승인/공개 연결은 다음 G5이며 현재 경로가 자동 생성하지 않는다.

| 기존 경로 | 시민 family의 처리 |
| --- | --- |
| legacy `draft/check-draft` | `DRAFT_SCHEMA_UNSUPPORTED`로 기존 D06 투영을 거부. 실패 실행 등 선행 거부 조건은 그대로 유지 |
| legacy 사람 인계 | `HANDOFF_SCHEMA_UNSUPPORTED` |
| D08 실행 연결 | `BINDING_SCHEMA_UNSUPPORTED` |
| 직접/사람 수정후 8필드 평가 | `EVALUATION_SCHEMA_UNSUPPORTED`, 기존 채점기·8필드 분모에 전달하기 전에 거부 |

새 점수·gold/D09·실자료 평가를 만들지 않는다. 기존3유형 실제 처리 수·실패·과거 보관본과 평가 기준은 보존한다. parser·실제 prepare/import/review CLI·원래 경로 제거 후 봉인 재검증·legacy guard의 합성 시험과 실제 공식자료 정확도·사람 승인·운영 인수는 구별한다. 전체 Python/Java·DB·원격 MySQL8.4 검증 결과와 미완료는 [G4 계획](../docs/superpowers/plans/2026-11-18-citizen-extraction.md)을 따른다. 미확정 사업·자료·평가 사항은 [별도 기록](../backend/docs/citizen-open-items.md)에서 관리한다.
