# 로컬 원문 업로드·텍스트화 설계

## 목적과 범위

I10의 준비된 JSON 입력에 txt/pdf/json 파일 업로드를 추가한다. 기존 Spring·MySQL·Python 경계를 유지하며 원문을 D03에 등록하고 추출용 입력을 준비한다. 원본·전처리 결과·실패를 구별하고 기존 승인·공개 검증에서도 같은 원문을 다시 검증할 수 있어야 한다.

근거는 `docs/spec/03_데이터와AI.md` D03, `04_계산규칙과기술설계.md` I10·파일 한도, `10_인원별WBS.md` B05/G02/G06이다. 아래 세부 HTTP·변환 정책은 기존 설계를 구현하기 위한 에이전트의 선택이다. 사용자에게 새로운 제품 요구로 합의받았다고 표시하지 않는다.

이번 단계는 파일→원문 보존→텍스트화→D03 등록→기존 AI 입력 준비까지다. AI 결과 파일5MiB 업로드, 실제 추출 호출, 사람 검토·독립 평가, 관리 UI·운영 배포는 전체 목표의 후속 단계로 남긴다. 기존 D05 등록과 API/장문 보관본의8MiB·실패 원출력 규칙을5MiB로 바꾸지 않는다.

## 입력과 성공 응답

기존 `POST /local/documents`의 `application/json`·`source-import-v1`·8MiB 입력은 그대로 둔다. 같은 URL에 `multipart/form-data`를 추가하며 정확히 두 part만 받는다.

- `metadata`: UTF-8 JSON, 최대64KiB, 중복/추가키·후행 JSON·잘못된 Unicode 거부.
- `file`: 최대20MiB. 파일명은 저장경로·ID·명령 인자로 사용하지 않는다. 형식은 metadata의 `format=txt|pdf|json`으로 명시하고 part media type·내용을 함께 검사한다.

metadata의 정확한 필드는 `schema_version=source-upload-v1`, `format`, `data_kind`, `document_id`, `document_version_id`, `version_no`, `publisher`, `official_url`, `title`, `official_number`, `published_date`, `collected_at`, `collection_method`, `use_note`다. ID·시각·버전은 기존 D03 준비 JSON처럼 명시한다. 같은 게시물의 수정본은 같은 document_id를 사용하고 최신+1 버전을 제출한다. 서버가 임의 새 문서ID·현재시각을 만들어 재시도와 문서 계보를 바꾸지 않는다. URL을 자동 수집하거나 같은 URL을 자동 병합하지 않는다.

새 원문은 항상 `use_review=pending`, `check_result=unchecked`, `checks=[]`, 확인 시각은 null로 시작한다. 업로드 사용자가 allowed/verified·검토자·좌표를 선언할 수 없다. 이용권한·확인은 기존 별도 source-review 절차로 기록한다.

성공200은 새 `source-upload-result-v1`으로 문서/버전ID·버전번호·등록 결과·원문/본문/AI입력 hash·전처리 버전·pending/unchecked 상태를 반환한다. 기존 JSON 응답 규격은 바꾸지 않는다. multipart 전체 bytes를 보존했다고 주장하지 않으며, metadata part와 파일 part의 원래 bytes를 각각 보존한다. filename·인증 헤더는 보관하지 않는다.

오류는 기존 공통 JSON/request_id 형식이다. 파일/본문 한도는413·분할/별도 검토 안내, 형식·본문 없음은422, ID/내용·버전 충돌409, PDF 도구 미준비503, 예상하지 못한 I/O500으로 구별한다. 원문·토큰·경로·SQL·자식stderr를 오류/로그에 반사하지 않는다.

## 텍스트화와 개인정보

