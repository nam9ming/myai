# 대형 PR 자동 리뷰 diff 복구 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 현재 checkout에서 구현하고 새 전체 검토자 한 명으로 검증한다.

**Goal:** 통합 PR20의 304파일 diff가 GitHub API의300파일 한도로 실패하는 문제를 고친다.

**Architecture:** 기본 브랜치의 신뢰된 리뷰 스크립트는 유지한다. 전체 Git 이력을 가져와 이벤트의 base/head SHA를 merge-base 기준으로 비교하고, 외부 diff/textconv 실행을 차단한다. API 키·모델·앞60000자 제한·기존 시크릿 정책은 바꾸지 않는다.

**Tech Stack:** 기존 Git·Bash·GitHub Actions·Node20 내장 시험. 새 의존성 없음.

**Spec:** 사용자 요청의 OpenAI PR 리뷰·정확한 커밋 검증, `docs/development-infra.md:60`, [실패41778238074](https://github.com/nam9ming/myai/actions/runs/41778238074).

## Global Constraints

- 앱 Java/Python·API·DB·실자료·키 파일·운영 서버는 변경하거나 사용하지 않는다. main 병합은 사람 담당이다.
- 기본 브랜치 checkout·persist-credentials=false·동일 저장소 PR 조건·기존 Secret 전달 정책을 유지한다. PR head 코드를 checkout/실행하지 않는다.
- 사용자 .gitignore와 AGENTS·기존 증거 보존. 영어 Conventional Commits50자 이내, 문서/PR 한국어.

## Review Focus

1. 300파일 초과에서도 전체 diff를 얻고 부분 AI 검토 한도는 유지한다.
2. base가 갈라지거나 head 브랜치가 전진해도 이벤트 SHA의 PR 변경만 비교한다.
3. diff 드라이버·textconv 또는 PR head 코드가 실행되지 않는다.
4. 이력이 없거나 Git 비교가 실패하면 빈 성공 리뷰를 만들지 않고 실패한다.
5. main의 기존 리뷰 스크립트로 실행 가능하며 새 스크립트의 main 반영을 요구하지 않는다.

### Task 1: 수집 단계·회귀 시험·인계

**Files:** `.github/workflows/ai-review.yml`, 신규 `test/ai-review-diff.test.mjs`, `docs/development-infra.md`.

**Interfaces:** workflow의 diff 단계 Bash를 시험에서 그대로 실행하되 `/tmp/pr.diff` 출력 경로만 소유 임시 경로로 치환한다. `BASE_SHA`, `HEAD_SHA`는 PR 이벤트의 불변 SHA다.

- [ ] 네트워크 없는 실제 Git 임시 저장소에서301파일·갈라진 base/전진한 head·외부 도구 미실행·없는 commit 실패 시험을 먼저 작성한다. `gh`는 관찰된 HTTP406 실패로 stub한다.
- [ ] `node --test test/ai-review-diff.test.mjs` RED 확인 후 fetch-depth0·Git3점 diff·외부 도구 차단을 연결하고 GREEN을 확인한다.
- [ ] `npm run lint`, `npm test`, `npm run build`와 현재 통합304파일의 로컬 diff를 검증한다. 앱 소스 미변경이므로 직전 Java404 결과와 새 원격 CI를 구분한다.
- [ ] 자체 전체 검토→새 전체 검토1회→유효 지적 전부 수정→PR/정확 head CI·AI·사람 피드백0→승인된 develop 병합·통합 PR20 자동 리뷰 복구를 검증한다.

**Expected:** GitHub diff API 호출 없이 전체 Git 변경을 수집하고 실패·빈 리뷰를 성공으로 숨기지 않는다. 앱 범위나 실제 인수 기준은 줄이지 않는다.
