# AI 수동 결과 파일 업로드 설계

## 목적·근거

I10·B05/G02/G06의 AI 결과5MiB 파일 업로드를 기존 Python 수동 보관·Java D05 등록에 연결한다. 사용자가 요청한 Java/Python 개발 루프를 따른다. 아래 전송 절차·새 HTTP prompt 한도는 에이전트의 구현 결정이며 사람이 별도로 승인했다고 표시하지 않는다. 공개/관리 분리·원출력/실패 보존·최대3시도·승인 전 비공개를 유지한다.

기존 JSON `/local/extractions/import`는 이미 준비된 archive를 등록한다. 새 경로는 아직 archive가 없는 실제 수동 실행의 input·metadata·prompt/output 원본을 받아 같은 import/freeze/DB 경로로 보낸다. 자동 AI 호출·새 모델 선택·API wire archive 위조·관리 UI·사람 승인/공개는 수행하지 않는다.

## 접근 비교

- 단일 multipart: 입력8MiB+출력3×5MiB만23MiB여서 기존21MiB 요청 한도로 전체1~3시도를 지원하지 못한다. 전역 한도 확대는 선택하지 않는다.
- ZIP 등 묶음: 새 압축/경로 검증과 한도 규칙이 필요하고 같은 합계 문제도 남는다.
- 선택: 초기 입력과 각 시도 파일을 분리하고 명시 finalize로 등록한다. 원본을 재구성하지 않고 기존 전송 한도를 유지한다. 중간 staging의 private 저장공간·백업/보존 관리가 추가로 필요하다.

## HTTP 계약

모든 경로는 기존 `local-api`의 loopback·token·Origin/Host·Accept·최소 로그 경계를 그대로 적용한다. 인증 전에 multipart를 파싱하지 않는다. 기존 전역 multipart off/local-api on·file20MiB/request21MiB·form-post21MiB·메모리 threshold/lazy parsing 기동 검사를 유지한다. 기존 JSON 경로도 유지한다.

| 요청 | 정확한 입력 | 성공 |
|---|---|---|
| POST `/local/extractions/uploads` | multipart: `control` JSON byte part, `metadata` JSON byte part, `input` file | 초기 원본 staging |
| PUT `/local/extractions/uploads/{run_id}/attempts/{attempt}/{artifact}` | multipart: `file` 하나. attempt=1..3, artifact=prompt 또는 output | 정확 slot staging |
| POST `/local/extractions/uploads/{run_id}/finalize` | 기존3키 JSON 등록 요청 | 기존 D05 등록 결과 |

control/finalize는 정확히 `schema_version:extraction-import-request-v1,run_id,expected_input_hash`다. UUID/64자리 소문자 SHA·URL 연결 검사를 기존 JSON 등록과 공유한다. 초기 metadata의 run_id도 같아야 하며 execution_mode는 manual_import, attempts는1..3이다. Java는 이 연결·slot 상한만 읽고17키 의미/input/output 검증은 Python에 유지한다. metadata 선언 N 밖 slot은 거부하며 finalize는 정확히1..N의 완전한 쌍을 요구한다.

control/metadata는 각각 application/json·선언 charset UTF-8·최대64KiB이며 새 finalize JSON도64KiB다. 기존 `/local/extractions/import` 등 JSON8MiB 경계는 유지한다. input은 application/json·최대8MiB이며 실제 bytes의 SHA가 expected_input_hash와 같아야 한다. 중복/추가 part·미지원 MIME·후행/중복키 제어 JSON은 거부한다. input/metadata가 최종 Python 의미 검증을 통과했다는 뜻으로 staging 응답을 사용하지 않는다.

prompt는 최대20MiB, output은 최대5MiB다. file MIME은 application/octet-stream 또는 text/plain이며 선언 charset이 있으면UTF-8만 허용한다. 파일 bytes는 변환하지 않는다. prompt/output은 빈 파일·잘못된 UTF-8·잘못된 결과 JSON도 수신할 수 있으며 출력 검증은 Python이 수행한다. input/metadata/control의 빈 파일은 거부한다. 파일명은 경로/ID로 쓰지 않고 응답/로그에 반사하지 않는다. 각 요청의 전체21MiB 경계도 별도로 유지한다.

staging 성공200은 `schema_version:extraction-upload-result-v1,run_id,expected_input_hash,state:staged,received_files,review_required:true`다. received_files는 이 응답이 확인한 고정 이름·size_bytes·sha256만 포함한다. 서버 경로·token·본문·모델 시각을 반환하지 않는다. finalize 성공200은 기존 `local-management-result-v1`이다. 실패 원출력이 정상 보관/등록된 경우에도200이며 기존 data.status=failed로 구별한다.

## 원본 저장·동시성

추가 환경변수 없이 기존 request root의 `extraction-uploads/`를 사용한다. root/디렉터리0700·파일0600, 중간 symlink/지원하지 않는 파일시스템을 거부한다. client는 임의 root·파일 경로를 지정하지 않는다.

초기화는 서버 UUID 후보 묶음에 control.json/input.json/metadata.json 및 size/SHA identity를 모두 준비한 뒤 run UUID index를 배타 hard link로 설치한다. 다른 초기 bytes는409, 정확 bytes는 첫 묶음을 재사용한다. 완료 index 없는 자기 실패 후보만 정리한다. 원래 control bytes도 유지한다.

