# 백엔드·DB — 강명묵

확정 기술: **Java21 / Spring Boot3.5.x / Gradle Wrapper / MySQL8.4 LTS**. 공개 API와 DB 저장 책임을 맡습니다. 현재는 명세·작업 안내이며 앱 코드·DB·마이그레이션을 구현하지 않았습니다.

1. [착수 가이드](../docs/spec/11_개발착수가이드.md), [작업 범위](TASK.md), [기술 구성](../docs/spec/08_기술구성과연결.md), [DB 설계](../docs/spec/09_DB설계와트랜잭션.md)를 읽습니다.
2. contracts의 예제로 공개 API3개를 만들고 Flutter와 먼저 연결합니다.
3. MySQL·검토 JSON import·snapshot과 Python 계산 CLI를 연결합니다. 계산을 Java로 다시 구현하지 않습니다.
4. Gradle Wrapper·실제 Boot 패치 버전·의존성·DB 마이그레이션·실행 명령을 저장소에 기록합니다.

목표 명령은 Windows `gradlew.bat bootRun`, Linux `./gradlew bootRun`입니다. 아직 프로젝트를 생성하지 않았으므로 현재 실행되는 명령은 아닙니다. DB·Python 경로 환경변수 이름과 실제 실행법은 구현 후 추가합니다. 운영 연구실 서비스는 수정하지 않습니다.
