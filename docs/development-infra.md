# 개발 인프라 적용·설정

## 적용 범위

`YUNGI-KIM/ai-lounge-infra`의 커밋 `85ebdae0b17252f846377360038204b470032f1f`에서 워크플로·템플릿·도구를 복사하고 myai에 맞게 조정했다. 원본과 자동 동기화되지는 않으며 갱신은 별도 PR로 검토한다.

**앱 설계는 그대로다:** Flutter Web·Dart / Java21·Spring Boot3.5.x·MySQL8.4 / Python3.13. Node.js20+는 협업 자동화에만 사용한다. Node 앱이나 인프라 예제 `app/`은 가져오지 않았다. 기존 역할·계약·인계 방식은 CONTRIBUTING.md와 담당 폴더 문서를 따른다.

| 워크플로 | 현재 동작 |
| --- | --- |
| CI | PR·main 변경 시 JS 린트, 인프라·계약 검증, JDK21 백엔드·MySQL 시험, HTML/JAR 산출물 보관 |
| Preview | `ENABLE_PREVIEW=true`일 때 내부 PR의 합성 HTML 시제품을 Pages에 발행 |
| AI Review | OpenAI API로 PR 변경분 리뷰·코멘트, `OPENAI_API_KEY`가 없으면 생략 |
| Notify / PR Notify | CI·Preview 결과와 PR 상태를 기존 디스코드 채널로 전송 |
| Project Sync | 기존 공유 보드에 이슈·PR 등록·상태 변경 |
| Weekly Report | 금요일 18:00 KST에 myai 활동을 기존 주간·발주처 채널로 전송 |
| Ping | 사람이 실행할 때 선택 채널에 연결 확인 메시지 전송 |

현재 Spring 백엔드 기초·합성 API·MySQL 스키마가 있다. CI의 `check`에서 MySQL8.4 전용 테스트 DB와 JDK21을 사용해 백엔드 시험·JAR 빌드를 실행한다. CI의 DB 비밀번호는 실행 ID로 만든 일회성 테스트 값이며 실서비스 자격증명이 아니다. Flutter·Python 서비스와 실제 import·공개·계산 연결은 미구현이므로 CI 성공을 전체 앱·성능 시험 완료로 표현하지 않는다. `npm run build`는 기존 합성 HTML 하나만 패키징한다.

## 로컬 확인

Node.js20+와 Python3.13을 준비한 뒤 myai 루트에서 실행한다. 외부 npm 패키지 설치는 없다.

```bash
npm run lint
npm test
npm run build
```

린트는 Git 추적 파일과 Git 제외 대상이 아닌 새 파일을 검사한다. `npm test`는 Node 테스트와 `contracts/validate_examples.py`를 실행한다. `dist/`는 생성물이며 커밋하지 않는다.

## 기존 디스코드 공유

이번 적용에서는 원본 저장소 Actions 안에서 webhook 6개와 `PROJECT_TOKEN`을 myai로 직접 복제했다.
값은 로컬·로그에 출력하지 않았으며 임시 복제 브랜치는 정리한다. 원본에 `ANTHROPIC_API_KEY`는 없었다.
아래 등록 명령은 이후 시크릿 추가·갱신 때 사용한다.

같은 채널로 보내려면 ai-lounge-infra에 등록한 **같은 webhook 값**을 myai 저장소에도 등록한다. 시크릿은 자동 상속되지 않으며 GitHub에 저장된 기존 값을 다시 내려받을 수 없다. 원래 보관한 값을 터미널 프롬프트에 입력한다. 채팅·커밋·명령 인자에 값을 쓰지 않는다.

```bash
bash scripts/set-discord-webhooks.sh nam9ming/myai
bash scripts/set-secret.sh OPENAI_API_KEY nam9ming/myai
bash scripts/set-secret.sh ANTHROPIC_API_KEY nam9ming/myai
bash scripts/set-secret.sh PROJECT_TOKEN nam9ming/myai
```

| myai 시크릿 | 기존 공유 대상 |
| --- | --- |
| `DISCORD_WEBHOOK_PR` | `#pr` |
| `DISCORD_WEBHOOK_CI` | `#ci` |
| `DISCORD_WEBHOOK_DEPLOY` | `#deploy` |
| `DISCORD_WEBHOOK_ERROR` | `#error` |
| `DISCORD_WEBHOOK_WEEKLY` | `#weekly` |
| `DISCORD_WEBHOOK_CLIENT` | `#갑-공유` |
| `DISCORD_WEBHOOK` | 내부 채널별 설정이 없을 때 대체 |

등록하지 않은 자동 알림 채널은 생략한다. 발주처 채널은 대체 webhook을 사용하지 않는다.

