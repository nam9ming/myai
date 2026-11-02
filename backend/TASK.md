# 백엔드·DB 작업

현재 기초 구현·실행 명령·미완료 범위는 [README](README.md)에 기록합니다. 아래 전체 작업 중 합성 API·초기 스키마부터 구현하며, 실제 import·공개·Python 연결 완료를 뜻하지 않습니다.

담당: 강명묵 · 기술 결정: Spring Boot·MySQL · 첫 결과: **11/3(화) 오후6시(KST)** · 연구실 시연: **11/4(수), 시각미정**

- Java21·Spring Boot3.5.x·Gradle Wrapper 프로젝트와 MySQL8.4 LTS 연결을 구성합니다. 실제 패치/Wrapper 버전을 고정합니다.
- GET `/api/v1/config`, POST `/api/v1/matches`, GET `/api/v1/events/{id}`를 공통 계약대로 구현합니다. 예제 응답으로 Flutter와 첫 연결을 진행합니다.
- [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)의 문서·추출·검토 revision·snapshot을 분리하고 Flyway 마이그레이션을 작성합니다.
- 김윤기가 전달한 검토 JSON을 로컬 import로 받습니다. 검증 실패·중복 import·revision 충돌을 처리하고 미검토 자료는 공개하지 않습니다.
- 시간·거리 계산은 [계산 CLI 계약](../contracts/calculation-bridge.md)으로 Python에 요청합니다. 서버가 선택한 불변 snapshot·좌표·현재시각과 사용자 조건을 전달하고 반환 형식을 검사합니다.
- 요청 검증422, 미등록404, 버전충돌409, DB/계산기 미준비503, 내부오류500을 공통 오류 형식으로 반환합니다.
- DB transaction·낙관적 잠금·공개 포인터 교체·rollback과 계산 실패에서 이전 데이터 보존을 확인합니다.
- 설치·실행·DB 준비·예제/실제 자료 여부·현재 계산 연결 상태·미완료를 README에 기록합니다.

오후6시에는 서버와 API3개의 실행 가능한 첫 버전 및 DB 준비 상태를 인계합니다. 미연결 계산을 완료로 표시하지 않습니다. 준비된 부분부터 Flutter와 연결합니다. 상세는 [화면 시연 작업 기준](../docs/wednesday-screen-brief.md)입니다.
