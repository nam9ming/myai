# 여기:it Flutter Web

안성시 시민용 시제품을 Flutter Web으로 구현했습니다. 온보딩·홈·목록·검색·상세·관심정보·설정을 원본 예시 16건으로 연결합니다. 기존 Spring 합성 API는 별도 모드에서 조회하며, 실제 시민용 API의 미지원 기능은 준비 상태로 표시합니다.

이번 구현의 시각·동작 기준은 사용자 지시와 인계 원본이며 [개발 계획](DEVELOPMENT_PLAN.md)에 기록했습니다. 최신 [TASK](TASK.md)와 [화면 명세](../docs/spec/02_화면과모바일UX.md)의 시민5분야·기존 기능 유지·계약 합의·접근성·인계 절차를 함께 따릅니다. 김윤기와 필드/API/오류를 합의하고 강명묵의 반복 시나리오 검증으로 연결합니다. 기존 계산 책임·근거·미상·공개/비공개 경계는 유지합니다.

주요 변경의 검증·커밋·작업 브랜치 공유 규칙과 최신 윤기 커밋 검토는 [GIT_WORKFLOW](GIT_WORKFLOW.md)를 따릅니다.

## 개발 버전과 실행

Flutter **3.50.0 stable** (`ab2912035e160d9cad6306df307576da6128ebdb`), 번들 Dart **3.14.0**을 사용합니다. `pubspec.lock`을 포함합니다. Windows에서 Chrome 157·Edge 157을 SDK가 인식하며, 아래 코드는 다른 OS에서도 같은 SDK로 실행할 수 있습니다. 실제 브라우저별 수동 검수는 [검증 기록](VERIFICATION.md)을 확인해주세요.

```powershell
cd frontend
flutter pub get --enforce-lockfile
flutter run -d web-server --web-hostname 127.0.0.1 --web-port 5173 --dart-define=DATA_MODE=prototype
```

브라우저는 자동으로 열지 않습니다. 직접 `http://localhost:5173/#/start` 또는 `http://localhost:5173/#/home`을 엽니다. 실행 터미널의 Ctrl+C로 종료합니다. 이 PC에서 SDK가 PATH에 없다면 저장소 루트의 `.local/dev.cmd`로 개발 셸을 연 뒤 실행할 수 있습니다. 로컬 SDK 설치 경로는 Git에 포함하지 않습니다.

## 데이터 모드

| 설정 | 동작 | 실제 확인 범위 |
|---|---|---|
| `DATA_MODE=prototype` | 원본 예시 16건, 고정 기준일 2026-11-16, 지역·관심·검색·무료·모집·기간 필터 | 단위·위젯 검사와 웹 빌드 |
| `DATA_MODE=backend-fixture` | Spring fixture의 config → 원래 고정 matches 조건 → 같은 snapshot 상세 | 실제 Spring HTTP·CORS 검사 |
| `DATA_MODE=api` | 공개 config·상세 소비, 시민용 목록은 준비 안내 | DTO·오류 모사·컴파일 검사. 실제 public DB/실자료 연결 미검증 |

API 모드의 기본 `API_BASE_URL`은 같은 origin의 `/api/v1`입니다. 개발 서버가 다르면 다음처럼 지정합니다.

```powershell
flutter run -d web-server --web-hostname 127.0.0.1 --web-port 5173 --dart-define=DATA_MODE=backend-fixture --dart-define=API_BASE_URL=http://localhost:8080/api/v1
```

백엔드 CORS 기본값은 `http://localhost:5173`입니다. API 연결 시 브라우저도 이 origin으로 열어주세요. fixture의 지점·영업시간은 **명시적으로 선택한 개발 모드의 합성 조건**입니다. 시민 설정에 영업시간을 자동 입력하지 않습니다. public 모드는 `/matches`에 임의 조건을 보내지 않습니다.

