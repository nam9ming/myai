# Python AI·계산 — 김윤기

확정 기술: **Python3.13**. AI 일괄 추출·원문 대조·검토본 JSON, C01~C10 시간/거리/관계 계산의 단일 원본과 CLI를 담당합니다. 공개 API·MySQL은 강명묵의 Spring Boot가 맡습니다. 현재 Python 실행 코드는 아직 없습니다.

1. [착수 가이드](../docs/spec/11_개발착수가이드.md), [담당 작업](TASK.md), [데이터·AI](../docs/spec/03_데이터와AI.md), [계산 규칙](../docs/spec/04_계산규칙과기술설계.md)를 확인합니다.
2. AI 원출력·사람 검토본·공개 자료를 분리하고 검토본은 Spring 로컬 import로 전달합니다. Python이 MySQL에 직접 쓰지 않습니다.
3. [계산 연결 계약](../contracts/calculation-bridge.md)에 맞춰 순수 계산 함수와 JSON stdin/stdout CLI를 작성합니다.
4. Python 가상환경·버전 고정 의존성·모듈 실행법·프롬프트/도구·실제 실행 결과와 미완료를 남깁니다.

Spring에서 사용할 목표 실행 형태는 저장소 루트 기준 `python -m processing.matching`입니다. 아직 모듈이 구현된 상태가 아닙니다. AI 추출은 별도 일괄 명령으로 실행하고 사용자 조회마다 AI를 호출하지 않습니다.
