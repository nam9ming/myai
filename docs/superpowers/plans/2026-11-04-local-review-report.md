# 로컬 검토 보고서 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 사용자가 에이전트 병렬 구현을 요청했으므로 파일 소유권을 나누고, 마지막 전체 브랜치 리뷰는 새 검토자 한 명에게 맡긴다.

**Goal:** S10의 원문·AI 원출력·수정값 비교, 검증 오류, 승인 기록, 공개 미리보기를 비공개 로컬 보고서로 제공한다.

**Architecture:** 기존 파일 import·승인 명령은 유지한다. 문서 버전 하나로 관련 저장 이력을 SELECT하고 기존 검증기를 재사용한다. 별도 비웹 `local-review-report` 명령이 독립 HTML 파일을 저장하고 stdout에는 ID·파일명·checksum만 반환한다. HTML은 모든 값을 텍스트로 표시하며 외부 자원을 요청하지 않는다.

**Tech Stack:** Java21·Spring Boot3.5·MySQL8.4·Python3.13, 기존 의존성만 사용.

**Spec:** `docs/spec/02_화면과모바일UX.md` S10, `docs/spec/06_개발실행계획.md` 관리 파일 대안, `backend/TASK.md`, `processing/TASK.md`.

## Global Constraints

- 공개 API·공통 사실 계약·계산 규칙·DB schema·프런트엔드 변경 없음. 공개 관리 HTTP 경로를 만들지 않는다.
- 실패 D05·모든 시도·미상/null·원문 이용 검토 미확정·사람 수정 이유를 그대로 보존한다. 기계 검증을 사람 승인으로 표시하지 않는다.
- 보고서는 DB·원본 파일에 쓰지 않는다. Flyway·웹·다른 실행 프로필은 기동 전에 차단한다.
- 출력은 원문 기준 루트의 Git 제외 `data/private/` 또는 `evaluation/private/` 아래 0700 디렉터리와 0600 파일만 허용한다. 기존 파일·링크는 덮어쓰지 않는다.
- 전체 HTML 최대64MiB. 크기 초과는 명시 오류이며 일부 값을 조용히 자르지 않는다. 비UTF8 원출력은 원본 base64·크기·SHA를 표시한다.
- 실제 자료·키·gold·D09는 이번 구현 시험에 사용하지 않는다. 합성 시험으로 사람 검토·운영·실자료 인수 완료를 주장하지 않는다.
- 영어 Conventional Commit 제목50자 이내. 문서·PR 한국어. 사용자 `.gitignore` 및 기존 AGENTS·동결 증거 보존. main 병합·배포는 사람 담당.

## Review Focus

1. 현재 revision에서 출처가 제거된 사건도 과거 연결을 통해 전체 수정 이력에 포함한다.
2. 실패·비UTF8·빈 output·불완전 API response를 정상 JSON으로 수리하거나 숨기지 않는다.
3. 원문·AI·검토 문자열의 HTML/URL/스크립트 주입과 private 출력 링크·권한·덮어쓰기를 차단한다.
4. preview 요청을 approve/publish로 바꿔도 DB·원본 변경 전에 거부한다. preview의 간접 freeze도 제거한다.
5. 선택 사건이 빠진 새 snapshot으로의 전환과 rollback을 before/after 양쪽에서 보여 준다. capture와 별도 검증·preview 시점을 혼동하지 않는다.

### Task 1: 봉인 원본의 읽기 전용 검증

**Files:** `processing/extraction/{archive.py,__main__.py}`, `processing/tests/test_extraction_freeze.py`, `backend/.../extraction/ExtractionArchiveReader.java`, `backend/.../service/{ExtractionImportService,PublicationService}.java`, 관련 Java 시험.

**Interfaces:** `verify_sealed_run(run_id, root)`은 기존 registration envelope를 반환한다. `ExtractionArchiveReader.readSealed(String,Path)`는 `VerifiedExtraction`을 반환한다. preview 참조 검증은 이 경로만 사용한다. 기존 등록의 freeze 동작은 유지한다.

