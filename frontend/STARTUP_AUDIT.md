# 초기 로딩 전수 조사 — 2026-11-17

## 결론과 측정 기준

현재 병목은 API가 아니라 글꼴·엔진 전송과 글꼴 해석이다. 같은 본문 글꼴을 두 가족 이름으로 등록하던 것을 `sans-serif` 하나로 통일했다. 전체 23,174자·가변 굵기·원본 SVG·백엔드·CSP는 유지했다.

완료 시점은 실제 `flutter-first-frame`이다. `runApp()` 반환이나 문구 변경을 완료로 계산하지 않는다. 220ms 로딩 화면 제거 대기는 별도다.

| 일반 망 비교 | 변경 전 | 변경 후 |
| --- | --- | --- |
| 본문 글꼴 엔진 처리 | 5회 | 2회 |
| 본문 글꼴 CPU 중앙값 | 391ms | 182ms |
| 첫 프레임 중앙값 | 1,471ms | 1,158ms |
| 느린 망 첫 프레임 중앙값(각 2회) | 45,061ms | 43,701ms |
| 느린 망 글꼴 CPU 중앙값 | 1,621ms | 679ms |

동일 로컬 HTTP 서버·동일 sandbox CSP·390×844 화면에서 전후 각 5회 교차 실행했다. Apple vendor로 전체 CanvasKit 분기를 선택했으나 실제 WebKit·iPhone·카카오톡 검사는 아니다. 캐시·공유 서버 부하의 영향을 받는다. CPU 시간은 `MakeFreeTypeFaceFromData`와 `registerFont`의 본문 파일 처리 합계다. 파일 다운로드는 이전에도 1회였고, 이제 엔진 파싱 1회와 공급자 등록 1회만 남는다.

느린 망은 100ms 지연·200,000 bytes/s 다운로드·CPU 4배 제한이다. 최종 비교는 서버의 `compare.json`과 배포 RESULT를 따른다. 로컬 비교 수치를 공개 HTTPS나 실제 기기 대기 시간으로 간주하지 않는다.

## 조사 항목

| 항목 | 확인 결과 | 판단 |
| --- | --- | --- |
| DNS/TLS/HTTP | 공개 응답·브라우저 네트워크 타이밍 확인 | 큰 파일 전송이 지배적. 연결 설정 유지 |
| API·DB | prototype 모드, fixture 18,951 bytes | 현재 첫 화면은 백엔드 대기 없음 |
| 본문 글꼴 | WOFF2 3,908,364 bytes, 1회 전송 | 초기 약 8MB의 절반 |
| 글꼴 중복 해석 | 본문·포스터 이름별 등록으로 5회 처리 | 한 등록을 공유해 2회로 수정 |
| 손실 없는 재압축 | 이전 글리프 정리 후보 약 34KB 절감 | 이득 작아 미적용 |
| 굵기 범위 축소 | 400–800: 3,918,264 bytes, 400–900: 3,993,500 bytes | 오히려 커지고 외곽선 정확 일치도 실패. 미적용 |
| 글꼴 분할·지연 | CanvasKit FontLoader에는 CSS unicode-range 자동 로딩 없음 | 가장 큰 후속 후보. 전체 문자·입력·새 API 자료 보존 설계 필요 |
| 시스템 글꼴 | CanvasKit은 HTML처럼 iOS 시스템 글꼴을 바로 사용하지 않음 | CSS 이름만 바꿔 한국어 파일 제거 불가 |
| 빌드 모드 | release 기본 O4, 아이콘 tree shaking 확인 | 이미 최적화 빌드. 소스맵·미사용 배포 파일은 실제 첫 요청과 구분 |
| 화면 지연 로딩 | 후속 화면을 Dart deferred import로 분리 가능 | JS는 초기 전송의 약 11%. 직접 링크·청크 로딩·압축 fallback 검증이 필요한 후속 후보 |
| JavaScript | 원본 약 3.01MB, gzip 0.885MB | 기존 압축 유지. 기능·의존성 전면 삭제 안 함 |
| CanvasKit | 전체 Wasm gzip 2,925,332 bytes, Chromium 2,071,190 bytes | Chromium 변형을 Safari에 강제하지 않음 |
| 다운로드 중 Wasm 컴파일 | 공개 HTTPS, 전후 각 2회 | Apple 분기 빠른 망 2,130/2,176ms, 느린 망 44,798/44,773ms. 개선 거의 없어 미적용 |
| 새 Wasm/Skwasm | 고정 SDK browser_environment.js에서 WebKit 기본 false | iPhone 개선책으로 채택 안 함. 허용 목록 강제 변경 안 함 |
| Wasm 멀티스레드 | 공개 페이지 crossOriginIsolated=false | 공유 보안 헤더 변경 안 함 |
| Brotli 크기 실험 | JS 683,839 bytes, 전체 Wasm 2,271,173 bytes | gzip보다 합계 약 0.855MB 절감 가능 |
| 브라우저 Brotli | 검사 브라우저 DecompressionStream gzip 지원, brotli/br 미지원 | 해제 라이브러리 추가 안 함. 서버 제공은 관리자 영역 |
| 재방문 캐시 | 기존 버전 URL·force-cache 실제 disk cache 적중 | 유지. 브라우저가 캐시 삭제하면 재다운로드 |
| Service Worker·저장소 | 현재 opaque sandbox | 저장·인증 경계 완화 안 함 |
| 로딩 UI | 인라인 SVG·시스템 글꼴·CSS | 이미지·글꼴 추가 다운로드 없음. 중앙 정렬 유지 |
| preload·병렬화 | 글꼴 preload, 글꼴 준비·fixture 읽기 병렬 | 이미 적용. fixture preload는 주 병목을 해결하지 못함 |
| 정적 HTML 첫 화면 | 엔진 전에 실제 온보딩 제공 가능 | 빠른 대안이나 Flutter UI·상태 이중 관리 필요. 구조 교체 안 함 |

