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
| `extraction/draft.py` | 검증된 원출력→숨김 검토 초안·안정 ID·근거 hash 변환·미상 보존 |
| `evaluation/dataset.py`, `storage.py`, `__main__.py` | D08 문서/사건 연결·분할 검증·비공개 manifest 불변 보관·CLI |
| `evaluation/bindings.py` | 동결 manifest·실제 입력 바이트·명시 선택한 D05 원본의 읽기 전용 대조 |
| `evaluation/gold.py`, `gold_storage.py` | 독립 정답 제공자의 선언·근거·사건 anchor 검사와 원본/지침/manifest 별도 동결 |
| `evaluation/scoring.py`, `records.py`, `evaluation_storage.py` | 8필드 채점·명시한 API 실행 연결·최초/재시험 원본 묶음 동결 |

[계산 연결 계약](../contracts/calculation-bridge.md)을 따릅니다. 지원 규칙은 `rules-v1`이며 미지원 버전을 정상 결과로 바꾸지 않습니다. `dictionary_version`은 선택한 snapshot의 고정 식별자이며 계산 중 새 사전을 읽지 않습니다. 입력 원본 바이트 SHA-256을 반환하며 개인 조건은 로그에 남기지 않습니다.

- 입력·출력 각각8MiB, JSON 깊이100. 선택한 카드와 중첩 묶음을 만드는 중에도 누적 출력 예산을 검사하고 JSON을 제한된 버퍼로 직렬화합니다. 성공0, 입력 오류2, 출력 초과3, 런타임 오류1로 종료합니다. 오류 시 stdout은 비어 있고 stderr에는 고정 오류 코드만 씁니다.
- Java adapter는 설정된 실행 파일·workdir, 공통 timeout, 동시 stdin/stdout/stderr 처리, 입출력·실행 수 제한, 응답 hash/버전·사실 대조를 담당합니다. CLI 단위 시험과 실제 DB·API 연결 시험을 함께 유지합니다.
- date_only와 미상 영업을 종일로 채우지 않습니다. 확정 overlap만 묶고, 총량을 확정하지 못하면 분 수는 null입니다. 부분 geometry에서 확인된 이내는 후보가 될 수 있지만 전체 최소 거리는 null로 유지합니다.
- 명시된 다른 종료 날짜에는 익일 offset을 다시 더하지 않습니다. 반복 날짜가 있으면 각 날짜의 시간+offset을 적용하며 빈 반복 배열은 발생 없음입니다. 날짜 범위만 보고 매일 반복시키지 않습니다.
- replay는 고정 cutoff 이전 문서·확인만 사용하고, 24시간 경과는 고정 reference_instant로 계산합니다. 재구성과 당시 검증본을 구분하며 현재 연결 상태는 별도 표시합니다.

Java D05 등록은 [D03/D05 연결 안내](../backend/docs/extraction-run-import.md)를 따른다. 원문을 먼저 등록하고 같은 전체 블록·전처리 버전의 AI 입력을 사용한다.

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

[extraction-evaluation-v1](../contracts/extraction-evaluation.md)에 따라 독립 gold와 버전마다 명시한 API 실행을 연결합니다. 사람이 사건/일정 대응과 생성 오류 판정을 기록합니다. 원출력은 바꾸지 않고 첫 raw·최종 자동 결과를 함께 채점합니다. null·누락·실패도 gold에 정답이 있으면 분모에 남습니다. 생성 여부의 의미 검토가 남으면 생성률은 N/A입니다.

```sh
python3.13 -m processing.evaluation check-evaluation \
  --input data/private/evaluation/selection.json
python3.13 -m processing.evaluation freeze-evaluation \
  --input data/private/evaluation/selection.json
python3.13 -m processing.evaluation verify-evaluation EVALUATION_REF
```

선택 입력의 키·정책·annotation은 계약 문서에 설명합니다. 기본 gold/run/initial 경로는 각각 `data/private/evaluation/gold`, `data/private/extraction-runs`, `data/private/evaluation/extractions`이며 `--gold-root`, `--run-root`, `--initial-root`로 지정할 수 있습니다. freeze/verify의 평가 보관 위치는 `--root`로 정합니다.

