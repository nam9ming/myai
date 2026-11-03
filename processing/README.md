# Python AI·계산 — 김윤기

C01~C10 순수 계산과 `calc-v1` CLI, Spring 공개 matches 연결, OpenAI 추출·수동 원출력 보관 CLI를 구현했습니다. 실제 API 연결 결과는 각 실행의 receipt로 확인하며, 합성 연결 시험을 실제 공지 처리·품질 평가로 세지 않습니다. 공개 API·DB는 Spring이 맡으며 계산 CLI는 AI·네트워크·DB를 호출하거나 사용자 조건을 저장하지 않습니다. 서버의 Python 실행 파일·작업 경로는 [백엔드 안내](../backend/README.md#python-계산-연결)를 따릅니다.

## 설치·실행

Python **3.13**을 사용합니다. 로컬 확인 버전은 **3.13.5**이며 외부 Python 의존성은 없습니다. Asia/Seoul을 제공하는 시스템 시간대 자료가 필요합니다. 로컬 macOS에서 검증하고 CI는 Linux에서 실행합니다. Windows 실행은 미검증입니다.

저장소 루트에서 실행합니다. 가상환경은 선택 사항이며 패키지 설치는 필요하지 않습니다.

```sh
python3.13 -m venv .venv
.venv/bin/python -m processing.matching < processing/examples/match-input.json
.venv/bin/python -m unittest discover -s processing/tests -v
```

입력 예제는 [검토 입력](../backend/examples/reviewed-import.json)의 합성 사실을 공개 snapshot 형태로 투영한 자료입니다. 기준 시각은 2026-11-03 11:00 KST로 고정했습니다. 결과는 후보1건·거리0m·영업 중첩120분입니다. 실제 공지 처리 실적이 아니며, 예제의 snapshot checksum은 형식 확인용 0값입니다. 운영에서는 Java가 저장된 canonical JSON의 실제 checksum을 검증한 뒤 전달해야 합니다.

## 모듈·계약

| 경로 | 역할 |
|---|---|
| `matching/protocol.py` | 중복 키·잘못된 UTF-8/Unicode·참조·시각·버전·입력 크기 검증 |
| `matching/intervals.py` | KST 조회창·전날 이월·구간 합집합·명시 반복 날짜 |
| `matching/geometry.py` | Haversine·최단 대권 선분·정류장 집합 거리 |
| `matching/engine.py` | occurrence별 3값 결합·최신성·취소·재현·정렬·동시간 묶음 |
| `matching/__main__.py` | stdin 한 건·stdout 한 건, 안전한 실패 종료 |
| `extraction/schema.py`, `validation.py` | AI 입력/출력 구조·knowledge·근거·참조·시간 순서 검증 |
| `extraction/prompt.py`, `metadata.py` | 고정 프롬프트·문서/블록/hash 제약·D05 제공값 검증 |
| `extraction/archive.py`, `__main__.py` | 비공개 준비/수동 가져오기/무결성 검증·실패 원출력 보존 |
| `extraction/api.py` | 고정 OpenAI Responses API·최대3시도·요청/응답/전송 상태 보관·오프라인 재검증 |
| `extraction/rules.py`, `rule_runs.py` | 고정 키워드/날짜/지명 기준선·AI와 분리한 규칙 실행 원본 보관 |
| `extraction/draft.py` | 검증된 원출력→숨김 검토 초안·안정 ID·근거 hash 변환·미상 보존 |
| `evaluation/dataset.py`, `storage.py`, `__main__.py` | D08 문서/사건 연결·분할 검증·비공개 manifest 불변 보관·CLI |
| `evaluation/bindings.py` | 동결 manifest·실제 입력 바이트·명시 선택한 D05 원본의 읽기 전용 대조 |
| `evaluation/gold.py`, `gold_storage.py` | 독립 정답 제공자의 선언·근거·사건 anchor 검사와 원본/지침/manifest 별도 동결 |
| `evaluation/scoring.py`, `records.py`, `evaluation_storage.py` | 8필드 채점·명시한 API/규칙/사람 수정 원본 연결·최초/재시험 원본 묶음 동결 |
| `evaluation/comparison.py`, `comparison_storage.py` | 같은 gold·회차·AI 부모의 세 방법을 짝지어 개선/악화·선언 시간을 집계하고 전체 평가를 동결 |
| `evaluation/matching_projection.py`, `matching.py`, `matching_storage.py` | 독립 수동 기대 분류/사유와6개 뷰를 비교하고 검색 존재·완전 분류·전체 원본을 별도 동결 |
| `evaluation/study_protocol.py`, `study.py`, `study_export.py` | D09 private 프로토콜/기록·동의/기한·전체 분모를 검사하고 M04/M05·JSON/CSV를 명시 내보내기 |
| `evaluation/human_handoff.py`, `handoff_storage.py` | 사람 수정값의 workflow 없는 D06 사실 투영·원본 전체 인계 이미지, 별도 Java 인계 요청으로 저장 |
| `evaluation/reviews.py` | 사람 수정후 출력·실제 변경 기록/검토 시간 선언·D05 전체의 별도 불변 보관 |

[계산 연결 계약](../contracts/calculation-bridge.md)을 따릅니다. 지원 규칙은 `rules-v1`이며 미지원 버전을 정상 결과로 바꾸지 않습니다. `dictionary_version`은 선택한 snapshot의 고정 식별자이며 계산 중 새 사전을 읽지 않습니다. 입력 원본 바이트 SHA-256을 반환하며 개인 조건은 로그에 남기지 않습니다.

- 입력·출력 각각8MiB, JSON 깊이100. 선택한 카드와 중첩 묶음을 만드는 중에도 누적 출력 예산을 검사하고 JSON을 제한된 버퍼로 직렬화합니다. 성공0, 입력 오류2, 출력 초과3, 런타임 오류1로 종료합니다. 오류 시 stdout은 비어 있고 stderr에는 고정 오류 코드만 씁니다.
- Java adapter는 설정된 실행 파일·workdir, 공통 timeout, 동시 stdin/stdout/stderr 처리, 입출력·실행 수 제한, 응답 hash/버전·사실 대조를 담당합니다. CLI 단위 시험과 실제 DB·API 연결 시험을 함께 유지합니다.
- date_only와 미상 영업을 종일로 채우지 않습니다. 확정 overlap만 묶고, 총량을 확정하지 못하면 분 수는 null입니다. 부분 geometry에서 확인된 이내는 후보가 될 수 있지만 전체 최소 거리는 null로 유지합니다.
- 명시된 다른 종료 날짜에는 익일 offset을 다시 더하지 않습니다. 반복 날짜가 있으면 각 날짜의 시간+offset을 적용하며 빈 반복 배열은 발생 없음입니다. 날짜 범위만 보고 매일 반복시키지 않습니다.
- replay는 고정 cutoff 이전 문서·확인만 사용하고, 24시간 경과는 고정 reference_instant로 계산합니다. 재구성과 당시 검증본을 구분하며 현재 연결 상태는 별도 표시합니다.

Java D05 등록은 [D03/D05 연결 안내](../backend/docs/extraction-run-import.md)를 따른다. 원문을 먼저 등록하고 같은 전체 블록·전처리 버전의 AI 입력을 사용한다.

같은 D03 버전의 원문 확인·사용권 변경은 Java [local-source-review](../backend/docs/source-review.md)로 별도 기록한다. 최초 source JSON·D05·사람 인계 이미지는 유지하며 추출/초안·사람 검토의 전체 원본 대조에 운영 metadata를 끼워 넣지 않는다. 확인만 갱신하려고 AI를 다시 실행하지 않는다. 승인·공개는 현재 권한·확인 이력을 사용하고 replay는 추가 확인의 checked_at과 recorded_at을 모두 cutoff와 대조한다. 이미 공개한 snapshot·계산 입력·export·rollback은 바꾸지 않는다. 이번 합성 검증에서 실제3건의 pending/uncertain 상태·AI 원본·키는 변경하지 않았다.

등록 시 `freeze`가 원래 archive와 분리한 읽기 전용 보관본을 만든다. POSIX 권한·hard link·원자적 디렉터리 rename 지원과 추가 보관 공간이 필요하며 DB는 보관본의 안정된 경로를 참조한다. 파일은0400, 실행 디렉터리는0500이다.

## AI 수동 원출력 기록

```sh
python3.13 -m processing.extraction prepare --input contracts/examples/ai-input.json
python3.13 -m processing.extraction import \
  --input data/private/input.json --metadata data/private/metadata.json \
  --attempt data/private/actual-prompt.txt data/private/raw-output.txt
python3.13 -m processing.extraction verify 71fb66f0-e610-4f9c-8f26-4bb77655ee8c
```

첫 명령은 합성 입력의 프롬프트만 생성합니다. 가져오기에는 실제 제공한 프롬프트·원출력과 새 run_id의 메타데이터를 준비합니다. 기본 저장 위치는 Git 제외 `data/private/extraction-runs`입니다. 같은 ID의 원본을 덮어쓰지 않으며 실패·과다 출력도 전부 보존합니다. 마지막 출력이 기계 검증을 통과해도 `review_required=true`이며 사람 승인과 다릅니다. 종료 코드·1~3시도·복구·hash 대상·미상 제공값 처리 등은 [실행 기록 계약](../contracts/extraction-run.md)을 따릅니다.

## OpenAI 개발용 추출

사용자 결정에 따라 개발 단계에서는 코드리뷰와 같은 OpenAI 키를 사용합니다. 로컬은 `OPENAI_API_KEY` 환경변수, GitHub는 기존 Actions Secret을 사용합니다. GitHub Secret을 로컬로 꺼내는 기능은 없습니다. 키를 인자·JSON·Git에 넣지 않습니다.

```sh
# 키는 실행 터미널의 OPENAI_API_KEY에 직접 설정한다.
export OPENAI_MODEL=gpt-6.1-sol
python3.13 -m processing.extraction run \
  --input processing/examples/ai-smoke-input.json \
  --preprocessing-version smoke-nfc-v1
```

기본 모델은 현재 코드리뷰 기본값과 같습니다. `--model`로 명시할 수 있으며 실제 계정의 접근 권한·비용은 실행 기록과 공급자 정보를 확인합니다. 실제 자료는 검토·비식별화한 `data/private/` 입력을 명시적으로 전달합니다. 도구는 파일을 자동 수집하거나 공개하지 않습니다.

새 API 실행의 `prompt-v2`는 블록별 SHA-256·Unicode 문자 수를 제공하고 전체 블록 근거 인용을 안내합니다. 모델 출력의 hash·문자 위치를 자동 수정하지 않습니다. 기존 API `prompt-v1` 기록은 원래 요청으로 계속 재검증·재사용하며 수동 `prepare`도 v1 바이트를 유지합니다. 프롬프트를 비교할 때는 새 run_id를 사용하고 실패 원본을 남깁니다.

요청별120초·최대3시도·출력8192토큰, 고정 HTTPS 주소·`store=false`를 사용합니다. 별도 HTTP 작업 프로세스에 DNS·헤더·chunk 수신까지 공통 deadline을 적용하고, 종료 정리에 최대1초가 추가될 수 있습니다. 전송/구조 오류만 재시도하며 인증·근거·의미 오류와 거절 응답은 중단합니다. 이미 받은 인증/리다이렉트 상태는 본문이 끊겨도 재시도하지 않습니다. 모든 시도의 원문 입력·실제 요청·응답 본문·전송 상태·추출 텍스트를 보관합니다. 수신 본문은8MiB+1에서 중단하고 초과·부분 수신을 명시하므로 그 경우 전체 응답 보관을 뜻하지 않습니다. 사용량은 모든 시도의 제공값이 있을 때만 합산하고, 상세 모델 버전·금액·통화는 추정하지 않습니다.

같은 `--run-id UUID`의 완료 실행은 입력·모델·전처리 버전이 일치하면 키 없이 재사용합니다. 동시 실행·중단한 실행은 자동 재전송하지 않습니다. 원본을 확인한 뒤 새 실행 ID로 재시도하며 이전 디렉터리는 남깁니다. 실행 기록은 기존 Java `local-extraction`→숨김 초안 경로로 등록합니다.

같은 저장소 PR에 `run-openai-extraction` 라벨을 **적용하는 이벤트**만 실제 합성 API 시험을 실행합니다. 일반 push/synchronize는 유료 추출을 실행하지 않습니다. 라벨을 다시 적용하거나 실패 작업을 재실행하면 새 호출이 발생합니다. 기존 `OPENAI_API_KEY`·리뷰 모델을 직접 사용하며 합성 원본 artifact는3일 보관합니다. 실제 공지는 이 workflow에 넣지 않습니다.

## D08 데이터셋·분할

문서 버전·입력 hash, 사건/문서 관계, 개발/확인 배정을 [manifest 계약](../contracts/dataset-manifest.md)으로 검증합니다. 공유 문서·정정/재게시 연결이 분할을 가르면 거부하고, 같은 문서의 복수 버전은 문서1개로 셉니다. 의심 중복은 자동 병합하지 않습니다. 노출·그룹 검토 경고와 실제40/개발20/확인20 대비 부족분을 함께 반환합니다.

```sh
python3.13 -m processing.evaluation check --input processing/examples/dataset-manifest.json
python3.13 -m processing.evaluation freeze --input data/private/dataset.json
python3.13 -m processing.evaluation verify DATASET_REF
```

예제는 합성4문서/5버전입니다. 실제 개발용3건은 dev만 배정한 비공개 manifest로 check/freeze/verify를 확인했으며 holdout은0건입니다. 같은 dataset_version의 다른 바이트는 충돌이고 기존 원본을 덮어쓰지 않습니다. 기본 root는 `data/private/evaluation/datasets`, 보관본 파일0400·디렉터리0500입니다. 키·AI·네트워크·DB를 사용하지 않습니다.

manifest만으로는 실제 본문이나 정답을 인증하지 않으며 `unexposed_as_declared`도 blind 평가 보증이 아닙니다. 실제 입력·실행 연결은 별도 [dataset-bindings-v1](../contracts/dataset-bindings.md) 명세로 검사합니다.

```sh
python3.13 -m processing.evaluation check-bindings \
  --input data/private/evaluation/bindings.json \
  --dataset-root data/private/evaluation/datasets \
  --run-root data/private/extraction-runs
```

모든 manifest 버전을 실제 입력 바이트·data_kind·읽기 전용 D05 원본과 대조합니다. 실패 실행도 원본 재검증 대상이고 첫/최종 상태를 구분합니다. 원본·경로를 stdout에 넣거나 검사 중 보관본을 고치지 않습니다. 실제 개발3건의 v1 실패/v2 성공6실행을 이 검사로 대조했습니다. 이는 문서6건·재시도 성공률·품질 평가를 뜻하지 않습니다.

## 독립 정답표

[dataset-gold-v1](../contracts/gold-archive.md)은 독립 원문 판독·다른 담당자의 교차 검토·사건 anchor·판정 지침·의견 차이 해결 기록을 받습니다. FieldValue/근거의 형식만 재사용하며 실제 AI 결과를 정답으로 복사하지 않습니다. 신원·독립 판독·의미 정확성은 제공자의 선언이며 검사 결과는 `declared_cross_reviewed`입니다.

```sh
python3.13 -m processing.evaluation check-gold --input data/private/gold.json
python3.13 -m processing.evaluation freeze-gold --input data/private/gold.json
python3.13 -m processing.evaluation verify-gold GOLD_REF
```

정답·판정 지침·manifest·각 버전의 입력 원본을 Git 제외 `data/private/evaluation/gold`에 함께 고정합니다. 파일0400·디렉터리0500이며 같은 gold_version의 다른 바이트를 덮어쓰지 않습니다. 원래 경로가 없어도 보관한 입력으로 재검증합니다. 키·AI·네트워크·DB를 사용하지 않습니다.

합성 자료로 도구를 검증했으며 실제3문서의 독립 정답표를 생성·동결하지 않았습니다. 사후에 만든 금표를 최초 평가로 표시할 수 없습니다.

## 8필드 평가·최초/재시험 보관

[extraction-evaluation-v1](../contracts/extraction-evaluation.md)에 따라 독립 gold와 버전마다 명시한 API·규칙 실행 또는 사람 수정 원본을 연결합니다. 사람이 사건/일정 대응과 생성 오류 판정을 기록합니다. AI/규칙은 원출력을 바꾸지 않고 첫 raw·최종 자동을 함께 채점하며 사람 수정값은 별도 human_reviewed 뷰를 사용합니다. null·누락·실패도 gold에 정답이 있으면 분모에 남습니다. 생성 여부의 의미 검토가 남으면 생성률은 N/A입니다.

```sh
python3.13 -m processing.evaluation check-evaluation \
  --input data/private/evaluation/selection.json
python3.13 -m processing.evaluation freeze-evaluation \
  --input data/private/evaluation/selection.json
python3.13 -m processing.evaluation verify-evaluation EVALUATION_REF
```

선택 입력의 키·정책·annotation은 계약 문서에 설명합니다. 기본 gold/initial 경로는 `data/private/evaluation/gold`, `data/private/evaluation/extractions`입니다. run은 method=ai_auto이면 `data/private/extraction-runs`, rules이면 `data/private/rule-runs`, human_reviewed이면 `data/private/evaluation/human-reviews`입니다. `--gold-root`, `--run-root`, `--initial-root`로 지정할 수 있으며 명시한 경로가 우선합니다. freeze/verify의 평가 보관 위치는 `--root`로 정합니다.

initial은 gold 동결 이후 시작한 실행만 받습니다. retest는 동일 cohort·정규화 지침·방법의 동결 initial을 참조하며 금표/정책 변경·노출 선언·점수 차이를 남깁니다. 새 실행은 initial 동결 이후 시작해야 하고, 금표 수정만 재채점할 때는 기존 실행을 유지할 수 있습니다. 재시험을 최초 성능·새 일반화 증거로 표시하지 않습니다.

보관본은 `selection.json`, 비공개 `result.json`, gold 전체, 선택한 D05 전체·규칙6파일 또는 사람 검토 전체(내부 D05 포함), retest의 최초 평가 전체를 포함합니다. 파일0400·디렉터리0500으로 검증한 뒤 배타 설치하며 같은 ID의 다른 입력은 충돌입니다. 원래 경로가 없어도 재검증·같은 입력 재사용이 가능합니다. 최초 평가와 실패 원본을 덮어쓰지 않습니다. 상세 값·근거·검토자·원래 경로는 private 파일에만 두고 stdout에는 요약/상대 artifact 목록만 출력합니다. 성공0·입력2·보관본 손상/충돌3·I/O5·내부 오류1로 종료합니다.

키·AI·네트워크·DB를 사용하지 않는 도구이며 실제40문서 성과를 측정하지 않았습니다. M02 수치는 ai_auto에서 real/문서 수/비노출 등의 선언과 확인용 정답 분모가 갖춰진 initial에만 제공하며, 그 자체로 의미 정확성·신원·blind holdout을 인증하지 않습니다. rules는 관측 점수를 유지하고 M02는 N/A입니다. 사람 수정값은 별도 human_reviewed 뷰로 채점하고 M02는 N/A입니다. review_id와 실제 parent ID/실패·모드를 구분하고 선언 검토 시간을 전체/dev/holdout별로 합산합니다. 세 방법 비교 도구는 아래 별도 CLI로 연결하며 실제 독립 금표/40건 평가는 후속 작업입니다.

## 세 방법의 짝지은 비교

[extraction-comparison-v1](../contracts/extraction-comparison.md)은 규칙/AI/사람 수정후의 동결 평가를 정확한 receipt로 선택합니다. 같은 gold·입력·평가 회차와 사람 검토의 정확한 AI 부모를 대조하고 gold 슬롯×8필드별 개선/악화/동일 정답/동일 오답을 집계합니다. gold 미상은 분모 밖에 남기고 실패/누락/생성 미확정과 첫 raw/최종 자동의 지표도 보존합니다.

```sh
python3.13 -m processing.evaluation check-comparison --input data/private/evaluation/comparison.json
python3.13 -m processing.evaluation freeze-comparison --input data/private/evaluation/comparison.json
python3.13 -m processing.evaluation verify-comparison COMPARISON_REF
```

`--evaluation-root` 기본값은 private evaluation/extractions, freeze/verify의 `--root`는 private evaluation/comparisons입니다. 세 평가의 전체 gold/source/initial을0400/0500으로 함께 보관하고 원래 경로 없이 재검증합니다. 같은 ID의 다른 입력은 충돌입니다. stdout에는 summary/receipt만 반환하며 종료0/2/3/5와 기존 CLI 동작을 유지합니다. 검토 시간은 선언 합계이고 실제 노동 감소·독립성·blind holdout 인증은 아닙니다. 키/AI/네트워크/DB를 쓰지 않으며 실제40건 비교·선별 엔진 평가는 미완료입니다.

## 매칭 분류·사유 평가

[matching-evaluation-v1](../contracts/matching-evaluation.md)은 동결 extraction-comparison 전체를 정확한 receipt로 선택하고 독립 수동 기대 candidate/needs_check/cancelled/excluded·사유와 gold/규칙 첫·최종/AI 첫·최종/사람 수정후의6개 뷰를 비교합니다. 같은 검토 사전에 각 방법 자신의 알려진 장소를 연결하며 gold의 좌표로 다른 방법의 미상을 채우지 않습니다. 출처 상태·사전·수동 판단은 제공자의 선언이고 D03 본문 대조나 실제 독립 검토 인증이 아닙니다.

구역 검토는 dictionary entry별로 고정하고 occurrence가 실제 참조한 장소만 집계합니다. unused location이나 gold 사건 대응으로 구역을 보완하지 않습니다. match/duplicate/additional annotation은 채점 identity만 정하므로 추가 출력도 자신의 장소·조건으로 candidate가 되어 orphan FP로 집계될 수 있습니다.

```sh
python3.13 -m processing.evaluation check-matching --input data/private/evaluation/matching-selection.json
python3.13 -m processing.evaluation freeze-matching --input data/private/evaluation/matching-selection.json
python3.13 -m processing.evaluation verify-matching MATCHING_REF
```

입력10키와 context/dictionary/cases/initial의 정확한 필드는 계약을 따릅니다. 모든 cohort 버전·gold 슬롯·실패·빈 출력·중복/추가를 유지하며 최신 선택·사실 병합·버전 비활성 옵션은 없습니다. candidate+실패는 검색 존재 TP일 수 있어도 완전 분류는 partial, 과거 취소+새 후보·상충 duplicate는 conflict입니다. 사건 전체 E와 슬롯 전체 A의 분모를 유지하고 이유를 합치지 않습니다. replay cutoff 당시 미확보는 unavailable이며 excluded가 아닙니다. 유형/구역 필터도 별도 disposition으로 남깁니다.

`--comparison-root` 기본값은 `data/private/evaluation/comparisons`, `--initial-root`와 freeze/verify의 `--root`는 `data/private/evaluation/matching`입니다. matching phase와 source phase는 별도로 보존하며 retest는 matching initial 전체를 참조합니다. 선택 비교·initial 전체를0400/0500으로 복사하고 원래 경로 없이 저장된 시각으로 재계산합니다. 같은 ID의 다른 입력은 충돌이며 check는 summary, freeze/verify는 receipt만 출력합니다. 종료0/2/3/5/1·8MiB/깊이100을 유지하고 새 의존성·키·AI·네트워크·DB를 쓰지 않습니다. 실제 독립 gold·40문서/holdout·사람 검토·D09·main 병합·배포 완료를 뜻하지 않습니다.

## 사용자 비교 평가 기록·분석

[user-study 계약](../contracts/user-study.md)은 protocol12키·records7키·result13키로 D09 자료/버전·동의·배정·전체 시작/실패/미시작과 M04/M05를 다룹니다. D08의 사람 수정후 추출과 별개이며 실제 참여자·동의·파일럿·과제·결과를 생성하지 않습니다. 실제 접근 담당자·보존 종료일·종료처리 기준은 확인이 필요하며 기본 보존기간·제한시간은 없습니다(300초는 제안값).

```sh
python3.13 -m processing.evaluation check-study --protocol protocol.json --input records.json
python3.13 -m processing.evaluation export-study --protocol protocol.json --input records.json --output reports/result.json --format json
python3.13 -m processing.evaluation export-study --protocol protocol.json --input records.json --output reports/result.csv --format csv
```

root 기본값은 `data/private/evaluation/user-studies`이며 protocol/input/output은 모두 root 상대경로입니다. group/other 권한 없는 root와 canonical 경로를 검사하고 기한의 다음 KST 자정부터 records를 읽기 전에 거부합니다. raw artifact hash·선택 snapshot identity/집합을 대조하며 전체 Java 공개 승인·원문 진실성을 인증하지 않습니다. JSON/CSV는 명시한0600 파일/0700 새 디렉터리에만 내보내고 원본/증빙을 자동 복제하거나 삭제하지 않습니다. 실제 기한 내 원본 유지·모든 export 처리는 접근 담당자의 책임입니다.

새 output의 중간 부모까지0700으로 생성하며9999-12-31 기한도 같은 KST 경계를 지원합니다. 동일 입력 JSON 재시도는 일시적 원입력 bytes로 전체 재계산·canonical bytes 대조와 현재 기한/권한 검사를 통과한 뒤 첫 evaluated_at을 재사용합니다. 원입력의 별도 영구 복사는 없고 CSV는 같은 bytes만 재사용합니다. protocol_version만100자 제한이며 다른 제어 label/버전/환경에 임의100/128자 상한을 추가하지 않습니다.

안내시간·로딩 포함·정답 피드백/조작 대행·원문 변경 여부는 명시 null을 허용합니다. unknown은 ns=null·사유를 보존하며0/false나 동일 null로 바꾸지 않고 primary 제외·전체 비교 미확인으로 남깁니다. 동의/privacy·필수 버전·환경은 strict 그대로입니다. CSV participant 행의 deviations 열에도 사유를 남깁니다.4순서 배정 수의 불균형은3명·6명에서도 경고하지만 새 eligibility gate나 순서 변경은 아닙니다.

6문항 모두 정답·비교 조건 준수 user만 기본 M05 쌍이며 전문가/파일럿은 분리합니다. no_show/withdrawn은 상세 시작 기록도 보존하지만 기본 쌍에서 제외하고 전체 비교를 미확인으로 남깁니다. 나노초/Fraction으로 음수·짝수 중앙값·20% 경계를 계산하고 unknown 누락은0으로 바꾸지 않습니다. 정확도/누락 악화면 개선 false, 전체 비교 미확인이면 null입니다. 모집 enum·배정 주기 확장·예외 bool·누락 incidence 분모 등 새 기술 선택은 계약에 구별했습니다. check는 ID/시각/경로/메모 없는 summary, export는 safe receipt만 stdout JSON 한 건이며 종료0/2/3/5/1입니다. summary/receipt도 비공개 D09 파생자료이며 작은 집계가 익명성 인증이나 실제 결과의 공개/외부 AI 전송 허용을 뜻하지 않습니다. 새 의존성·AI·네트워크·DB·공개 endpoint는 없습니다. 실제40건·모집/동의/실증·D09 성과·main 병합/배포 완료를 뜻하지 않습니다.

## 사람 수정후 추출 원본

[human-review-v1](../contracts/human-review.md)은 사람이 별도로 작성한 extract-schema-v1 수정값을 frozen D05 전체와 묶어 보관합니다. D06만 역변환해 개별 knowledge를 추측하지 않습니다. 실제 전후 값·JSON 타입·근거·검토자/종료 시각과 맞는 변경 기록이 필요하며 검토 소요시간은 제공한 시각의 차이입니다.

```sh
python3.13 -m processing.evaluation check-review --input data/private/review.json
python3.13 -m processing.evaluation freeze-review --input data/private/review.json
python3.13 -m processing.evaluation verify-review "$REVIEW_REF"
```

검토 JSON의6개 최상위 키·source/changes 형식과 root 옵션은 계약을 따릅니다. 기본 source root는 data/private/extraction-runs, 검토 보관 root는 data/private/evaluation/human-reviews입니다. 원문/수정값·검토자·사유는 비공개 파일에만 두고 stdout은 ID/hash/상태/건수/선언 소요시간만 반환합니다. 성공0/입력2/보관 손상·충돌3/I/O5/내부1입니다.

API/수동·성공/실패 D05의 실제 모드와 원출력을 보존합니다. 실패 source의 새 유효 출력은 before=null의 전체 변경 기록이 필요합니다. 기계 검사는 실제 사람이 판독했다는 증거·독립 정답·승인·공개가 아닙니다. 이 도구는 D06 저장과 별개이며 D08 human_reviewed 채점/최초·재시험은 위 평가 CLI로 연결합니다. 선언 시간은 문서별 합계이며 실제 사람별 순작업 시간이나 재시험의 새 작업시간을 인증하지 않습니다. 세 방법 비교는 아래 별도 CLI를 사용하며 실제 검토본 전달은 후속 작업입니다. 키·AI·네트워크·DB는 사용하지 않습니다.

## 사람 수정값의 D06 사실 투영

[human-handoff-v1](../contracts/human-handoff.md)은 frozen human-review의 수정값을 기존 시간/장소/근거 규칙으로 투영하고 부모 D05 전체와 별도 보관합니다. 실패 부모도 실패 상태를 유지하며 미상·중복·빈 사건과 원래 변경 기록을 보존합니다. 실제 DB revision/승인/변경 기록은 만들지 않습니다.

```sh
python3.13 -m processing.evaluation check-handoff --input data/private/evaluation/handoff.json
python3.13 -m processing.evaluation freeze-handoff --input data/private/evaluation/handoff.json
python3.13 -m processing.evaluation verify-handoff HANDOFF_REF
```

`--review-root` 기본값은 private evaluation/human-reviews, freeze/verify의 `--root`는 private evaluation/handoffs입니다. summary는 projection_only·backend_import_supported=false·review_required=true이며 투영 JSON을 직접 Java에 넣지 않습니다. 별도 [Java 인계 요청](../backend/docs/human-handoff-import.md)으로 전체 이미지·source-root의 원문 asset/hash·등록 D03/D05·명시 revision을 대조합니다. 원래 경로 없는 재검증·동시/충돌·0400/0500·종료0/2/3/5를 지원하며 키·AI·외부 네트워크·DB는 사용하지 않습니다.

## 규칙 자동 기준선

[rule-profile-v1/rules-run-v1](../contracts/rule-baseline.md)은 개발용에서 고정한 리터럴 유형 키워드·날짜/시간 패턴·지명/별칭·대상/예외 주변 문장으로 추출합니다. 아래 프로필·입력은 합성입니다. 실제 확인 평가에 쓰기 전 개발용 사전의 검토·고정이 필요하며 도구가 검토를 인증하지 않습니다.

```sh
python3.13 -m processing.extraction rules-run \
  --input contracts/examples/ai-input.json \
  --profile processing/examples/rule-profile.json \
  --preprocessing-version smoke-nfc-v1
python3.13 -m processing.extraction rules-verify RUN_UUID
```

기본 위치는 Git 제외 `data/private/rule-runs`이며 `--root`로 지정합니다. 입력·프로필·실제 출력·메타데이터·identity·receipt를 파일0400/디렉터리0500의6파일 이미지로 배타 설치합니다. 입력/프로필의 정확한 바이트와 전처리 버전이 같을 때만 같은 `--run-id UUID`를 재사용합니다. 원래 입력 경로 없이 전체 hash·시간 순서·결정적 결과를 재검증합니다. AI D05 등록·초안 경로에는 이 형식을 넣지 않습니다.

문서당 사건/일정1건의 약한 기준선이며 복수/미지원 날짜·시간은 미상으로 남깁니다. 원문에 없는 연도/주소/좌표를 채우지 않고 알려진 빈 예외와 미기재를 구별합니다. 출력8MiB 또는 대상/예외 각각256문장 초과는 실패 원본과 RULE_OUTPUT_LIMIT으로 보존합니다. stdout은 원문·경로 없는 receipt이며 성공0·실행 실패4·입력2·보관 손상/충돌3·I/O5·내부1입니다. 키·AI·네트워크·DB를 사용하지 않습니다.

출력은 기존8필드 채점기와 D08 선택/최초·재시험 동결의 `method=rules`에 연결합니다. 사건/생성 의미 판정 annotation은 사람이 제공하며,1회 실행이므로 first/final annotation이 같아야 합니다. 선택한 모든 실행의 규칙/프로필 버전·SHA가 같아야 하고, policy에는 프로필 검토자·실행 전 고정 시각·development_only/holdout_feedback/unknown 선언을 남깁니다. initial은 development_only만 받으며 holdout_feedback 재시험은 의미 피드백·노출 표시가 필요합니다. 신원·실제 사전 고정의 진실성은 인증하지 않습니다.

위 평가 CLI를 그대로 사용합니다. 보관본은6파일 규칙 원본·gold·initial 전체를 포함하며 원래 경로 없이 재검증합니다. 기존 AI 평가 형식/바이트도 유지합니다. 세 방법의 짝지은 개선/악화 비교는 아래 별도 CLI를 사용합니다. 실제 지명 검토·독립 정답·40건 평가를 수행한 결과가 아닙니다. Windows와 전원 중단 내구성은 미검증이며 POSIX 권한은 WORM이 아닙니다.

## 검증·남은 작업

등록한 D05에서 `python3.13 -m processing.extraction draft`로 ai-draft-import-v1을 생성하고 Java local-import로 저장할 수 있다. 실행 인자·사람 검토본 작성·승인 경계는 [초안 연결 안내](../backend/docs/ai-review-draft.md)를 따른다. API 실행과 분리된 로컬 변환이며 AI 원본과 초안을 사람이 확인해야 한다.

자동 시험으로 시간·거리·결합·취소·최신성·재현·정렬·중첩·실제 CLI 오류를 확인합니다. 실제 Java 공개 상세 예제와 사실 필드 전체도 대조합니다. AI 검증은 한글/emoji·미상·형식/근거 오류·실패 원본·충돌·동시 실행·중단 재개·손상·실제 subprocess를 확인합니다. CI에서 Python3.13 시험과 기존 계약·백엔드 시험을 함께 실행합니다. 시험 목록은 `tests/`, 설계 결정은 [계산 계획](../docs/superpowers/plans/2026-11-03-calculation-cli.md)과 [추출 기록 계획](../docs/superpowers/plans/2026-11-03-extraction-validation.md)에 있습니다.

AI 원출력·사람 검토본은 별도 보존합니다. 공식 공사·행사·교통 개발 공지3건의 첫 v1 실행은 `EVIDENCE_MISMATCH`로 중단돼 원본을 남겼습니다. 같은 입력의 새 v2 실행은 각각1회 기계 검증을 통과했고 사건1건씩·근거7/5/15개를 추출했습니다. 재실행을 새 문서3건으로 중복 집계하지 않습니다.

새 전용 MySQL8.4.13에서 실제 JAR로 D03 3문서/3버전·기존 D05 v1 실패3/v2 성공3·D06 `ai_draft/draft/hidden` 초안3을 저장했습니다. D06에는 개발 구역·사전 후보의 식별자만 연결했으며 `area_membership=uncertain`, 검토자·검토 시각·geometry는 null입니다. 원래 미배정 초안과 모든 원본은 보존했습니다. 후보를 확정하거나 지점5개·사전 행을 DB에 등록하지 않았습니다. 정확한 재실행·변조/실패 실행/다른 문서 참조·직접 승인 거부와 원본/공개 테이블 불변의 결과는 [저장 검증](../backend/docs/ai-review-draft.md#실제-개발-자료의-저장-검증)을 따릅니다.

원문은 `use_review=pending`·`check_result=uncertain`이며 사람의 사실성·이용권한 확인은 완료되지 않았습니다. 구역·사전·문서 관계/분할과 좌표를 사람이 확인하고 별도 검토 revision을 준비해야 합니다. 사람 검토본 전달·독립 정답표·40문서/holdout 평가·승인/공개·운영 배포는 후속 작업입니다. 같은 문서의6실행을6문서로 집계하지 않으며 실제 데이터셋은 여전히 dev3/holdout0입니다. 세부 요구는 [TASK.md](TASK.md)를 따릅니다.
