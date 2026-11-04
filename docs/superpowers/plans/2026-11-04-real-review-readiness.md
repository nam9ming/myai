# 실자료 검토 인계·장문 조건 진단 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 독립 조사/측정은 병렬로 맡기고 부모만 DB·JAR·Git을 실행한다. 마지막 전체 검토는 새 검토자 한 명에게 맡긴다.

**Goal:** 기존 실제 자료를 바꾸지 않고, 처리한 개발 문서의 S10 비공개 검토 보고서와 전체 입력 길이·모델 한도 근거를 준비한다.

**Architecture:** 검증한 기존 SQL을 새 소유 MySQL에 복원하고 SELECT 전용 계정으로 기존 `local-review-report`를 실행한다. 등록 루트가 다른 상대 원문은 SHA를 대조한 새 private source-view 사본으로 모으며, 원본과 사본의 identity를 구분한다. 실제 입력은 기존 parser·v2 prompt·request 생성 순수 함수로만 측정한다. 원문·AI·사람/공개 상태를 바꾸거나 새 모델 호출을 하지 않는다.

**Tech Stack:** 기존 Java21·Spring Boot3.5·MySQL8.4.13·Python3.13·stdlib. 새 라이브러리 없음.

**Spec:** `backend/docs/review-report.md`, `backend/TASK.md`, `processing/TASK.md`, `docs/spec/03_데이터와AI.md:194`, `docs/spec/04_계산규칙과기술설계.md:153`.

## Global Constraints

- 이전 백업의47 D03·23 D05·숨김 revision20개/206행을 기준으로 실제 복원 상태를 대조한다. 운영 DB가 아니다.
- 새 컨테이너·임시 credential만 생성/정리하며 다른 Docker 자원·기존 파일·동결 pack은 보존한다. 복원 DB에 전체 DB 시험을 실행하지 않는다.
- 실제 원문·보고서·진단 상세는 Git 제외 private 경로에만 둔다. 공개 PR에는 aggregate 결과/방법/미완료만 적는다. 키·gold/D09·사용자 평가 기록은 읽지 않는다.
- 추출/토큰계산 API는 호출하지 않는다. 기존 GitHub PR 코드리뷰 자동화는 별도이며 등록 Secret을 사용한다.
- 미검토·사용권 pending·미확정 구역/5지점·실패 원출력·숨김 상태를 보존한다. 사람 검토/승인·독립 평가·공개를 생성하거나 완료로 표시하지 않는다.
- 8MiB JSON과 제안200,000문자·제공자 token 한도를 구분한다. 문자/바이트를 token으로 추측하지 않으며 G02 전체 분할 구현을 이 진단으로 대체하지 않는다.
- 사용자 .gitignore·AGENTS·main 보존. 영어 Conventional Commit50자 이내, 문서/PR 한국어.

## Review Focus

1. 실행 횟수와 고유 문서 수, 실패와 archive 무결성, 기계 검증과 사람 검토를 구별한다.
2. 보고서 생성 뒤 전체 DB 행/스키마·원본 hash/mode·공개0이 그대로이고 SELECT 계정의 권한 범위를 확인한다.
3. 47문서의 입력 ID/hash·D03 전체 blocks 관계를 대조하며 사본/중복 실행을 추가 문서로 세지 않는다.
4. 길이 측정은 v2 실제 framing을 사용하고 개인정보·본문·키·미확인 token 값을 출력/전송하지 않는다.
5. 검토 index/HTML은 private로만 열고 외부 자원·실행 문자열·잘림/누락 없이 실패·미상을 보존한다.

### Task 1: 입력 길이·공식 한도 근거

**Files:** private 측정 코드/결과, 필요한 public 진단 방법·미완료 설명.
**Interfaces:** 부모가 D03와 대조한 입력 경로·ID·hash 목록을 제공한다. 측정자는 `parse_input`, `render_prompt(..., API_PROMPT_VERSION)`, `request_bytes`만 사용하고 DB/키/API를 호출하지 않는다.

- [x] 공식 모델 한도와 실제 모델/프롬프트 버전·계정별 미확인을 구분한다.
- [x] 합성 self-check 후 실제47입력의 bytes·blocks·code points·v2 prompt/request bytes·기존 usage를 측정한다. 원본 전후 hash/mode를 대조한다.

### Task 2: 실제 S10 검토 묶음·읽기 전용 검증

**Files:** private 부모 실행 코드/보고서/index/검증, backend/processing 안내의 aggregate 결과.
**Interfaces:** 기존 RecoveryDatabase 소유 가드·검증된 SQL·현재 JAR의 `local-review-report`를 사용한다. 새 DB와 출력만 생성하고 preview/승인/공개는 요청하지 않는다.

- [x] 백업·선택 metadata hash 검증→새 빈 소유 DB 복원→47/23/20·206행·공개0 대조·SELECT 계정 준비.
- [x] 고유 처리 문서20건의 모든 시도/실패를 포함한 private HTML과 인계 index를 만든다. 보고서 항목 검증과 stdout 성공을 구별한다.
- [x] 생성 전후 DB/스키마·기존 원본을 대조하고 HTML 링크/표시·외부 자원 부재를 검사한 뒤 소유 자원/credential을 정리한다.
- [ ] 전체 자체 검토→새 전체 검토1회→유효 지적 수정→aggregate 문서 PR·정확 head CI/AI/사람 피드백→승인된 develop 병합·통합 검증·인계 증거 동결.

**Expected:** 실제 검토 가능한 파일과 재현 가능한 진단 근거를 제공한다. 사람 승인·정답/90%·40문서·D09·실기기·운영/main 배포 게이트는 남겨 둔다.
