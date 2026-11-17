# 여기:it Flutter Web 개발 계획

작성일: 2026-11-17 KST. 기준 브랜치: `develop`, 확인 커밋: `339e04f6d2bfac386fbc973fbe3e3b5b0aa02677`.

공유 기준 갱신: 윤기의 문서 변경을 검토하고 최신 `develop` `6145aac75da2fa071cca72d91c5b113f1b48921d`를 반영했다. 실행 코드와 계약 예제는 동일하다. 이후 주요 변경은 [Git 공유 규칙](GIT_WORKFLOW.md)에 따라 검증·커밋·작업 브랜치 공유를 수행한다.

기존 시민용 시제품을 Flutter Web으로 옮긴다. 온보딩부터 설정까지 예시 16건으로 먼저 연결하고, 기존 Spring 공개 API는 별도 어댑터로 검증한다. 2026-11-17에 제품 앱·전체 예시 화면·Spring 어댑터를 구현했다. 자동 검증과 실제 fixture HTTP는 통과했으며 브라우저 수동 인수와 실제 시민 API 확장은 남아 있다. 최신 결과는 [VERIFICATION](VERIFICATION.md)을 따른다.

## 기준과 현재 상태

- 이번 요청과 루트 `CODEX_TASK.md`를 최신 범위로 적용한다. 과거 `frontend/TASK.md`의 가게 조건 필수 진입, 새 디자인 제안, 지난 담당·일정은 이번 구현에 적용하지 않는다.
- 시각 기준은 인계 원본과 [배포 시제품](https://yeogi-it-neighborhood.kmnam001.chatgpt.site/#/start)이다. Figma는 보조 자료다.
- `AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`, 프론트 안내 문서, `contracts/README.md`, 화면·계산·시험·기술구성·착수 명세와 백엔드 공개 조회 안내를 확인했다.
- `develop/frontend/`에는 README와 TASK만 있다. 재사용할 Flutter 앱·라우터·의존성은 아직 없다.
- 작업·공유 브랜치는 `frontend/yeogi-it-flutter`다. 사용자 지시에 따라 검증한 변경을 이 브랜치에 공유하며 develop/main 병합·배포는 별도 검토한다.
- 루트 `yeogi-it-flutter-handoff.zip`의 원본을 `.local/handoff/yeogi-it-flutter-handoff/`에 풀고 manifest의 34개 파일 크기·SHA-256을 모두 검증했다. 시제품 기준 커밋은 `4c5edf0a10751d2463400e62a2538e2101ab23df`, 백엔드 기준 커밋은 현재 `develop`과 같다. 백엔드 연결 문서와 검수 목록도 확인했다.
- ZIP의 CODEX_TASK는 담당자가 이상헌으로 표기되어 있다. 루트 문서와의 내용 차이는 이 한 곳이며, 루트의 최신 담당자 남규민을 적용하고 원본 파일은 보존했다.
- 원본 예시 16건, 시·도 17개, 전체 포함 탭 6개, 기준일 `2026-11-16`을 확인했다. 배포 사본 `.local/reference-deployed/`와 비교하면 JS·CSS·SVG는 byte가 같고 index.html만 배포 스크립트 주입으로 다르다. 구현에는 ZIP 원본을 사용한다.

## 구현 단계와 완료 기준

| 단계 | 작업 | 다음 단계로 넘어갈 기준 |
|---|---|---|
| 0 준비 | 저장소·브랜치·SDK·편집기·기존 검증 확인 | [로컬 개발환경](LOCAL_ENVIRONMENT.md)의 결과와 남은 제약 확인 |
| 1 기반 | Flutter Web 프로젝트, 디자인 토큰, 공통 위젯, 모델, 16건 fixture, hash 라우터, 저장소 | 직접 URL 진입·쿼리 검증·저장 실패 복구가 동작하고 원본 ID·날짜·자산 보존 |
| 2 첫 사용자 흐름 | 온보딩 6단계 → 홈 → 목록 → 상세 → 저장 | 데스크톱·모바일에서 처음 방문부터 저장·뒤로 복원까지 연결 |
| 3 전체 시민 화면 | 검색·필터 모달·관심정보·설정·지역 준비 안내·모션 | 모든 경로 연결, draft 취소와 재방문 복원, 권한 거부·빈 결과 처리 |
| 4 API 연결 | DTO 매핑, 계약 fixture, 기존 공개 API HTTP, 지원 범위 표시 | 성공·404·409·422·503·500을 구분하고 snapshot·근거·미상 값 보존 |
| 5 검수와 인계 | 화면 비교, 키보드·확대·모션 감소, 빌드·README·캡처 | 실행 결과와 미지원 목록, `build/web/` 전체 인계 위치 기록 |

1단계부터 화면 구현과 DTO 계약 검증을 진행할 수 있다. 시민용 API 확장을 기다리며 예시 모드의 화면 구현을 중단하지 않는다. API가 실패했을 때 예시 모드로 자동 전환하지 않는다.

## 프로젝트 구성과 기술 선택

```text
frontend/
  lib/
    app/                       진입·설정·hash 라우팅·테마
    core/                      공통 위젯·clock·오류·로컬 저장
    features/
      onboarding/
      home/
      notices/                 목록·검색·필터·상세
      saved/
      settings/
    data/                      repository·API DTO·화면 모델 매핑
  assets/
    prototype/                 예시 16건과 지역 선택지
    posters/                   원본 SVG
  test/                        필터·매핑·상태·라우팅 검증
```

시작은 Flutter SDK의 `ChangeNotifier`·`ValueNotifier`와 `Router` API를 기준으로 한다. UI는 HTTP·JSON 필드를 직접 읽지 않고 `NoticeRepository`와 화면 모델을 사용한다. 저장·설정 상태는 화면 사이에서 공유하고 모달·설정의 draft는 적용 전 상태와 분리한다.

`PrototypeFixtureRepository`와 `SpringNoticeRepository`를 분리하고 지원 가능한 분야·필터·검색 범위를 repository 기능 정보로 노출한다. 미지원과 0건을 다른 상태로 표시한다. API DTO의 원본 문맥을 남겨 여러 출처, 근거, `field_values`, `history`가 단순 표시 모델 변환 중 사라지지 않게 한다.

외부 직접 의존성은 `material_ui 1.11.1`, `flutter_svg 2.4.0`, `web 1.1.2`로 제한했다. 용도와 SDK/브라우저 API 대안은 README에 기록했다. 상태관리·라우팅은 SDK를 사용한다. Flutter 3.50.0·Dart 3.14.0과 `pubspec.lock`을 고정했다.

## 화면별 구현 순서

| 경로 | 우선 구현할 동작 |
|---|---|
| `#/start?step=0..5` | 지역 선택, 3개 진행 묶음, 뒤로 복원, 위치 버튼에서만 권한 요청, 모든 선택 입력 생략 허용 |
| `#/home` | 예시 안내·헤더·6개 탭, 포스터 4개, 지원 3개, 변경 패널, 공사·교통 2개 |
| `#/list` | `cat/q/free/open/period/district/sort` 복원, 조건 AND, 칩별 해제, 목록 스크롤 복원 |
| `#/search` | 추천어, 무료 바로가기, 검색 전·0건·로딩·오류 구분, 오래된 응답 무시 |
| `#/detail?id=...` | 신청/진행 기간 분리, 근거·대상·예외·출처·이력, API snapshot 문맥, 잘못된 ID 안내 |
| `#/saved` | 공통 저장 상태, 전체/변경 소식, 빈 상태, 모드별 ID 분리 |
| `#/settings` | 저장값/draft 분리, 취소·적용, 지역·관심·선택 정보·위치 설정, 온보딩 재시작 |

목록에서 상세로 갔다 돌아오면 필터와 스크롤을 복원한다. 상세 직접 진입의 뒤로 버튼은 앱 내부 목록으로 이동한다. 설정은 버전이 있는 로컬 저장이며 계정 동기화로 표현하지 않는다. 손상된 JSON·저장 불가에서는 메모리 기본값으로 복구하고 지속 저장 불가를 알린다.

## 데이터와 API 연결

| 모드 | 데이터와 범위 | 검증 목적 |
|---|---|---|
| `prototype` | 시민용 예시 16건, 기준일 `2026-11-16` | 전체 화면과 사용자 흐름 |
| `backend-fixture` | Spring `fixture` 프로필의 별도 합성 자료 | 실제 HTTP·DTO·오류·snapshot 연결 |
| `api` | Spring `public` 프로필의 공개 자료 | 공개 데이터 준비 상태와 지원 기능 확인 |

기존 공개 API는 `GET /config`, `POST /matches`, `GET /events/{id}?snapshot_id=...`이며 접두사는 `/api/v1`이다. config는 지점·자료 범위·snapshot·서버 시각을 제공한다. matches는 고정 지점과 영업시간 조건, `construction/event/traffic` 유형을 전제로 한다. 시민용 일반 목록·교육/지원/생활 분류·신청 마감/무료 필터·전역 검색을 제공하는 계약은 없다.

백엔드 호환 검증은 별도 개발 실행에서 계약의 명시적 fixture 조건을 선택해 수행한다. 사용자 위치를 `point_id`로 보내거나 임의 영업시간을 채우지 않고, 가게 조건을 시민 서비스의 첫 단계로 만들지 않는다. 실제 DB 상세는 사실 응답이므로 I02 계산 문맥이 없으면 분류·거리·중첩을 표시하지 않는다.

시민용 확장 제안과 화면 영향은 [API 차이와 협의 항목](API_GAPS.md)에 기록한다. 백엔드·Python·공개 enum을 이번 작업에서 변경하지 않는다.

## 구현 중 지킬 데이터 규칙

- 무료는 `cost == 0`만 해당한다. `null`은 미기재로 표시한다.
- 모집 중은 신청 시작·마감과 취소/확인 필요 상태로 판단한다. 행사 진행일을 신청일로 사용하지 않는다.
- 이번 주는 KST 월요일부터 다음 월요일 직전까지의 구간과 진행 기간의 교집합으로 처리한다. 장기 행사·월/연 경계를 시험하며 원본의 `2026-11-22` 하드코딩을 복사하지 않는다.
- 예시 개인화 점수는 화면 정렬 용도로만 사용한다. Python의 후보/확인 필요/취소 판정을 Dart에서 재구현하지 않는다. 성별·나이대로 신청 가능 여부를 단정하지 않는다.
- 안성 외 지역은 준비 안내를 표시한다. 안성 예시를 선택 지역의 실제 소식으로 바꾸어 표시하지 않는다.
- 예시 SVG를 API의 실제 포스터로 사용하지 않는다. fixture 출처·example.org는 실제 신청 링크가 아니다.
- `null`과 알려진 빈 배열, snapshot 작성 시각과 응답/확인 시각을 구분한다. Python code point 근거 위치와 Dart UTF-16 인덱스를 직접 혼용하지 않는다.
- 409 공개본 교체는 새 버전 선택 안내, 503은 준비/장애 안내로 처리한다. 재시도는 `retryable`을 따르고 실패를 0건으로 바꾸지 않는다.

## 화면과 동작 검증

원본 CSS에서 색상·타이포·간격·포스터 비율을 추출한다. 기본 폭 1160/넓은 화면 1260, 홈 4열·목록 3열, 모바일 2열, 상세 우측 360, 1600/1020/760/370 경계를 적용한다. 신규 디자인을 만들지 않는다.

- 360·390·768·1440 logical px에서 온보딩·홈·목록·상세·관심정보·설정을 비교하고 760 경계 양쪽, 200% 확대·긴 제목을 추가 확인한다.
- Tab/Shift+Tab/Enter/Space, 모달 Escape·focus 복원, 44px 터치 영역·Semantics, 하단 고정 바 가림과 모션 감소를 확인한다.
- 예시 기준 교육+무료+모집 중 2건, 도예 검색 1건, 없는 검색어 0건을 확인한다. null 비용·취소·마감 없는 항목·기간 경계를 별도 검증한다.
- 저장/해제의 화면 간 동기화·새로고침 복원, 설정 draft 취소, 손상된 저장소·위치 거부/시간 초과·이미지 실패를 확인한다.
- API는 계약 fixture와 실제 HTTP 결과를 분리해 기록한다. 화면 캡처에는 모드·기준일·viewport를 함께 남긴다.

앱 생성 후 필수 명령은 `flutter pub get`, `dart format --output=none --set-exit-if-changed lib test`, `flutter analyze`, `flutter test`, `flutter run -d chrome --web-port 5173 --dart-define=DATA_MODE=prototype`, `flutter build web --dart-define=DATA_MODE=prototype`이다. 저장소의 기존 npm 검사도 유지한다.

첨부 `acceptance-cases.json`의 30건 원본은 보존하고 [검증 범위별 결과](acceptance-results.json)를 별도로 작성했다. 자동 검증과 실제 브라우저 수동 확인을 구분한다. 최종 보고는 Flutter 화면, 백엔드 합성 HTTP, 실제 시민용 데이터 연결의 완료 여부를 각각 적는다. 기존 T01~T23과 100개 시나리오·실자료 평가 목표는 프론트 핵심 검증만으로 완료 처리하지 않는다.

## 남은 검수와 통합

1. 사용자의 화면 제어 제한을 지키며 실제 브라우저 새로고침·뒤로/앞으로·위치 권한·외부 원문과 원본 시제품의 직접 시각 비교를 수동 검수한다.
2. 시민용 데이터·신청/비용·지역 조회·검색·변경 피드 계약은 API_GAPS에 따라 담당자와 조율한다.
3. 검증한 변경을 작업 브랜치에 공유하고 이후 `develop` PR에서 자체/독립/자동 리뷰와 인수를 거친다. 현재 develop/main 병합·배포는 수행하지 않는다.

브랜치별 검토를 거쳐 `develop`에 통합한다. `main` 병합과 운영 배포는 이번 준비 작업에 포함하지 않는다.
