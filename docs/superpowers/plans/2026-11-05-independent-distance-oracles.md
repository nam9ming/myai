# Independent Distance Oracles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** T09의 독립 고정 좌표·거리 수치 회귀 증거를 보강한다.

**Architecture:** 기존 GeometryTest에 점·선분 시험2개를 추가한다. 기대값은 별도 계산한 literal이며 제품 코드는 그대로 사용한다.

**Tech Stack:** Python3.13·unittest·표준 라이브러리, 기존 Node 검증·Java/MySQL CI.

**Spec:** [설계](../specs/2026-11-05-independent-distance-oracles-design.md), [T09](../../spec/05_시험과인수기준.md), [C05](../../spec/04_계산규칙과기술설계.md).

## Global Constraints

- 구면 반경6,371,008.8m·좌표 경도/위도 순서·오차0.01m 이내. 오차를500m 검색 반경에 추가하지 않는다.
- 기대값 실행 중 생성·제품 상수/함수 재사용·새 의존성·실제 키/원문/gold 접근 없음.
- 기존 모든 시험·제품 동작·공개 계약 유지. 합성 회귀와 실제 인수를 구별한다.
- 영어 Conventional commit, 한국어 문서/PR. main 병합·배포는 사람이 결정한다.

## Review Focus

1. 자오선에만 맞는 잘못된 축/모형: 고정 사선 좌표를 함께 검사한다.
2. 수치 오차를 검색 반경으로 오인:499.9/500.1 포함·제외와 기존 정확500 주입을 유지한다.
3. 선분을 양 끝점으로만 계산: 비영 내부 거리의 독립 값을 확인한다.
4. 무한 대권을 유한 구간으로 오인: 끝점 밖의 고정 좌표를 확인한다.
5. 자기참조 기대값·허술한 검증: 별도 계산 근거·반경/끝점-only 음성 대조·제품 hash 불변을 확인한다.

### Task 1: 독립 기준값·회귀·종료 기록

**Files:** Modify `processing/tests/test_geometry.py`, `processing/README.md`, `backend/README.md`, `docs/superpowers/plans/2026-11-05-extraction-result-upload.md`. Create this plan and linked design.

**Interfaces:** 기존 `haversine(p,q)`, `segment_distance(point,start,end)`, `locate(point,location)`를 소비한다. `GeometryTest.test_independent_point_oracles`와 `test_independent_segment_oracles`를 제공하며 새 제품 API는 없다.

- [x] 설계의7행을 고정 literal로 사용해 두 시험을 추가한다. 점은 거리 오차≤0.01m·locate 포함 여부·basis, 선분은 직접 거리 오차≤0.01m를 검사한다. 기존10개 시험은 유지한다.
- [x] private 별도 실행에서 제품 반경6300000과 끝점-only 선분 대체를 각각 주입한다. 신규 해당 시험이 assertion으로 실패해야 하며 제품 파일은 수정하지 않는다. 원본 구현으로 되돌리면 신규2개가 통과해야 한다. 시험 추가만으로서 기존 제품의 RED 결함을 주장하지 않는다.
- [x] `/opt/homebrew/bin/python3.13 -m unittest processing.tests.test_geometry -v`:12개·실패/오류/skip0. 원본 제품/전체 Python code fingerprint와 별도 계산 원본을 보존한다.
- [x] 이전 PR47의 병합·통합·563항목 동결·판단26건 인계/자기 scratch 정리 결과를 해당 계획에 기록하고 Backend의 낡은 업로드 검증 후속 문구를 갱신한다. Python README에는 신규 시험 근거만 연결한다.
- [x] `/opt/homebrew/bin/python3.13 -m unittest discover -s processing/tests -v`, Node24의 `npm run lint`, `npm test`, `npm run build`, `python3.13 contracts/validate_examples.py`: 전체 Python632개·Node34·계약9·린트/정적 build 종료0 예상. 실제 count/exit·skip·source hash를 대조한다. Java는 변경 없으며 정확 head 원격 CI의 전체790개를 확인한다.
- [x] Commit: `test: add independent distance oracles`.

## 최종 게이트

- [x] 관련 호출부·fixture·계약·문서·계산/오류 영향의 전체 자체 검토, 모든 유효 지적 수정·재검증.
- [ ] 새 문맥 전체 브랜치 리뷰1회, 유효 minor 포함 수정·회귀. 추가 독립 재리뷰 없음.
- [ ] PR→정확 head CI/AI 원문·새 사람 피드백→유효 미해결0→비main 병합·통합 검증·판단 인계·비공개 증거 보존. main은 사람이 병합한다.

## 실행·자체 검토

기하12개·신규2개와 전체 Python632개/330.531초가 실패/오류/skip0이다. 반경6300000 음성 대조는3 assertion, 끝점-only 대체는2 assertion으로 실패했고 원래 구현을 복원하면 신규2개가 통과했다. 이는 시험 검출력 확인이며 기존 제품 결함의 재현이 아니다. 제품 Python42개와 전체 시험 중84개 소스 hash가 유지됐다. Node24.21.0의34개·계약9·린트418파일·정적 HTML build도 종료0이다. 정적 HTML을 Flutter 빌드로 집계하지 않는다.

별도 계산 원본과 수치·단위·문서 링크·기존10개 기하 시험·관련 계산/CLI/오류 경계를 자체 검토했고 유효 미해결/보류 minor0이다. Java 제품은 변경하지 않았으며 정확 head 원격 CI에서790개 전체와 빌드·산출물을 확인한다. 독립 리뷰·원격 CI/AI·비main 병합/통합은 최종 게이트에 남아 있다.
