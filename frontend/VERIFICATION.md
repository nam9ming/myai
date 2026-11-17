# 여기:it 구현과 검증 기록

확인일: 2026-11-17 KST. 작업·공유 브랜치 `frontend/yeogi-it-flutter`. 개발 시작 기준은 `339e04f6d2bfac386fbc973fbe3e3b5b0aa02677`이며 공유 전 윤기의 최신 `develop` `6145aac75da2fa071cca72d91c5b113f1b48921d` 문서 변경을 통합했다. 실행 코드·JSON 예제 변경은 없다. 사용자 지시에 따라 검증한 버전을 작업 브랜치에 공유하며 develop/main 병합·운영 배포는 수행하지 않는다. 공유 절차와 변경 검토는 [GIT_WORKFLOW](GIT_WORKFLOW.md)를 따른다.

## 구현한 범위

- Flutter Web 프로젝트·고정 의존성·로컬 폰트·원본 SVG·예시 16건.
- 온보딩 6단계, 홈, 목록·검색·필터 모달, 상세·근거·출처·변경 이력, 관심정보, 설정·지역 선택.
- hash 라우팅·쿼리 정규화, 상세 직접 진입의 앱 내부 복귀, 조건·스크롤 복원, 오래된 응답 무시.
- 설정 draft 취소·저장, 모드별 저장 namespace와 snapshot/revision 문맥, v1 로컬 데이터 이전·손상/쓰기 실패 복구.
- 위치 요청 중복 방지·거부/시간 초과 후 진행, 모션 감소·포커스·키보드·상태 라벨, 44px 이상 조작 영역.
- Spring config/matches/detail 어댑터, 사실 DTO·null/빈 배열·근거·복수 출처 보존, 별도 합성 모드, 미지원·0건·오류 구분.
- 공개 source_refs와 이력의 이전/새 근거 연결, 예시 원문 차단, 실제 http/https 클릭 열기와 주소 확인·복사 실패 안내.

수정 범위는 `frontend/`와 새 Flutter 전용 `.github/workflows/frontend.yml`이다. 기존 백엔드·Python·공개 계약·공통 CI와 기존 테스트는 수정하지 않았다. 별도 CI는 파일만 추가했으며 GitHub Actions에서 실제 실행한 결과는 아직 없다.

## 실행한 검증

| 명령 또는 확인 | 결과 | 실제 검증 범위 |
|---|---|---|
| `flutter pub get --enforce-lockfile` | 통과 | Flutter 3.50.0·Dart3.14.0 고정 의존성 |
| `dart format --output=none --set-exit-if-changed lib test tool` | 통과 | Dart 소스·테스트·HTTP 검증 도구 |
| `flutter analyze` | 통과 | 오류·경고 없음 |
| `flutter test` | **85건 통과** | 모델·상태·매핑·오류·응답 순서·화면·내비게이션·권한 모사·링크 제어 |
| `flutter test tool/spring_http_test.dart` | **3건 통과** | 실제 Spring fixture HTTP config→고정 matches→상세, 미지원 조건503, 허용/거부 CORS |
| `python tool/verify_sources.py` | 통과 | 원본 SVG7개 bytes·예시16건·기준일·serif 파생본·라이선스 |
| `flutter build web`의 세 DATA_MODE | 통과 | `api`, `backend-fixture`, `prototype` 각각 컴파일. public 데이터 운영 완료 의미는 아님 |
| `python tool/check_web_build.py` | 통과 | 모드별 HTML/JS/로컬 CanvasKit/폰트/SVG의 실제 정적 HTTP 경로 |
| 원본 manifest | 통과 | 인계 ZIP34개 파일 크기·SHA-256, 현재 backend ref와 일치 |
| 기존 `npm run lint`, `npm run build` | 통과 | 공통 검증·기존 합성 HTML 패키징. Flutter 빌드와 별개 |
| 기존 `npm test` | 기존 실패 유지 | 30개 중 15통과·15실패, 준비 단계와 동일한 Windows 경로·LF·Git null 장치 문제 |

