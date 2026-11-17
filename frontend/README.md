# 여기:it Flutter Web 프런트 — 이상헌

[확정 요구] **Flutter Web / Dart**, 안성시민 전체를 위한 교육·배움 / 지원·혜택 / 행사·문화 / 공사·교통 / 생활정보 화면을 만듭니다. 기존 소상공인 조건 선별도 유지합니다. Flutter stable의 동일 버전을 사용하고 번들 Dart 버전·`pubspec.lock`을 기록합니다. 저장소에는 현재 README·TASK만 있으며 Flutter 프로젝트·웹 빌드는 아직 없습니다.

[설계 제안] [시민용 웹 시제품](https://yeogi-it-neighborhood.kmnam001.chatgpt.site/)은 통합 메인·분야별 목록·지역/관심 탐색·상세·관심·설정의 검토 대상입니다. 공지는 합성이고 원문은 예시이며 기존 백엔드와 연결되지 않았습니다. [Figma 참고 링크](https://www.figma.com/design/lM2PFXTrzaJmLqbkVp4gUO)도 제공됐으나 디자인 확인·확정을 뜻하지 않습니다. AI/Figma 시안 → 검토·피드백 → 화면 확정 → Flutter 구현 순서입니다.

1. [착수 가이드](../docs/spec/11_개발착수가이드.md), [작업 범위](TASK.md), [화면 명세](../docs/spec/02_화면과모바일UX.md)를 확인하고 연령·디지털 이용 수준·접근성을 함께 검토합니다.
2. 목록·상세·검색, 지역·분야·모집 상태·비용·기간·정렬의 화면별 필드·오류를 김윤기와 합의합니다. 신청 시작/마감과 진행 일정을 분리하고 비용 누락을 무료로 표시하지 않습니다.
3. API 접근을 한곳에 모으고 기존 [api-v1 합성 fixture](../contracts/README.md)와 새 계약 제안·실제 Spring 연결을 구분합니다. 기존3유형·지점·영업시간 응답을 새5분야 구현으로 간주하지 않습니다.
4. 관심저장·개인설정은 초기 브라우저 저장으로 구성합니다. 계정 동기화·새 인증·알림 발송은 자동 필수 범위가 아니며 저장 범위·초기화 동작을 합의합니다.
5. `pubspec.yaml`·`pubspec.lock`·`flutter --version` 결과, 실제 실행·빌드 명령과 명묵의 반복 시나리오 확인 결과를 인계합니다.

프로젝트 구현 후의 목표 명령 예: `flutter pub get`, `flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=http://localhost:8080/api/v1`, `flutter build web`. 아직 현재 폴더에서 실행 가능하다는 뜻은 아닙니다.

배포는 `build/web/` 전체를 사용하고 base href·API URL·브라우저 이력을 실제 경로에 맞춥니다. [과거 기록] `docs/reference/meeting-demo.html`과 기존 `npm run build` 산출물은 합성 HTML 참고자료이며 Flutter 소스·새 시제품 API 연결 결과가 아닙니다. [기술 구성](../docs/spec/08_기술구성과연결.md)을 함께 확인합니다.
