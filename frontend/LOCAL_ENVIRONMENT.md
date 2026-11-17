# 여기:it 로컬 개발환경

확인일: 2026-11-17 KST. 작업 위치: `C:\myai`. 환경 준비 기록에 제품 구현 후의 변경을 추가했다. 제품 앱의 최신 실행·검증 결과는 [README](README.md)와 [VERIFICATION](VERIFICATION.md)을 따른다.

제품 앱·전체 예시 화면·Spring fixture의 실제 HTTP 검증을 수행했다. 사용자 요청 이후 Computer Use로 화면·마우스·키보드를 제어하지 않았으며 이후 이미지는 Flutter 위젯에서 생성했다. 기본 PATH의 Java 8은 보존하고 `.tools/jdk-21.0.13+9/`에 Temurin21을 별도로 준비했다.

## 저장소와 원본

- 원격: `https://github.com/nam9ming/myai.git`
- 기준: `origin/develop`, 커밋 `339e04f6d2bfac386fbc973fbe3e3b5b0aa02677`
- 로컬 작업 브랜치: `frontend/yeogi-it-flutter`
- 루트 `CODEX_TASK.md`와 사용자 ZIP을 보존했다. 커밋·push·PR·배포는 하지 않았다.
- 인계 ZIP: `C:\myai\yeogi-it-flutter-handoff.zip`
- 검증한 원본: `C:\myai\.local\handoff\yeogi-it-flutter-handoff\`
- manifest의 34개 파일 크기·SHA-256이 모두 일치한다. 검증 기록은 `.local/handoff-verification.json`, 재검증 도구는 `.local/verify-handoff.mjs`다.
- ZIP의 CODEX_TASK는 담당자만 이상헌으로 표기되어 있다. 최신 루트 문서의 남규민 표기를 따른다.

## 설치와 확인 결과

| 항목 | 확인 결과 | 경로 또는 용도 |
|---|---|---|
| OS | Windows 10 Pro 22H2 x64, RAM 약 23.9GB | 현재 개발 PC |
| 저장 공간 | 준비 전 C 약 295GB, D 약 0.1GB 여유 | 모든 추가 도구는 C에 설치 |
| PowerShell | 5.1 | 기본 셸 |
| Git | 2.56.1.windows.1 portable 설치 | `.tools/git/cmd/git.exe` |
| Flutter | 3.50.0 stable, revision `ab2912035e` | `.tools/flutter/bin/flutter.bat` |
| Dart | Flutter 번들 3.14.0 | 별도 Dart 설치 없음 |
| Node.js | 26.13.1 LTS, npm 11.20.0 | `.tools/node-v26.13.1-win-x64/`, 공통 검증용 |
| Python | 기존 3.12.10 | `.tools/python312/`에 로컬 venv, python3.exe 별칭 준비 |
| Chrome | 157.0.8103.51 | `C:\Program Files (x86)\Google\Chrome\Application\chrome.exe` |
| Edge | 157.0.4341.42 | Flutter 웹 실행 대상에서 확인 |
| VS Code | 기존 설치 사용 | Flutter·Dart 확장 3.146.0 설치 |
| Java | 기본 PATH의 Java 8 보존, 로컬 Temurin 21.0.13+9 추가 | `.tools/jdk-21.0.13+9/`, fixture 실행 검증 |
| Python 3.13 | PATH에서 확인되지 않음 | 실제 Python 계산/백엔드 전체 시험 전에 별도 준비 |
| Docker·MySQL | 실행 환경 미확인 | prototype 화면 개발의 선행 조건이 아님 |

Git·Flutter·Node 배포 파일은 공식 배포 SHA-256과 비교한 뒤 압축을 풀었다. 확인한 배포 정보는 [Flutter SDK archive](https://docs.flutter.dev/install/archive), [Git for Windows](https://git-scm.com/install/windows), [Node.js 배포 목록](https://nodejs.org/dist/index.json)이다.

SDK·캐시·샘플·편집기 설정은 `.tools/`, `.local/`, `.vscode/`에 두고 이 PC의 `.git/info/exclude`로 Git 대상에서 제외했다. 사용자/시스템 PATH와 영구 PowerShell 실행 정책은 변경하지 않았다. 저장소 로컬 `core.autocrlf=false`를 지정했으며 기존 소스를 일괄 재작성하지 않았다.

## 터미널과 편집기 사용

VS Code에서 **새 터미널**을 열면 `.vscode/settings.json`의 PATH·Flutter SDK·Git 경로를 적용한다. 기존 터미널에는 새 설정이 소급 적용되지 않는다. 다른 PowerShell 창에서는 다음 명령으로 개발용 셸을 연다.

```powershell
cd C:\myai
.\.local\dev.cmd
git --version
flutter --version
node --version
python3 --version
```

`dev.cmd`는 현재 터미널 안에 개발 도구 PATH를 물려준 PowerShell을 연다. 종료는 `exit`다. `.local/activate.ps1`도 제공하지만 기본 스크립트 실행 정책에 막힐 수 있으므로 위 CMD 진입을 사용할 수 있다. 자동 검증에서는 해당 프로세스에만 실행 정책을 지정해 사용했다.

원본 시제품은 저장소 루트에서 실행한다. 이는 Flutter 제품 앱 실행과 별개다.

```powershell
python -m http.server 4173 --bind 127.0.0.1 --directory .local/handoff/yeogi-it-flutter-handoff/reference-prototype
# http://127.0.0.1:4173/#/start
# http://127.0.0.1:4173/#/home
```

제품 앱을 생성한 뒤에는 프론트 개발 포트를 5173으로 맞춘다. 백엔드 기본 CORS는 `http://localhost:5173`만 허용하므로 API를 연결할 때 `127.0.0.1`과 `localhost`를 섞지 않는다. API 주소는 `http://localhost:8080/api/v1`, 배포 base href와 API 주소는 환경별로 분리한다.