코드 리뷰는 `OPENAI_API_KEY`와 OpenAI Responses API를 사용한다. 기본 모델은 `gpt-6.1-sol`이며 저장소 변수 `OPENAI_REVIEW_MODEL`로 변경한다. SDK 의존성은 추가하지 않는다. 요청에는 기본 브랜치의 팀 규칙과 최대 60000자의 PR diff를 보내고 `store=false`를 사용한다. 부분 검토·API 오류·빈 응답·미완료 응답은 명시하며 최종 승인은 사람이 한다. 모델 응답 예산은 추론 토큰을 포함해 최대 8192토큰이며 요청 제한 시간은 120초다. API 비용은 등록한 OpenAI 키에 청구된다. [OpenAI 텍스트 생성 문서](https://developers.openai.com/api/docs/guides/text), [모델 문서](https://developers.openai.com/api/docs/models/gpt-6.1-sol).

리뷰 스크립트는 비밀값 보호를 위해 기본 브랜치에서 읽는다. 기본 브랜치가 이전 Anthropic 버전이면 실행을 생략하며, OpenAI 리뷰 자동화는 main 반영 후 새 PR 또는 추가 커밋에서 확인한다.

diff는 전체 Git 이력에서 PR 이벤트의 고정 `base.sha...head.sha`를 merge-base 기준으로 수집한다. GitHub diff API의300파일 한도를 사용하지 않으며, 기본 브랜치 checkout을 유지하고 PR head 코드를 실행하지 않는다. 외부 diff 드라이버·textconv도 차단한다. 전체 이력 다운로드 비용은 늘지만 모델에 전달하는 앞60000자 부분 검토 한도는 그대로다. 로컬 회귀 시험에는 기존 Git과 Bash가 필요하다. [checkout 이력 설정](https://github.com/actions/checkout#fetch-all-history-for-all-tags-and-branches)·[Git diff 기준](https://git-scm.com/docs/git-diff)을 따른다.

주간 리포트는 기존 Anthropic 구성을 유지한다. `ANTHROPIC_API_KEY`가 없으면 원본 활동 목록을 사용하며, 요약 모델은 `ANTHROPIC_SUMMARY_MODEL`로 변경한다. `OPENAI_API_KEY`만 등록해도 주간 리포트의 AI 요약이 켜지는 것은 아니다.

main 반영·시크릿 등록 후 아래 명령은 실제 기존 채널에 메시지를 보낸다.

```bash
gh workflow run ping.yml --repo nam9ming/myai -f channel=ci -f message='myai 연결 확인'
```

## 기존 보드 공유

보드는 [YUNGI-KIM/projects/1](https://github.com/users/YUNGI-KIM/projects/1), 노드 ID는 `PVT_kwHOBcP-6s4BiHww`를 그대로 사용한다. `PROJECT_TOKEN`이 없으면 동기화만 생략한다.

기존 토큰이 myai 이슈·PR 읽기와 해당 보드 쓰기를 모두 허용해야 한다. ai-lounge-infra만 대상으로 한 fine-grained 토큰은 다른 소유자의 myai까지 자동으로 확장되지 않는다. 보드 소유자인 YUNGI-KIM 계정의 토큰으로 두 대상에 접근할 수 있는지 확인한다. classic 토큰은 `project`와 필요한 저장소 접근 범위를 점검한다.

| 이벤트 | Status |
| --- | --- |
| 이슈 등록·재개 | 대기 |
| PR 등록·재개 | 리뷰중 |
| PR 머지 | 검수대기 |
| 이슈 종료 | 완료 |

위 Status 옵션이 보드에 있어야 한다. 머지하지 않고 닫은 PR은 상태를 바꾸지 않는다. 기존 카드 일괄 이관은 수행하지 않는다.

## 팀장·설정 담당자 확인

1. PR 검토 후 main에 반영한다. 시크릿을 쓰는 작업은 기본 브랜치의 도구를 실행하므로 첫 도입 PR에서는 알림·보드·AI 실행 일부를 생략한다. 외부 fork PR은 CI만 검증한다.
2. 저장소 시크릿은 협업자도 등록할 수 있다. Pages·브랜치 보호·Actions 정책은 설정 권한자가 확인한다.
3. 브랜치 보호 적용 명령은 `bash scripts/setup-branch-protection.sh nam9ming/myai main`이다. `check` 통과·리뷰 1인·대화 해결을 요구한다. `enforce_admins=false`이므로 관리자 우회는 허용하며 기존 보호 설정을 갱신하므로 설정 담당자가 실행한다.
4. 공개 프리뷰가 필요할 때만 저장소 변수 `ENABLE_PREVIEW=true`를 등록한다. 첫 실행으로 `gh-pages`가 생기면 Settings → Pages에서 `Deploy from a branch` → `gh-pages` → `/ (root)`를 설정한다. Actions의 읽기·쓰기와 PR 코멘트 권한도 확인한다. 프리뷰 경로는 `https://nam9ming.github.io/myai/pr-번호/`이며 연구실 운영 배포와 별개다.
5. 코드·시크릿 등록만으로 연결 완료라고 보고하지 않는다. CI 실행, 채널 수신, 보드 상태 이동, 활성화했다면 프리뷰 접속을 각각 확인한다.

참고: [GitHub 시크릿 등록·권한](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets), [워크플로 권한·신뢰 경계](https://docs.github.com/en/actions/reference/security/secure-use).

## 되돌리기

인프라 도입 커밋을 revert하면 기존 문서·앱 계약 상태로 돌아간다. 외부 설정은 별도로 관리한다. 프리뷰 중단은 `ENABLE_PREVIEW`를 제거하거나 `false`로 바꾸고 Pages·이미 발행된 `gh-pages` 내용은 설정 담당자가 별도로 정리한다. 시크릿·보드 카드·디스코드 메시지는 코드 revert로 삭제되지 않는다.