미지원 교육·지원·생활 분야, 무료·신청 마감·동네·전역 검색을 API에 있는 것처럼 취급하지 않습니다. API 오류는 0건이나 예시 데이터로 대체하지 않습니다. 409 공개본 교체는 사용자 선택 후 새로 읽고, 재시도는 서버의 `retryable`을 따릅니다. 확장 범위는 [API_GAPS](API_GAPS.md)를 참고해주세요.

## 라우팅과 저장

기본 hash URL 전략과 Flutter `Router`/`Navigator`를 사용합니다. 경로는 `#/start?step=0..5`, `#/home`, `#/list`, `#/search`, `#/detail?id=...`, `#/saved`, `#/settings`입니다. 목록 쿼리는 `cat/q/free/open/period/district/sort`를 사용합니다. API 상세 링크에는 `snapshot_id`도 보존합니다.

상세에서 돌아갈 때 목록 조건·스크롤을 복원합니다. 상세 직접 진입의 목록 버튼은 앱 내부에 남습니다. 오래된 비동기 응답은 최신 설정·목록·snapshot을 덮어쓰지 않습니다. 필터 모달·설정 draft는 적용 전 값과 분리합니다.

설정은 `yeogi-settings-v2`, 저장은 `yeogi-saved-v2-<mode>`에 버전 2로 기록합니다. API 저장은 event_id·snapshot_id·revision_id 문맥을 남깁니다. 같은 origin에 기존 `yeogi-settings-v1`/`yeogi-saved-v1`이 있으면 읽어 옮길 수 있습니다. 다른 origin의 저장 데이터 이전·계정 동기화는 지원하지 않습니다. 손상된 JSON·저장 실패는 메모리 기본값과 지속 저장 불가 안내로 처리합니다.

위치는 버튼에서만 권한을 요청하고 좌표를 저장하지 않습니다. 거부·미지원·시간 초과 후 직접 선택한 지역으로 진행합니다. 현재 위치→행정구역 변환·실거리 검색은 미지원입니다. 앱의 위치 사용 해제와 브라우저 권한 철회는 다릅니다.

## 의존성과 자산

| 직접 패키지 | 고정 버전 | 용도와 대안 |
|---|---|---|
| `material_ui` | 1.11.1 | Flutter 3.50 기본 템플릿의 Material 위젯. 대안은 deprecated `flutter/material.dart` 또는 SDK 기본 위젯 직접 조합 |
| `flutter_svg` | 2.4.0 | 원본 SVG·아이콘을 벡터로 표시. PNG 변환이나 HTML view 삽입 대신 원본 해상도 유지 |
| `web` | 1.1.2 | Dart 공식 브라우저 API 바인딩. fetch·localStorage·위치·외부 링크·모션 감소 이벤트. 대안은 JS interop 바인딩 직접 작성 |

상태는 SDK `ChangeNotifier`, 라우팅은 SDK Router를 사용합니다. 별도 상태관리·라우팅·UI 패키지를 추가하지 않았습니다. 웹 코드와 메모리 구현을 조건부 import로 나누어 화면 제어 없이 테스트합니다.

원본 SVG 7개는 bytes를 보존했고 원본 시제품 커밋은 `4c5edf0a10751d2463400e62a2538e2101ab23df`입니다. [자산 manifest](assets/prototype/SOURCE_MANIFEST.json)에 원본 해시·파생 fixture 해시를 기록합니다. SVG를 실제 API 공지 포스터로 재사용하지 않습니다.

본문 Noto Sans KR는 원본 variable TTF를 글자·굵기 축 손실 없이 WOFF2로 압축한 로컬 자산을 사용합니다. `main()`에서 한 번 다운로드한 ByteData를 `FontLoader`의 `sans-serif` 한 이름으로 등록하며 본문과 SVG 포스터가 공유합니다. 같은 10MB TTF를 굵기별로 7번 받던 초기 로딩을 제거했습니다. 원본 TTF는 재생성용으로 보존하고 웹 빌드에는 포함하지 않습니다. 압축 내역은 `assets/fonts/BODY-COMPRESSION.json`, 재생성은 `python tool/compress_body_font.py` (`fonttools[woff]==4.68.0`)를 따릅니다. 포스터의 `serif`는 Noto Serif KR에서 **포스터에 쓰인 글자와 ASCII만 추린** 56,264 bytes의 `YeogiPosterSerif`를 사용합니다. OFL 라이선스와 [파생 기록](assets/fonts/SERIF-SUBSET.json)을 함께 포함합니다. 기본 한국어·포스터 글꼴은 원격 CSS 없이 로컬 자산에서 읽고, 실패 시 Flutter 기본 fallback을 사용합니다.