- txt: 엄격한 UTF-8. LF 통일·NFC 정규화 후 처리한다. 잘못된 encoding·Unicode·허용하지 않는 제어문자는 거부하며 조용한 대체/잘라내기를 하지 않는다.
- json: 정확히 `{"schema_version":"text-body-v1","text":"본문"}`만 허용한다. 기존5키 AI입력이나 source-import를 추측해 재해석하지 않는다. 기존 source-import는 원래 application/json 경로로 제출한다.
- pdf: 설정한 절대 `pdftotext` 실행 파일을 shell 없이 고정 argv `-enc UTF-8 -eol unix -layout - -`로 호출한다. HTTP에서 받은 원래 bytes를 stdin에 전달하고 stdout에서 읽어, 보관 파일을 다시 여는 사이 다른 bytes가 변환되지 않게 한다. UTF-8/LF·페이지 경계를 유지하며 암호화·깨짐·본문 없음은 명시 실패·별도 검토다. OCR·첨부/매크로 실행을 구현했다고 표시하지 않는다.

PDF의 텍스트 없는 페이지가 하나라도 있으면 전체 등록을422 `PDF_PAGE_REVIEW_REQUIRED`로 중단한다. 마지막 form-feed 종료 표식은 새 빈 페이지로 세지 않으며 중간/실제 마지막 빈 페이지는 거부한다. 의도된 빈 페이지도 수동 검토 경로가 필요하다는 비용을 받아들인다. 기존 OCR 텍스트층이 있는 PDF는 그 내장 텍스트를 추출할 수 있으나 OCR을 실행했다고 기록하지 않는다. 글자/머리말이 있는 이미지·도표의 누락까지 자동 판별할 수 없으므로 모든 PDF receipt/응답에 `text_scope=embedded_text_only`, `text_review_required=true`를 명시하고 사람의 전체 원문 대조 전 추출 완전성을 주장하지 않는다. txt/json도 비식별·사실 검토를 자동 완료하지 않는다. 이는 builder check의 혼합 스캔 질문에 대한 에이전트의 보수적 처리 선택이다.

PDF 실행 파일 경로는 서버 설정으로만 받는다. 설치된 Poppler를 활용하고 Maven/Python 라이브러리를 추가하지 않는다. 로컬 확인 버전은25.04.0이며 실제 변환에 사용한 버전을 기록한다. CI에는 실행 가능한 Poppler 도구가 필요하다. stdout/stderr는 동시에 제한해 읽고 전체10초 deadline·초과 시 종료/회수·키 없는 최소 환경을 적용한다. stdout은 최대4MiB, stderr는64KiB이며 초과를 정상 텍스트로 취급하지 않는다. OS 메모리 격리나 모든 PDF 읽기 순서의 정확성을 보증하지 않는다.

새 변환 본문에는 고정 전화·이메일 패턴 치환을 적용하고 범주·위치만 redaction_log에 남긴다. 제거한 실제 값을 로그에 복제하지 않는다. 이 치환이 모든 개인정보를 제거한다는 보장은 없으며 AI 전송 전 실제 비식별 검토가 필요하다. 업로드 자체는 외부 AI를 호출하지 않는다.

정규화·치환 후 Unicode code point 기준 전체200,000자 이하를 검사한다. Java UTF-16 길이를 문자 수나 Python offset으로 혼용하지 않는다. txt/json은 문단/행, pdf는 페이지 순서를 보존하고 긴 행도 결정적으로 나눠 블록당 최대2,000 code point로 만든다. 블록ID는 문서 안에서 유일하며 pdf 페이지 번호를 유지한다. 기존 AI입력/원본의 블록을 재분할하지 않는다. 빈 블록은 근거로 만들지 않는다.

전처리 버전은 정규화·치환·블록 정책과 PDF 도구 버전을 식별한다. cleaned_text는 블록 text를 정해진 LF로 결합하며 원문 bytes hash·본문 UTF-8 hash·각 블록 hash·AI입력 bytes hash를 구분한다. AI입력은 기존5키 `data_kind/document_version_id/title/published_date/blocks` 투영으로 만들며 기존 Python parse_input 및 D03 대조를 통과해야 한다.

## 파일 보관·재실행·DB