initial은 gold 동결 이후 시작한 실행만 받습니다. retest는 동일 cohort·정규화 지침·방법의 동결 initial을 참조하며 금표/정책 변경·노출 선언·점수 차이를 남깁니다. 새 실행은 initial 동결 이후 시작해야 하고, 금표 수정만 재채점할 때는 기존 실행을 유지할 수 있습니다. 재시험을 최초 성능·새 일반화 증거로 표시하지 않습니다.

보관본은 `selection.json`, 비공개 `result.json`, gold 전체, 선택한 D05 전체, retest의 최초 평가 전체를 포함합니다. 파일0400·디렉터리0500으로 검증한 뒤 배타 설치하며 같은 ID의 다른 입력은 충돌입니다. 원래 경로가 없어도 재검증·같은 입력 재사용이 가능합니다. 최초 평가와 실패 원본을 덮어쓰지 않습니다. 상세 값·근거·검토자·원래 경로는 private 파일에만 두고 stdout에는 요약/상대 artifact 목록만 출력합니다. 성공0·입력2·보관본 손상/충돌3·I/O5·내부 오류1로 종료합니다.

키·AI·네트워크·DB를 사용하지 않는 도구이며 실제40문서 성과를 측정하지 않았습니다. M02 수치는 real/문서 수/비노출 등의 선언과 확인용 정답 분모가 갖춰진 initial에서만 제공하며, 그 자체로 의미 정확성·신원·blind holdout을 인증하지 않습니다. 단순 규칙 기준선·사람 수정값 연결·실제 독립 금표/40건 평가는 후속 작업입니다.

## 검증·남은 작업

등록한 D05에서 `python3.13 -m processing.extraction draft`로 ai-draft-import-v1을 생성하고 Java local-import로 저장할 수 있다. 실행 인자·사람 검토본 작성·승인 경계는 [초안 연결 안내](../backend/docs/ai-review-draft.md)를 따른다. API 실행과 분리된 로컬 변환이며 AI 원본과 초안을 사람이 확인해야 한다.

자동 시험으로 시간·거리·결합·취소·최신성·재현·정렬·중첩·실제 CLI 오류를 확인합니다. 실제 Java 공개 상세 예제와 사실 필드 전체도 대조합니다. AI 검증은 한글/emoji·미상·형식/근거 오류·실패 원본·충돌·동시 실행·중단 재개·손상·실제 subprocess를 확인합니다. CI에서 Python3.13 시험과 기존 계약·백엔드 시험을 함께 실행합니다. 시험 목록은 `tests/`, 설계 결정은 [계산 계획](../docs/superpowers/plans/2026-11-03-calculation-cli.md)과 [추출 기록 계획](../docs/superpowers/plans/2026-11-03-extraction-validation.md)에 있습니다.

AI 원출력·사람 검토본은 별도 보존합니다. 공식 공사·행사·교통 개발 공지3건의 첫 v1 실행은 `EVIDENCE_MISMATCH`로 중단돼 원본을 남겼습니다. 같은 입력의 새 v2 실행은 각각1회 기계 검증을 통과했고 사건1건씩·근거7/5/15개를 추출했습니다. 재실행을 새 문서3건으로 중복 집계하지 않습니다.

실제 JAR로3건의 D05 validated 등록을 전용 시험 DB에서 확인했습니다. 비공개 ai_draft/draft/hidden 파일은 구역을 미배정 UUID, 사전을 development-unassigned로 명시했으며 실자료 D06 DB에 저장하지 않았습니다. 실제 구역·사전·문서 관계/분할을 확정한 뒤 새 경로로 초안을 재생성하고 사람이 원문을 대조해야 합니다. 기계 검증은 사실성·사람 승인·공개와 다릅니다. 사람 검토본 전달·정답표 평가·운영 배포·실자료40문서 성능 측정은 후속 작업입니다. 세부 요구는 [TASK.md](TASK.md)를 따릅니다.
