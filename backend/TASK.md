# 백엔드·DB 작업

구현한 기능과 실행 명령, 미완료 범위는 [README](README.md)에 기록합니다. 합성 API·초기 스키마·비공개 검토본 import와 로컬 승인·미리보기·공개·복구·snapshot JSON 내보내기를 구현했습니다. 공개 API는 DB snapshot을 조회하며 matches를 실제 Python 계산에 연결했습니다. [import 규격](docs/reviewed-import.md)·[승인·공개·내보내기 안내](docs/review-publication.md)·[공개 조회 안내](docs/public-snapshot-api.md)와 README의 Python 설정을 따릅니다.

D03 선등록·D05 archive 검증/등록·D06 실행 참조는 [연결 안내](docs/extraction-run-import.md)를 따른다. Python OpenAI 개발용 실행의 api archive도 같은 경로로 등록하며 Java가 직접 AI를 호출하지 않는다. D06 숨김 초안과 검토 승격은 [초안 안내](docs/ai-review-draft.md)를 따른다. 실자료 추출·평가·배포는 후속 작업이다.

담당: 강명묵 · 기술 결정: Spring Boot·MySQL · 첫 결과: **11/3(화) 오후6시(KST)** · 연구실 시연: **11/4(수), 시각미정**

- Java21·Spring Boot3.5.x·Gradle Wrapper 프로젝트와 MySQL8.4 LTS 연결을 구성합니다. 실제 패치/Wrapper 버전을 고정합니다.
- GET `/api/v1/config`, POST `/api/v1/matches`, GET `/api/v1/events/{id}`를 공통 계약대로 구현합니다. 예제 응답으로 Flutter와 첫 연결을 진행합니다.
- [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)의 문서·추출·검토 revision·snapshot을 분리하고 Flyway 마이그레이션을 작성합니다.
- 김윤기가 전달한 검토 JSON을 로컬 import로 받습니다. 검증 실패·중복 import·revision 충돌을 처리하고 미검토 자료는 공개하지 않습니다.
- 시간·거리 계산은 [계산 CLI 계약](../contracts/calculation-bridge.md)으로 Python에 요청합니다. 서버가 선택한 불변 snapshot·좌표·현재시각과 사용자 조건을 전달하고 반환 형식을 검사합니다.
- 요청 검증422, 미등록404, 버전충돌409, DB/계산기 미준비503, 내부오류500을 공통 오류 형식으로 반환합니다.
- DB transaction·낙관적 잠금·공개 포인터 교체·rollback을 시험하고 계산 실패 시 이전 데이터가 보존되는지 확인합니다.
- 설치·실행·DB 준비·예제/실제 자료 여부·현재 계산 연결 상태·미완료를 README에 기록합니다.

오후6시에는 실행 가능한 서버와 API3개의 첫 버전, DB 준비 상태를 인계합니다. 아직 연결하지 않은 계산은 완료로 표시하지 않습니다. 준비된 부분부터 Flutter와 연결하며 상세한 기준은 [화면 시연 작업 기준](../docs/wednesday-screen-brief.md)을 따릅니다.