포스터 serif 재생성은 선택 작업입니다. `fonttools==4.68.0`이 설치된 Python에서 원본 TTF 경로를 전달합니다.

```powershell
python tool/subset_poster_font.py C:\path\to\NotoSerifKR-Original.ttf
```

## 검증 명령

```powershell
python tool/verify_sources.py
dart format --output=none --set-exit-if-changed lib test tool
flutter analyze
flutter test
flutter build web --dart-define=DATA_MODE=prototype
python tool/compress_web_assets.py build/web
```

기본 단위·위젯 검증과 별도로 Spring fixture의 실제 HTTP를 확인할 수 있습니다. JDK21을 준비하고 첫 터미널에서 저장소 루트 기준으로 실행합니다.

```powershell
.\backend\gradlew.bat -p backend bootRun --args="--spring.profiles.active=fixture" --no-daemon
```

두 번째 터미널은 `frontend/`에서 실행합니다. 이 테스트는 창을 띄우지 않으며 DB를 사용하지 않습니다.

```powershell
flutter test tool/spring_http_test.dart
```

위젯 이미지는 사용자 화면을 제어하지 않고 별도로 생성합니다.

```powershell
flutter test test/screens_test.dart --dart-define=CAPTURE_QA=true --plain-name "화면 제어 없이"
```

파일은 로컬 `.local/qa/`에 저장합니다. 생성 이미지만으로 원본 브라우저와의 일치나 실제 브라우저 인수를 완료 처리하지 않습니다. 기존 저장소의 `npm run lint`, `npm test`, `npm run build`도 유지합니다. Flutter CI는 별도 `frontend.yml`에 추가했으며 기존 check를 변경하지 않았습니다.

## 빌드와 인계

`flutter build web`의 **`build/web/` 전체**를 사용합니다. CanvasKit도 `canvaskit/`에서 로컬 로딩합니다. 하위 경로에서는 `--base-href /경로/`를 지정하고 API 접두사·직접 URL·새로고침을 확인해야 합니다. 공개 배포 빌드에는 실제 API 주소 또는 같은 origin 경로를 사용하며 localhost를 지정하지 않습니다.

빌드·캐시·SDK·비공개 자료는 소스 커밋에서 제외합니다. 현재 버전의 변경·실행 결과·남은 수동 검수와 산출물 위치는 [VERIFICATION](VERIFICATION.md), 인수 30건별 범위는 [acceptance-results.json](acceptance-results.json)에 기록했습니다. 실제 시민용 데이터 연결·100개 시나리오·실자료 평가·main 병합·운영 배포는 완료하지 않았습니다.

기존 [착수 가이드](../docs/spec/11_개발착수가이드.md), [기술 구성](../docs/spec/08_기술구성과연결.md), [계약](../contracts/README.md)의 계산 책임과 공개/비공개 경계를 유지합니다.

## 초기 로딩과 오류 안내

CanvasKit와 앱을 내려받는 동안 정적 로딩 화면이 표시됩니다. 엔진 준비와 앱 실행 단계를 구분하며 실제 `flutter-first-frame` 이벤트에서 로딩 화면을 제거합니다. 12초 이상 걸리면 다시 시도 버튼과 카카오톡 내부 브라우저에서 Safari로 여는 안내를 표시합니다. 로더·스크립트·비동기 초기화 오류는 오류 안내로 전환합니다. 재시도는 페이지를 새로 읽습니다. 서버의 CSP·캐시 설정을 변경하지 않으며 실제 iPhone 카카오톡 앱 검수와 테스트 브라우저 결과를 구분합니다.

