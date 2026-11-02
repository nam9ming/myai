#!/usr/bin/env bash
# 디스코드 채널 하나로 임베드 메시지를 보낸다.
#
#   WEBHOOK=<url> scripts/discord-send.sh <제목> [본문] [색상] [링크]
#
# 추가 필드는 FIELDS 환경변수에 "이름=값" 형태로 줄바꿈 구분해 넘긴다.
# WEBHOOK 이 비어 있으면 전송을 건너뛰고 0으로 끝낸다. 알림 때문에 파이프라인이 멈추면 안 된다.
set -euo pipefail

TITLE="${1:?제목이 필요하다}"
DESC="${2:-}"
COLOR="${3:-6841958}"
URL="${4:-}"

if [ -z "${WEBHOOK:-}" ]; then
  echo "::notice::웹훅이 등록되지 않은 채널이라 전송을 건너뜀 — ${TITLE}"
  exit 0
fi

FIELDS_JSON=$(
  printf '%s\n' "${FIELDS:-}" \
  | grep -v '^[[:space:]]*$' \
  | jq -R -s 'split("\n") | map(select(length>0) | split("=") | {name: .[0], value: (.[1:] | join("=")), inline: true})'
)

jq -n \
  --arg title "$TITLE" \
  --arg desc "$DESC" \
  --arg url "$URL" \
  --argjson color "$COLOR" \
  --argjson fields "$FIELDS_JSON" \
  '{embeds:[({title:$title, color:$color, fields:$fields}
            + (if $desc == "" then {} else {description:$desc} end)
            + (if $url  == "" then {} else {url:$url}  end))]}' \
  > /tmp/discord-payload.json

curl -sS --fail-with-body -X POST \
  -H "Content-Type: application/json" \
  -d @/tmp/discord-payload.json "$WEBHOOK" > /dev/null
echo "전송 완료 — ${TITLE}"
