#!/usr/bin/env bash
# 채널별 디스코드 웹훅을 한 번에 등록한다.
# 값은 화면에 표시되지 않고 명령 인자나 셸 기록에도 남지 않는다.
# 비워두고 Enter 를 치면 그 채널은 건너뛴다.
set -euo pipefail

REPO="${1:-nam9ming/myai}"

CHANNELS=(
  "DISCORD_WEBHOOK_PR|#pr|PR 열림 · 머지"
  "DISCORD_WEBHOOK_CI|#ci|테스트 · 빌드 결과"
  "DISCORD_WEBHOOK_DEPLOY|#deploy|배포 완료 · 프리뷰 URL"
  "DISCORD_WEBHOOK_ERROR|#error|main 브랜치 실패 · 운영 오류"
  "DISCORD_WEBHOOK_WEEKLY|#weekly|주간 자동 리포트"
  "DISCORD_WEBHOOK_CLIENT|#갑-공유|발주처에 보이는 요약"
)

echo "저장소: ${REPO}"
echo "채널마다 웹훅 URL 을 붙여넣는다. 아직 만들지 않은 채널은 그냥 Enter."
echo

for entry in "${CHANNELS[@]}"; do
  IFS='|' read -r NAME CHANNEL DESC <<< "$entry"
  printf '%-24s %s (%s)\n' "$CHANNEL" "$DESC" "$NAME"
  printf '  URL: '
  read -rs VALUE
  echo
  if [ -z "$VALUE" ]; then
    echo "  건너뜀"
  else
    printf '%s' "$VALUE" | gh secret set "$NAME" --repo "$REPO"
    echo "  등록 완료"
  fi
  unset VALUE
  echo
done

echo "현재 등록된 시크릿:"
gh secret list --repo "$REPO"
echo
echo "연결 확인: gh workflow run ping.yml -f channel=ci -f message='연결 확인'"