Brotli는 오프라인 실제 파일을 압축하고 역압축 일치까지 확인한 후보일 뿐, 배포하지 않았다. 올바른 Content-Encoding·MIME·캐시·gzip/원본 fallback 검증이 필요하다. WOFF2는 이미 압축되어 추가 Brotli가 줄이지 못했다. 공용 서버 설정은 그대로다.

## 다음 우선순위

1. 전체 한글과 현재 화면 문자를 먼저 제공하고 나머지를 필요할 때 로드하는 글꼴 분할. 실제 공지·한자·검색 입력의 누락·레이아웃 이동을 검증해야 한다.
2. 관리자에게 해당 팀 파일에 한정한 서버 Brotli 제공 가능 여부 확인. 약 0.855MB는 초기 약 8MB의 11%다. 200KB/s에서 전송량 기준 약 4.3초이며 실제 첫 프레임 개선은 재측정해야 한다.
3. 즉시 첫 화면이 필요하면 정적 HTML 온보딩과 Flutter 연결 구조 비교. 현재 Flutter 소스를 임의로 전면 교체하지 않는다.

## 재현과 검증

`tool/check_startup.cjs`에서 압축·전체 CanvasKit·원본 fallback·원본 모드·압축 파일 누락 각각 본문 다운로드 1회, 엔진 처리 2회, 실제 첫 프레임을 확인한다. 기존 모션 감소·지연·오류 복구 검사도 유지한다.

```sh
PLAYWRIGHT_MODULE=/path/to/playwright node tool/check_startup.cjs build/web /tmp/yeogi-startup-check
```

서버 조사 원본 스크립트·JSON·Slurm 로그는 `/cephfs/home/team_asai1/deployments/startup-audit/`에 있다. profile은 공개 HTTPS의 기존 방식/스트리밍 컴파일 비교, compare는 로컬 동일 서버의 글꼴 수정 전후 비교, compression은 압축 크기 실험, public-audit는 공개 헤더·네트워크·브라우저 기능 검사다. 전체 빌드의 lint·분석·87개 Flutter 테스트와 실제 공개 데스크톱·모바일 동작 검사도 통과했다. 물리 iPhone 검증은 미완료다.
