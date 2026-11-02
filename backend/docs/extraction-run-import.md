# D03 선등록·D05 AI 실행 기록 등록

Java21·MySQL8.4.13·Python3.13을 사용한다. 준비된 수동 AI 도구의 원본 기록을 DB에 등록하며 실제 모델 호출·자료 수집·사실성 검토·공개 승인을 수행하지 않는다. 외부 Python 의존성은 없다.

## 원문만 먼저 등록

DB 환경변수와 JAR를 [백엔드 안내](../README.md)에 따라 준비한다. `source-import-v1`은 기존 검토본과 같은5키 `schema_version/data_kind/documents/evidence/events`다. documents≥1, evidence/events=[]이며 D03 원문·hash·블록·확인 이력·이용권한 검증을 재사용한다. 사건·revision·공개본은 만들지 않는다. 기존 `reviewed-import-v1`의 근거·사건 최소1은 유지한다.

```sh
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-import \
  --myai.import.file=backend/examples/source-import.json \
  --myai.import.source-root=backend/examples \
  --myai.import.actor=synthetic-collector
```

예제는 합성이다. 실제 자료는 `data/private/` 아래 파일과 원문 root를 지정한다. 같은 source 배치는 기존 결과를 반환하고 `import_batches.source_kind=source`로 구분한다. 원문을 수정하려면 새 문서 버전이 필요하다.

## 같은 문서의 추출 입력 준비

AI 입력은 D03의 `data_kind/document_version_id/title/published_date`와 `block_index`를 `blocks`로 옮긴5키다. 전체 블록 순서·ID·페이지·텍스트와 metadata.preprocessing_version까지 저장된 D03과 같아야 한다. 현재는 전체 문서 입력이며 chunk 입력은 지원하지 않는다.

다음은 위 합성 source 예제의 입력만 생성하며 기존 파일을 덮어쓰지 않는다.

```sh
umask 077
python3.13 - <<'PY'
import json
from pathlib import Path
source = json.loads(Path('backend/examples/source-import.json').read_text(encoding='utf-8'))
doc = source['documents'][0]
value = {'data_kind': source['data_kind'],
         **{k: doc[k] for k in ('document_version_id', 'title', 'published_date')},
         'blocks': doc['block_index']}
target = Path('data/private/ai-input.json')
target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
with target.open('x', encoding='utf-8') as stream:
    json.dump(value, stream, ensure_ascii=False, indent=2)
PY
python3.13 -m processing.extraction prepare --input data/private/ai-input.json
```

실제 제공한 프롬프트·시도별 원출력과 정확한 run_id/document_version_id·도구 표시값·전처리 버전의 metadata를 [Python 기록 계약](../../contracts/extraction-run.md)에 따라 import한다. 미확인 비용·시각을 추정하거나 합성 예제를 실제 실행 실적으로 집계하지 않는다. GitHub 코드 리뷰 키와 로컬 추출 키는 별도다.

## 검증 후 DB 등록

저장소 루트에서 실행한다. archive-root는 `<run_id>/`를 포함하는 비공개 상위 디렉터리다. run-id는 실제 가져온 기록의 UUID로 바꾼다.

```sh
export MYAI_PYTHON_WORKDIR="$PWD"
export MYAI_PYTHON_EXECUTABLE=python3.13
java -jar backend/build/libs/myai-backend-0.1.0.jar \
  --spring.profiles.active=local-extraction \
  --myai.extraction.run-id=71fb66f0-e610-4f9c-8f26-4bb77655ee8c \
  --myai.extraction.archive-root="$PWD/data/private/extraction-runs" \
  --myai.extraction.actor=synthetic-registrant
```

actor는 비어 있지 않은128자 이하 문자열이며 제어 문자를 허용하지 않는다. `MYAI_EXTRACTION_TIMEOUT_MS` 기본60000, 허용1~60000ms다. 실행 파일/workdir는 계산기와 같은 설정이다. DB 트랜잭션 전에 고정 인자 `processing.extraction verify`를 호출하며 입출력8MiB·stderr64KiB·공통 timeout·interrupt/자식 정리를 적용한다. child stderr를 결과에 복사하지 않는다.