## 실제 검증 결과

| 검증 | 결과 | 범위와 남은 항목 |
|---|---|---|
| `flutter --version`, `flutter devices` | 정상 | Chrome·Edge를 웹 대상으로 인식 |
| `flutter doctor -v` | 웹·네트워크 정상 | Android SDK 없음, Windows C++ 구성 미완료. 두 항목은 웹 개발에 필요하지 않음 |
| `npm run lint` | 통과 | 저장소 파일 문법·비밀값 패턴 검사 |
| `python3 contracts/validate_examples.py` | 통과 | 합성 JSON 9개 계약 관계 검증 |
| `npm run build` | 통과 | 기존 `dist/index.html` 합성 HTML 미리보기이며 Flutter 빌드가 아님 |
| `npm test` | 실패 | 최종 실행 30개 중 통과 15·실패 15. 로그 `.local/logs/npm-test.log` |
| 인계 manifest 검증 | 통과 | 34개 파일, 백엔드 ref가 현재 develop과 일치 |
| 원본 로컬 HTTP 확인 | 통과 | 4173에서 HTML·JS·CSS·SVG 5개 경로의 200 응답과 원본 bytes 확인, 확인 후 서버 종료 |
| 원본 fixture 핵심 조건 | 통과 | 총16·교육+무료+모집 중2·도예1·없는검색어0 |
| 별도 Flutter 샘플 `pub get`·format·analyze | 통과 | `.local/flutter-probe/`, 제품 소스와 별도 |
| 샘플 `flutter test` | 통과 | 기본 위젯 환경 시험 1건 |
| 샘플 `flutter build web --dart-define=DATA_MODE=prototype` | 통과 | `.local/flutter-probe/build/web/`, 제품 화면 빌드가 아님 |
| 샘플 `flutter test --platform chrome` | 실패 | iframe JS 실행 정지 진단, 3분 후 시간 초과. Chrome 자동 테스트 경로 재확인 필요 |
| 제품 단위·위젯 검증 | 통과 | 최신 건수와 범위는 VERIFICATION 참고 |
| 제품 브라우저 원본 비교·인수 검수 30건 | 부분 검증 | acceptance-results.json, 실제 브라우저 수동 검수 남음 |
| Spring fixture HTTP·CORS | 통과 | JDK21, Spring3.5.16, 실제 HTTP 테스트 3건 |
| public API·DB·계산 | 미실행 | 전용 DB·실자료·Python3.13 준비 후 별도 검증 |

현재 공통 npm 테스트의 실패는 `test/ai-review-diff.test.mjs`의 LF 전제 문자열 분할, `test/ai-review.test.mjs`의 Windows 절대 경로 `--import` 처리, `test/infrastructure.test.mjs`의 Git `\\.\nul` 처리에서 발생한다. python3 호출은 로컬 venv 별칭으로 해결했다. 공통 자동화와 시험 코드는 이번 준비 범위에서 수정하거나 건너뛰지 않았다.

Chrome 자동 테스트 시간 초과는 웹 빌드 성공과 구분한다. 실제 제품을 구현한 뒤 브라우저 실행·뒤로/앞으로·직접 URL·스크린샷 비교를 반드시 수행한다. 이 샘플의 성공을 제품 검수나 실제 API 연결 완료로 보고하지 않는다.

## 남은 확인

1. 실제 브라우저의 원본 비교·이력·권한·외부 링크를 수동 확인한다. 사용자 화면 제어는 요청에 따라 사용하지 않는다.
2. 공통 Windows npm 테스트 이슈를 별도 작업으로 관리한다.
3. public/전체 회귀가 필요할 때 Python3.13·전용 MySQL 환경과 실제 공개 자료를 확인한다.
