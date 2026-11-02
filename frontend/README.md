# Flutter Web 프런트 — 이상헌

확정 기술: **Flutter Web / Dart**. Flutter stable의 동일 버전을 사용하고 번들 Dart 버전·`pubspec.lock`을 기록합니다. 현재는 작업 안내이며 Flutter 프로젝트·웹 빌드는 아직 없습니다.

1. [착수 가이드](../docs/spec/11_개발착수가이드.md), [작업 범위](TASK.md), [화면 명세](../docs/spec/02_화면과모바일UX.md)를 확인합니다.
2. contracts의 JSON을 asset fixture로 읽어 S01→S02→S03→원문 이동을 구현합니다.
3. API 접근을 한곳에 모으고 fixture/실제 Spring API 전환을 설정으로 구분합니다.
4. `pubspec.yaml`·`pubspec.lock`·`flutter --version` 결과와 실제 실행·빌드 명령을 기록합니다.

프로젝트 구현 후의 목표 명령 예: `flutter pub get`, `flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=http://localhost:8080/api/v1`, `flutter build web`. 아직 현재 폴더에서 실행 가능하다는 뜻은 아닙니다.

배포는 `build/web/` 전체를 사용하고 base href·API URL·브라우저 이력을 실제 경로에 맞춥니다. 디자인·동선 참고 HTML은 `docs/reference/meeting-demo.html`이며 Flutter 소스가 아닙니다. [기술 구성](../docs/spec/08_기술구성과연결.md)을 함께 확인합니다.
