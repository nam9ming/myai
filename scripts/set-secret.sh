#!/usr/bin/env bash
# 저장소 시크릿을 안전하게 등록한다.
# 값은 화면에 표시되지 않고, 명령 인자나 셸 기록에도 남지 않는다.
set -euo pipefail

NAME="${1:-}"
REPO="${2:-nam9ming/myai}"

if [ -z "$NAME" ]; then
  echo "사용법: bash scripts/set-secret.sh <시크릿이름> [저장소]"
  echo
  echo "  bash scripts/set-secret.sh DISCORD_WEBHOOK"
  echo "  bash scripts/set-secret.sh OPENAI_API_KEY"
  echo "  bash scripts/set-secret.sh ANTHROPIC_API_KEY"
  exit 1
fi

printf '%s 값을 붙여넣고 Enter (화면에 표시되지 않음): ' "$NAME"
read -rs VALUE
echo

if [ -z "$VALUE" ]; then
  echo "값이 비어 있다. 취소한다."
  exit 1
fi

printf '%s' "$VALUE" | gh secret set "$NAME" --repo "$REPO"
unset VALUE

echo "등록 완료: ${REPO} → ${NAME}"
echo
echo "확인:"
gh secret list --repo "$REPO"