Python 성공0과 원출력 검증 실패4를 각각 D05 validated/failed로 등록한다. input/metadata/receipt 원본과 hash를 대조한 뒤 짧은 RR 트랜잭션에서 D03 입력·합성 태그·전처리 버전을 확인한다. 손상·미완료·잘못된 원본은 등록하지 않는다. 같은 run_id·같은 원본은 최초 결과를 재사용하며 다른 원본·archive 경로·receipt는 충돌이다. 동시 중복 복구는 실패 트랜잭션 종료 후 새로 조회한다.

V3는 provider/model을 nullable로 바꾸고 모델/계약/전처리 버전·실행 방식·시도 수·합성 태그·metadata/receipt 원문과 hash·최초 등록 actor/시각을 보존한다. 비용·usage·외부 나노초 시각·미상 사유는 LONGTEXT 원본에 남긴다. registered_at은 DB 등록 시각이며 실제 모델 시각·Python recorded_at과 다르다. legacy 행의 없는 metadata는 null로 유지하고 성공으로 승격하지 않는다. legacy 행의 별도 이관은 미지원이다.

stdout은 안전한 JSON 한 건이다. 바깥 `status=succeeded`는 등록 성공이며 안쪽 `result.status`는 AI 원출력의 validated/failed다. 모두 `review_required=true`다. 본문·raw_ref·실제 경로·원출력은 결과에 넣지 않는다. 강제 웹 모드와 public/fixture/다른 local 프로필 혼합은 context refresh 전에 차단한다.

| 종료 코드 | 의미 |
|---|---|
| 0 | 등록/동일 원본 재사용 성공. AI 상태는 result.status 확인 |
| 2 | 설정·입력 오류·미등록 D03 |
| 3 | 손상/미완료·문서/전처리 불일치·동일 ID 충돌 |
| 4 | DB/Python 의존성 장애. retryable 확인 |
| 5 | 파일 I/O 실패 |
| 1 | 내부·프로토콜·영구 SQL 오류 |

## D06 인계·보관

사람이 원문을 대조해 기존 reviewed-import-v1의 숨김 draft/needs_review를 준비한다. AI를 참고한 revision은 `origin=ai_reviewed`, `originating_run_ids`와 해당 `source_version_ids`를 연결한다. D05 기계 검증 성공·전체 metadata/hash가 있는 실행만 참조할 수 있으며 failed·legacy는 거부한다. import·승인·preview·publish는 등록 후에도 archive를 다시 검증하고 DB의 metadata/receipt·입출력 hash·D03 입력과 대조한다. 검증은 트랜잭션 밖이며 실행 ID별로 중복을 줄이고 각 사건의 source_version_ids를 따로 확인한다. 쓰기 직전에는 등록 행을 FOR SHARE로 읽어 전체 행 fingerprint가 같은지 확인한다. 검증 성공이 의미·예외·종일·좌표·현재 상태를 승인하지 않는다. D06 자동 초안 변환은 후속 작업이다.

D05 evidence hash는 블록 UTF-8, D06은 문서 전체 cleaned_text UTF-8다. 검토본 준비 시 문서 버전·블록·인용/code point 위치를 대조하고 hash 대상을 구분한다. 보정한 값으로 AI 원본을 덮어쓰지 않는다.

DB는 비공개 archive 절대 참조와 checksum을 저장한다. 파일을 복제하지 않으므로 경로·0700/0600 권한·백업·코드 버전을 함께 보존한다. 이동·편집·삭제 후 등록 성공을 원본 보존 완료로 간주하지 않는다. 이후 소비 전에도 verify하며 실패 원본을 지우지 않는다. 등록·검토 import만으로 공개 head/API는 바뀌지 않는다. 승인·공개는 기존 별도 명령과 사람 검토를 거친다.

반려와 이미 공개된 snapshot의 조회·rollback은 기존 불변 공개본 계약을 따른다. 새 AI 출처로 소비할 때의 재검증과 원본 파일의 장기 보존·백업 책임을 구분한다.
