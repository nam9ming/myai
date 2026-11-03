# OpenAI 추출 실행 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 개발용으로 기존 코드리뷰 키를 사용해 OpenAI 추출을 실행하고 시도별 원본·실패를 검증 가능한 D05 archive로 연결한다.

**Architecture:** 기존 prompt-v1·추출 검증·archive/freeze·Java 등록을 재사용한다. 부모 deadline으로 종료하는 표준 HTTPS 작업 프로세스가 고정 Responses API를 호출하며 각 요청, 수신 응답, 추출 텍스트, 전송 상태를 비공개 보관한다. archive 검증은 네트워크 없이 원본으로 결과·재시도 정책·metadata를 다시 계산한다.

**Tech Stack:** Python3.13 표준 라이브러리, Java21/Spring Boot, 기존 GitHub Actions/OpenAI Secret.

**Spec:** docs/spec/03_데이터와AI.md D05·AI 검증/재시도; docs/spec/07_결정사항과자체점검.md Q03; contracts/extraction-run.md; 사용자 지시: 개발 단계에서 기존 코드리뷰 API 키 재사용.

## Global Constraints

- 최대3시도. 전송/구조 오류만 재시도하며 의미/근거 오류·인증 오류는 중단한다.
- prompt-v1과 전체 원문 재전달, 구조 오류 피드백은 경로만. 평가 정답·사용자 조건·도구 실행 없음.
- 키는 OPENAI_API_KEY 환경변수만 사용한다. HTTPS 고정 주소·store=false, 새 의존성·DB migration·공개 API 변경 없음.
- API 응답은8MiB+1까지만 수신하고 초과/부분 응답은 불완전 상태를 명시한다. 요청별120초, 출력8192토큰. 절대 정확한 서버 실행시간/요금을 추정하지 않는다.
- 기존 수동 archive의 형식과 receipt 바이트는 유지한다. API archive는 execution_mode=api와 시도별 response/exchange 원본을 추가한다.
- 실제 모델/원문 품질 평가는 합성 연결 시험과 구분한다. main 병합은 사람, 하위 PR은 정확한 head CI·리뷰 통과 후 병합한다.

## Review Focus

- 인증/리다이렉트/로그 노출: 고정 host만 호출하고 키를 요청 body·archive·stdout에 넣지 않는 회귀.
- 중간 전송 실패/큰 응답: 부분 수신 상태와 원본 보존·유한 대기를 실제 loopback HTTP로 확인.
- 의미 오류/인증 오류 반복: 호출 수와 보관된 시도로 정책을 확인.
- 중단/동시/재실행: 같은 run_id를 중복 과금하지 않고 완료 재사용·미완료 차단.
- 이전 수동 archive·Java 등록/초안: 기존 회귀와 실제 Python→Java→전용 MySQL 연결 검증.

## Task 1: 검증 가능한 API 실행·CLI·Java 연결

**Files:** Create `processing/extraction/api.py`, `processing/extraction/transport.py`, `processing/tests/test_extraction_api.py`; modify `archive.py`, `metadata.py`, `__main__.py`, Java `ExtractionArchiveReader.java`와 관련 시험.

**Interfaces:** `run_api(input_path, preprocessing_version, root=DEFAULT_ROOT, run_id=None, model=None) -> receipt`; `request_bytes(document, model, error_path=None) -> bytes`; `check_api_attempt(request, response, exchange, document, model, error_path=None) -> (output_bytes, result, usage)`.

내부 `python -m processing.extraction.transport`는 stdin 요청과 환경변수 키를 읽고 stdout에 HTTP 상태 한 줄·수신 본문만 쓴다. 종료0=완전 수신,2=timeout,3=전송 실패,4=본문 한도 초과다. 부모가 DNS·헤더·chunk 수신 전체를 제한하고 종료 정리에 최대1초가 추가될 수 있다.

- [ ] API 성공→시도 원본/사용량/시간 보관·verify/freeze, 구조 재시도3회·근거 오류 중단·전송/인증/부분 응답·변조·동시/중단/재사용 시험을 먼저 작성한다.
- [ ] `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_extraction_api -v`에서 미구현 실패를 확인한다.
- [ ] 기존 검증/기록을 재사용해 구현한다. CLI `run --input FILE --preprocessing-version VERSION [--run-id UUID] [--model MODEL] [--root ROOT]`를 추가한다.
- [ ] Java가 api receipt와 추가 artifact를 검증하도록 연결하고 실제 API 형식 archive의 등록/실패/변조 회귀를 추가한다.
- [ ] 전체 Python·전용 MySQL 포함 Java·JAR 시험을 실행한다. 커밋 제목·본문은 영어 Conventional Commits다.

## Task 2: 개발용 실제 연결 시험·인계·리뷰

**Files:** Create `.github/workflows/extraction-smoke.yml`, `processing/examples/ai-smoke-input.json`; modify processing README/TASK·추출 계약·backend 인계 문서.

**Interfaces:** `run-openai-extraction` 라벨 이벤트와 같은 저장소 PR만 합성 원문을 기존 Secret/리뷰 모델로 실행한다. raw는 짧은 보존기간 artifact로 보관하고 성공/실패·사용량을 구분한다.

- [ ] 로컬 HTTP 시험으로 실제 요청/응답·헤더/본문·deadline과 원본 보관을 확인하고 기존 전체 회귀를 실행한다.
- [ ] 실제 OpenAI 합성 연결은 self-review 후 라벨을 한 번 적용해 실행한다. 일반 PR push는 유료 추출을 자동 실행하지 않는다.
- [ ] 합성 처리와 실제3건/40건/평가의 미완료를 한국어 문서에 명시한다.
- [ ] 전체 변경을 별도 리뷰1회와 자체 리뷰로 확인한다. 유효 지적은 재현→수정→전체 회귀 후 PR 제출/갱신한다.
- [ ] 정확한 head의 CI·AI 리뷰·실제 연결 결과를 확인한 후 하위 PR만 영어 제목·본문으로 병합한다. 통합 tree·최종 CI·main 미변경을 확인하고 소유 시험 자원만 정리한다.