인증·Origin/Host 검사는 multipart parsing 전에 기존 필터가 수행한다. local-api 전용 multipart의 파일20MiB/전체21MiB 실제 수신 한도를 적용한다. threshold를 전체 한도 이상으로 두어 servlet이 private 원문을 공용 임시 디렉터리에 쓰지 않게 한다. metadata64KiB·정확한 part 수는 별도 검사한다. 인증 실패·unknown metadata·초과 파일은 원문/DB 쓰기0이다.

원문은 source root 아래 고정 `uploads/<raw_sha256>.<format>`로 배타 설치한다. 요청 metadata·생성 source-import JSON·AI입력·정책/파일 hash를 담은 receipt는 request root의 업로드 전용 하위 디렉터리에 버전ID로 보관한다. 운영자가 관리하는 private root만 사용하고 링크·경로 이탈·기존 다른 내용·권한 충돌은 거부한다. 디렉터리0700/파일0600, 실패 시 기존 파일을 덮어쓰지 않는다.

유효 metadata의 known-domain 실패는 원문/전처리 보관본이 남을 수 있다. 등록 DB transaction과 파일 저장을 하나의 원자적 작업이라고 주장하지 않는다. 같은 버전ID의 정확한 재실행은 저장한 metadata/file bytes와 결정된 source-import를 재사용하고 PDF를 다시 변환해 과거 결과를 바꾸지 않는다. 다른 metadata·파일·형식은409다. 부분 준비/충돌·동시 동일 업로드는 성공을 가장하지 않으며 원본을 보존하고 재시도 가능 여부를 명시한다.

D03 등록은 기존 ReviewedImportReader/Service의 전체 검증·원문hash·버전순서·중복/충돌·rollback을 재사용한다. 자동 사건·D05·승인·공개를 만들지 않는다. 새 자료뿐 아니라 저장 후 source-review/preview/approve/publish·재실행에서도20MiB 원문 검증이 동작해야 한다.

## 기존 한도·보고서·복구

공통 JSON reader8MiB를20MiB로 바꾸지 않는다. raw asset 읽기만20MiB로 분리하며 공개 요청32KiB·기존 관리/CLI/AI입력8MiB·D05 원출력 규약은 유지한다. 기존 raw8MiB+1 거부 시험은 올바른 SHA를 가진8MiB+1/20MiB 허용·20MiB+1 거부 시험으로 바꾼다.

S10은 raw asset 전체를20MiB까지 읽어 기존 text/base64로 embed한다. AI artifact8MiB·전체 JSON/HTML64MiB는 유지하며 합계 초과는 REPORT_TOO_LARGE다. 원문을 생략하거나 일부만 넣어 보고서를 성공 처리하지 않는다. 파일당 raw20MiB 허용이 모든 자료 조합의64MiB 보고서 성공을 보장하지 않는다.

source root의 uploads와 request root의 업로드 metadata/receipt/source-import/AI입력을 함께 백업한다. 선택 원본 복구 후 기존 문서 hash·등록 재실행·S10·미승인 공개 차단을 대조한다. 운영 백업 정책·전원 중단 내구성은 별도 인수다.

## 완료 증거

합성 txt/pdf/json 모두 실제 로컬 HTTP→원문 보존→D03 등록→Python 입력 검증까지 확인한다. 최대 원문·200,000자 code point·chunk 계획, malformed/크기/파트/프로세스 실패, 같은 입력 재실행·다른 입력 충돌·동시 업로드·DB 실패 원본 보존을 시험한다. 실제 MySQL·JAR·S10·승인/공개·복구와 기존 JSON/공개/CLI 전체 회귀를 실행한다.

부모 전체 자체 검토·유효 지적 수정 후 새 문맥 전체 브랜치 리뷰1회, 정확한 PR head CI·자동 리뷰·새 피드백, 비main 병합·통합 검증·비공개 증거 동결 순서를 유지한다. 합성 검증을 실제 PDF 정확도·개인정보 검토·사람 승인·40문서/90%·운영 완료로 보고하지 않는다.
