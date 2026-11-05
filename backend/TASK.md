# 백엔드·DB 작업

[수동 AI 결과 파일 업로드](docs/extraction-upload.md)를 기존 Python import·D05 등록에 연결했습니다. 초기 파일·각 시도·finalize를 나누어 받으며 실패 원출력·같은 UUID/hash 재시도·기존 승인 경계를 유지합니다. 실제 DB/JAR·보고서·공동 복구·전체 회귀와 리뷰/PR/통합은 [진행 계획](../docs/superpowers/plans/2026-11-05-extraction-result-upload.md)에서 별도로 확인합니다.

B05/I10/I11의 [로컬 관리 HTTP API](docs/local-management-api.md)는 기존 import·승인/공개 서비스를 연결하고 원입력 보관·loopback/토큰·Origin 경계를 적용했습니다. 전체 회귀와 격리 MySQL·실제 합성 JAR에서 등록·수정·승인/반려·미리보기·공개/복구·동시 충돌·공개 API3종을 검증했습니다. 기존 JSON 관리 경로의 검증·리뷰 기록은 [계획](../docs/superpowers/plans/2026-11-04-local-management-api.md)을 따릅니다.

[txt/pdf/json 원문 업로드](docs/source-upload.md)·텍스트화를 추가해 원문20MiB까지 보존하고 pending/unchecked D03와 Python 입력을 준비합니다. 기존 JSON/CLI/AI입력8MiB, S10의 AI artifact8MiB·전체 JSON/HTML64MiB는 유지하며 S10 raw 원문만20MiB 전체를 표시합니다. source/request 두 root의 원본·준비본을 함께 보존하며 DB 실패 뒤에도 완료 준비본으로 정확히 재시도합니다. 전체 회귀·리뷰·PR/CI·통합 결과는 [업로드 계획](../docs/superpowers/plans/2026-11-05-document-upload.md)에서 추적합니다. 관리 UI·실제 AI 품질/개인정보·사람 검토/승인·실자료 독립 평가·운영 배포는 후속 작업입니다.

[장문 v2 보관본](../contracts/chunked-extraction.md)의 D05 등록·봉인 재검증·전체 파생 출력 hash·보고서·실제 사람 인계를 연결합니다. 문서 cycle1~3/실제 HTTP 호출 수를 구별하며 기존 DB 제약과 공개 승인 경계를 유지합니다. 작은 기존 v1 및 큰 실패 원출력의 전체 보존도 유지합니다.