각 attempt-N.prompt/output은 완성 임시 파일의 배타 설치로 추가한다. 같은 slot·같은 bytes는 재사용하고 다른 bytes는409다. 중단 임시 파일은 완료 slot으로 보지 않는다. metadata의 N이 초기화 뒤 변하지 않고 각 slot도 교체 불가이므로 완전한1..N 뒤에 새 정상 slot은 생기지 않는다. finalize는 고정 파일 집합·size/SHA·링크/권한을 다시 검사한다. Python의 복사 전후 full fingerprint도 유지한다. JVM lock만으로 여러 호출/프로세스의 충돌을 보장하지 않는다.

이미 완료한 canonical UUID가 있다면 기존 Python verify의 검증된 receipt를 사용한다. metadata/input와 허용 artifact 집합·size/SHA가 같은 재전송만 허용하고 새 시도·교체는409다. api/v2 실행을 manual로 바꾸지 않는다. canonical 검증 실패를 부재로 바꾸지 않는다. 동일 HTTP staging이 이미 존재하는 중단 finalize는 같은 전체 bytes로 기존 Python import_run을 재개한다. canonical 미완료인데 HTTP staging이 없는 외부 CLI 실행은422로 거부하고 기존 CLI의 정확 원본 재개를 안내한다. canonical 원본을 HTTP 쓰기 대상으로 사용하지 않는다.

상태조회·취소·자동 만료·자동재시도·새 DB staging 테이블은 추가하지 않는다. staging과 canonical/extraction root 및 DB를 함께 백업하고 같은 경로에 복원한다. 앱 밖 관리자 변경·전원 중단 내구성·운영 보존 정책을 이 기능으로 보증하지 않는다.

## Python·D05 연결

`PythonProcess`의 고정 argv·공통1~60000ms deadline·stdout8MiB/stderr64KiB·interrupt/kill/reap을 재사용한다. keyless entry를 추가해 환경을 비우고 실행에 필요한 PATH/locale만 허용한다. OPENAI/DB/local token·PYTHONPATH 등은 전달하지 않는다. 새 import뿐 아니라 이어지는 archive verify/freeze도 이 entry를 사용한다. 기존 ExtractionArchiveReader의 고정 archive 명령도 같은 entry로 통일해 재사용 중 환경 상속이 다시 생기지 않게 한다. 기존 execute의 기본 정책과 계산기 등 나머지 호출자는 유지한다. Python 모듈 경로는 기존 절대 workdir이며 새 호출은 -B/-s를 사용한다.

`ExtractionArchiveReader`에 서버 staging 경로와 순서 있는1..3쌍으로 기존 `python -m processing.extraction import --input ... --metadata ... --attempt ... --root ...`를 호출하는 얇은 연결을 추가한다. 새 Python framework·17키/identity validator·AI 호출은 추가하지 않는다. metadata/input 의미 검증과 모든 후보 full fingerprint·기존 identity 재사용/충돌은 import_run이 최종 판단한다. receipt 기록 전 중단은 완료로 보지 않는다.

종료0/4와 receipt의 validated/failed 일치를 확인한 뒤 기존 `LocalManagementService.extraction`→`ExtractionImportService.importRun`의 freeze·원본/D03 전체 대조·DB 트랜잭션/중복 등록을 재사용한다. Python 실행 동안 DB transaction을 유지하지 않는다. 파일 성공과 DB 성공은 별개다. DB 실패 후 같은 UUID/hash finalize는 원래 archive와 DB 결과를 재사용하며 새 UUID/모델 재호출을 만들지 않는다.

CLI exit3의 정확한 고정 stderr 코드 ARCHIVE_CONFLICT만 내부409로 분류한다. 다른 임의 진단을 응답·로그에 넣지 않고 기존 validation422/integrity422/I/O500·runtime503을 유지한다. bounded stderr의 내부 결과 전달 보완은 기존 Result 생성자/호출자 호환을 지킨다. timeout/중단/초과 drain을 성공으로 처리하지 않는다. 그 외 경계는 기존 오류 형식으로 입력422·부재404·충돌409·한도413·media415다.

## 한도·검증 범위

새 HTTP metadata64KiB/prompt20MiB/output5MiB는 기존 CLI metadata8MiB/수동 prompt 무제한/큰 실패 출력 전체 보존을 변경하지 않는다. transport 초과413은 미수신 전체 파일을 보존했다는 뜻이 아니다. S10은 기존 AI artifact8MiB/전체 JSON·HTML64MiB를 유지하고 초과는 생략 없이 보고서 실패·별도 검토로 안내한다. 업로드/D05 성공과 보고서 성공은 별개다.

시험:1·3시도/실패/빈·잘못된 output/한도 경계/중복·추가 part/인증 전 parsing/공개404/환경·로그 비노출/순서·UUID/hash·metadata 충돌/초기·slot·finalize 동시성/중간 I/O·DB 실패/완료·중단 canonical/봉인 후 재사용/백업 복원/기존 원본·공개본 불변. 실제 Python CLI·MySQL·기동 JAR로 증명하고 전체 Java/Python·계약/Node 회귀를 유지한다. 실제키/API·실자료·사람 검토·독립 gold·운영 서버·배포는 사용하지 않는다.

실행 방식은 기존 native 구현·명시 파일 소유권의 병렬 agent·전체 자체 검토·유효 minor 포함 수정·계획당 새 문맥 전체 코드 리뷰1회·정확 head CI/AI·비main 병합/통합 증거 동결 루프다. 현재 PR46의 통합/동결 완료 전에는 제품 코드를 구현하지 않는다.

새 문맥 builder check `/root/extraction_upload_builder_check`: nothing important left. 읽기 전용·구현/시험 없음. 부모가 import 뒤의 기존 verify/freeze도 keyless여야 한다는 연결을 명시했으며, 제품 범위·기존 CLI 한도는 바꾸지 않았다.

