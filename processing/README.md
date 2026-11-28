# 여기:it Python AI·계산

[현행 업무] 김윤기의 현재 업무는 기존 백엔드 재사용 조사·변경·프런트 연동입니다. 이상헌과 화면별 필드/API/오류를 합의하고 명묵의 반복 시나리오 검증에서 확인한 백엔드 원인을 수정합니다. Python 계약·추출·평가 변경은 그 조사 결과와 남규민의 분야·수집처·개인화·차별화 범위 합의에 맞춰 정합니다. 기존 김윤기 AI 배정은 과거 기록이며 새 전담 배정·실제 공수를 추정하지 않습니다. [작업 기준](TASK.md)을 함께 확인합니다.

[확정 요구] 여기:it은 안성시민 전체의 교육·배움 / 지원·혜택 / 행사·문화 / 공사·교통 / 생활정보를 다루며 기존 소상공인 기능을 유지합니다. [기존 구현·계약] 아래 `rules-v1/calc-v1`·추출/보관·평가 도구와3유형 처리 기록은 재사용 기반입니다. 기존5지점·500m·14일·영업시간 규격을 시민 서비스 전체의 제한이나 새5분야 완료로 해석하지 않습니다.

[합의 필요] 새 분야의 신청기간/진행일정·대상/자격·신청조건/방법·준비사항·비용·지역·원문·확보된 변경 전후/확인시점은 [공통 계약 보완 순서](../contracts/README.md#yeogi-it-contract-agreement)로 정합니다. 비용 누락은 무료가 아니며 신청 마감은 진행 종료가 아닙니다. 미상·없는 이력을 보존하고 연령·관심으로 자격을 확정하지 않습니다. 차별화 후보3개의 정확한 명칭·내용과 실제 AI 실행 방식은 확인·합의 전이며 공개 조회 중 AI를 호출하지 않는 기존 경계는 유지합니다.

Java의 [S10 로컬 검토 보고서](../backend/docs/review-report.md)는 이미 봉인된 D05 전체를 `verify-sealed`로 읽기 전용 검증한다. 모든 시도·불완전 API response·실패를 수정하지 않으며 사람 수정값과 구별한다. D03 raw 원문만 파일당20MiB 전체를 text/base64로 표시하며 AI artifact8MiB·전체 JSON/HTML64MiB, 기존 계산·추출 입력8MiB는 유지한다. 생성/복사하는 `freeze`는 기존 등록에 유지한다.

C01~C10 순수 계산과 `calc-v1` CLI, Spring 공개 matches 연결, OpenAI 추출·수동 원출력 보관 CLI를 구현했습니다. 실제 API 연결 결과는 각 실행의 receipt로 확인하며, 합성 연결 시험을 실제 공지 처리·품질 평가로 세지 않습니다. 공개 API·DB는 Spring이 맡으며 계산 CLI는 AI·네트워크·DB를 호출하거나 사용자 조건을 저장하지 않습니다. 서버의 Python 실행 파일·작업 경로는 [백엔드 안내](../backend/README.md#python-계산-연결)를 따릅니다.

T09의 [독립 거리 기준값 시험](../docs/superpowers/specs/2026-11-05-independent-distance-oracles-design.md)은 고정 합성 좌표·별도 계산한 기대 거리로 점·선분의 오차0.01m와500m 경계를 확인합니다. 이 수치 오차는 검색 반경에 더하지 않습니다.

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
| `extraction/citizen.py` | 시민5분야·title/categories·12개 원문 사실, 별도 수동 출력 schema·프롬프트 |
| `extraction/prompt.py`, `metadata.py` | 고정 프롬프트·문서/블록/hash 제약·D05 제공값 검증 |
| `extraction/archive.py`, `__main__.py` | 비공개 준비/수동 가져오기/무결성 검증·실패 원출력 보존 |
| `extraction/api.py` | 고정 OpenAI Responses API·최대3시도·요청/응답/전송 상태 보관·오프라인 재검증 |
| `extraction/chunks.py`, `chunk_archive.py` | 장문 block 계획·원문 근거/ID 보존·문서 cycle/실제 호출 분리·v2 원본 전체 재검증 |
| `extraction/rules.py`, `rule_runs.py` | 고정 키워드/날짜/지명 기준선·AI와 분리한 규칙 실행 원본 보관 |
| `extraction/draft.py` | 검증된 원출력→숨김 검토 초안·안정 ID·근거 hash 변환·미상 보존 |
| `evaluation/dataset.py`, `storage.py`, `__main__.py` | D08 문서/사건 연결·분할 검증·비공개 manifest 불변 보관·CLI |
| `evaluation/bindings.py` | 동결 manifest·실제 입력 바이트·명시 선택한 D05 원본의 읽기 전용 대조 |
| `evaluation/gold.py`, `gold_storage.py` | 독립 정답 제공자의 선언·근거·사건 anchor 검사와 원본/지침/manifest 별도 동결 |
| `evaluation/scoring.py`, `records.py`, `evaluation_storage.py` | 8필드 채점·명시한 API/규칙/사람 수정 원본 연결·최초/재시험 원본 묶음 동결 |
| `evaluation/comparison.py`, `comparison_storage.py` | 같은 gold·회차·AI 부모의 세 방법을 짝지어 개선/악화·선언 시간을 집계하고 전체 평가를 동결 |
| `evaluation/matching_projection.py`, `matching.py`, `matching_storage.py` | 독립 수동 기대 분류/사유와6개 뷰를 비교하고 검색 존재·완전 분류·전체 원본을 별도 동결 |
| `evaluation/study_protocol.py`, `study.py`, `study_export.py` | D09 private 프로토콜/기록·동의/기한·전체 분모를 검사하고 M04/M05·JSON/CSV를 명시 내보내기 |
| `evaluation/human_handoff.py`, `citizen_handoff.py`, `handoff_storage.py` | 명시 family별 D06 사실 투영·원본 전체 인계 이미지, 별도 Java 인계 요청으로 저장 |
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

같은 수동 실행 원본을 [로컬 HTTP 파일 업로드](../backend/docs/extraction-upload.md)로 전달할 수도 있습니다. Java는 자격정보를 제거한 자식 환경에서 기존 import/freeze를 호출하며 AI를 새로 실행하지 않습니다. 새 HTTP의 metadata64KiB·prompt20MiB·output5MiB와 기존 CLI metadata8MiB·manual prompt 무제한·큰 실패 출력 보존은 별도입니다. 실제 검증·리뷰·통합 상태는 [진행 계획](../docs/superpowers/plans/2026-11-05-extraction-result-upload.md)을 따릅니다.

```sh
python3.13 -m processing.extraction prepare --input contracts/examples/ai-input.json
python3.13 -m processing.extraction import \
  --input data/private/input.json --metadata data/private/metadata.json \
  --attempt data/private/actual-prompt.txt data/private/raw-output.txt
python3.13 -m processing.extraction verify 71fb66f0-e610-4f9c-8f26-4bb77655ee8c
```

첫 명령은 합성 입력의 프롬프트만 생성합니다. 가져오기에는 실제 제공한 프롬프트·원출력과 새 run_id의 메타데이터를 준비합니다. 기본 저장 위치는 Git 제외 `data/private/extraction-runs`입니다. 같은 ID의 원본을 덮어쓰지 않으며 실패·과다 출력도 전부 보존합니다. 마지막 출력이 기계 검증을 통과해도 `review_required=true`이며 사람 승인과 다릅니다. 종료 코드·1~3시도·복구·hash 대상·미상 제공값 처리 등은 [실행 기록 계약](../contracts/extraction-run.md)을 따릅니다.

## 포털·공식 웹 수집 원본 비교 시범

전국문화축제 CSV와 안성행사알림이 상세 JSON, 전국도서관 CSV와 안성시 도서관 공지 상세 HTML을 비교한다. 원본을 비공개 작업 디렉터리에 준비하고 저장소 루트에서 실행한다. 포털 CSV는 EUC-KR과 UTF-8, 공식 웹 상세는 UTF-8을 지원한다. 이 절의 수집 명령은 모두 인자 오류를 종료 1로 알리고, 종료 2는 원본이나 실패 기록을 남긴 부분 결과에만 쓴다.

```sh
python3.13 -B -m processing.collection culture \
  --portal-csv data/private/festivals.csv \
  --web-detail data/private/event-detail.json --web-id 123
python3.13 -B -m processing.collection living \
  --portal-csv data/private/libraries.csv \
  --web-detail data/private/library-notice.html --web-id 456
```

표준 데이터는 안성시 행을 골라 읽는다. 축제 주소가 비어 있으면 안성시 주최기관 또는 공식 도메인을 기준으로 후보에 넣는다. 결과에는 각 입력 파일의 SHA-256, CSV 원본 레코드 번호(헤더와 빈 줄 제외), 검토할 두 출처의 값, 관계 후보가 들어 있다. 행사에서 공식 링크·제목·시작일·종료일이 모두 일치하면 후보로 표시하고, 중복 후보는 함께 남긴다. 겹치는 값이 다르면 출처별 값을 보여준다. 도서관 이름이 공지에 독립된 이름으로 등장하면 운영 기준과의 관계 후보를 표시한다. 시민 공지 등록 전에 출처, 적용 날짜·시간과 예외를 확인한다.

게시물별 본문·첨부 형식은 2026-11-27에 공식 상세 HTML로 확인했다.

| 게시판 | 확인한 형식 |
| --- | --- |
| 안성시청 공지 | [4404번 개통](https://www.anseong.go.kr/portal/bbs/view.do?bIdx=201589&mId=0501010000&ptIdx=16)은 이미지와 함께 시간표·요금을 본문으로 제공한다. [15번 변경](https://www.anseong.go.kr/portal/bbs/view.do?bIdx=201456&mId=0501010000&ptIdx=16)은 적용일을 본문으로, 시간표를 이미지로 안내한다. |
| 안성시청 공지 | [진로체험 캠프](https://www.anseong.go.kr/portal/bbs/view.do?bIdx=203043&mId=0501010000&ptIdx=16)는 일정·대상을 본문과 이미지 대체 텍스트에 싣고 신청은 포스터 QR로 안내한다. [바우처 지원사업](https://www.anseong.go.kr/portal/bbs/view.do?bIdx=192611&mId=0501010000&ptIdx=16)은 요약과 상세 공고 PDF를 함께 제공한다. |
| 안성시 도서관 공지 | [휴관 일정](https://www.anseong.go.kr/library/bbs/view.do?bIdx=195773&mId=0401010000&ptIdx=16)은 본문형, [서비스 전환](https://www.anseong.go.kr/library/bbs/view.do?bIdx=201918&mId=0401010000&ptIdx=16)은 본문·이미지 혼합형, [작은도서관 위탁](https://www.anseong.go.kr/library/bbs/view.do?bIdx=202585&mId=0401010000&ptIdx=16)은 본문·공고문·평가기준·제출서식 HWPX 혼합형이다. |

도서관 HTML은 본문과 이미지·첨부 유무를 구분한다. 읽을 수 있는 본문이 없는 글은 오류로 남긴다. 행사 상세는 원문 주소와 선택 링크를 함께 다루며, 썸네일이나 첨부 이미지가 있으면 확인 표시를 남긴다. 설명에 섞인 HTML은 원문 필드로 보관한다. 두 공식 웹 상세 모두 입력에 포함된 게시물 번호를 `--web-id`와 대조한다.

시청 공지 게시판(`board="city"`)은 도서관 공지와 같은 목록·상세 구조라 같은 파서를 게시판별 메뉴 번호와 문구로 사용한다. 목록은 POST `page`로, 상세는 `view.do?bIdx=…&mId=0501010000&ptIdx=16` GET으로 요청한다. 목록 맨 위의 번호 없는 `공지` 아이콘 글은 매 페이지에 반복되므로 `parse_board_listing`이 번호가 붙은 글과 나누어 반환한다. 번호 칸은 숫자 또는 `공지` 아이콘 하나만 허용하고 그 밖의 표시는 형식 변경으로 본다. 고정 글만 있는 페이지도 거부한다. 고정 글이 원래 게시 위치의 번호 행에 함께 나오는 경우는 보관한 1~3페이지와 따로 조회한 6~15페이지(원본 미보관)에서 관찰되지 않았지만 허용한다. 도서관 목록은 이 번호 칸 검사를 적용하지 않고 기존 기준을 유지한다. 묶음 수집과 D03 연결은 아래 [시청·안성배움e 공지 게시판 목록·상세 수집](#시청안성배움e-공지-게시판-목록상세-수집)을 따른다.

2026-11-27 시청 공지 1~3페이지에서는 같은 고정 글 3건이 모두 반복됐다. 고정 글 3건, 번호 글 30건 중 15건, 아래 진로체험 캠프 1건까지 19건의 상세에서 본문만 있는 글 4건, 본문과 본문 이미지가 함께 있는 글 9건, 본문과 첨부가 함께 있는 글 6건을 확인했다. [진로체험 캠프](https://www.anseong.go.kr/portal/bbs/view.do?bIdx=203043&mId=0501010000&ptIdx=16)처럼 포스터 이미지의 대체 텍스트에 본문 전체가 다시 들어간 글도 있다. 본문에 없는 일정·조건·신청 링크는 별도 원본을 확인할 때까지 미상으로 둔다. 같은 제목의 다른 게시물은 원문 ID별로 보관하고, 정정이나 재게시 관계는 내용과 게시 시각을 대조한다.

### 공식 웹 상세 내려받기 및 보관

포털 CSV를 준비한 뒤 공식 웹 게시물 번호로 한 건을 내려받아 함께 보관한다. 공공데이터포털에서 [축제](https://www.data.go.kr/data/15013104/standard.do)·[도서관](https://www.data.go.kr/data/15013109/standard.do) 표준 CSV를 내려받는다. 웹 요청은 안성시 고정 HTTPS 상세 경로에만 전송하며 리디렉션을 따르지 않는다. 원문은 포털 20MiB, 웹 8MiB까지 읽고 웹 소켓 작업별 대기 시간은 15초다.

```sh
python3.13 -B -m processing.collection.capture living \
  --portal-csv data/private/libraries.csv --web-id 203047 --name library-203047-first
```

`data/private/collection/<name>/`에 포털·웹 원본 바이트와 `capture.json`을 저장한다. 수집 루트와 묶음은 실행 사용자만 접근할 수 있어야 하며 수집 이름은 한 번만 쓴다. 웹 요청 주소·수신 시각·원본 해시와 비교 후보는 수집 기록에서 확인한다. 완료 파일인 `capture.json`은 마지막에 생성한다.

종료 0은 원본 보관과 파싱 성공, 2는 원본 보관과 파싱 실패, 1은 입력·웹 요청·저장 오류다. 형식이 바뀌거나 본문이 없는 경우 종료 2로 원본과 파싱 사유를 남긴다. 저장이 중단되어 완료 파일이 없으면 그 묶음은 사용하지 않는다. 성공한 비교에도 이미지·첨부 확인 표시와 미확정 관계가 남을 수 있다.

D03 등록이 필요하면 사람이 원문·추출할 내용·개인정보를 대조한 뒤 [기존 원문 등록](../backend/docs/extraction-run-import.md)에 원문 상대 경로·해시와 확인한 원출처 주소를 연결한다. `portal.catalog_url`은 비교 대상의 카탈로그 주소다. 현재 CSV를 어디서 받았는지는 운영자가 대조한다. 등록 초기 상태는 `pending`과 `unchecked`로 유지한다.

### 공공데이터포털 표준 OpenAPI 수집

공공데이터포털에서 해당 표준 API의 활용 신청을 완료하고 실행 환경의 `DATA_GO_KR_SERVICE_KEY`에 디코딩된 키를 넣는다. 실행 인자와 수집 기록에는 키를 넣지 않는다.

```sh
python3.13 -B -m processing.collection.portal culture --name festival-portal
python3.13 -B -m processing.collection.batch culture \
  --portal-snapshot festival-portal --begin 2026-11-01 --end 2026-11-30 --name festival-compare
```

`living`으로 도서관 표준 API도 수집할 수 있다. 전국 응답을 페이지당 500건씩 최대 20페이지, 응답당 8 MiB까지 받는다. 응답 원본·해시·키를 뺀 요청 주소·수신 시각은 `data/private/collection-portal/<name>/`에 보관한다. 모든 페이지가 확인되어야 기존 안성시 필터를 적용할 수 있는 비교용 `portal.csv`를 만든다. 종료 0은 완료, 2는 실패 기록 보관, 1은 설정 또는 저장 실패다. `--portal-snapshot`은 원본에서 CSV를 다시 만들어 보관본과 대조한 뒤 목록을 수집한다. 수동 CSV는 `--portal-csv`로 계속 받는다.

### 공공데이터포털 파일데이터 API 수집 (교육장·도로 공사)

파일데이터를 API로 제공하는 `api.odcloud.kr`에서 두 자료를 받는다. 키는 위 표준 API와 같은 `DATA_GO_KR_SERVICE_KEY`(디코딩된 키)에서만 읽고 실행 인자·원본 파일·수집 기록에 남기지 않는다. 응답이 키를 그대로·URL 인코딩·JSON 이스케이프 형태로 되돌려 보내면 저장하기 전에 거부한다.

```sh
python3.13 -B -m processing.collection.odcloud digital-learning --name learning-odcloud
python3.13 -B -m processing.collection.odcloud road-construction --name road-odcloud
```

| 키 | 자료 | 사용하는 API(Swagger 최신 항목) | 안성시 판단 |
| --- | --- | --- | --- |
| `digital-learning` (교육) | [디지털배움터 교육장 현황](https://www.data.go.kr/data/15134509/fileData.do) | `/api/15134509/v1/uddi:b87e06b5-9a2a-4627-a3b3-c7a850904a62` (`_20260814`) | `관리지역`이 `경기도`이고 `시군구`가 `안성시`(앞뒤 공백 제외) |
| `road-construction` (공사) | [국토교통부 도로 공사정보](https://www.data.go.kr/data/15052289/fileData.do) | `/api/15052289/v1/uddi:7cb3d05a-3099-4572-8a39-997740b78f76` (`_20260801`) | `주요사업지` 또는 `공사위치`에 `안성시` 포함 |

경로·인자·응답 구조는 2026-11-27에 받은 공개 Swagger 문서([15134509](https://infuser.odcloud.kr/oas/docs?namespace=15134509/v1), [15052289](https://infuser.odcloud.kr/oas/docs?namespace=15052289/v1))를 근거로 했다. 두 문서 모두 GET `page`·`perPage`·`returnType`, 인증은 `serviceKey` 쿼리 또는 `Authorization` 헤더, 응답은 `page`·`perPage`·`totalCount`·`currentCount`·`matchCount`·`data`다. 수집기는 `returnType=JSON`과 `serviceKey` 쿼리를 쓴다. 교육장 열은 `관리지역`·`시군구`·`배움터명`·`배움터주소`·`배움터 유형`·`이용정원`이고, 도로 공사 열은 `발주청`·`공사명`·`공사구분`·`주요사업지`·`사업개요`·`노선명`·`공사위치`·`시공사`·`현장주소`·`시작일`·`준공일`·`도급액(원)`이다. 같은 자료의 이전 항목(`_20240830`·`_20250820`, `_20230829`)은 수집하지 않는다.

자료가 개정되면 같은 namespace에 새 uddi 항목이 붙는다. 수집기는 위 표의 uddi만 받으므로 새 항목이 공개되어도 스스로 알지 못하고 옛 항목을 계속 완료로 남긴다. 그래서 실행 전에 Swagger 문서에서 가장 최근 항목(제목 끝 날짜)이 표의 항목과 같은지 확인한다. 더 새 항목이 있으면 `processing/collection/odcloud_format.py`의 `DATASETS`(uddi·제목·열)와 이 표·시험을 함께 고친 뒤 새 이름으로 다시 수집한다. 옛 항목으로 만든 보관본은 지우지 않고 남긴다. 판독과 D03은 같은 자료의 다른 uddi로 만든 보관본을 변조와 구별되는 오류(`현재 코드와 다른 파일데이터 API 항목(uddi)`)로 거부하므로, 새 수집본을 선택한다.

**인증된 실제 응답은 확인하지 않았다.** 이 환경에는 키가 없어 합성 응답으로만 시험했다. 그래서 문서와 다른 응답은 추정하지 않고 거부한다. 응답 최상위 키나 행의 열 이름이 Swagger와 정확히 같지 않거나, 요청한 `page`·`perPage`와 다르거나, `currentCount`가 행 수와 다르거나, 행 수가 전체 건수로 계산한 페이지 건수와 다르면 실패로 남긴다. 조건 인자를 보내지 않으므로 `matchCount`가 `totalCount`와 다른 경우도 실패다. 값은 문자열·정수·`null`만 받는다. 페이지 사이에 전체 건수가 바뀌거나, 앞 페이지에서 받은 행이 뒤 페이지에 다시 오면 멈춘다. 정렬 인자 없이 페이지를 넘기므로 서버 정렬이 흔들리면 행이 겹치고 그만큼 다른 행이 빠지기 때문이다. 원본 자료에 같은 행이 실제로 두 번 있어 페이지 경계에 걸린 경우도 구별할 수 없어 실패로 남긴다. 한 응답 안의 같은 행은 원본 자료의 중복일 수 있어 그대로 둔다. 전국 자료의 전체 건수가 0건이면 API 항목 변경이나 오류일 수 있어 `안성시 자료 없음`과 구별해 실패로 남긴다. HTTP 오류는 `파일데이터 API HTTP 응답 오류(상태 코드)`로 기록한다. 크기 초과·대기 시간 초과·연결 실패·지원하지 않는 인코딩 같은 전송 오류도 `파일데이터 API 응답…` 문구로 기록한다(예: `파일데이터 API 응답을 받지 못했습니다.`). 첫 실제 실행에서 이 규칙과 다른 점이 나오면 원본과 실패 사유를 보고 문서와 코드를 함께 고친다.

페이지당 500건씩 최대 20페이지(10,000건), 응답당 8 MiB까지 차례로 받고 요청 사이에 0.6초를 쉰다. 고정 HTTPS 호스트에만 요청하며 리디렉션은 따르지 않는다. `data/private/collection-odcloud/<name>/`에 받은 응답 원본 `page-N.json`, 모든 페이지를 확인한 뒤 만든 `anseong.json`, 마지막으로 `odcloud.json`을 저장한다. `odcloud.json`에는 Swagger·카탈로그 주소, 키를 뺀 요청 주소, 수신 시각, 원본 해시, 실패 사유가 남는다. 종료 0은 완료, 2는 실패 기록 보관, 1은 입력·설정·저장 오류다.

`anseong.json`의 `rows`는 안성시 행이며 원본 페이지·순번, 판단에 쓴 열과 원문 값(`match`), 빈 열 목록(`missing`), 원본 행 전체(`record`)를 그대로 담는다. 도로 공사 `시작일`·`준공일`이 비어 있으면 `missing`에 남기고 날짜를 채우지 않는다. 날짜 형식은 실제 응답을 확인하기 전이라 해석하지 않는다. `needs_review`는 사람이 확인할 행이며 `reason`으로 나눈다. `blank_location`은 판정 열(교육장 `시군구`, 도로 공사 `주요사업지`·`공사위치` 모두)이 비어 판정할 수 없는 행이다. `null`, 공백, `-`처럼 글자·숫자가 없는 값과 낱말 자리표시 `미정`·`미상`·`없음`·`해당없음`·`N/A`를 빈 값으로 본다. 낱말 자리표시는 NFC 정규화 뒤 공백을 모두 지우고 대소문자 구별 없이 비교하므로 `해당 없음`·`n/a`도 같다. 이 목록(`odcloud_format.py`의 `PLACEHOLDERS`)에 없는 낱말은 채워진 값으로 보고 판정하므로, 첫 실제 수집에서 판정 열의 서로 다른 값을 확인해 자리표시가 더 있으면 목록·이 문서·시험을 함께 고친다. `rows`의 `missing`도 같은 기준이라 `미정` 날짜는 미상으로 남는다. 이때 `mentions`는 모든 열에서 찾은 `안성` 표기다. 판정 열이 비었는데 `안성` 표기도 없는 행은 전국 행이 모두 들어갈 수 있어 `record`를 담지 않고 원본 페이지·순번만 `blank_location_unmentioned`에 남긴다. `mention`은 위치 열(교육장 `관리지역`·`시군구`·`배움터명`·`배움터주소`, 도로 공사 `주요사업지`·`공사위치`)에 `안성`이 보이지만 규칙에 맞지 않는 행이다. 예를 들어 `관리지역`이 `경기`인 행, 무주군 `안성면`, `안성시` 없이 `경기 안성`으로 적은 행이 여기에 들어간다. `other_mention`은 도로 공사 위치 열에 `안성`이 없지만 `발주청`·`공사명`·`사업개요`·`노선명`에 보이는 행이다. 위치 열이 `경기도`처럼 넓게만 적힌 행이 여기에 들어간다. 도로 공사의 `현장주소`는 현장사무실 위치일 수 있고 `시공사`는 업체 이름이라 판단과 `mention`·`other_mention` 검토에서 제외하고, `blank_location` 행의 참고 표기에만 나타난다. `odcloud.json`의 `selection`에는 세 목록의 건수가 남는다. 판정과 `안성` 표기 찾기는 NFC로 정규화한 값으로 하고 `match`·`record`에는 원문 값을 그대로 남긴다. 공사 구간이 여러 시군에 걸치면 안성시 포함 여부만 표시하고 안성시 안의 구간은 따로 확인한다. 교육장 자료는 교육장 위치·유형·이용정원만 있고 수업 일정·신청 조건은 없다.

### 공식 목록과 상세를 한 묶음으로 수집하기

포털 CSV 한 개를 고정한 뒤 공식 목록의 첫 페이지부터 게시물 번호를 찾아 상세를 비교한다. 행사는 최대 31일의 날짜 범위를 받는다. 도서관은 공지 목록의 게시판·페이지 번호를 대조하며 날짜 옵션 없이 사용한다.

```sh
python3.13 -B -m processing.collection.batch culture \
  --portal-csv data/private/festivals.csv --begin 2026-11-01 --end 2026-11-30 \
  --max-pages 20 --max-items 80 --name events-november
python3.13 -B -m processing.collection.batch living \
  --portal-csv data/private/libraries.csv --max-pages 2 --max-items 20 --name recent-library
```

기본 한도는 3페이지·20건이며 최대 20페이지·80건까지 지정할 수 있다. 요청을 하나씩 보내며 사이에 0.5초를 둔다. 목록 응답은 건당 2MiB, 상세는 건당 8MiB까지 받는다. HTTP 401·403·429·503을 받으면 이후 요청을 멈춘다. 조회 중 목록 건수나 페이지 수가 바뀌거나 ID가 중복되면 해당 페이지는 원본과 실패 사유를 보관하고 이전 페이지에서 확인한 번호만 사용한다.

`data/private/collection-batches/<name>/`에 포털 CSV, 받은 목록·상세 원본, 성공한 상세의 비교 결과를 저장한다. `batch.json`에는 각 원본의 해시와 수신 시각, 목록·상세 처리 상태가 있다. 맨 마지막에 `batch.json`이 생긴 묶음만 사용한다. 종료 0은 수집 중 보고된 페이지와 선택한 상세를 모두 처리한 경우, 2는 한도 도달 또는 일부 실패를 기록한 경우, 1은 입력·보관 오류다. 사이트 목록의 전체 건수가 같아도 수집 중 게시물이 바뀔 수 있다. 정기 실행은 후속 단계다.

### 도서관·시청·안성배움e 공지 이미지·첨부 원본 보관

게시물 번호로 공식 상세 HTML을 보관하고 본문 이미지와 첨부 목록을 확인한다. 읽을 수 있는 본문이 없는 공지도 게시물 번호와 제목이 확인되면 후보를 남긴다. 실제 다운로드 동작은 HTML에서 확인된 규격으로만 해석한다. [안성시 robots.txt](https://www.anseong.go.kr/robots.txt)에서 제한한 이미지 경로와 확인 요청에 HTTP 403을 반환한 파일 경로는 목록에만 기록한다.

```sh
python3.13 -B -m processing.collection.media inspect --web-id 202585 --name library-notice
```

`data/private/collection-media-notices/library-notice/notice.json`의 `media` 배열에서 순서대로 1부터 번호를 센다. 주소를 확인할 수 없는 항목은 `source_url=null`로 남긴다. 원문과 첨부를 비교해 용도·사용 조건·개인정보를 확인한 운영자가 확보한 파일을 해당 항목에 연결한다. 아래 시각은 예시이며 `--downloaded-at`에는 실제로 내려받은 시각을 UTC로 적는다.

```sh
python3.13 -B -m processing.collection.media store \
  --notice library-notice --asset 1 --file data/private/notice.hwpx \
  --downloaded-at 2026-11-27T08:00:00Z --name reviewed-attachment
```

이미지는 PNG·JPEG, 첨부는 PDF·HWP·HWPX·PNG·JPEG를 파일당 8MiB까지 받는다. 파일 헤더 또는 컨테이너 표식을 확인하고 부모 HTML, 연결 주소, SHA-256, 운영자가 입력한 수신 시각을 다시 대조한다. 부모 HTML과 매체 파일을 각각 `collection-media-notices/`, `collection-media/`에 보관한다. 두 묶음을 함께 보존한다. 운영자가 원문과 파일의 대응을 확인한다. 본문 추출·OCR·QR 판독은 별도 단계다.

시청·안성배움e·읍면동 공지는 `inspect --board city|edu|town-<경로 이름> --web-id <공지 번호>`로 같은 방식으로 보관한다(읍면동은 `--batch <묶음 이름>` 필수, 경로·주소 규칙은 아래 게시판 수집 절). 이때 `notice.json`에 `board`(`city`·`edu`·`town-<경로 이름>`)와 해당 게시판 상세 주소가 남고, `store`·D03 준비는 기록된 게시판의 주소와 파서로 다시 대조한다. 게시판 상세는 마크업이 같으므로 본문 영역 밖 `viewForm`의 게시판 주소(시청 `/portal/bbs/view.do?ptIdx=16&mId=0501010000`, 안성배움e `/edu/portal/bbs/view.do?ptIdx=300&mId=0901040000`, 읍면동 `/csc/<경로 이름>/bbs/view.do?ptIdx=16&mId=0500000000`)도 대조한다. 시청·안성배움e·읍면동은 이 표식이 반드시 있어야 하고, 도서관은 표식이 있으면 도서관 주소여야 한다. 도서관 기록은 `board` 없이 기존 형식을 유지한다. 읍면동 상세는 다른 읍면동 경로로도 열려 상세만으로는 소속을 알 수 없으므로, 읍면동 `inspect`는 같은 게시판 `board_batch` 묶음 이름을 `--batch`로 받는다. 그 묶음의 `batch.json`이 같은 게시판이고, 파싱에 성공한 목록 원본(`list-<페이지>.html`)의 해시가 기록과 같고, 그 원본을 지금 파서로 다시 읽은 번호 글·고정 글에 요청 번호가 있어야 상세를 요청한다. 묶음 이름은 `notice.json`의 `listing_batch`로 남고 `store`·D03 준비도 같은 대조를 다시 한다. 이 필드가 없는 이전 읍면동 기록은 거부되므로 `--batch`로 다시 받는다. 시청·안성배움e도 `--batch`를 주면 같은 대조를 한다. 첨부 주소는 페이지 스크립트의 `contextPath`(도서관·시청·읍면동은 빈 값, 안성배움e는 `/edu`)에 `/cmm/fms/FileDown.do`를 붙여 만들고, 페이지가 선언한 값이 게시판과 다르면 매체 목록을 거부한다. 안성배움e는 이 선언이 정확히 한 번 있어야 한다. 선언은 본문 영역 밖 최상위 `<script>` 가운데 내용 전체가 `var yh = {JSON 객체};`인 페이지 설정에서만 읽고, 본문·주석·다른 스크립트의 같은 문자열은 무시한다. 안성배움e 주소는 페이지 스크립트와 `/edu/common/js/common/EgovFileUtils.js`의 정의로 정했다. 그 함수가 먼저 쓰는 `G_CONTEXT_PATH`는 페이지 HTML과 확인한 `lib.js`·`common.js`에 정의가 없었다. 본문 이미지는 HTML의 루트 `/common/imgView.do` 주소만 연결하므로 다른 경로의 이미지는 `source_url=null`로 남는다(안성배움e 표본에는 본문 이미지가 없었다). 자동 확인 요청은 루트와 `/edu` 경로 모두 HTTP 403이라 실제 응답은 운영자가 내려받을 때 확인한다. 2026-11-27 시청 공지 203043(포스터 이미지 1개)과 203050(PDF 2개·HWPX 1개)에서 매체 주소를 모두 확인했다. 시청 묶음 수집에서 본문 텍스트가 없어 `parse_failed`가 된 이미지형 공지는 같은 번호를 `inspect --board city`로 다시 받아 별도 묶음으로 보관한다. 이 묶음은 묶음 수집 기록과 연결되지 않으며, 그 사이 게시물이 바뀌었으면 원본도 다르다.

### 도로 공사현황 목록·상세 수집

공사·교통 분야의 공사 사업 정보는 안성시 [도로 공사현황](https://www.anseong.go.kr/depart/contents.do?mId=0901020100)에서 수집한다. 포털 비교 원본 없이 공식 웹만 사용하며, 공식 메뉴의 `예정`·`진행중`·`완료` 구분을 각각 `planned`·`ongoing`·`completed`로 지정한다. 목록은 공식 메뉴가 쓰는 `searchGubun=1`·`state`·`mId` 조합에 수집기가 `page`를 붙인 GET 주소로 요청한다. 공식 화면은 페이지 이동을 POST로 보내지만 같은 GET 주소가 같은 목록을 반환하는 것을 확인했다. 공식 목록은 상세를 `req.post`로 열지만, 수집기는 같은 공사 번호와 구분의 `view.do?idx=…&mId=…&state=…` GET 주소로 요청한다. 리디렉션은 따르지 않는다. 경로는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다.

```sh
python3.13 -B -m processing.collection.road_batch ongoing --name road-ongoing-20261127 --max-items 30
python3.13 -B -m processing.collection.road_batch completed --name road-completed-p5 --start-page 5 --max-pages 4 --max-items 80
```

한 번에 최대 20페이지·80건이므로 그보다 긴 목록은 `--start-page`로 나누어 받는다. 시작 페이지가 1이 아니면 마지막 페이지에 도달해도 `discovery_status=end_reached`, 묶음 상태는 `partial`이다. 실행 사이에 공사가 추가·이동되면 페이지 경계가 밀린다. 나누어 받을 때는 연달아 실행하고, 각 묶음 `batch.json`의 `pages[].reported_pages`와 `web_ids`를 이어 붙여 페이지 수 변화와 번호 중복을 확인한다. 앞쪽 공사가 삭제되거나 다른 구분으로 옮겨져 생긴 누락은 이 방법으로 드러나지 않는다. 보관된 `list-N.html`의 `번호` 열은 1페이지 첫 값이 전체 건수이고 1씩 줄어들므로, 묶음 경계에서 번호가 이어지는지도 대조한다.

`data/private/collection-road-works/<name>/`에 목록·상세 HTML 원본과 파싱 결과 `parsed-<번호>.json`, 마지막으로 `batch.json`을 저장한다. 요청 간격·중단 HTTP 상태와 종료 코드 0·2는 위 목록 수집과 같다. 인자 오류를 포함한 입력·보관 오류는 종료 1이다. 목록 표의 구분 제목과 페이지 번호, 상세의 숨은 공사 번호와 목록 복귀 주소를 요청과 대조한다.

상세의 `지역`·`사업위치`·`사업량`·`공사기간`·`현재현황`·`담당부서`·`전화번호`는 표시 문구 그대로 `fields`에 보관한다. 제목과 값 안에서는 `span`·`a`·`b`·`strong`·`font` 같은 인라인 태그와 `br`·`p`·`li`·`ul`·`ol`만 허용하고, 줄바꿈·문단 경계는 공백 하나로 바꾼다. 그 밖의 태그가 나오면 형식 변경으로 본다. 빈 값은 `null`과 `missing:<필드>` 표시로 남긴다. 7개 항목 중 하나라도 없거나 다른 항목명이 나오거나 항목이 중복되면 형식 변경으로 보고 원본과 파싱 실패 사유를 남긴다. `공사기간`이 정확히 `YYYY-MM-DD ~ YYYY-MM-DD`이고 시작일이 종료일보다 늦지 않을 때만 `construction_period_range`에 날짜를 넣는다. 신청·행사 일정과 섞지 않도록 공사기간임을 이름에 남긴다. 날짜가 뒤집혔으면 `period_inverted`, 다른 형식이면 `period_unparsed`로 표시하고 원문을 고치지 않는다.

`listing_state`는 수집 시점에 공식 사이트가 분류한 메뉴 구분이다. `현재현황`에서 진행·종료를 추정하지 않으며 실제 도로 통제 구간·시간·우회 안내와 구별한다. 통제 안내는 시청 공지 등 별도 원본에서 수집해 공사 사업과 연결한다. 상세에 저장된 지도 화면은 타일과 화면 좌표뿐이어서 읽지 않는다.

2026-11-27 공식 HTML로 확인한 형식은 다음과 같다.

| 확인 범위 | 결과 |
| --- | --- |
| 목록 | 예정 1페이지 12건, 진행중 2페이지 26건, 완료 14페이지 275건. 세 구분 모두 결과가 있었다. 결과가 없는 응답은 다른 조회 조건(`searchGubun=2`)에서 `검색된 결과가 없습니다.` 한 행으로 확인했다. |
| 상세 표본 24건 (예정 3·진행중 7·완료 14) | 모두 같은 7개 항목. 지도 영역은 글마다 타일·경로 도형 구성이 달라 HTML 크기가 약 35만~37만 바이트로 차이가 있다. |
| `현재현황` | `설계중(용역사:…)`, `보상중(10%)`, `공정률 20%`, `준공`처럼 자유 서술이다. 완료 구분에도 `공사 중`, `공사중 [10%]`으로 남은 글이 있다. |
| `공사기간` | [1608번](https://www.anseong.go.kr/depart/roadConstruction/view.do?idx=1608&mId=0901020300&state=2)은 `2021-08-26 ~ 2021-06-22`로 역전되어 있다. 예정 12건 중 10건이 `2027-03-01 ~ 2028-12-31`이어서 실제 일정인지 담당 부서 확인이 필요하다. |
| 명령 실행 | 예정 12건·진행중 26건 전체, 완료 앞 20건(건수 한도)과 완료 14페이지 15건(`--start-page 14`)을 받아 73건 모두 파싱했고 D03 준비 경로의 원본·파싱 결과 재검증을 통과했다. 1608번만 `period_inverted`로 표시됐다. |

### 시청·안성배움e 공지 게시판 목록·상세 수집

교육·지원·교통 통제 안내가 함께 올라오는 시청 공지는 게시판 키 `city`로 받는다. 목록은 POST `page`, 상세는 GET으로 요청하며 두 경로(`/portal/bbs/list.do`, `/portal/bbs/view.do`)는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다. 한도·간격·중단 HTTP 상태·`--start-page`는 도로 공사현황과 같은 공통 묶음 규칙(`web_batch.py`)을 쓰고, 종료 코드도 도로 공사현황과 같다.

```sh
python3.13 -B -m processing.collection.board_batch city --name city-20261127 --max-pages 2 --max-items 40
```

`data/private/collection-boards/<name>/`에 목록·상세 HTML, `parsed-<번호>.json`(게시판별 파서 버전 포함, 현재 `city-notice-parser-v3`·`edu-notice-parser-v3`·읍면동 `town-<경로 이름>-notice-parser-v1`), 마지막으로 `batch.json`을 저장한다. 파서 버전은 게시판마다 따로 올리므로 한 게시판의 규칙을 바꿔도 다른 게시판 기록은 그대로 쓸 수 있다. 이전 공유 이름(`board-notice-parser-v1·v2`)으로 만든 기록은 D03에서 다시 수집하라는 오류로 거부된다. 본문 영역(`div.bod_view` 자신 포함)은 허용 목록만 받고, 목록 밖 표기가 있으면 공지·매체 파서 모두 거부한다. 허용 목록은 2026-11-27 실제 본문 128쪽(시청·안성배움e·도서관)에서 쓰인 태그·속성·인라인 스타일에 화면에 그대로 보이는 일반 문서 요소를 더한 것이다(`processing/collection/libraries.py`의 `_BODY_TAGS`·`_BODY_ATTRS`·`_STYLE_RULES`). `hidden`·`popover`·`inert` 같은 속성, `svg`·`iframe`·`video`·`link`·`progress` 같은 태그, `open`이 없는 `details`, `type="hidden"`이 아닌 `input`, `a`·`form`·`input` 밖의 `name`(같은 이름의 `details`는 하나만 열린다), `src`·`href` 밖 속성의 중복, 숫자가 아니거나 범위 밖인 `width`·`height`(`img` 10~9999, 그 밖 10~999, 10~100%)·`cellpadding`·`cellspacing`·`border`(0~99)는 거부한다. 본문 영역의 `script`는 실제 본문에 있던 첨부 도구 외부 파일(`/dwr/interface/EgovFileMngDwr.js`·`/dwr/engine.js`·`/dwr/util.js`·`/common/js/common/EgovFileUtils.js`와 `/edu/` 변형)만 내용 없이 받고, `template`은 받지 않는다. 인라인 스타일은 선언마다 허용 속성과 값 형태(단위별 하한·상한, 음수 크기, 색 형식, 낱말 값)를 확인하며, 목록 밖 속성·함수·단위·지수 표기, 같은 속성의 중복 선언, 주석·역슬래시가 있으면 거부한다(Word의 `mso-*`는 브라우저가 해석하지 않아 받는다). 문서 전체에서는 태그 경계를 Python 패치 버전과 무관하게 브라우저(HTML5) 규칙으로 고정한다. 주석은 `-->`에서만 닫고, `script`·`style`·`title`·`textarea`·`iframe`·`noscript` 등의 내용은 원문 텍스트로 읽으며 `</이름` 뒤에 공백·`/`·`>`가 올 때만 끝낸다. 빈 요소가 아닌 태그의 `/>`는 무시하고 `</ x>`는 가짜 주석으로 넘긴다. 브라우저와 해석이 갈리는 `<!-->`·`<!--->`·`--!>`·닫히지 않은 주석·`<?`·`<!`, 따옴표가 든 `<!` 선언, CDATA, 따옴표가 든 종료 태그, `</br>`(브라우저는 `<br>`로 읽는다), 엄격한 문법을 벗어난 시작 태그(따옴표 밖 `\xa0` 같은 유니코드 공백 포함), 인쇄 가능한 ASCII 밖의 글자(유니코드·제어 문자)나 공백·따옴표·`/`·`<`·`=`·`>`·백틱이 든 태그·속성 이름(Python은 켈빈 기호 `K`를 `k`로 바꿔 `<linK>`를 `link`로 읽는다. 실제 원본은 모두 ASCII 이름이라 브라우저보다 엄격하게 거부한다), `plaintext`, `svg`·`math`가 한 번 열린 뒤의 `<`가 든 원문 텍스트 요소·`/>`로 닫은 원문 텍스트 요소·`template`(브라우저는 그 안의 `style`·`title` 등을 마크업으로 읽는다. 이 파서는 브라우저가 svg를 닫는 규칙을 따라 하지 않고 문서 끝까지 열린 것으로 본다), 스크립트 이중 이스케이프(`<!--` 뒤 `<script` 안에서 Python이 스크립트를 끝낸 경우)는 거부한다. 3.13.5와 3.14의 표준 파서는 이 경계를 서로 다르게 읽었다. 이 경계 규칙은 `processing/collection/html_tokens.py`의 `PinnedHTMLParser`에 있고, HTML을 읽는 새 수집기도 이를 상속해 같은 규칙을 쓴다. 본문 영역 밖 `script`·`template`의 내용은 화면에 나오지 않으므로 무시한다. 확인하지 않는 것은 허용한 외부 스크립트의 실행 결과, 본문 영역 바깥 요소(조상 포함)의 숨김, class로 지정한 스타일시트 숨김(`class="blind"` 등), 허용한 값끼리의 조합으로 생기는 숨김(글자색과 배경색이 같음, 고정 크기 상자의 넘침 잘림 등)이다. 같은 실제 128쪽의 공지·매체 결과는 develop과 같았고, Python 3.13.5·3.14.6에서도 서로 같았다. 3.12는 `;` 없는 개체가 붙은 속성 값(`&ampx=`)을 3.13 이상·브라우저와 다르게 풀어 지원하지 않는다. 시작 페이지의 상단 고정 글을 먼저 받고 이후 페이지에서 반복되는 고정 글은 다시 받지 않는다. 순회 중 고정 글 목록이 바뀌거나 번호 글이 페이지 사이에 중복되면 그 페이지를 실패로 남기고 멈춘다. `pages[].pinned_ids`에 페이지별 고정 글을 기록한다.

고정 글도 건수 한도에 포함되므로 `--max-items`는 고정 글 수와 페이지당 10건 × 페이지 수의 합보다 크게 잡는다(최대 80건이므로 페이지 7장 이하). 한도에 걸리면 마지막 페이지의 뒤쪽 글은 `pages[].web_ids`에만 남고 상세를 받지 않으므로, `pages[]`와 `items`를 대조해 빠진 글이 있으면 다음 묶음을 그 페이지부터 다시 시작한다. 나누어 받으면 고정 글과 다시 받은 페이지의 번호 글이 여러 묶음에 들어가므로, 같은 공지 번호는 D03에 한 묶음의 원본만 등록한다. 페이지 경계 밀림과 앞쪽 삭제로 생기는 누락은 도로 공사현황의 나누어 받기 주의와 같다.

본문 텍스트가 없는 이미지형 공지는 원본과 함께 `parse_failed`로 남는다. 본문 이미지·첨부 확보와 OCR은 별도 단계다. 2026-11-27 실행에서는 1~2페이지의 고정 글 3건과 번호 글 20건, 23건을 모두 파싱했고 D03 준비 경로의 재검증을 통과했다.

교육 프로그램 안내가 올라오는 [안성배움e 프로그램 안내](https://www.anseong.go.kr/edu/portal/bbs/list.do?ptIdx=300&mId=0901040000)는 게시판 키 `edu`로 같은 명령을 쓴다(`board_batch edu`, `media inspect --board edu`). 경로는 `/edu/portal/bbs`, 메뉴 번호는 `0901040000`, 게시판 번호(`ptIdx`)는 시청·도서관의 16이 아닌 300이며, `/edu/` 경로는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다. 같은 CMS지만 상세 제목이 `<h4>`가 아니라 본문 영역 바로 아래 `div.bod_view_title`에 있으므로 이 게시판은 그 블록에서만 제목을 읽고, 그 자리에 `<h4>`가 나오면 형식 변경으로 거부한다. 2026-11-27 1~2페이지(전체 33페이지)의 20건은 고정 글 없이 모두 파싱·D03 재검증을 통과했고, 모두 첨부가 있었다(HWPX 6개·JPEG 11개·PNG 9개).

읍면동 15곳의 공지사항은 게시판 키 `town-<경로 이름>`으로 같은 명령을 쓴다(`board_batch town-yangseong`, `media inspect --board town-yangseong --batch <묶음 이름>`). 출처 이름은 `town_<경로 이름>_notice`, 오류 문구는 `양성면 공지`처럼 읍면동 이름을 쓴다. `/csc/`는 `/csc/gongdo/contents.do?mId=0100000000`(공도읍 첫 화면)으로 넘어가며, 그 화면의 읍면동 메뉴에서 아래 경로 이름을 확인했다. 각 사이트의 `공지사항` 메뉴 번호는 모두 `0500000000`, 게시판 번호는 시청과 같은 16이다. 목록은 `/csc/<경로 이름>/bbs/list.do?ptIdx=16&mId=0500000000`에 POST `page`, 상세는 `/csc/<경로 이름>/bbs/view.do?bIdx=…&mId=0500000000&ptIdx=16` GET이며 `/csc/` 경로는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다. 목록 화면 제목은 `공지사항 목록 | <읍면동> | 안성시청 홈페이지`였다.

| 키 | 읍면동 | 키 | 읍면동 | 키 | 읍면동 |
| --- | --- | --- | --- | --- | --- |
| `town-gongdo` | 공도읍 | `town-daedeok` | 대덕면 | `town-samjuk` | 삼죽면 |
| `town-bogae` | 보개면 | `town-yangseong` | 양성면 | `town-gosam` | 고삼면 |
| `town-geumgwang` | 금광면 | `town-wongok` | 원곡면 | `town-anseong1` | 안성1동 |
| `town-seoun` | 서운면 | `town-iljuk` | 일죽면 | `town-anseong2` | 안성2동 |
| `town-miyang` | 미양면 | `town-juksan` | 죽산면 | `town-anseong3` | 안성3동 |

상세 마크업은 시청 공지와 같다. 제목은 `<h4>`, 본문은 `div.view_cont`, 페이지 설정의 `contextPath`는 빈 값이라 첨부 주소는 시청과 같은 루트 `/cmm/fms/FileDown.do`다(페이지는 루트 `/common/js/common/EgovFileUtils.js`를 불러오며, `/common/`은 robots.txt 제한 경로라 그 파일은 받지 않았다). 상세의 `viewForm` 주소(`/csc/<경로 이름>/bbs/view.do?ptIdx=16&mId=0500000000`)는 반드시 있어야 하고 요청한 읍면동과 같아야 한다. 읍면동 목록의 `goTo.view` 인자(`'16','0500000000'`)는 15곳이 모두 같으므로 읍면동 게시판만 `form#list`의 action이 그 읍면동 목록 주소와 정확히 한 번 일치해야 목록을 받는다. 시청·안성배움e 목록은 메뉴 번호로 구별되므로 기존처럼 action을 보지 않는다.

읍면동 게시판은 시청 공지와 게시물 번호(`bIdx`) 공간을 공유한다. 시청 공지를 읍면동마다 일부 골라 보여 주고 읍면동에만 올린 글도 섞인다. 같은 번호의 상세는 어느 게시판 경로로 받아도 제목·본문·게시일이 같지만 조회수·메뉴·`viewForm`이 달라 원본 해시는 게시판마다 다르다. 다른 읍면동에만 있는 번호도 그 경로로 열리고 파싱된다(미양면 목록에만 있던 203049를 공도읍 경로로 확인). 그러므로 상세 주소는 그 게시판에 실렸다는 증거가 아니며, 게시판 소속은 묶음 수집 `pages[].web_ids`·`pinned_ids`의 목록 기록으로만 판단한다. 묶음 수집은 그 게시판 목록에 나온 번호만 상세를 받고, 매체 `inspect`도 같은 게시판 묶음의 목록 원본에 나온 번호만 받는다.

2026-11-27 15곳 모두 1페이지 목록(전체 29~40페이지)과 상세 6건씩(고정 글 3건과 앞쪽 번호 글 3건, 모두 90건)을 받아 전부 파싱했고, 90건 모두 D03 준비 경로의 원본·파싱 결과 재검증을 통과했다. `form#list` 검사를 넣은 뒤 양성면 4건 묶음을 다시 받아 같은 재검증을 확인했다. 상세 표본에서 본문 이미지는 루트 `/common/imgView.do` 주소로 모두 연결됐고, `media inspect --board town-gongdo --web-id 202988`에서 HWPX 첨부 1개의 루트 다운로드 주소를 확인했다(`--batch` 검사를 넣기 전). 실제 파일 응답은 확인하지 않았다. 본문 허용 목록과 브라우저 기준 태그 경계를 들인 뒤 2026-11-28 같은 실제 상세 97쪽(15곳 묶음 94쪽, 공도읍 매체 202988, 공도읍 탐색용 203001·203049)을 다시 읽었다. Python 3.13.5·3.14.6 모두 공지·매체 파서가 전부 통과했고, 묶음 94건의 공지 결과는 보관한 `parsed-<번호>.json`과 같았다. 허용 목록은 읍면동 표본 없이 정한 것이므로 이 결과는 위 표본 범위에서만 확인한 것이다.

2페이지 이후 목록은 2026-11-28(한국 시간) 공도읍 1·2페이지를 같은 요청 함수로 다시 받아(요청 2건, 1초 간격) 확인했다. 두 페이지 모두 `form#list` action이 `/csc/gongdo/bbs/list.do?ptIdx=16&amp;mId=0500000000`으로 같았다. 페이지 번호는 action이 아니라 POST 본문으로만 가므로 action 대조를 바꾸지 않았다. 두 페이지의 전체 페이지 수(36)와 고정 글 3건(201926·185869·183576)이 같았고 번호 글 10건씩은 서로 겹치지 않아, 묶음 수집의 페이지 순회 검사(전체 페이지 수·고정 글 유지, 번호 글 중복 없음)를 통과하는 형태였다. 2페이지 원본은 `town-gongdo`에서 파싱되고 `city`·`town-yangseong` 키에서는 거부됐다. 원본은 비공개 `data/private/town-page2-check-20261128/`에 두었다. 상세는 받지 않았고, 3페이지 이후와 다른 14곳의 2페이지는 확인하지 않았다. 2026-11-27에 저장한 1페이지 묶음으로 매체 `--batch` 대조도 요청 없이 확인했다. 202988은 공도읍 묶음으로 통과했고, 203049는 공도읍 묶음에서 거부되고 미양면 묶음에서 통과했다.

이날 관찰한 게시판 간 중복은 다음과 같다. 상단 고정 글 3건(201926·185869·183576)은 시청과 15곳에 모두 같은 번호로 있었다. 시청 1~2페이지의 번호 글 가운데 203066·203062·203043·203041·203040·203003·203002·203001·202994는 15곳의 1페이지에도 있었고, 202945는 1페이지가 그 글까지 닿은 13곳에 있었다. 여러 곳에서 받은 같은 번호의 상세는 원본 해시가 게시판마다 모두 달랐고 출처 이름·원문 주소를 뺀 파싱 결과는 같았다. 202988(공도읍)과 203049(미양면)는 시청 1~2페이지와 다른 읍면동 1페이지에 없었다. 공도읍 2페이지 번호 글 10건 가운데 5건(202945·202944·202883·202882·202881)은 시청 1~2페이지에도 있었다. 그 밖의 2페이지 이후 소속과 시청 3페이지 이후는 확인하지 않았다.

### 안성맞춤아트홀 공연·전시 일정 목록·상세 수집

행사·문화 분야의 공연·전시·아카데미 일정은 [안성맞춤아트홀 전체일정](https://www.anseong.go.kr/arthall/concert/list.do?mId=0202010100)에서 월 단위로 받는다. 공식 화면은 POST지만 같은 목록을 주는 GET `list.do?…&year=…&month=…&page=…`와 상세 GET `view.do?idx=…`으로 요청하고 리디렉션은 따르지 않는다. `/arthall/`은 `robots.txt` 제한 목록에 없다. 한도·중단 HTTP 상태·`--start-page`는 공통 묶음 규칙(`web_batch.py`), 요청 간격은 1.5초다. D03 연결은 후속 작업이다.

```sh
python3.13 -B -m processing.collection.arthall_batch capture --year 2026 --month 12 --name arthall-2026-12
python3.13 -B -m processing.collection.arthall_batch verify --name arthall-2026-12
```

`data/private/collection-arthall/<name>/`에 목록·상세 원본, `parsed-<번호>.json`(`arthall-concert-parser-v2`), 마지막으로 `batch.json`을 쓴다. 종료 코드는 0 완료, 2 한도 도달·일부 실패, 1 입력·보관·검증 오류다. `verify`는 요청 없이 원본 해시·목록의 공연 번호·현재 파서 결과를 기록과 대조하고, 완료 묶음이면 목록의 공연을 순서대로 빠짐없이 담았는지도 본다. 통과하면 원래 상태(`batch_status`)·건수를 출력하고 일부 실패 묶음은 2로 끝난다. 다른 파서 버전의 기록은 다시 수집하라며 거부한다.

- 목록: `form#listForm`의 주소와 숨은 `year`·`month`(`06`처럼 두 자리)·`rangeType`(빈 값)·`page`가 요청과 같아야 한다. 공연 번호는 `go_view('…')` 버튼에서만 읽는다. 쪽 번호 영역은 현재 쪽 하나와 1부터 빠짐없는 쪽 링크만 받는다(다음·끝 버튼은 형식 변경). 결과가 없는 달은 `검색된 전체일정이 없습니다.` 한 줄에 쪽 번호 영역이 없었다.
- 상세: 목록 복귀 `form#cancel` 주소와 예매 스크립트 `module.init('<번호>', …)`의 번호가 요청과 같아야 한다. 없는 번호는 HTTP 200으로 `존재하지 않는 공연/전시입니다.` 알림만 담은 213바이트 화면이 오며 그 사유로 실패를 남긴다.
- 기록: `div.conInfo_list`의 공연명(`h4`)·구분(`기획`·`대관`·`아카데미`)·항목을 표시 문구 그대로 두고 공백·줄바꿈만 공백 하나로 바꾼다. 항목 15개(`_FIELDS`: `장르`·`기간`·`입장권`(관람료)·`티켓 오픈 일시` 등)는 `fields`에, 그 밖의 항목은 `other_fields`에 두고 `unmapped_field`로 표시한다. 같은 항목명이 두 번 나오면 거부한다. 빈 값이나 없는 항목은 `null`이고, 실제 13건에 모두 있던 9개 항목은 `missing:<필드>`도 남긴다. `입장권`(`무료`·`사전 예매자에 한해 무료`·좌석별 가격)에서 무료 여부나 금액을, `관람연령`에서 참여 자격을 추정하지 않는다.
- 일정: 진행 일정인 `기간`은 정확히 `YYYY-MM-DD ~ YYYY-MM-DD`일 때만 `performance_period`에, 예매(신청) 시작은 `티켓 오픈 일시`가 `YYYY-MM-DD HH:MM ~`일 때만 `ticket_open_at`에 따로 넣는다. 종료 시각은 화면에 없다. 빈 `~`는 `ticket_open_blank`, 다른 형식은 `ticket_open_unparsed`, 기간 역전·형식 차이는 `period_inverted`·`period_unparsed`로 표시하고 원문은 고치지 않는다. 자유 서술인 `시간`은 해석하지 않는다.
- 예매 정보: 포스터 옆 `div.ticket_btns`의 버튼 문구(`booking_buttons`)와 `module.init`의 셋째 인자(인터파크 상품 번호, `ticketing_goods_code`)만 둔다. 예매 창은 로그인 세션 값을 붙인 POST라 고정 주소가 없어 상세 주소를 진입점으로 쓰고, 세션 값(넷째 인자 이후)은 읽지 않는다.
- 본문: 탭 제목(`ul.tab_view`)과 `div.tap_wrapper<N>`의 글자·이미지 주소를 `sections`에 둔다. 실제 본문에 링크가 없어 `a`를 받지 않으므로 `links`는 늘 빈 목록이다. 모바일 안내(`p.p_notice`)는 빼되 안에 태그가 있거나 `</p>` 전에 다른 태그가 닫히면 거부한다. `div` 경계는 공백 하나로 띄운다. `goTab` 번호가 없는 본문에 내용이 있으면 루트가 `display: none;`이면 숨김으로 거부하고 아니면 `untitled_section:<N>`, 본문 글자가 없으면 `sections_without_text`로 표시한다. 항목 값은 `br`만, 공연명과 탭 제목은 글자만 받는다. 포스터 영역부터 목록 버튼(`div.btnboxR`)까지 영역 사이에는 빈 `div.cleB`만, 포스터 영역의 링크는 예매 버튼 안에서만 받는다.
- 허용 목록: 읽는 영역(목록 `div.con_list`·`div.bod_page`, 상세 `div.conInfo_img`·`div.conInfo_list`·`ul.tab_view`·`div.tap_wrapper<N>`) 안에서는 실제 원본 29건에 있던 태그·속성 이름·인라인 스타일 선언(탭 본문 `p`·`font`의 15개)만 받고 나머지는 거부한다. 저절로 실행되는 `onerror`는 실제 값 하나만 받는다. 영역 루트는 `class`만, 탭 본문 루트는 `id`와 값이 정확히 `display: none;`인 `style`도 받는다(값 없는 `style`은 거부). 같은 이름 속성이 두 번 나와도 거부한다.
- 중첩: 태그 경계는 공용 `PinnedHTMLParser`로 고정한다. 영역과 영역 밖 숨김 요소(`template`, `hidden` 속성, `display`·`visibility`·`\`가 든 인라인 스타일) 안에서는 끝 태그가 가장 안쪽의 열린 요소를 닫아야 하고, 숨김 요소 안의 영역은 거부한다. 예외는 탭 본문에서 영역 안에 열려 있지 않은 `</p>`·`</strong>`·`</font>`(3829에 있었다)로, 브라우저처럼 무시한다. 태그·속성 이름은 공용 파서 규칙대로 ASCII만 받고(이름 속 따옴표 포함 거부), 빈 요소 규칙이 다른 svg·math는 문서 어디서든 거부한다.
- 한계(HTML만으로 정할 수 없어 확인하지 않는다): 영역 밖 조상은 위 숨김 표기와 끝 태그 짝만 보므로 다른 방법(popover·닫힌 `dialog`·`details`·opacity 등)으로 숨긴 조상, 스타일시트·class로 생기는 숨김, 허용한 글자색·배경색·크기의 조합으로 안 보이는 글자, 페이지·외부 스크립트(`interpark.js` 등)와 클릭 처리기의 효과(탭 전환은 위 규칙만 본다). 브라우저의 암묵적 닫기·트리 재구성(`<li>`가 앞 `li`를 닫는 것 등)도 따라 하지 않아, 영역 안 글자의 화면상 위치나 영역 경계가 달라질 수 있다.

2026-11-28 실제 응답 확인 결과다(요청 30건, 1.5초 이상 간격). 원본은 비공개 `data/private/arthall-research/`·`collection-arthall/`에 있다.

| 확인 범위 | 결과 |
| --- | --- |
| 목록 | 2026-11 4건·2026-12 6건(모두 1쪽), 2027-06 결과 없음. 쓰지 않는 연간 보기(`rangeType=after`)는 7쪽이며 GET `page=2`가 2쪽을 돌려줬다. |
| 명령 실행 | `capture` 2026-11(4건)·2026-12(6건) 모두 `complete`, 당시(v1) `verify`도 3.13.5·3.14.6에서 통과했다. 현재 파서도 원본 29건에서 두 버전 결과가 같지만 저장 묶음은 v1 기록이라 `verify`는 거부한다. |
| 상세 13건 | 탭 본문에 글자가 있는 글 5건(할인·매진·대관 안내), 이미지뿐인 글 6건, 탭이 없는 글 2건이다. 대관 전시 1건은 탭 대신 `내용` 항목에 설명이 있다. |
| 예매 | 기획 공연·아카데미·유료 체험이 있는 전시 9건에 `예매하기` 버튼과 상품 번호가 있었다. 대관 2건, 무료 전시 1건, 라인업 안내 1건은 버튼이 없다. `티켓 오픈 일시`는 8건이 시각, 5건이 빈 `~`다. |
| 형식 차이 | 공연명에 `<테오팀 … 콘서트>`처럼 이스케이프되지 않은 `<`가 있다. `<` 뒤가 한글이면 글자로 읽고, 영문이면 브라우저도 태그로 읽으므로 거부한다. 라인업 안내(3389)는 `장르`가 비었고 기간이 2026-08-12~12-16이다. 3869는 탭 번호가 2부터다. 3089는 포스터 대체 문구와 `시간`이 다르다. |

확인하지 않은 것: 한 달이 2쪽 이상인 월별 목록(쪽 번호 형식은 연간 보기에서만 봤다), 표(`table`)가 든 탭 본문(지금은 거부한다), 탭 이미지 안의 글자(OCR은 별도 단계), 실제 예매 창과 잔여석, 2026-01~10월 목록과 그 상세 대부분.

### 지자체복지서비스 OpenAPI 목록·상세 수집

지원·혜택 분야의 안성시 복지서비스는 [한국사회보장정보원_지자체복지서비스](https://www.data.go.kr/data/15108347/openapi.do)(공공데이터포털 15108347)에서 받는다. **이 수집기는 합성 XML 응답으로만 시험했고 인증 키가 필요한 실제 API는 호출하지 않았다.** 아래 요소 이름과 검증 기준은 공개 문서에서 옮긴 것이며, 실제 응답과 다르면 원본과 실패 사유를 남기고 멈춘다.

```sh
DATA_GO_KR_SERVICE_KEY=<디코딩 키> python3.13 -B -m processing.collection.welfare_batch --name welfare-20261127
```

공공데이터포털에서 활용 신청을 마친 디코딩 키를 실행 환경의 `DATA_GO_KR_SERVICE_KEY`에만 넣는다. 키는 요청 주소에만 붙고 원본·파싱 결과·`batch.json`·오류 문구에는 쓰지 않는다. 응답 본문에 키가 그대로, URL 인코딩, JSON 이스케이프(`\/`·`\u00XX`), XML 문자 참조로 들어 있거나 `+`가 공백으로 풀린 형태로 들어 있으면 원본을 쓰기 전에 그 요청을 실패로 기록하고 남은 요청을 멈춘다. 겹친 인코딩은 다섯 번까지 풀어 보고, 그래도 끝나지 않으면 키 포함 여부를 확인할 수 없으므로 같은 방식으로 거부한다. NUL 바이트가 있는 본문(UTF-16·UTF-32 등)과 UTF-8로 읽을 수 없는 본문(EBCDIC 등)은 키가 원문이든 URL 인코딩이든 이 비교를 빠져나갈 수 있으므로 키 확인 전에 같은 방식으로 거부하고 원본을 남기지 않는다. 키 확인도 파서처럼 앞의 UTF-8 BOM을 떼고 엄격한 UTF-8로 읽는다. 이런 본문은 어차피 UTF-8 XML 파서가 읽지 않는다.

- 요청: `https://apis.data.go.kr/B554287/LocalGovernmentWelfareInformations`의 `/LcgvWelfarelist`(목록)와 `/LcgvWelfaredetailed`(상세)만 GET으로 보낸다. 리디렉션은 따르지 않는다. 목록은 `pageNo`·`numOfRows=100`·`ctpvNm=경기도`·`sggNm=안성시`·`arrgOrd=001`(최신순)을, 상세는 `servId`를 쓴다. 조회수로 순서가 바뀌는 인기순 대신 최신순을 고정했다. 기록하는 `source_url`은 키를 뺀 같은 주소다.
- 한도: 응답당 2 MiB, 목록 `--max-pages` 1~20(기본 5), 상세 `--max-items` 1~500(기본 200). 요청은 하나씩 0.6초 간격으로 보내고 HTTP 401·403·429·503을 받으면 이후 요청을 멈춘다. HTTP 200이라도 서비스 오류로 보이는 응답이면 그 원본과 사유를 남기고 이후 요청을 멈춘다. 서비스 오류는 UTF-8 XML로 읽을 수 없는 본문, 문서와 다른 최상위 요소(예: 게이트웨이의 `OpenAPI_ServiceResponse`), 최상위 바로 아래의 `resultCode`가 없거나 성공 코드가 아닌 경우다. 다만 UTF-8이 아니거나 NUL 바이트가 있는 본문은 위와 같이 원본 없이 사유만 남긴다. 이미 찾은 서비스의 상세도 더 요청하지 않고 `not_attempted`로 남긴다. `batch.json`의 `stop_http_status`에는 멈춘 HTTP 상태(200 응답이면 `null`)를, `stop_reason`에는 멈춘 사유를 쓴다.
- XML: UTF-8만 받고, `<!--`·`<![CDATA[`가 아닌 `<!` 선언(DOCTYPE·ENTITY)이 있으면 파싱 전에 거부한다. 파싱은 표준 라이브러리 `xml.etree.ElementTree`로 하며 새 의존성은 없다. 정의되지 않은 엔터티와 문법 오류는 형식 오류다.
- 봉투 검증: 최상위 요소, `resultCode`가 성공 코드인지, 응답의 `pageNo`·`numOfRows`가 요청과 같은지, `totalCount`와 페이지 항목 수가 맞는지 확인한다. 목록 항목마다 `servId`(`WLF`+숫자 8자리)·`servNm`과 `ctpvNm=경기도`·`sggNm=안성시`가 있어야 한다. 순회 중 전체 건수가 바뀌거나 페이지 사이에 같은 `servId`가 나오면 그 페이지를 실패로 남기고 이전 페이지의 서비스만 상세를 받는다. 상세는 `servId`가 요청과 같아야 하고, 시도·시군구가 있으면 안성시여야 한다. 문서에 없는 하위 구조, 같은 요소의 반복, 최상위·`servList`·하위 목록 요소에 하위 요소 없이 들어 있는 글자는 형식 변경으로 거부한다.

`data/private/collection-welfare/<name>/`에 `list-<페이지>.xml`, `detail-<servId>.xml`, 파싱 결과 `parsed-<servId>.json`(파서 버전과 두 원본 해시 포함), 마지막으로 `batch.json`을 쓴다. 종료 코드는 0 완료, 2 한도 도달·일부 실패, 1 입력·키 설정·보관 오류다.

파싱 결과는 API 요소 이름을 키로 원문 텍스트를 그대로 둔다. 앞뒤 공백·줄바꿈도 바꾸지 않는다. 문서의 요소가 없거나 공백뿐이면 값을 `null`로 두고 `unknown`에 `missing`·`empty`를 남긴다. 문서에 없는 단일 값 요소는 `undocumented`에 원문 그대로 보관한다. 시행기간(`enfcBgngYmd`·`enfcEndYmd`)은 날짜로 해석하지 않고, 지원대상·선정기준에서 자격·연령·소득을, 급여서비스 내용에서 금액·비용을 추정하지 않는다. 서비스 URL은 상세 응답에 없어 목록 항목의 `servDtlLink`를 함께 보관한다(`record.list`). 상세 하위 목록(`inqplCtadrList` 등)의 서비스구분코드가 코드표와 다르면 거부한다. 목록 항목에는 이 코드가 없다.

요소 이름의 출처는 다음과 같다. 2026-11-27에 공개 페이지와 첨부 문서를 받아 확인했다.

| 용도 | 요소 | 근거 |
| --- | --- | --- |
| 요청 | `serviceKey`·`pageNo`·`numOfRows`·`ctpvNm`·`sggNm`·`arrgOrd`, 상세 `servId` | 상세 페이지 요청변수 표·Swagger |
| 목록 봉투 | `resultCode`·`resultMessage`·`numOfRows`·`pageNo`·`totalCount`, 반복 항목 `servList` | Swagger `LcgvWelfarelist` 응답 |
| 서비스명·ID | `servNm`·`servId` | Swagger 목록·상세 응답 |
| 시행기간 | `enfcBgngYmd`·`enfcEndYmd` | Swagger 상세 응답 |
| 지원주기·제공유형 | `sprtCycNm`·`srvPvsnNm` | Swagger 목록·상세 응답 |
| 지원대상·선정기준·급여서비스 | `sprtTrgtCn`·`slctCritCn`·`alwServCn` | Swagger 상세 응답 |
| 신청방법 | `aplyMtdNm`(목록·상세), `aplyMtdCn`(상세) | Swagger |
| 문의처·관련 사이트·근거법령·서식 | `inqplCtadrList`·`inqplHmpgReldList`·`baslawList`·`basfrmList`의 `wlfareInfoDtlCd`·`wlfareInfoReldNm`·`wlfareInfoReldCn` | Swagger 상세 응답 |
| 서비스구분코드 010·020·030·040, 정렬순서 001 | `wlfareInfoDtlCd`, `arrgOrd` | 첨부 `지자체복지서비스_코드표(v1.0).doc` |
| 서비스 URL | `servDtlLink` | Swagger 목록 응답(상세 응답에는 없음) |
| 기타 | `servDgst`·`bizChrDeptNm`·`lifeNmArray`·`trgterIndvdlNmArray`·`intrsThemaNmArray`·`inqNum`·`lastModYmd` | Swagger |
| 최상위 요소 | `response` | Swagger의 `xml.name` |
| 최상위 요소 | `wantedList`·`wantedDtl` | 같은 기관의 다른 API인 [중앙부처복지서비스](https://www.data.go.kr/data/15090532/openapi.do) `활용가이드_중앙부처복지서비스(v2.2).doc`의 응답 예시 |
| 성공 코드 | `0` | 같은 활용가이드 v2.2의 오류 코드표 |
| 성공 코드 | `00` | 공공데이터포털 표준 API(`portal_format.py`) 기준 |

이 API 상세 페이지의 참고문서는 코드표 하나이며 응답 XML 예시와 오류 코드표가 없다. 같은 기관의 중앙부처 API는 Swagger에 `response`로 적혀 있지만 활용가이드 예시는 `wantedList`·`wantedDtl`을 쓴다. 그래서 두 문서의 이름을 모두 허용했다. 이 API의 실제 최상위 이름·성공 코드는 미확인이다. 최대 `numOfRows`, 한글 지역 인자의 인코딩, 목록 항목의 `ctpvNm`·`sggNm` 포함 여부, 게이트웨이 오류 응답 형식, 최신순 정렬의 페이지 안정성도 실제 응답으로 확인하지 않았다. 게이트웨이가 200과 함께 다른 최상위 요소(예: `OpenAPI_ServiceResponse`)를 보내면 최상위 요소 불일치로 기록하고 남은 요청을 멈춘다. 다음 세 가지도 실제 응답으로 확인하지 않았고, 해당하면 수집이 실패로 남는다. 첫째, `servDtlLink`의 `&`가 `&amp;`로 이스케이프되지 않으면 목록 페이지 전체가 XML 형식 오류가 된다. 둘째, 경기도 공통 서비스처럼 `sggNm`이 빈 목록 항목이 있으면 그 페이지 전체가 실패한다. 셋째, 중앙부처 API의 신청방법 목록 `applmetList` 같은 하위 목록이 상세에 나오면 문서에 없는 하위 구조로 거부한다. XML 문법 오류는 오류 화면과 구별할 수 없어 서비스 오류로 본다. 그래서 상세 한 건의 원문에 이스케이프되지 않은 `&` 같은 문법 오류가 하나만 있어도 남은 상세(`--max-items` 최대 500건)를 요청하지 않고 배치 전체가 멈춘다. 같은 원문이 계속 오면 다시 실행해도 같은 자리에서 멈추므로 이 실패가 나오면 원본을 보고 처리 방식을 다시 정한다. 첫 실제 실행에서 `batch.json`과 원본을 보고 위 항목을 확인한 뒤 이 표를 갱신한다. 이전 조사에서 확인한 안성시 공공근로사업 `WLF00000915`([복지로 상세](https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=WLF00000915))도 이번 작업에서 다시 조회하지 않았다.

### 안성시 고시·공고 목록·상세 수집

지원사업 원공고(대상·금액·마감·신청 방법)와 도로정비 허가·도로지정 같은 고시는 [안성시 고시·공고](https://www.anseong.go.kr/portal/saeol/gosiList.do?mId=0501040000)에서 받는다. 목록은 `GET /portal/saeol/gosiList.do?seCode=01&mId=0501040000&page=N`(`seCode=01`은 고시/공고 구분), 상세는 `GET /portal/saeol/gosiView.do?notAncmtMgtNo=…&mId=0501040000`이다. 공식 화면은 `listForm` POST로 열지만 같은 GET 주소도 같은 화면을 반환함을 확인했다. 리디렉션은 따르지 않는다. `/portal/saeol/`은 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다. D03 연결은 후속이다.

```sh
python3.13 -B -m processing.collection.gosi_batch capture --name gosi-20261128 --max-pages 2 --max-items 20
python3.13 -B -m processing.collection.gosi_batch verify --name gosi-20261128
```

`data/private/collection-gosi/<name>/`에 목록·상세 HTML, `parsed-<번호>.json`(파서 `gosi-notice-parser-v3`. v2 이하는 거부되니 다시 수집), 마지막으로 `batch.json`을 쓴다. 한도·`--start-page`·중단 HTTP 상태·종료 코드(0 완료, 2 한도 도달·일부 실패, 1 입력·보관 오류)는 공통 묶음 규칙(`web_batch.py`)과 같고, 요청 간격은 1.5초다. `verify`는 요청 없이 원본 해시, 목록 번호, 파싱 결과를 현재 파서로 다시 만들어 대조하고(실패분도 해시를 보고, 현재 파서가 읽으면 다시 수집하게 한다) 파싱 건수와 첨부 후보 수를 출력한다. 하나라도 다르면 종료 1이다.

- 목록: `form#listForm`의 action은 요청 주소(검색어 없음, 같은 페이지)와 정확히 같고, 표 제목은 `고시/공고게시판 목록`으로 시작하고, `Total … Page 현재 / 전체`는 요청 페이지와 맞아야 한다. 행마다 고시공고번호·제목·담당부서·등록일 칸과 `boardView('<페이지>', '<번호>')` 링크 하나가 없으면 형식 변경이다. 목록도 상세처럼 `html_tokens.py`의 `PinnedHTMLParser`(브라우저 기준 태그 경계)로 읽어 빈 요소가 아닌 태그의 `/>`는 무시하고, 해석이 갈리는 표기는 문서 어디서든 거부한다.
- 상세 대조: 상세 HTML의 게시물 번호는 첨부 `바로 보기` 인자에만 있다. 없는 번호(999999999)도 HTTP 200으로 제목·항목이 빈 같은 화면을 돌려주므로 제목이 없으면 실패로 남긴다. 제목·고시공고번호·등록일·담당부서는 같은 묶음 목록 행과, `바로 보기`의 번호·내려받기 인자는 요청·바로 앞 첨부와 정확히 같아야 하고, `form#detailForm` action은 고시·공고 상세 주소여야 한다.
- 허용 목록: 읽는 영역(목록의 `div.board_page`·목록 표, 상세의 `div.bod_view`)은 아래 실제 원본의 구조(`_LISTING_SHAPE`·`_BODY_SHAPE`)만 받는다. 요소마다 자리·태그·class 값(값 없는 `class` 포함)·속성 이름이 표본과 같아야 하고, 글자는 읽는 칸과 표본 고정 문구(`첨부 파일`·`바로 보기`·공공누리 제4유형 안내·표 머리글)만 받는다. 인라인 스타일, 중복 속성(`class`·`id`는 영역 밖에서도), 표본에 없는 태그·자리(본문의 그림·표·중첩 목록, 암묵적으로 닫히는 자리 등), 가장 안쪽 요소를 닫지 않는 종료 태그, `</img>` 같은 빈 요소 종료 태그(`</br>`은 공용 기반이 거부), 영역 밖 숨김 요소(`script`·`style`·`template`, 목록은 `noscript`도) 안의 다른 숨김 요소의 짝 없는 종료 태그(`template` 안 `</style>` 등)는 거부한다. 마지막 것은 브라우저가 무시하나 공용 기반(`libraries.py`)은 숨김 깊이를 줄여 다른 게시판은 이보다 약하다(공용 수정은 담당자와 조율). 실제 원본은 모두 규칙을 지켰고 Python 3.13.5·3.14.6 결과도 같았다. HTML만으로 정할 수 없는 것(영역 바깥 요소(조상 포함)의 숨김·배치, 허용한 class를 숨기는 스타일시트, 글자색·배경색·크기 조합, 공공누리 그림 내용, 페이지·외부 스크립트 실행 결과)은 확인하지 않는다.
- 본문: `fields`는 표시 문구 그대로다(공백·줄바꿈만 정리). `등록일`은 신청·진행 일정이 아닌 게시 날짜로, 정확히 `YYYY.MM.DD`일 때만 `registered_on`에 넣고 아니면 `registered_date_unparsed`를 표시한다. 본문의 접수기간·지원 금액·대상은 `description` 원문으로만 두고 해석하지 않는다. 빈 항목은 `null`과 `missing:<필드>`다. 빈 `div.view_cont`는 첨부가 핵심일 수 있어 실패가 아니나, `bod_view` 바로 아래 `div.view_cont`·`dl.view_file`이 하나라도 없거나 첨부 영역이 둘이면(없는 번호 화면에도 둘 다 있다) 형식 변경이다.
- 첨부: `dl.view_file`의 링크를 `attachments`에 `kind`·`source_url`·`label`·`format`(PDF·HWP·HWPX·PNG·JPEG, 그 밖은 `null`)으로 남긴다. 주소는 페이지 스크립트(`goDownload`)의 `https://eminwon.anseong.go.kr/emwp/jsp/ofr/FileDown.jsp?…`를 encodeURI 규칙으로 재현한다. 그 전에 브라우저가 `javascript:` 주소의 탭·줄바꿈 제거·퍼센트 디코딩·JS 이스케이프를 하므로 인자는 실제 원본 36벌의 문자(한글 음절·ASCII 영숫자·공백·`()./[]_~「」`)만 받고, 그 밖의 문자(`&`·`%`·`\`·탭 등)나 다른 형식 링크(`goDownload_direct`, 빈 `href` 등)는 `source_url=null`이다. 첨부는 내려받지 않는다(이 호스트 robots.txt가 2026-11-28 HTTP 302라 판단 불가, 공시송달 명단 등 개인정보 첨부도 있음). 확보·OCR·본문 추출은 운영자 검토 뒤 별도 단계다.
- 정정 관계: 제목·본문에 적힌 다른 고시공고번호(`제YYYY-N호`)만 `referenced_notice_numbers`에 원문으로 남긴다. 번호 체계가 발행 주체(`안성시`·`안성시 공도읍` 등)마다 따로라 앞의 `경기도|안성시 … 고시|공고` 문구(`안성시공도읍 공고`, `안성시 공고(제YYYY-N호)` 포함)까지 담는다. 자기 번호 제외와 중복 제거는 주체까지 같은 번호(공백·괄호 무시, `경기도 (및) 안성시 …`는 `안성시 …`)로만 한다. 붙여 쓴 낱말은 조사와 가리지 못해 `안성시에서 공고 제YYYY-N호`는 `안성시 공고 …`와 다른 값이다. 주체 없이 `제YYYY-N호`만 남은 값(`경기도`·`안성시`로 시작하지 않는 주체, 짝 없는 괄호 등)은 어느 공고인지 몰라 연결 근거로 쓰지 않는다. 제목의 `(정정)`·`재공고`로 원공고를 추정하지 않는다(개별공시지가 정정처럼 정정 공고가 아닌 글도 있다).

2026-11-28 실제 요청 35건(robots.txt 2건, 목록 6쪽, 상세 27쪽(없는 번호 1건 포함), 1.5초 이상 간격)의 결과다. 원본은 비공개 `data/private/gosi-check-20261128/`·`collection-gosi/gosi-real-20261128/`에 있다.

| 확인 범위 | 결과 |
| --- | --- |
| 목록 | `Total 6579`, 658페이지. 1·2쪽 10행, 마지막 658쪽 9행(2008·2009년 글). 검색 결과 2건과 다른 주소로 받은 1쪽은 action이 수집기 주소와 달라 거부됐다. |
| 상세 표본 16건 (2009년 2건·2026년 14건) | 구조가 모두 같았고 목록 행이 있는 15건이 파싱됐다(행 없는 71814는 거부). 본문은 글자와 `br`뿐이었다(이미지형·빈 본문 없음). 첨부는 모두 1~3개(HWPX 최다, HWP·JPG·PDF·XLSX)였다. |
| 명령 실행 | `capture --max-pages 1 --max-items 10`의 1쪽 10건이 모두 파싱됐고(첨부 HWPX 11·PDF 1·XLSX 1), Python 3.13.5·3.14.6 `verify`가 같은 결과로 통과했다. |
| 정정 공고 | 제목 검색 `정정` 85건 중 상세 3건(75255·74979·74835)의 본문에 원공고 번호가 없었다(HWPX 첨부는 확인하지 않음). |

첨부 없는 글, 3쪽 이후 목록, 페이지 사이 글 이동은 확인하지 않았다. 표본에 없던 구조(그림이 든 본문 등)는 실패로 남으니 원본을 보고 허용 목록을 정한다. 공공누리 제4유형이라 공개 전 게시물별 이용 조건을 확인해야 한다.

### 안성청년포털 청년정책 목록·상세 수집

지원·혜택 분야의 청년정책은 [안성청년포털 청년정책 목록](https://www.anseong.go.kr/youth/policy/list.do?mId=0201040000)에서 받는다. 목록은 `/youth/policy/list.do?mId=0201040000`에 POST `page`, 상세는 `/youth/policy/view.do?mId=0201040000&idx=…` GET으로 요청한다. 목록 링크에 붙는 `categoryId`는 빼도 같은 상세(숨은 `categoryId` 포함)가 와서 붙이지 않는다. 이 메뉴의 이름은 `청년문화사업`이지만 목록의 숨은 `categoryId`가 빈 값이라 네 분야(일자리·농업, 주거, 문화사업, 복지·건강)가 모두 나온다. 숨은 값이 비어 있지 않으면 특정 분야로 걸러진 목록으로 보고 거부한다. `/youth/`는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없고, 대표 이미지의 `/common/` 경로는 제한 경로라 이미지는 주소만 남긴다.

```sh
python3.13 -B -m processing.collection.youth_batch capture --name youth-20261128 --max-pages 6 --max-items 72
python3.13 -B -m processing.collection.youth_batch capture --name youth-20261128-p7 --start-page 7 --max-pages 6 --max-items 72
python3.13 -B -m processing.collection.youth_batch verify --name youth-20261128
```

요청 사이 간격은 1.5초다. 한도·중단 HTTP 상태·`--start-page`·종료 코드와 나누어 받을 때의 주의는 도로 공사현황과 같은 공통 묶음 규칙(`web_batch.py`)을 따른다. 고정 글은 없다. `data/private/collection-youth-policies/<name>/`에 목록·상세 HTML, `parsed-<번호>.json`(`youth-policy-parser-v3`), 마지막으로 `batch.json`을 쓴다. `verify`는 요청 없이 목록·상세 원본 해시(파싱 실패 포함)와 목록 카드를 대조하고, 현재 파서로 다시 만든 파싱 결과가 기록과 같은지 확인한 뒤 통과한 정책 수를 출력한다(불일치나 이제 읽히는 실패 원본은 종료 1). 같은 대조는 `youth_batch.read_youth_batch()`로 쓸 수 있다. D03 연결은 후속이다.

- `listing`: 목록 카드의 분야·제목·`신청기간`·`신청방법` 표시 문구. 신청기간은 상세에 없고 목록에만 있다. 칸 이름은 `신청기간`이지만 본문의 사업·운영 `기 간`과 같은 값이 든 글이 있어(아래 표) 확정된 신청 일정으로 보지 않는다. 정확히 `YYYY-MM-DD ~ YYYY-MM-DD`이고 시작일이 종료일보다 늦지 않을 때만 `listing_period_range`에 날짜로 옮기고, 아니면 `period_unparsed`·`period_inverted`·`missing:application_period`로 표시한다. 모든 기록에 `application_period_unconfirmed`를 단다. 목록이나 상세의 신청방법 값 전체가 방법 대신 상태어·자리표시이면 `application_method_not_method`를 단다. `마감`·`종료`가 든 한 낱말(`모집마감`·`조기마감`·`(마감)`)과 그 앞 낱말 하나(`접수 종료`·`접수 조기마감`·`신청 (마감)`), 글자·숫자가 없는 값(`.`)이 여기에 든다. `선착순 마감 시까지 방문 접수`처럼 방법 문구 안의 상태어는 표시하지 않는다. 두 표시 모두 값은 고치지 않는다.
- `fields`: 상세 본문(`description`, 줄 구분 유지)·등록일·`작성자`·`신청방법`. 조회수는 요청마다 바뀌어 보관하지 않는다. `div.view_info`에 다른 항목명이 나오면 형식 변경으로 거부한다. 상세 신청방법이 없으면 `null`과 `missing:application_method`로 남긴다. 목록과 상세의 신청방법·분야 번호가 다르면 `listing_method_differs`·`listing_category_differs`로 표시하고 두 값을 모두 그대로 둔다.
- 지원 대상·금액: 별도 항목이 없어 뽑지 않고 `unknown.support_target`·`support_amount`를 `not_extracted`로 둔다. 본문이 제목 한 줄인 글(877)도 있어 값이 있는 위치도 단정하지 않는다. 연령·소득 문구에서 자격을 추정하지 않는다.
- `city_notice_candidate`: 같은 사업이 [시청 고시·공고](https://www.anseong.go.kr/portal/saeol/gosiList.do?mId=0501040000)에도 올라오며 자격·마감은 시청 원공고·정정 공고가 기준이다. 목록 카드 제목으로 만든 고시·공고 제목 검색 주소만 `status=unverified`로 남긴다. 수집기는 이 주소를 요청하지 않고 시청 공고 값으로 덮어쓰지 않는다.
- `images`: 본문 앞 대표 이미지 영역(`div.photo_viewer`)의 원본 이미지 주소로, 슬라이드 `li` 바로 아래 `onclick="fn_view_original(this);"` 버튼의 `data-origin`에서만 읽는다. 그 버튼에 `data-origin`이 없거나 원본 주소가 하나도 없으면 거부하고, 줄인 보기 꼬리(`&width=500&heigth=500`)는 표본처럼 큰 보기 `figure>img`에만 받는다. 큰 보기·썸네일 `img` 주소(꼬리 제외)가 원본 주소 중 하나가 아니어도 거부한다. 이 영역은 상세 24쪽 틀에 나온 부모>자식 짝별 속성(`_VIEWER_ATTRS`), 스크립트 주소 2종, 글자(버튼 문구·초기화 한 줄)만 받고 나머지는 거부한다. 스크립트 개수·순서와 글자 위치는 보지 않는다(이 영역 글자는 기록하지 않는다). 첨부 링크가 있으면 `attachment`로 표시한다.
- HTML 검사: 문서 전체는 `html_tokens.py`의 `PinnedHTMLParser` 태그 경계 규칙을 따르고(빈 요소가 아닌 태그의 `/>`는 닫지 않는다), 상세 본문 영역(대표 이미지 영역 제외)은 시청 공지와 같은 본문 허용 목록(`libraries.py`)도 거친다. 그 위에 읽는 영역(목록 `form#list`, 상세 `div.bod_view`, 둘 다 자신 포함)은 2026-11-28 저장한 실제 목록 5쪽·상세 24쪽에 나온 태그별 속성과 부모>자식 짝만 받는다(`youth_policy.py`의 `_LISTING_*`·`_DETAIL_*`). 표본에 인라인 스타일이 없어 `style` 속성은 받지 않는다. 표본에 없던 `hidden`·`popover` 속성, 목록 폼 안의 `script`·`style`·`template`·`textarea`, 상세 본문의 `p`·`table` 같은 태그는 숨김 여부를 따지지 않고 거부한다. 영역 안 종료 태그는 가장 안쪽 요소만 닫아야 한다(실제 29쪽 모두 해당). 부모>자식 짝을 고정해 브라우저가 시작 태그로 요소를 대신 닫는 경우(`p` 안 `div`, `li` 안 `li`)도 막고, 목록의 `a` 안 `a`는 따로 거부한다. 목록 폼 밖에서 `template` 안 짝 없는 `</style>`처럼 숨김 요소의 종료 태그가 열린 순서와 다르면 거부한다.
- 확인하지 않는 것(HTML만으로 정할 수 없는 한계): 읽는 영역 바깥 요소(조상 포함)의 숨김, class로 지정한 스타일시트 숨김(실제 목록에도 `legend class="blind"`가 있다), 스타일시트의 글자색·배경색·크기 조합으로 생기는 숨김, 허용한 `onclick`·`onerror`와 외부 스크립트(스와이프·첨부 도구)의 실행 결과.

2026-11-28 실제 확인(요청 33건, 순차·1.5초 이상 간격):

| 확인 범위 | 결과 |
| --- | --- |
| 목록 | 전체 12페이지. 1·2·12페이지 모두 12건이었다. 12페이지에는 신청기간이 2023년인 정책도 그대로 있다. |
| 상세 | 명령으로 받은 1페이지 12건과 12페이지 앞 6건을 모두 파싱했고 Python 3.13.5·3.14.6의 `verify`를 통과했다(v1). v1 묶음의 `verify`는 이후 파서 버전 불일치로 종료 1이다. v2는 같은 원본 18건, v3는 따로 받은 856·861·871·877·881을 더한 23쪽을 요청 없이 다시 파싱해 모두 읽었다. 공용 `PinnedHTMLParser`·표본 허용 목록·엄격한 중첩 검사와 실패 원본 검증을 더한 뒤에도 목록 5쪽·상세 24쪽(`categoryId` 없이 받은 881 포함)을 3.13.5·3.14.6에서 다시 파싱한 결과는 같았다. |
| 형식 차이 | 877은 본문이 제목 한 줄이고 내용은 PDF·XLSX 첨부에만 있으며 신청방법은 `.`이다. 875·874의 신청방법은 `모집마감`이다. 본문에 `지원대상:` 항목이 있는 글은 881(청년월세) 하나였고, 나머지는 `추진배경`·`사업개요`·`총사업비` 형식의 사업 계획이다. 모든 상세에 대표 이미지가 1개 있었다. |
| 신청기간 칸 | 1페이지 868·874·875와 따로 받은 856의 카드 기간(2026-01-01 ~ 2026-12-31)은 본문 사업 `기 간`(2026. 1. ~ 12.)과 같았고, 861의 카드 기간(2026-03-01 ~ 2026-12-31)도 본문 `기 간`(2026. 3. ~ 12.)과 같았다. 874 본문 추진계획의 참여자 모집은 `2026. 1. ~ 2.`이다. 카드 기간이 본문 `접수시기`와 같은 글은 881뿐이었다. `application_method_not_method`는 v2 18건 중 874·875·877, v3 23쪽에서는 따로 받은 877까지 4쪽이다. |
| 시청 원공고 | 881의 목록 제목으로 검색한 고시·공고는 1건(안성시 공고 제2026-917호)이었다. 접수 기간(3.30.~5.29.)은 같았지만 지원대상 문구는 달랐다(청년포털은 소득 기준 포함, 원공고 본문은 전입신고 필수 명시). 다른 정책의 검색 결과는 확인하지 않았다. |

### 문화도시 안성 공지 게시판 수집 (축제포털 공지는 미등록)

행사 일정 변경·취소가 올라오는 [문화도시 안성 공지사항](https://www.anseong.go.kr/ccas/bbs/list.do?mId=0501000000&ptIdx=1363)은 게시판 키 `ccas`로 시청 공지와 같은 공유 게시판 경로를 쓴다. 한도·간격·종료 코드·본문 허용 목록도 시청 공지와 같다. 출처 이름은 `ccas_notice`, 파서 버전은 `ccas-notice-parser-v1`이다. D03 정책 검토는 후속이지만 D03 `prepare`는 지금도 이 묶음을 받는다(아래 주의 참고).

```sh
python3.13 -B -m processing.collection.board_batch ccas --name ccas-20261128 --max-pages 3 --max-items 30
python3.13 -B -m processing.collection.media inspect --board ccas --web-id 201494 --name ccas-201494 --batch ccas-20261128
```

2026-11-28 실제 목록·상세에서 아래 값을 확인한 뒤 등록했다. `/ccas/`·`/festival/` 경로는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다.

- 목록은 `/ccas/bbs/list.do?ptIdx=1363&mId=0501000000`에 POST `page`를 보내고, 상세는 `/ccas/bbs/view.do?bIdx=…&mId=0501000000&ptIdx=1363`을 GET으로 받는다. 메뉴 번호는 `0501000000`, 게시판 번호는 1363이다. 목록 링크 인자는 `goTo.view('list','<번호>','1363','0501000000')`이고, 목록 화면 제목은 `공지사항 목록 | 알림마당 | 대한민국 문화도시 안성`이다.
- 상세 마크업은 시청 공지와 같다. 제목은 `<h4>`, 본문은 `div.view_cont`, `viewForm` 주소는 `/ccas/bbs/view.do?ptIdx=1363&mId=0501000000`이다. 페이지 설정의 `contextPath`가 빈 값이라 첨부 주소는 루트 `/cmm/fms/FileDown.do`다.
- 상세 경로는 다른 게시판 글도 열어 준다. 축제포털 공지 200586(ptIdx 16)을 이 경로로 요청하면 문화도시 안성 `viewForm`으로 그대로 보였다. 거꾸로 축제포털 경로로 문화도시 글 202581을 요청해도 열렸다. 그래서 읍면동 게시판처럼 `form#list`의 action을 대조하고, 매체 `inspect`에는 `--batch`를 요구해 목록 원본에 나온 번호만 받는다.

실행 결과(요청 21건, 하나씩 2초 간격): 목록은 3페이지에 26건(10·10·6건)이었고 고정 글은 없었다. 3페이지 모두 이 키로 파싱되었다. 1페이지 상세 10건을 받아 저장 원본을 `board_batch`에 다시 넣었다. 이때 요청 함수만 저장 원본으로 바꾸었다. 결과는 3건 파싱, 7건 `parse_failed`였다. 파싱한 글은 202581(행사 일정 변경), 198562(행사 취소), 201494(첨부 포함)다. 실패 7건은 모두 본문 그림 `<img>`에 붙은 `onerror="this.src='/common/img/error/error_img.png'"` 하나 때문이었다. 이 속성은 공유 본문 허용 목록 밖이며, 실패한 글에는 201541 `[10.18 행사취소 공지]`도 있다. 원본과 실패 사유는 남는다. 허용 목록은 시청·안성배움e·읍면동이 함께 쓰므로 이번에는 바꾸지 않았다. 이 값만 받을지는 따로 정한다. Python 3.13·3.14의 결과는 같았다. 2페이지 이후의 상세는 받지 않았다.

주의: `BOARDS`에 등록했으므로 D03 `prepare archive_kind=board`는 지금도 이 묶음을 받는다. board 묶음 재검증(`d03_sources.py`)과 게시판 번호 공간 키(`d03.py`의 `_board_notice`)가 이 키를 쓰기 때문이다. 저장 원본으로 만든 묶음은 파싱된 3건이 D03 원본 재검증을 통과했다. 그런데 이 게시판의 번호 공간 키는 `1363`이라 시청 `16`과 따로 대조되고, 두 게시판 사이의 중복은 잡지 못한다. 실측한 `bIdx`는 ptIdx와 무관하게 하나의 순번처럼 보였다(문화도시 186393~202684, 축제포털·시청 16번 게시판과 같은 범위). 시청 상세 경로로 문화도시 글 202581을 요청하자(추가 요청 1건) 시청 `viewForm`으로 열렸고, `city` 파서가 같은 제목·본문의 시청 공지로 파싱했다. 시청 `media inspect`는 `--batch`를 요구하지 않는다. 그래서 `media inspect --board city --web-id 202581`과 이 게시판 묶음이 같은 글을 D03에 두 문서로 넣을 수 있다. 후속 D03 PR에서 번호 공간을 `bIdx` 하나로 합치고 교차 중복 거부 시험을 넣기 전까지 문화도시 안성 글을 다른 게시판 주소로 준비하지 않는다.

[축제포털 공지사항](https://www.anseong.go.kr/festival/bbs/list.do?ptIdx=16&mId=0401000000)(교통통제 안내 예: [200586](https://www.anseong.go.kr/festival/bbs/view.do?bIdx=200586&mId=0401000000&ptIdx=16))은 목록 구조가 달라 등록하지 않았다. 목록 화면 제목은 `공지사항 목록 | 게시판 | 축제포털`이다. 1·2페이지 모두 `div.bod_head`와 `현재 페이지 / 전체 페이지` 표시(`p.page_num`)가 없었다. 임시로 등록해 읽어 보니 공유 목록 파서가 두 페이지 모두 목록 HTML 구조 오류로 거부했다. 전체 페이지 수는 페이지 이동 링크(`goPage(1~6)`)로만 짐작할 수 있다. 짐작으로 순회를 끝내지 않으려고 등록하지 않았다. 상세는 같은 구조였다. 제목은 `<h4>`, `viewForm`은 `/festival/bbs/view.do?ptIdx=16&mId=0401000000`, `contextPath`는 빈 값이다. 받은 상세 3건 가운데 200586(교통통제)과 201721은 파싱됐고 둘 다 첨부가 있었다. 200997(셔틀버스)은 붙여 넣은 인라인 스타일(따옴표가 든 `font-family`, `text-wrap` 등) 때문에 허용 목록에서 거부됐다. 상세 경로가 다른 글도 열어 주므로, 목록 없이 상세만 받는 길도 만들지 않았다. 게시판 번호는 시청과 같은 16이다.

실제 원본은 Git 제외 `data/private/boards-probe/`(권한 0700)에 두었다.

### 수집 원본을 D03 등록 입력으로 준비하기

단건 수집은 `archive_kind=single`과 `capture.json`, 목록 수집은 `archive_kind=batch`와 `batch.json`을 사용한다. 직접 내려받은 포털 CSV는 `asset=portal`, 웹 상세는 게시물 번호를 지정한다. 부분 수집 묶음에서도 파싱에 성공한 상세를 선택할 수 있다. 명령은 수집 기록의 원본 해시와 파일을 대조하고 웹 상세의 게시물 번호를 다시 확인한다.

API 수집은 `archive_kind=portal`, API 수집 이름, `asset="1"` 같은 응답 페이지 번호를 지정한다. `official_url`은 `portal.json`의 해당 `source_url`과 맞추고 `collected_at`은 `null`로 둔다. D03은 해당 응답 원본과 기록된 수신 시각을 연결한다. 비교에 API 묶음을 사용했다면 D03 원본은 해당 API 응답 페이지를 선택한다. 한 응답 페이지에 등록할 행이 여러 개면 문서마다 같은 `asset`을 지정한다. 문서 번호·버전 번호는 문서마다 달라야 하며, API 응답이 아닌 수집 종류는 문서마다 다른 원본을 써야 한다.

파일데이터 API 수집은 `archive_kind=odcloud`, `archive_name`에는 `odcloud --name` 값, `asset`에는 응답 페이지 번호를 넣는다. `official_url`은 `odcloud.json`의 해당 `source_url`, `collected_at`은 `null`로 둔다. 명령은 모든 응답 원본의 해시·응답 구조·건수를 다시 확인하고 `anseong.json`을 원본에서 다시 만들어 대조한 뒤 해당 페이지 원본을 연결한다. 등록 방식은 `data-go-kr-odcloud-api`로 기록된다. 교육장처럼 안성시 행 여러 개가 한 페이지에 있으면 포털 API와 같이 문서마다 같은 페이지 번호를 지정한다.

도서관·시청·안성배움e·읍면동 매체는 `archive_kind=media`, `archive_name`에는 `store --name` 값, `asset`에는 같은 항목 번호를 문자열로 넣는다. `official_url`은 `notice.json`의 `source_url`(해당 게시판의 부모 공지 주소), `collected_at`은 `null`로 둔다. D03이 운영자 입력 다운로드 시각과 매체 원본 해시를 연결한다. 사람 검토를 마친 제목·본문을 전달하고 기존 D03 명령으로 등록한다.

도로 공사현황은 `archive_kind=road`, `archive_name`에는 `road_batch --name` 값, `asset`에는 공사 번호를 넣는다. 포털 원본은 선택할 수 없다. `official_url`은 `batch.json`의 해당 상세 `source_url`, `collected_at`은 `null`로 둔다. 명령은 상세 원본 해시와 함께 보관된 파싱 결과를 원본에서 다시 만든 값과 대조한다. 파싱 결과의 `parser_version`이 현재 파서와 다르면 변조와 구분되는 오류로 거부하므로 현재 버전으로 다시 수집한다. 시청·안성배움e·읍면동 공지는 `archive_kind=board`, `archive_name`에는 `board_batch --name` 값, `asset`에는 공지 번호를 넣고 같은 방식으로 대조한다. 등록 방식은 `official-web-board`로 기록된다.

시청·도서관·읍면동 게시판은 게시물 번호(`bIdx`) 공간(`ptIdx=16`)을 공유하고, 같은 공지라도 원본 해시가 게시판마다 달라 그대로 두면 별개 문서로 들어간다. 그래서 D03 준비는 공지(`board`)·도서관(`single`·`batch`)·매체(`media`) 문서의 원문 주소에서 공지 번호를 읽어, 기존 `collection-d03/*/source-import.json`의 문서와 이번 입력의 문서를 대조한다. 같은 번호가 다른 게시판 주소로 이미 준비되었으면 거부한다. 같은 게시판이어도 공지 본문 문서가 다른 문서 ID로 이미 있으면 거부한다. 같은 문서 ID의 새 버전(내용이 바뀐 공지)과, 같은 게시판 공지에 딸린 여러 매체 문서는 받는다. 완료 파일(`source-import.json`)이 없는 준비본은 등록할 수 없으므로 건너뛰고, 읽을 수 없거나 형식이 맞지 않는 준비본이 있으면 준비를 거부한다. 먼저 준비한 게시판이 기준이 되므로 운영자는 다음 순서로 원본을 고른다.

1. 시청 목록에 실린 공지는 시청(`city`) 묶음의 원본을 준비한다.
2. 시청 목록에 없으면 그 공지가 목록에 실린 도서관(`living`) 또는 읍면동 게시판의 원본을 준비한다. 여러 곳에만 실렸으면 한 곳을 골라 그 게시판으로만 준비한다.
3. 이미 다른 게시판으로 준비한 공지는 그 준비본을 유지한다. 다른 게시판에 실린 사실은 각 묶음의 `batch.json` 목록 기록으로 남는다.

안성배움e(`ptIdx=300`)는 번호 공간이 따로라, 같은 숫자라도 시청·읍면동 공지와 다른 공지로 보고 본문 문서 ID 대조만 따로 한다. 도서관 본문(`official-web-capture`)도 게시판 본문과 같이 본문 문서 ID를 대조하므로, 같은 도서관 공지를 별개 단건(`single`)·목록(`batch`) 묶음에서 다른 문서 ID로 준비하면 거부한다. 같은 문서 ID의 새 버전은 받는다. 2026-11-27 수집한 시청 1페이지 묶음의 202960(`[양성작은도서관] 12월 프로그램 및 동아리 참여자 모집`)은 도서관 상세에도 원문 주소만 다르고 같은 제목·본문으로 있었다. 동시에 실행한 준비끼리는 서로의 결과를 보지 못하므로 D03 준비는 한 번에 하나씩 실행한다. 2026-11-28 실제 공도읍·미양면 1페이지 묶음(2026-11-27 수집)의 임시 사본에서 공도읍 201926을 준비한 뒤 미양면 201926은 문서 ID와 관계없이 거부됐고, 미양면에만 있는 203049는 준비됐다(임시 사본과 준비본은 삭제했다).

지자체복지서비스 API 수집은 `archive_kind=welfare`, `archive_name`에는 `welfare_batch --name` 값, `asset`에는 `WLF00000915` 같은 서비스 ID를 넣는다. 포털 원본은 선택할 수 없다. `official_url`은 복지로 공개 상세 화면 `https://www.bokjiro.go.kr/ssis-tbu/twataa/wlfareInfo/moveTWAT52011M.do?wlfareInfoId=<servId>`이고, `collected_at`은 `null`로 둔다. `batch.json`의 상세 요청 주소(`items[].source_url`)는 키를 뺐지만 키 없이는 열리지 않아 사람이 검토할 원문 주소로 쓰지 않는다. 복지로 주소 형식은 위의 `WLF00000915` 조사에서 확인한 것이며, 응답의 `servDtlLink`는 `record.list`에 원문 그대로 남아 있어 대조할 수 있다. 명령은 상세 응답과 그 서비스가 실린 목록 페이지의 원본 해시를 확인하고, 두 원본에서 파싱 결과를 다시 만들어 보관본과 대조한다. 파서 버전이 다르면 다시 수집한다. 등록 방식은 `data-go-kr-welfare-api`이며 D03 원본은 상세 응답 XML이다.

다음은 이미 보관한 `synthetic-capture` 묶음의 합성 예다. 실제 등록 입력은 담당자가 원본·개인정보·추출 대상 문구를 대조해 작성한다. 게시일·공식 문서번호 미상은 `null`로 둔다. 웹 수신 시각은 수집 기록을 사용하므로 `collected_at`을 `null`로 둔다. 포털 CSV는 실제 다운로드 출처를 담당자가 확인하고, `official_url`에는 수집 기록의 `portal.catalog_url`, `collected_at`에는 실제로 받은 시각을 입력한다. `redaction_log`는 제거 위치와 범주를 `location`, `category`로 적고 제거한 실제 값은 적지 않는다.

```json
{
  "archive_kind": "single",
  "archive_name": "synthetic-capture",
  "data_kind": "synthetic",
  "documents": [
    {
      "asset": "17",
      "official_url": "https://www.anseong.go.kr/event/program/popup/detail.do?idx=17",
      "document_id": "10000000-0000-4000-8000-000000000001",
      "document_version_id": "10000000-0000-4000-8000-000000000002",
      "version_no": 1,
      "publisher": "합성 기관",
      "title": "합성 공지",
      "published_date": null,
      "official_number": null,
      "collected_at": null,
      "cleaned_text": "사람이 확인한 합성 본문",
      "redaction_log": []
    }
  ]
}
```

```sh
python3.13 -B -m processing.collection.d03 --input data/private/source-review-input.json --name march-reviewed
```

`data/private/collection-d03/<name>/`에 검토 입력의 원본 `review.json`과 등록 입력 `source-import.json`을 저장한다. 같은 이름은 덮어쓰지 않는다. 제목·본문의 유니코드 NFC와 본문 줄바꿈을 정규화한다. 등록 입력에 원본 바이트나 다른 게시물 후보의 문구를 복사하지 않는다. 검토 입력과 등록 입력은 각각 8MiB, 수집 기록은 64MiB까지 사용한다. 수집 기록 한도를 넘으면 완료 파일 없이 이미 받은 원본을 남긴다. 수집 디렉터리와 원본·기록은 실행 사용자 소유와 비공개 권한을 유지한다. D03 초기 상태는 `pending`·`unchecked`다. [기존 Java 등록 명령](../backend/docs/extraction-run-import.md#수집-묶음에서-준비한-원문-등록)을 명시적으로 실행해야 DB에 반영된다.

### 안성배움e 전체 강좌 목록·상세 수집

교육·배움 분야의 강좌는 [안성배움e 강좌 전체보기](https://www.anseong.go.kr/edu/portal/edu/eduLctre/selectEduLctreWebList.do?mId=1400000000)에서 받는다. 공지 게시판 `board_batch edu`(`BOARDS["edu"]`)와 다른 강좌 신청 화면이다. 목록은 `selectEduLctreWebList.do?mId=1400000000&page=N`, 상세는 강좌 번호 `eduLctreNo`로 `eduLctreView.do?eduLctreNo=…&mId=1400000000`을 GET으로 요청하고 리디렉션은 따르지 않는다. 두 경로는 `/edu/` 아래이며 2026-11-28 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없었다. 포털 비교 원본 없이 공식 웹만 쓴다. D03 연결은 후속이다.

```sh
python3.13 -B -m processing.collection.edu_course_batch --name edu-courses-20261128 --max-pages 2 --max-items 20
```

`data/private/collection-edu-courses/<name>/`에 목록·상세 HTML, `parsed-<번호>.json`(`edu-course-parser-v9`, 이전 버전 기록은 파서 버전 오류로 거부), 마지막으로 `batch.json`(`citizen-edu-course-batch-v1`)을 쓴다. 한도·`--start-page`·중단 HTTP 상태·종료 코드는 도로 공사현황과 같은 공통 묶음 규칙(`web_batch.py`)이다. 요청 간격만 1.5초로 늘렸다. `read_course_batch`는 보관한 상세 원본의 해시, 파서 버전, 현재 파서로 다시 만든 파싱 결과를 대조한 뒤 강좌별 기록과 원본 경로·해시·수신 시각을 돌려준다.

목록은 `p.page_num`(`전체 N건 [ 현재 / 전체페이지 ]`)의 현재 페이지를 요청과 대조하고, `수강신청 목록` 표의 행마다 상세 링크(제목·접수상태 단추)가 한 강좌 번호만 가리켜야 받는다. `p.page_num`과 목록 표 안은 실제 목록 6쪽에 있던 태그 경로 16가지(`p > b`, `table > caption`·`colgroup > col`·`thead > tr > th > br`·`tbody > tr > td > a`·`br`·`span`, `edu_courses.py`의 `_LIST_TAGS`)와 경로별 속성(`class`·`href`·`scope`, `col`의 `style="width:…"` 다섯 값), class 값(`page_num`·`bod_maintain`·`text_left`·`btn`·`xsmall`·`type3`·`type5`·`mL5`·`mR5`)만 받는다. `noscript`·`dialog`처럼 태그로 숨긴 글자와 표 바로 아래 같은 다른 위치의 행도 거부한다. 숨긴 행의 강좌 번호나 숨긴 숫자가 붙은 전체 페이지 수(순회 종료 판단)를 읽지 않기 위해서다. 목록·상세는 공용 브라우저 기준 태그 경계 규칙(`html_tokens.py`의 `PinnedHTMLParser`)으로 읽고, `script`·`style`·`template` 안쪽은 맞는 종료 태그가 올 때까지 숨김으로 본다(`template` 안의 짝 없는 `</style>`·`</script>`는 무시). 읽는 영역 안의 종료 태그는 가장 안쪽 열린 요소를 닫아야 하고(실제 원본 34쪽 모두 그랬다), 어긋나거나 `</img>` 같은 빈 요소의 종료 태그가 있으면 거부한다. 영역 밖에서 연 서식 요소(`a`·`b`·`font` 등 14가지, `_FORMATTING`)와 그 뒤에 연 요소가 종료 태그로 안쪽부터 차례대로 닫히지 않은 채 영역이 시작돼도 거부한다. 브라우저는 `<p><a hidden></p>`처럼 암묵적으로 닫히거나 `object` 안의 `</b>`처럼 무시된 서식 요소를 영역 안 다음 글자·태그 앞에 같은 속성으로 다시 만들어 일부만 숨길 수 있다(실제 원본 34쪽은 영역 시작 때 남은 요소가 없었다). 선언형 shadow root(`shadowrootmode`·`shadowroot` 속성의 `template`)는 부모 요소의 원래 자식 대신 template 안쪽을 그리므로 문서 어디서든 거부한다. 이 수집기가 `div#learning_cont` 안의 제목 줄과 `dl > dt + dd` 항목을 읽는다. 상세 HTML에는 강좌 번호를 담은 입력값이 없다. 그래서 페이지 머리의 QR 주소(요청 주소를 되돌려 주는 값)가 요청 번호와 같은지만 확인한다. 이 값은 본문이 그 강좌라는 서버 보증이 아니다. 같은 화면의 공유 도구에 있는 다른 형식의 QR 주소(모든 표본에서 `eduLctreNo=3203&eduInsttNo=7`)는 읽지 않는다. 첨부 주소는 페이지 설정의 `contextPath`로 만들므로, 선언이 정확히 한 번 `/edu`일 때만 받는다. 목록·상세 모두 확인하지 않는 것은 읽는 영역 바깥 요소(`p.page_num`을 감싼 `div.bod_head`, `div#learning_cont`의 조상, 제목 줄·항목 묶음의 형제)의 숨김, 허용한 class·`id`에 스타일시트가 건 숨김, 허용한 값끼리의 조합으로 생기는 숨김(글자색과 배경색이 같음, 고정 크기 상자의 넘침 잘림 등), 인라인·외부 스크립트의 실행 결과다.

| 상세 항목 | `fields` 키 |
| --- | --- |
| 제목 줄 접수상태 | `reception_status` |
| 접수기간 | `application_period` |
| 접수현황(신청·모집인원·대기) | `enrollment_status` |
| 선발방법 | `selection_method` |
| 교육기간 / 교육시간 | `course_period` / `course_schedule` |
| 교육장 / 강사명 / 수강료 / 문의전화 | `venue` / `instructor` / `fee` / `contact_phone` |
| 강좌소개 / 유의사항 | `description` / `notes` |

값은 표시 문구 그대로 둔다. `br`만 줄바꿈으로 남기고 줄마다 공백을 하나로 줄이며 빈 줄은 버린다. 제목·접수상태·항목명·값 칸·첨부 이름에는 `br`·`span`·`em`·`a`만 허용하고 그 밖의 태그(`noscript`·`details` 등 안의 글자는 화면에 나오지 않을 수 있다)는 형식 변경으로 거부한다. 사진 칸의 `button`은 `file_slide_prev`·`file_slide_next` class에 `span` 하나와 `이전`·`다음` 글자만 있을 때 건너뛰고, 그 밖의 단추는 그림을 감쌀 수 있어 거부한다. 제목 줄과 항목 묶음은 실제 상세 28쪽에 있던 태그 경로 19가지(`div > span`, `div > dl > dt`·`dd`와 `dd` 아래 `br`·`a`·`span > em`, 사진·첨부 칸의 `div`·`button > span`·`a > img`·`a > span`, `_TAGS`)와 경로별 속성(`alt`·`class`·`href`·`id`·`onclick`·`src`·`target`·`title`·`type`, `style="vertical-align:middle"`), class 값(`bod_*`·`em_b_black`·`mL5` 같은 여백·`updateFileList`·`file_slide*`, `edu_courses.py`의 `_CLASSES`)만 받고, 문서 전체에서 중복 속성(브라우저는 첫 값을 쓴다)은 거부한다. 이 사이트의 화면 숨김 class(`blind`·`skip`)도 거부한다. `skip`은 첨부 링크 바로 아래의 `파일 다운로드` 안내에서만 받고 파일 이름에서 뺀다. 제목 줄·항목 묶음·`dl` 행에서 요소 밖에 놓인 글자(공백 제외)는 화면에 보이지만 읽을 칸이 없어 거부한다. `div#learning_cont`는 실제 28쪽처럼 속성이 `id="learning_cont" class="learning_content"`뿐일 때만 받는다. 13개 항목 중 하나라도 빠지거나 다른 항목명·중복이 나와도 거부한다. 빈 값은 `null`과 `missing:<키>`로 남긴다. 접수기간(신청 일정)과 교육기간·교육시간(수업 일정)은 다른 키에 두고 날짜로 해석하지 않는다. `수강료`의 `무료`는 문구 그대로 두고, 빈 칸은 `null`이며 무료로 바꾸지 않는다. 정원은 `enrollment_status`의 `모집인원` 문구에만 있고 숫자로 뽑지 않는다. 강좌소개의 대상·연령 문구에서 신청 자격을 추정하지 않는다. 같은 제목의 다른 회차는 강좌 번호와 원문 주소로 구별한다. `교육장 사진`·`강의계획서 및 이미지` 칸은 그림(`alt`, `/edu/common/imgView.do` 주소)과 첨부(파일 이름, `/edu/cmm/fms/FileDown.do` 주소)를 `media`에 순서대로 남기고 `image:<칸>`·`attachment:<칸>`으로 표시한다. 형식이 다른 주소는 `null`이다. 그림·첨부 내용은 읽지 않는다. 목록에만 있는 `지역`·`접수방법` 열은 `list-N.html` 원본에만 남는다.

2026-11-28 공식 HTML로 확인한 결과는 다음과 같다(요청 36건, 1.5초 이상 간격).

| 확인 범위 | 결과 |
| --- | --- |
| 목록 | 전체 3,292건·330페이지. 1·2·150·250·300페이지 모두 10행. 목록 순서가 강좌 번호 순은 아니다(250페이지 `1035, 1016, 992…`). |
| 명령 실행 | 1페이지 10건, 250페이지 10건(`--start-page 250`) 모두 파싱했다. `read_course_batch` 재검증을 Python 3.13.5·3.14.6에서 통과했고 두 결과는 같았다. |
| 탐색용 상세 8건 | 5085·5086·5094·4673·2803·2788·347·339. 모두 같은 13개 항목이고 두 Python 버전의 결과가 같았다. |
| 같은 제목의 회차 | 5084·5085·5086·5087은 제목이 같고 접수기간·교육기간·신청 인원만 다르다. |
| `수강료` | 2025~2026년 표본은 모두 `무료`. 2023~2024년 표본은 `48,000 원 ( 재료비 280000 )`, `48,000 원 ( 교재비 )`, `48,000 원 ( 개별 프린트 )`, `48,000 원 ( 100000 )`처럼 괄호 안 부가 문구가 붙는다. 빈 칸은 보지 못했다. |
| `교육시간` | `화/14:00 ~ 16:00` 줄이 요일마다 나뉜 형식과 `화 목/10:00 ~ 12:00` 한 줄 형식이 섞여 있다. |
| `접수현황` | 대기 정보가 없는 형식과 `(대기신청 0명 / 대기정원 10명)`이 붙은 형식이 있다. 339번은 대기정원 `9999명`, 5094번은 신청 6명·모집인원 1명이었다. |
| 그림·첨부 | 실행 20건 중 교육장 사진 5건, 강의계획서 그림 5건, 첨부 4건(JPEG), 둘 다 없음 11건(2024년 표본 10건 모두). 탐색용 347번은 HWP 강의계획서 첨부였다. 강좌 안내가 포스터 그림·첨부에만 있을 수 있어 표시를 보고 확인한다. |
| 없는 번호 | `eduLctreNo=999999999`은 HTTP 200의 196바이트 `alert('잘못된 접근입니다.')` 화면이고 구조 오류로 거부된다. |

상세 표본은 공공누리 표시가 없었다. 앱 공개 전 이용 조건 확인이 필요하다. 로그인 후 화면, 접수예정·대기접수 같은 다른 접수상태의 제목 줄, 빈 수강료, 명령으로 여러 페이지를 이어 받는 순회(`--max-pages` 2 이상)는 실제로 실행하지 않았다.

### 도서관 행사신청 목록·상세 수집

교육·배움 분야의 도서관 프로그램은 안성시 도서관 [행사신청](https://www.anseong.go.kr/library/activity/program/list.do?mId=0202020000)에서 수집한다. 포털 비교 원본 없이 공식 웹만 사용한다. 목록은 공식 폼의 `currentPageNo`를 붙인 `list.do?mId=0202020000&currentPageNo=<페이지>`로, 상세는 `view.do?idx=<번호>&mId=0202020000`로 GET 요청한다. 공식 화면은 페이지 이동을 POST 폼으로 보낸다. 2026-11-28에 같은 GET 주소가 요청한 페이지를 돌려주는 것을 확인했다. 리디렉션은 따르지 않는다. 두 경로는 [robots.txt](https://www.anseong.go.kr/robots.txt)의 제한 목록에 없다.

```sh
python3.13 -B -m processing.collection.library_program_batch --name library-programs-20261128 --max-pages 2 --max-items 40
python3.13 -B -m processing.collection.library_program_batch --name library-programs-p3 --start-page 3 --max-pages 2 --max-items 40
```

요청은 하나씩 1.5초 간격으로 보낸다. 페이지·건수 한도, `--start-page`와 `end_reached`·`partial`, HTTP 401·403·429·503 중단, 종료 코드 0·2·1은 도로 공사현황 수집과 같다. 2026-11-28 기준 목록은 110페이지(페이지당 20건)이고 지난 행사도 포함한다. 정렬 기준은 확인하지 않았다. `data/private/collection-library-programs/<name>/`에 목록·상세 HTML 원본, 파싱 결과 `parsed-<번호>.json`, 마지막으로 `batch.json`을 저장한다.

- 목록: `form#listForm`의 action, 숨은 `currentPageNo`, 페이지 이동의 현재 페이지를 요청과 대조한다. 전체 페이지 수는 `맨끝으로`의 `module.goPage(N)`에서 읽는다. 표 머리글 7개(`도서관`…`접수현황`)가 바뀌거나 행마다 상세 링크가 정확히 하나가 아니면 형식 변경으로 본다. 행 안 신청 버튼의 `data-idx`가 상세 링크 번호와 다르거나 행사명·접수현황 칸이 비어도 형식 변경이다. 다른 칸이 비면 `listing`에 `null`, `unknown["listing.<필드>"]=empty`를 남긴다.
- 신청 상태: 접수현황은 상세에 없어 목록 행의 문구를 `record.listing.application_status`에 그대로 둔다. `접수중`·`대기자접수중`·`접수마감`·`접수완료`를 확인했다. 이 문구나 상세 신청 버튼의 `data-state`(`apply_button_state`, `A`·`B`·`C`·`F` 확인)로 접수 가능 여부를 계산하지 않는다. 목록 행의 다른 칸도 `listing`에 원문으로 둔다.
- 상세: 표 `문화강좌 신청확인`의 항목을 `fields`에 표시 문구 그대로 보관한다. 신청 기간 `접수기간`(`application_period`)과 진행 일정 `행사기간`·`행사요일`·`행사시간`(`activity_*`)은 키를 나누고 날짜로 해석하지 않는다. `행사대상`·`재료비`·`준비물`·`접수방법`에서 자격이나 무료 여부를 추정하지 않으며 `없음.` 같은 문구도 그대로 둔다. 줄 안의 공백은 하나로 줄이고 `br`·문단 경계는 줄바꿈으로 남긴다.
- 빈 값: `진행자`·`재료비`·`준비물`·`유의사항` 행이 없는 게시물이 있다. 행이 없으면 `null`과 `unknown.<필드>=missing`, 행은 있으나 비면 `empty`를 남긴다. 실제로 `행사요일`·`접수방법`이 빈 사례가 있었다. 다른 필수 항목이 빠지거나 모르는 항목명·중복 항목이 나오면 형식 변경으로 보고 원본과 실패 사유를 남긴다.
- 첨부: 첨부 파일은 받지 않는다. 파일 이름·크기 표시를 줄 단위로 `attachments`에 두고 `attachment` 표시를 남긴다. `자료없음`이면 빈 목록이다. 파일 목록도 `자료없음`도 없이 첨부 스크립트만 있는 칸은 유무를 확정할 수 없어 `null`과 `unknown.attachments=empty`로 둔다. 값 안의 그림은 `image:<필드>`로 표시한다.
- 허용 표기: 목록 칸에는 실제 표본에 나온 `a`·`br`·`span`·`strong`만 받는다. 상세 값 칸에는 인라인 글자 태그와 `br`·`p`·`img`·`a`만, 첨부 칸에는 첨부 목록 구조와 전자정부 첨부 스크립트만 받는다. 칸 안쪽 태그와 대상 표의 `table`·`caption`·`colgroup`·`col`·`thead`·`tbody`·`tr`·`th`·`td`에 `style`·`hidden` 속성이 있으면 화면 표시를 확정할 수 없어 형식 변경으로 본다. 표 바깥 조상 요소의 숨김과 CSS 클래스에 의한 숨김은 확인하지 않는다. 표 밖 `script`·`style`·`template`·`noscript`의 내용은 무시하고, `template` 안의 짝 없는 `</style>`·`</noscript>` 등은 브라우저처럼 무시해 `template`이 문서 끝까지 열려 있으면 거부한다. 상세의 숨은 번호가 없으므로 신청 버튼의 `data-idx`를 요청 번호와 대조하고, `data-state`가 없거나 비어도 형식 변경으로 본다. 태그·주석·원문 텍스트·종료 태그의 경계는 공지 수집과 같은 `PinnedHTMLParser`의 브라우저 규칙을 따르고, 해석이 갈리는 표기(`<!-->`·`--!>` 주석, CDATA, 따옴표가 든 종료 태그 등)는 형식 변경으로 본다. 빈 요소가 아닌 태그의 `/>`는 브라우저처럼 무시하므로 `<span/>`은 칸이 끝날 때까지 닫히지 않아 거부되고 `<script/>` 뒤 글자는 스크립트 내용으로 숨는다. 실제 표본에는 이런 표기가 없었고, 공용 기반으로 바꾼 파서 `library-program-parser-v2`의 실제 28쪽 결과는 이전과 같았으며 Python 3.13.5·3.14.6에서도 서로 같았다.
- 통합예약: 신청 버튼은 같은 번호를 포털 통합예약 신청 양식의 `programIdx`로 넘긴다(공식 `program.js`). 이 번호를 `cross_reference_candidate.integrated_reservation_program_idx`에 후보로만 남긴다. 통합예약에 같은 번호의 같은 행사가 있는지는 확인하지 않았다. 레코드를 합치거나 중복을 판정하지 않는다.

`read_program_assets(private_root, name, ids)`는 `batch.json`에 기록된 목록·상세 원본 해시를 확인한다. 두 원본을 현재 파서로 다시 읽어 `parsed-<번호>.json`과 같은지 대조한 뒤 상세 원본 경로·해시·주소·수신 시각과 `collection_method=official-web-library-program`을 돌려준다. 접수현황 문구의 원본은 목록 페이지이므로 `listing_raw_asset_path`·`listing_raw_sha256`·`listing_url`·`listing_collected_at`도 돌려준다. 파일은 바꾸지 않는다. **D03 연결은 후속**이며 `d03`·`d03_sources`는 아직 이 수집 종류를 받지 않는다. 연결할 때 신청 상태의 증거로 상세 원본과 함께 목록 원본도 등록해야 한다.

2026-11-28 실제 확인: 목록 7페이지(1·2·4·30·60·90·110) 135행과 상세 19건을 파싱했고(1페이지 재요청·수집 실행 2페이지를 포함하면 175행) Python 3.13·3.14 결과가 같았다. 상세 19건 중 첨부 목록 4건, 스크립트만 있는 첨부 칸 1건이 있었고 그림만 있는 본문은 없었다. 한 상세는 `행사내용`의 신청기간(`~마감시까지`)이 `접수기간` 칸과 달랐다. 둘 다 원문으로 두고 맞추지 않는다. 확인한 상세에는 공공누리 표시가 없었다. 앱 재게시 전 안성시 정책에 따른 이용 조건 확인이 필요하다.

## 시민 수동 추출·보관

[extract-citizen-v1](../contracts/citizen-extraction.md)은 기존 ai-input-v1·manual archive-v1을 재사용하는 별도 family입니다. title/categories와12개 원문 사실을 FieldValue로 보존하며 분류 미상은 null+ambiguous입니다. 날짜·무료·자격·모집/취소·일정 대응을 추론하지 않습니다. 작성자의 기술 계약이며 실제 팀원·Flutter 최종 합의나 새 평가 기준을 대신하지 않습니다.

```sh
python3.13 -B -m processing.extraction prepare \
  --input contracts/examples/citizen-ai-input.json \
  --schema-version extract-citizen-v1
```

기본 `data/private/extraction-runs/prepared/extract-citizen-v1/<input_sha256>/`에 input.json/prompt.json을 만듭니다. 옵션은 prepare에만 있으며 생략 시 기존 prepared/<input_sha256>·prompt-v1 bytes는 유지합니다. 생성 템플릿 citizen-prompt-v1과 실제 수동 prompt_version 선언을 구별하고 실제 prompt/metadata/output bytes를 보관합니다. import는 metadata의 `schema_version=extract-citizen-v1`, `execution_mode=manual_import`로 선택하며 기존1~3시도·실패 전체·freeze/verify-sealed를 재사용합니다. 시민 API·archive-v2/chunk·새 provider/규칙 실행은 추가하지 않습니다.

사람 수정은 부모 metadata의 family에 맞는 check/freeze/verify-review와 전체 changes·실패 부모 보관을 사용합니다. 합성 CLI의600초 선언은 declared_only이며 실제 사람 검토 실적이 아닙니다. [시민 인계](../contracts/citizen-human-handoff.md)는 `citizen-human-handoff-v1`6키 선택에서 `citizen-human-handoff-projection-v1` 사실을 만들고 기존 check/freeze/verify-handoff로 전체 이미지를 보관합니다. title/categories 미해결은 `HANDOFF_CITIZEN_FACTS_UNRESOLVED`로 거부하고12개 원문 사실·known[]/null·실패 부모 상태를 보존합니다. 명시 split_group_id는 D06 관계 group이며 D08 개발/확인 배정이 아닙니다. area/dictionary는 요구하거나 대신 생성하지 않습니다.

Java 저장 요청은 `citizen-human-handoff-import-v1`로 전체 이미지와 명시 revision/CAS를 선택하며 투영 JSON 자체를 직접 import하지 않습니다. 원문/등록 D03/D05 대조·숨김 검토 revision·별도 승인/공개·S10 연결과 전체 검증 상태는 [G5 계획](../docs/superpowers/plans/2026-11-18-citizen-human-handoff.md)을 따릅니다. 기존 draft/check-draft·`human-handoff-v1` 선택·D08 bindings/직접 및 사람 수정후 평가는 시민 family를 각각 `DRAFT_SCHEMA_UNSUPPORTED/HANDOFF_SCHEMA_UNSUPPORTED/BINDING_SCHEMA_UNSUPPORTED/EVALUATION_SCHEMA_UNSUPPORTED`로 거부합니다. 실패 실행 등의 선행 거부와 기존8필드 분모도 유지합니다.

합성 parser·실제 CLI·archive/review·legacy 거부 시험과 실제 공식자료 정확도·사람 인수는 구별합니다. 전체 Python/Java·실제 DB/HTTP·원격 MySQL8.4 결과는 [G4 추출 계획](../docs/superpowers/plans/2026-11-18-citizen-extraction.md)과 [G5 인계 계획](../docs/superpowers/plans/2026-11-18-citizen-human-handoff.md)에서 단계별로 확인합니다. 현재 검증되지 않은 운영·실자료 성과를 처리 건수에 더하지 않습니다.

## OpenAI 개발용 추출

이 절은 기존3유형 extract-schema-v1의 개발 API입니다. 시민 family는 위 수동 보관 경로를 사용합니다.

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

[기존 구현·계약] 아래 수집·실행·분할 수치는 기존3유형 기반 시험 기록입니다. 실제20고유문서·47 D03·D05 23실행/25시도(기계 검증 통과19/실패4)·숨김 revision20·승인/공개0과 manifest dev3/holdout0은 새5분야 평가 실적이 아닙니다. 기존40문서/dev20·holdout20·8필드90%·공개표시100%·사용자6명 목표/최소3명 평가 추진·탐색시간 중앙값20% 단축 목표를 유지하며 새 분야별 자료·필드·과제·분모 적용은 재합의합니다.

문서 버전·입력 hash, 사건/문서 관계, 개발/확인 배정을 [manifest 계약](../contracts/dataset-manifest.md)으로 검증합니다. 공유 문서·정정/재게시 연결이 분할을 가르면 거부하고, 같은 문서의 복수 버전은 문서1개로 셉니다. 의심 중복은 자동 병합하지 않습니다. 노출·그룹 검토 경고와 실제40/개발20/확인20 대비 부족분을 함께 반환합니다.

```sh
python3.13 -m processing.evaluation check --input processing/examples/dataset-manifest.json
python3.13 -m processing.evaluation freeze --input data/private/dataset.json
python3.13 -m processing.evaluation verify DATASET_REF
```

예제는 합성4문서/5버전입니다. 실제 개발용3건은 dev만 배정한 비공개 manifest로 check/freeze/verify를 확인했으며 holdout은0건입니다. 같은 dataset_version의 다른 바이트는 충돌이고 기존 원본을 덮어쓰지 않습니다. 기본 root는 `data/private/evaluation/datasets`, 보관본 파일0400·디렉터리0500입니다. 키·AI·네트워크·DB를 사용하지 않습니다.

2026-11-04 공식 사이트에서 후보49개를 관찰하고 게시판·게시ID로 대조해 고유 게시물48개를 정리했습니다. 본문 수신47개에는 기존 개발3건이 포함되며, 나머지1개는 가입 안내만 반환돼 검색전용으로 남겼습니다. 조회 시각·수신 표현·hash·URL 별칭·재공지 관계 후보는 Git 제외 `data/private/evaluation/intake/official-notices-2026-11-04/`에 보관했습니다. `intake-index.json`과 `review-list.csv`로 목록을 확인하며 원래 제목·수신 내용은 JSON을 기준으로 합니다.

신규44건의 D03 배치·AI 입력·프롬프트를 Git 제외 `data/private/development-notices/2026-11-04-d03-preparation/`에 준비했습니다. 최종 입력은 `current-preparation.json`이 가리키는 `package-v2/`이며, 초기 준비본의 신청 URL 숫자 매개변수 오치환7곳을 수정했습니다. 기존 Java `ReviewedImportReader`로44건을 검증하고 raw/text hash 손상 대조군2건의 거부를 확인했습니다. Python `parse_input`·실제 `prepare` CLI도 각각44건을 통과했으며 원본 SHA·전체 블록·입력/프롬프트 hash를 대조했습니다. NFC/LF 정리와 전화·이메일 고정 패턴18곳 치환을 적용했고, 이용권한은 pending·원문 확인은 unchecked로 유지했습니다.

신규44건은 기존 개발3건을 원래 CLI 입력으로 재구성한 새 V4 시험 DB에 D03만 추가해 총47문서/버전으로 저장·재실행·SQL 복원을 검증했습니다. 기존 D05 실패3/성공3·숨김 D06 3개는 그대로이며 신규 추출 API·D05/D06은 생성하지 않았습니다. 실제 JAR28회·HTTP10회·전체16테이블/122행과 선택3개 root의 tar337항목을 대조했고 검증 서버는 정리했습니다. [백업·복원 범위](../backend/docs/backup-recovery.md#실제-개발-자료47건의-db-검증)를 따릅니다.

이후 신규44건 중17건을 개발 전용으로 고정해 기존 OpenAI 추출기에 연결했습니다. 인명5문서·주소 문맥 미확정1문서·재공지 후보2문서를 보류하고 게시일 내림차순·게시 identity순으로 선택했으며, 결과를 보고 대상을 바꾸지 않았습니다. 유형 힌트는 행사9·교통7·혼합1·공사0입니다. 이미지/첨부를 전송하지 않았고 미수신·ALT와 본문 완전성 한계를 유지했습니다. 사람의 권리/개인정보 승인을 대신한 선정은 아닙니다.

`gpt-6.1-sol`·`prompt-v2`의 실제19요청에서16건은 기계 검증을 통과했고,1건은 `LOCATION_BINDING_UNKNOWN` 누락으로3시도 후 실패했습니다. 실패 원출력은 보정·대체하지 않았습니다. 완료17개 ID를 키 없이 재사용·verify하고 성공16실행에서 미배정 숨김 사건17개를 생성했습니다. 새 전용 DB의 D05 성공16/실패1 등록·D06 저장·전체16테이블206행의 SQL 복원은 [저장 검증](../backend/docs/ai-review-draft.md#개발용17건의-추출과-저장-확장)을 따릅니다. 실행·선택·원본은 Git 제외 `data/private/development-notices/2026-11-04-development-extraction/`에 보관하며, 앞 준비 pack의 상태 표시는 준비 당시 기록으로 유지합니다.

후속 단계에서 이17건의 원본/등록 archive·단일 source·초안을 포함한321파일/55디렉터리를 별도 tar로 백업하고 같은 절대 경로에 복원했습니다. 원본 보관→부재/다른 경로 거부6회→복원본의 전체 D05 17/D06 16 재사용을 실제 JAR로 확인했습니다. 총39 CLI·HTTP15회·현재206행/스키마/data SQL·공개0과 원본 복귀/기존2618항목 보존을 대조했습니다. 추가 추출 API나 키 접근은 없으며 [선택 파일 복구의 범위와 제한](../backend/docs/backup-recovery.md#개발용17건의-선택-파일-유실-복구-검증)을 따릅니다.

후보는 미배정 상태입니다. 추가17건을 D08 manifest에 배정하지 않았으며 실제 데이터셋은 dev3/holdout0입니다. 남은27건은 보류8·개발 상한 미선택19로 구분하고 blind holdout으로 인증하지 않습니다. 운영 DB 등록·지역·이용권한·사건 관계와 추가 개인정보 검토, 개발20/확인20 분할·독립 정답표·실제 품질 평가가 남아 있습니다. 수신한 DOM·도구 응답과 작성된 ALT는 서버 원본 바이트·본문 완전성·공식 수정 시각을 인증하지 않습니다.16기계 검증 통과를 추출 정확도·사람 검토 실적으로 표시하지 않습니다.

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

[human-review-v1](../contracts/human-review.md)은 부모 metadata에 명시한 extract-schema-v1 또는 extract-citizen-v1의 수정값을 frozen D05 전체와 묶어 보관합니다. D06만 역변환해 개별 knowledge를 추측하지 않습니다. 실제 전후 값·JSON 타입·근거·검토자/종료 시각과 맞는 변경 기록이 필요하며 검토 소요시간은 제공한 시각의 차이입니다.

```sh
python3.13 -m processing.evaluation check-review --input data/private/review.json
python3.13 -m processing.evaluation freeze-review --input data/private/review.json
python3.13 -m processing.evaluation verify-review "$REVIEW_REF"
```

검토 JSON의6개 최상위 키·source/changes 형식과 root 옵션은 계약을 따릅니다. 기본 source root는 data/private/extraction-runs, 검토 보관 root는 data/private/evaluation/human-reviews입니다. 원문/수정값·검토자·사유는 비공개 파일에만 두고 stdout은 ID/hash/상태/건수/선언 소요시간만 반환합니다. 성공0/입력2/보관 손상·충돌3/I/O5/내부1입니다.

API/수동·성공/실패 D05의 실제 모드와 원출력을 보존합니다. 실패 source의 새 유효 출력은 before=null의 전체 변경 기록이 필요합니다. 기계 검사는 실제 사람이 판독했다는 증거·독립 정답·승인·공개가 아닙니다. 이 도구는 D06 저장과 별개이며 기존 extract-schema-v1의 D08 human_reviewed 채점/최초·재시험은 위 평가 CLI로 연결합니다. 시민 family는 기존 채점을 거부하고 명시 시민 인계 경로를 사용합니다. 선언 시간은 문서별 합계이며 실제 사람별 순작업 시간이나 재시험의 새 작업시간을 인증하지 않습니다. 세 방법 비교는 아래 별도 CLI를 사용하며 실제 검토본 전달은 후속 작업입니다. 키·AI·네트워크·DB는 사용하지 않습니다.

## 사람 수정값의 D06 사실 투영

[human-handoff-v1](../contracts/human-handoff.md)은 frozen human-review의 수정값을 기존 시간/장소/근거 규칙으로 투영하고 부모 D05 전체와 별도 보관합니다. 실패 부모도 실패 상태를 유지하며 미상·중복·빈 사건과 원래 변경 기록을 보존합니다. 실제 DB revision/승인/변경 기록은 만들지 않습니다.

[시민 인계](../contracts/citizen-human-handoff.md)는 별도 `citizen-human-handoff-v1`6키 선택과 split만 담은 context를 사용합니다. 아래 명령의 입력 파일만 해당 선택으로 바꾸며 기존8키 선택에 시민 출력을 섞지 않습니다. 시민12사실은 원문 FieldValue를 유지하고 legacy 시간/장소 정규화를 적용하지 않습니다.

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

## 장문 API 분할

기존 `run` 명령은 전체 v2 첫 요청 body가131072bytes를 넘으면 [prompt-v3/archive-v2 분할](../contracts/chunked-extraction.md)을 사용합니다. 원문 block을 자르지 않고 연속 core와 이전1block을 보내며, token 한도와 구별한 팀 body 예산·4096bytes 피드백 여유를 적용합니다. 단일 block과 필수 문맥 자체가 초과하면 API를 호출하지 않고 원본·계획·실패를 보관합니다.

metadata.attempts는 최대3개의 문서 cycle이고, 실제 호출 수는 receipt.total_calls입니다. 각 cycle에서 chunk마다1요청만 하며 retryable 실패이면 전체 새 cycle을 실행합니다. 모든 실제 요청/응답/실패와 전체 파생 결과를 남기고 사용량 미상은 합계null입니다. 기존 작은 API 요청·수동 import·v1/v2 프롬프트와 보관 bytes는 유지합니다.

전송하지 않은 block 인용과 문서 전체 not_stated 추정을 거부합니다. chunk 사이 사건·일정·장소를 임의로 합치지 않으며, v2 직접 draft/check-draft는 `CHUNK_DRAFT_REVIEW_REQUIRED`입니다. 실제 사람이 전체 관계를 확인한 human-review/handoff를 사용합니다. D08은 `api-document-cycle-v1`·`prompt-v2-or-v3` 정책으로 첫/최종 전체 문서 결과를 평가하고 기존 정책은 v1만 받습니다. 기계 검증을 실제 사람 검토·40문서 정확도 성과로 표시하지 않습니다.

입력보다 큰 plan·cycle manifest·receipt도 전체 canonical size/SHA로 검증합니다. 큰 receipt의 Python 보관·동결·재사용과 D08 평가/사람 인계는 접두부만 읽지 않습니다. identity8MiB, Java 연결 stdout/receipt8MiB·최대60초, S10 AI artifact8MiB·전체 JSON/HTML64MiB 한도는 유지합니다. S10 D03 raw 원문만 파일당20MiB까지 전체 표시하며, Python 단독 성공과 Java 등록·보고서 성공을 구별합니다.

## 실제 입력 길이 진단

2026-11-04에 DB D03의 전체 block 투영·hash와 대조한 기존47입력을 로컬에서 측정했습니다. 기존 `parse_input`·`render_prompt(..., prompt-v2)`·`request_bytes`만 사용하며 키·추출/토큰계산 API를 호출하지 않았습니다. 원입력/index의 SHA·권한·fileKey는 전후 동일합니다.

| 항목 | 최대 | 중앙값 |
| --- | ---: | ---: |
| D03 정제 본문 Unicode code points | 1,691 | 525 |
| 입력 JSON UTF-8 bytes | 6,929 | 2,118 |
| 입력 block 수 | 44 | 11 |
| v2 prompt UTF-8 bytes | 31,827 | 22,761 |
| 첫 요청 body UTF-8 bytes | 38,088 | 28,360 |

D03 정제 본문 길이는 DB 값을 직접 계산했고, block.text 합계와 구별합니다. 전체715블록이며 제안200,000문자(code point/UTF-16 각각)·입력8MiB 초과는0입니다. 요청 body는 `gpt-6.1-sol`·첫 시도 framing·헤더 제외이며 재시도 피드백은 넣지 않았습니다. 이 측정을 G02 장문 분할 구현이나 공급자 token 한도 검증으로 대체하지 않습니다.

기존 실행은 고유20문서·23run·25시도이며, v1 3회/v2 20회·기계 검증 통과19/실패4입니다. `usage_in`180,568·`usage_out`61,954는 각 실행의 전체 시도 사용량 합계입니다. 단일 prompt token 수나 문자별 환산값이 아니며, 상세 `model_version`23건은 모두 null로 남겼습니다.

2026-11-04 확인한 [OpenAI 모델 문서](https://developers.openai.com/api/docs/models/gpt-6.1-sol)의 context window는1,050,000tokens·최대 출력128,000tokens입니다. 프로젝트의 `max_output_tokens=8192`와 별개입니다. 정확한 입력 token 수는 같은 model/instructions/input으로 [입력 토큰 계산 API](https://developers.openai.com/api/docs/guides/token-counting)를 사용할 수 있지만 이번에는 호출하지 않았습니다. 계정별 접근 권한·rate/spend 한도는 미확인이고 문자/바이트로 token 수를 추정하지 않습니다.

상세 수치는 Git 제외 `data/private/evaluation/evidence/real-review-readiness-2026-11-04/diagnostics/input-lengths.json`, 처리20문서의 보고서는 [실자료 검토 인계 안내](../backend/docs/review-report.md#실제-개발-자료의-검토-인계-준비)를 따릅니다. 사람 검토·독립 정답표·dev20/holdout20·90% 평가·승인/공개·배포는 미완료입니다.

## 검증·남은 작업

등록한 D05에서 `python3.13 -m processing.extraction draft`로 ai-draft-import-v1을 생성하고 Java local-import로 저장할 수 있다. 실행 인자·사람 검토본 작성·승인 경계는 [초안 연결 안내](../backend/docs/ai-review-draft.md)를 따른다. API 실행과 분리된 로컬 변환이며 AI 원본과 초안을 사람이 확인해야 한다.

자동 시험으로 시간·거리·결합·취소·최신성·재현·정렬·중첩·실제 CLI 오류를 확인합니다. 실제 Java 공개 상세 예제와 사실 필드 전체도 대조합니다. AI 검증은 한글/emoji·미상·형식/근거 오류·실패 원본·충돌·동시 실행·중단 재개·손상·실제 subprocess를 확인합니다. CI에서 Python3.13 시험과 기존 계약·백엔드 시험을 함께 실행합니다. 시험 목록은 `tests/`, 설계 결정은 [계산 계획](../docs/superpowers/plans/2026-11-03-calculation-cli.md)과 [추출 기록 계획](../docs/superpowers/plans/2026-11-03-extraction-validation.md)에 있습니다.

AI 원출력·사람 검토본은 별도 보존합니다. 공식 공사·행사·교통 개발 공지3건의 첫 v1 실행은 `EVIDENCE_MISMATCH`로 중단돼 원본을 남겼습니다. 같은 입력의 새 v2 실행은 각각1회 기계 검증을 통과했고 사건1건씩·근거7/5/15개를 추출했습니다. 재실행을 새 문서3건으로 중복 집계하지 않습니다.

새 전용 MySQL8.4.13에서 실제 JAR로 D03 3문서/3버전·기존 D05 v1 실패3/v2 성공3·D06 `ai_draft/draft/hidden` 초안3을 저장했습니다. D06에는 개발 구역·사전 후보의 식별자만 연결했으며 `area_membership=uncertain`, 검토자·검토 시각·geometry는 null입니다. 원래 미배정 초안과 모든 원본은 보존했습니다. 후보를 확정하거나 지점5개·사전 행을 DB에 등록하지 않았습니다. 정확한 재실행·변조/실패 실행/다른 문서 참조·직접 승인 거부와 원본/공개 테이블 불변의 결과는 [저장 검증](../backend/docs/ai-review-draft.md#실제-개발-자료의-저장-검증)을 따릅니다.

원문은 `use_review=pending`·`check_result=uncertain`이며 사람의 사실성·이용권한 확인은 완료되지 않았습니다. 구역·사전·문서 관계/분할과 좌표를 사람이 확인하고 별도 검토 revision을 준비해야 합니다. 사람 검토본 전달·독립 정답표·40문서/holdout 평가·승인/공개·운영 배포는 후속 작업입니다. 같은 문서의6실행을6문서로 집계하지 않으며 실제 데이터셋은 여전히 dev3/holdout0입니다. 세부 요구는 [TASK.md](TASK.md)를 따릅니다.
