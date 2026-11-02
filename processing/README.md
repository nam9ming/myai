# Python AI·계산 — 김윤기

C01~C10 순수 계산과 `calc-v1` CLI, Spring 공개 matches 연결, AI 추출 계약 검증·수동 원출력 보관 CLI를 구현했습니다. **실제 모델 호출은 아직 미구현**입니다. 공개 API·DB는 Spring이 맡으며 계산 CLI는 AI·네트워크·DB를 호출하거나 사용자 조건을 저장하지 않습니다. 서버의 Python 실행 파일·작업 경로는 [백엔드 안내](../backend/README.md#python-계산-연결)를 따릅니다.

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

[계산 연결 계약](../contracts/calculation-bridge.md)을 따릅니다. 지원 규칙은 `rules-v1`이며 미지원 버전을 정상 결과로 바꾸지 않습니다. `dictionary_version`은 선택한 snapshot의 고정 식별자이며 계산 중 새 사전을 읽지 않습니다. 입력 원본 바이트 SHA-256을 반환하며 개인 조건은 로그에 남기지 않습니다.

- 입력·출력 각각8MiB, JSON 깊이100. 선택한 카드와 중첩 묶음을 만드는 중에도 누적 출력 예산을 검사하고 JSON을 제한된 버퍼로 직렬화합니다. 성공0, 입력 오류2, 출력 초과3, 런타임 오류1로 종료합니다. 오류 시 stdout은 비어 있고 stderr에는 고정 오류 코드만 씁니다.
- Java adapter는 설정된 실행 파일·workdir, 공통 timeout, 동시 stdin/stdout/stderr 처리, 입출력·실행 수 제한, 응답 hash/버전·사실 대조를 담당합니다. CLI 단위 시험과 실제 DB·API 연결 시험을 함께 유지합니다.
- date_only와 미상 영업을 종일로 채우지 않습니다. 확정 overlap만 묶고, 총량을 확정하지 못하면 분 수는 null입니다. 부분 geometry에서 확인된 이내는 후보가 될 수 있지만 전체 최소 거리는 null로 유지합니다.
- 명시된 다른 종료 날짜에는 익일 offset을 다시 더하지 않습니다. 반복 날짜가 있으면 각 날짜의 시간+offset을 적용하며 빈 반복 배열은 발생 없음입니다. 날짜 범위만 보고 매일 반복시키지 않습니다.
- replay는 고정 cutoff 이전 문서·확인만 사용하고, 24시간 경과는 고정 reference_instant로 계산합니다. 재구성과 당시 검증본을 구분하며 현재 연결 상태는 별도 표시합니다.

Java D05 등록은 [D03/D05 연결 안내](../backend/docs/extraction-run-import.md)를 따른다. 원문을 먼저 등록하고 같은 전체 블록·전처리 버전의 AI 입력을 사용한다.

## AI 수동 원출력 기록

```sh
python3.13 -m processing.extraction prepare --input contracts/examples/ai-input.json
python3.13 -m processing.extraction import \
  --input data/private/input.json --metadata data/private/metadata.json \
  --attempt data/private/actual-prompt.txt data/private/raw-output.txt
python3.13 -m processing.extraction verify 71fb66f0-e610-4f9c-8f26-4bb77655ee8c
```

첫 명령은 합성 입력의 프롬프트만 생성합니다. 가져오기에는 실제 제공한 프롬프트·원출력과 새 run_id의 메타데이터를 준비합니다. 기본 저장 위치는 Git 제외 `data/private/extraction-runs`입니다. 같은 ID의 원본을 덮어쓰지 않으며 실패·과다 출력도 전부 보존합니다. 마지막 출력이 기계 검증을 통과해도 `review_required=true`이며 사람 승인과 다릅니다. 종료 코드·1~3시도·복구·hash 대상·미상 제공값 처리 등은 [실행 기록 계약](../contracts/extraction-run.md)을 따릅니다.

## 검증·남은 작업

자동 시험으로 시간·거리·결합·취소·최신성·재현·정렬·중첩·실제 CLI 오류를 확인합니다. 실제 Java 공개 상세 예제와 사실 필드 전체도 대조합니다. AI 검증은 한글/emoji·미상·형식/근거 오류·실패 원본·충돌·동시 실행·중단 재개·손상·실제 subprocess를 확인합니다. CI에서 Python3.13 시험과 기존 계약·백엔드 시험을 함께 실행합니다. 시험 목록은 `tests/`, 설계 결정은 [계산 계획](../docs/superpowers/plans/2026-11-03-calculation-cli.md)과 [추출 기록 계획](../docs/superpowers/plans/2026-11-03-extraction-validation.md)에 있습니다.

AI 원출력·사람 검토본은 별도 보존합니다. 실제 자료 수집·AI 추출·정답표 평가·운영 배포·실자료40문서의 성능 측정은 후속 작업입니다. 합성 자료의 연결·처리 시간 관찰은 실자료 평가와 구분합니다. 세부 요구는 [TASK.md](TASK.md)를 따릅니다.