Spring 검증은 Temurin **21.0.13+9**, Spring Boot **3.5.16**, Gradle **8.14.3**으로 DB 없는 fixture 프로필에서 수행했다. 서버가 반환한 예시 snapshot과 사건 ID를 연결했으며, 사실 전용 별도 예제의 ID를 섞지 않았다. 변경한 영업 조건은 503 `CALCULATOR_NOT_READY`와 `retryable=true`를 반환했다. 프론트는 원래 오류·재시도 가능 여부를 보존한다.

Flutter 위젯 검증은 화면·마우스·키보드를 제어하지 않는다. 테스트의 브라우저 뒤로 이벤트·권한 거부·외부 링크는 테스트 더블 또는 프레임워크 이벤트로 검사했다. 사용자 요청 이후 Computer Use를 사용하지 않았다.

## 화면 검사 범위

- 온보딩·홈·목록·검색·상세·관심정보·설정을 360/390/768/1440 logical px에서 위젯 레이아웃으로 확인했다.
- 369/370/760/761 경계와 200% 글자 확대·긴 한국어 제목, 저장 시 스크롤 유지, 목록→상세→뒤로 복원을 확인했다.
- 포스터 내부 확대·필터 토글 시 fade 재시작 방지, Escape 후 focus 복원과 Enter 재진입·모션 감소를 확인했다.
- `.local/qa/prototype-20261116-390-home.png`, `...-start.png`, `...-detail.png`는 Flutter 위젯 렌더링 이미지다. 실제 브라우저 캡처나 원본과의 golden 일치 결과가 아니다.
- 이미지 검사에서 발견한 SVG generic font의 한국어 누락을 로컬 sans-serif/serif 바인딩으로 보완했다. serif는 원본 SVG에서 사용하는 글자만 남겨 약23.8MB에서56,264 bytes로 줄였다. SVG 파일 자체는 변경하지 않았다.

## 빌드 산출물

현재 `frontend/build/web/`는 prototype 모드의 전체 정적 빌드다. 모드별 사본은 다음 로컬 경로에 둔다.

```text
C:\myai\.local\builds\20261117-final\prototype\
C:\myai\.local\builds\20261117-final\backend-fixture\
C:\myai\.local\builds\20261117-final\api\
```

`build/web/`에는 HTML·JS·원본 SVG·폰트·CanvasKit 등 전체 파일이 필요하다. 한 파일만 복사해서 실행하지 않는다. 개발 주소·정적 서버 명령·base href 주의사항은 README를 따른다. 인계용 prototype ZIP은 `.local/releases/yeogi-it-prototype-web-20261117.zip`에 둔다. 이들 생성물·SDK·캐시·입력 ZIP은 소스 커밋에 포함하지 않는다.

## 남은 인수와 연결

원본 30건의 범위별 결과는 [acceptance-results.json](acceptance-results.json)에 기록했다. 자동 통과24건과 부분 검증6건을 구분하며 전체 인수 완료로 보고하지 않는다.

1. 실제 Chrome/Edge에서 새로고침·뒤로/앞으로·스크롤과 하위 경로 호스팅 확인.
2. 실제 브라우저 위치 거부·미지원·시간 초과, 외부 새 탭·팝업 차단·클립보드 실패와 복구 확인.
3. 같은 viewport의 원본 웹과 간격·타이포·모션을 직접 비교하고 전체 Tab/Shift+Tab/Space·스크린리더 검수.
4. 시민용 분야·신청/비용·지역·검색·변경 피드 API 확장과 실제 공개 데이터 확보. public DB·Python 계산·실제 시민 데이터 연결·실자료 평가·총100개 시나리오는 미완료.
5. 공유한 작업 브랜치의 CI·리뷰와 `develop` PR 인수. main 통합·운영 배포는 별도 검토.

준비 단계의 Chrome 자동 시험 시간 초과와 공통 Windows npm 테스트 실패는 남은 환경 이슈다. 현재의 VM 위젯 통과·웹 컴파일 성공을 실제 브라우저 전체 동작이나 공통 CI 통과로 바꿔 보고하지 않는다.