- [ ] 합성 sealed 성공/실패·mutable·손상·누락·파일 bytes/mode 불변 시험부터 추가한다. 새 메서드/명령 부재 RED를 확인한다.
- [ ] 기존 verify·봉인 검사·프로토콜 parser를 재사용해 구현한다. Python 집중 시험과 Java 컴파일/집중 시험 GREEN을 확인한다.
- [ ] 부모가 변경 범위·RED/GREEN 근거를 기록하고 명시 파일만 커밋한다.

### Task 2: 저장 이력·비교·오류 수집

**Files:** 신규 `backend/.../review/ReviewReportService.java`, `backend/.../repository/ReviewReportRepository.java`, `backend/src/test/.../ReviewReportMySqlTest.java`.

**Interfaces:** `ReviewReportService.build(UUID documentVersionId, Path sourceRoot, Path previewRequest)` → `ObjectNode`. 최상위 키는 `format_version`, `document_version_id`, `capture`, `documents`, `extractions`, `events`, `review_audits`, `publication`, `preview`. 각 검증 결과는 `status/code/field`를 보존한다. JSON은 private 보고서 내부값이며 공개 API 계약이 아니다.

- [ ] 합성 D03만/실패 D05/복수 시도/사람 수정·승인·반려/과거 출처 제거/다른 출처 추가/공개 후 제외·rollback을 구성하고 누락·쓰기·오류 은폐를 검출하는 시험부터 RED 확인한다.
- [ ] SELECT 전용 bounded capture 후 기존 hash·source·stored·handoff·sealed 검증기를 재사용한다. 파일 검증과 preview는 capture와 별도 검사 시점을 명시한다. legacy/부재/무효 항목도 DB 행과 오류를 남긴다.
- [ ] preview 미지정은 미실행으로 표시한다. 지정하면 정확한 preview 타입/action과 선택 사건 관련성을 확인하고 기존 공개 게이트로 실행한다. 실패는 보고서에 기록한다. 성공은 실제 공개가 아님을 표시한다.
- [ ] 부모가 전용 합성 MySQL에서 집중 시험을 실행하고 전체 DB/파일 전후 보존을 대조한다. 작업자는 DB/Docker/Gradle을 별도 실행하지 않는다.

### Task 3: private HTML·CLI·문서·전체 검증

**Files:** 신규 `backend/.../review/{ReviewReportWriter,LocalReviewReportCommand}.java`, `backend/.../config/LocalReviewReportStartupGuard.java`, 관련 시험, `application-local-review-report.yml`, `META-INF/spring.factories`, `MyaiBackendApplication.java`, README/TASK·안내 문서.

**Interfaces:** writer는 Task2 JSON을 원문/AI/사람값 3열 및 전체 이력·오류·preview로 텍스트 출력한다. 파일 선택·수정·승인·공개는 기존 문서화된 명령으로 수행한다. 파일 저장 후 receipt에 보고서 버전/문서ID/파일명/SHA만 출력한다.

- [ ] 스크립트/HTML/unsafe URL·null·비UTF8·크기·0700/0600·symlink·기존 파일·외부 출력·mixed/web/Flyway/알 수 없는 인자·실패 stdout 시험부터 RED 확인한다.
- [ ] 표준 Java/Jackson과 기존 temp→hardlink no-clobber 패턴으로 구현한다. 320px·키보드·확대에서 전체 정보에 도달하는 정적 문서 구조와 CSP를 적용한다.
- [ ] 문서에 실행 명령, private 출력, capture/검증/preview 시점, 실패 의미, 미완료 인수 범위를 기록한다.
- [ ] 부모가 Java/MySQL·Python 전체 시험, 계약 JSON·lint·Node·build를 실행한다. 이후 자체 전체 리뷰→새 전체 리뷰 한 번→유효 지적 모두 수정/재검증→PR→정확 head의 CI/AI·사람 피드백 확인→develop 병합→통합 검증을 수행한다.

**Expected:** 시험 실패·건너뛰기0, 원본·DB 보존, 공개 변경0. 실자료/실기기/운영 인수·main/배포는 미완료로 남긴다.