### 로딩 화면과 압축 전송

첫 화면이 그려지기 전에는 시스템 글꼴로 로고와 주황색 비정률 로딩 바를 표시합니다. 추가 이미지나 글꼴을 받지 않으며 모션 감소 설정에서는 움직임을 생략합니다. 첫 프레임에서 200ms 페이드로 전환하고, 지연·실패 시 기존 재시도 안내를 유지합니다. 실제 완료 전 퍼센트를 표시하지 않습니다.

`python tool/compress_web_assets.py build/web`는 JavaScript와 CanvasKit의 gzip 사본을 생성합니다. 현대 브라우저의 표준 `DecompressionStream`으로 압축을 풀며, 고정 Flutter 3.50.0의 `window.flutterCanvasKit` 초기화 훅과 `buildConfig.builds[].mainJsPath`를 사용합니다. 원본 SDK 파일은 수정하지 않습니다. 해당 훅을 사용하는 최적화는 SDK 버전을 올릴 때 브라우저 검사를 다시 해야 합니다. 미지원 브라우저·압축 파일 실패 시 원본 경로로 복귀하고, 디버그 실행은 원본 로더를 사용합니다. 압축 JavaScript는 같은 문서에서 만든 Blob URL로 실행하며 원래 문서의 자산 경로와 CSP를 유지합니다. CSP에서 Blob 스크립트를 차단하는 환경에는 주소의 해시 앞에 `?startup=raw`를 붙여 원본 로딩 모드를 사용합니다. 오류 화면에서 재시도할 때도 이 모드로 복귀합니다. CEHUB의 공용 서버 설정은 변경하지 않습니다.

본문 글꼴은 정적 preload로 먼저 요청해 엔진과 병렬로 받습니다. 브라우저 검사에서 실제 요청이 한 번인지 확인합니다.

압축/원본/미지원/손상된 압축 경로와 모션 감소·지연·오류 안내 검사는 Playwright가 있는 별도 도구 환경에서 실행합니다. 앱의 npm 의존성을 추가하지 않습니다.

```bash
PLAYWRIGHT_MODULE=/path/to/playwright node tool/check_startup.cjs build/web /tmp/yeogi-startup-check
```

### 중앙 로고와 재방문 최적화

대기 화면의 이미지는 기존 favicon SVG를 인라인으로 재사용합니다. 별도 이미지 요청 없이 화면의 가로·세로 중앙에 고정하며, 하단 안내·재시도 버튼은 로고의 위치를 밀어내지 않습니다. 작은 화면에서는 대기 패널을 스크롤해 재시도 버튼에 접근할 수 있습니다.

압축 파일마다 SHA-256 기반 버전 쿼리를 넣고 브라우저 HTTP 캐시를 재사용합니다. 내용이 달라진 파일만 새 버전을 사용하며, HTML과 bootstrap의 서버 캐시 정책은 유지하므로 새 배포를 확인할 수 있습니다. LocalStorage·IndexedDB·Service Worker를 추가하거나 CSP를 완화하지 않습니다. 글꼴 준비와 공지 fixture 읽기도 병렬로 시작합니다.

### 글꼴 해석 중복 제거

동일한 글꼴을 두 가족 이름으로 등록하면 CanvasKit이 WOFF2 해석과 글꼴 공급자 재등록을 반복합니다. 본문 테마·직접 스타일·SVG의 글꼴 이름을 `sans-serif`로 통일해 한 번만 등록합니다. 전체 23,174자와 원래 가변 굵기·포스터 SVG는 유지합니다. 다운로드 중 Wasm 컴파일 방식과 Wasm 빌드 지원 조건, 전송·초기화 측정 결과는 성능 조사 보고서에서 별도로 구분합니다.

초기 전송·글꼴 해석·Wasm·압축·캐시 전체 조사와 후속 후보는 [STARTUP_AUDIT](STARTUP_AUDIT.md)를 확인해주세요.