처리한 실제20문서의 [S10 검토 묶음](docs/review-report.md#실제-개발-자료의-검토-인계-준비)을 SELECT 전용 계정으로 생성·대조했습니다. 모든23실행/25시도·실패·숨김 초안을 보존하며 원본/DB 불변을 확인했습니다. 이는 사람 검토·승인/공개가 아닌 검토 인계 준비이며 실제 브라우저/기기·운영 인수는 남아 있습니다.

R15/R16의 [최소 요청 로그](docs/request-logging.md)를 연결했다. 전체 동기 HTTP에서 요청당1회 서버 ID·오류·latency·확인된 선택 버전만 남기며 요청 조건·원문·IP·예외 stack은 수집하지 않는다. 실제 자료·기기 인수와 운영 보존/접근 정책은 후속 작업이다.

S10의 파일 방식 [로컬 검토 보고서](docs/review-report.md)를 추가했다. 원문·모든 D05 시도·현재/과거 D06·사람 수정·승인/공개 이력·오류·명시 preview를 private HTML로 비교한다. 읽기 전용 capture·sealed 검증·비웹 기동·private 출력을 적용하며 기계 검사와 실제 사람 검토/공개를 구별한다. 실제 자료·기기 인수와 운영 승인은 후속 작업이다.

구현한 기능과 실행 명령, 미완료 범위는 [README](README.md)에 기록합니다. 합성 API·초기 스키마·비공개 검토본 import와 로컬 승인·미리보기·공개·복구·snapshot JSON 내보내기를 구현했습니다. 공개 API는 DB snapshot을 조회하며 matches를 실제 Python 계산에 연결했습니다. [import 규격](docs/reviewed-import.md)·[승인·공개·내보내기 안내](docs/review-publication.md)·[공개 조회 안내](docs/public-snapshot-api.md)와 README의 Python 설정을 따릅니다.

D03 선등록·D05 archive 검증/등록·D06 실행 참조는 [연결 안내](docs/extraction-run-import.md)를 따른다. Python OpenAI 개발용 실행의 api archive도 같은 경로로 등록하며 Java가 직접 AI를 호출하지 않는다. D06 숨김 초안과 검토 승격은 [초안 안내](docs/ai-review-draft.md)를 따른다. 개발용 실제 3건은 새 전용 시험 DB에서 D03 3문서/3버전·기존 D05 실패3/성공3·후보 연결 D06 숨김 초안3 저장을 확인했다. 당시 구역·사전 후보와 원문 이용 검토는 미확정 상태로 보존했다. 구역명·범위 설명·5지점 선정은 [2026-11-05 채택 기록](../docs/spec/07_결정사항과자체점검.md)을 따르며, 좌표·지명 사전·원문 이용 검토와 실제 사람 검토·독립 평가·승인/공개·배포는 후속 작업이다.

신규44건의 D03을 더해 총47문서/버전의 등록·복원을 확인한 뒤, 이 중 개발용17건의 실제 API 실행을 연결했다. 신규 D05는16기계 검증 통과/1실패를 그대로 저장했고, 성공16건에서 미배정 숨김 사건17개를 추가했다. 최종 D05 23개·숨김 revision20개·16테이블206행을 실제 JAR116회·HTTP10회와 두 번째 빈 서버의 SQL 복원으로 대조했다. 기존47건 V4 상태·원본1398항목을 보존했으며 공개4테이블은0이다. 시험 서버는 정리했고 운영 DB가47건이라고 표시하지 않는다. [추출 확장](docs/ai-review-draft.md#개발용17건의-추출과-저장-확장)·[백업 범위](docs/backup-recovery.md#개발용17건을-추가한-db-복원-검증)를 따른다. 기존 V3 SQL의 동일 복구·전체 과거 자료의 동시 유실 복구·사람 승인/공개·독립 정답표/40문서 평가·배포는 미완료다.

이후 신규17건의 선택321파일/55디렉터리를 백업·canonical 부재에서 복원하고 실제39 CLI(거부6/전체 재실행33)·HTTP15회로206행/스키마·data SQL·공개0을 대조했다. 보관 원본과 복원본의 identity·전체 내용을 구별했고 검증 뒤 원본을 같은 경로로 돌려 기존2618항목을 보존했다. [선택 파일 복구](docs/backup-recovery.md#개발용17건의-선택-파일-유실-복구-검증)는 전용 DB의 제어된 검증이며 전체 과거 자료 동시 유실·운영 보존/접근·전원 중단 내구성·사람 승인/배포는 남아 있다.

동결한 사람 수정본은 [인계 명령](docs/human-handoff-import.md)으로 D06에 저장한다. 명시 revision·실제 DB 전후 값·전체 원본을 보존하고 수정/승인/공개 때 다시 대조한다. 비공개 미상과 실패 부모 연결을 실제 자료 승인으로 간주하지 않는다.

같은 D03 버전의 확인·사용권 갱신은 [local-source-review](docs/source-review.md)로 기록한다. V4 운영 이력·source_checks·부모 운영 번호/hash를 원자적으로 갱신하고 원본 D03 6열·D05·사람 인계는 보존한다. 승인·공개는 현재 운영 권한과 확인 상태를 사용하며 replay는 확인·등록 두 cutoff를 검사한다. Java/MySQL 전체328개와 실제 JAR41항목으로 초기0·정확한 재실행·권한만 변경하는 요청·충돌·원본 보존·공개 경합·SELECT 전용 미리보기를 합성 검증했다. 권한 전용 마지막 이력 유실 거부와 기존 V3 데이터의 V4 업그레이드도 확인했다. 전체 회귀·코드 리뷰·원격 검증 결과는 관련 PR 기록을 따른다. 실제3건은 pending/uncertain을 유지하며 실제 사람 검토·gold/40문서 평가·운영 배포는 미완료다.

담당: 강명묵 · 기술 결정: Spring Boot·MySQL · 첫 결과: **11/3(화) 오후6시(KST)** · 연구실 시연: **11/4(수), 시각미정**

B08의 환경·기동/정지·DB와 선택 원본 백업·새 빈 DB/같은 실제 경로 복원은 [인계 안내](docs/backup-recovery.md)를 따른다. 독립 Docker/MySQL·표준 tar 합성 시험의 실행 결과는 관련 PR 검증 기록으로 확인하며, 복원 DB에 기존 전체 DB 시험을 실행하지 않는다. 실제 운영 정책·백업 접근/보존·서버 경로·계정/grants·PITR·실자료 독립 평가/40문서/D09·main 병합/배포는 별도 후속 작업이다.

- Java21·Spring Boot3.5.x·Gradle Wrapper 프로젝트와 MySQL8.4 LTS 연결을 구성합니다. 실제 패치/Wrapper 버전을 고정합니다.
- GET `/api/v1/config`, POST `/api/v1/matches`, GET `/api/v1/events/{id}`를 공통 계약대로 구현합니다. 예제 응답으로 Flutter와 첫 연결을 진행합니다.
- [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)의 문서·추출·검토 revision·snapshot을 분리하고 Flyway 마이그레이션을 작성합니다.
- 김윤기가 전달한 검토 JSON을 로컬 import로 받습니다. 검증 실패·중복 import·revision 충돌을 처리하고 미검토 자료는 공개하지 않습니다.
- 시간·거리 계산은 [계산 CLI 계약](../contracts/calculation-bridge.md)으로 Python에 요청합니다. 서버가 선택한 불변 snapshot·좌표·현재시각과 사용자 조건을 전달하고 반환 형식을 검사합니다.
- 요청 검증422, 미등록404, 버전충돌409, DB/계산기 미준비503, 내부오류500을 공통 오류 형식으로 반환합니다.
- DB transaction·낙관적 잠금·공개 포인터 교체·rollback을 시험하고 계산 실패 시 이전 데이터가 보존되는지 확인합니다.
- 설치·실행·DB 준비·예제/실제 자료 여부·현재 계산 연결 상태·미완료를 README에 기록합니다.

오후6시에는 실행 가능한 서버와 API3개의 첫 버전, DB 준비 상태를 인계합니다. 아직 연결하지 않은 계산은 완료로 표시하지 않습니다. 준비된 부분부터 Flutter와 연결하며 상세한 기준은 [화면 시연 작업 기준](../docs/wednesday-screen-brief.md)을 따릅니다.
