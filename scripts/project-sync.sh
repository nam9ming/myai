#!/usr/bin/env bash
# 이슈나 PR 을 보드에 올리고 Status 를 지정한 값으로 맞춘다.
#
# gh project CLI 를 쓰지 않는다. CLI 는 소유자가 사용자인지 조직인지 먼저 조회하는데,
# 보드 권한만 가진 토큰으로는 그 조회가 막혀 "unknown owner type" 으로 실패한다.
# GraphQL 을 직접 부르면 보드 노드 ID 만 있으면 되고 소유자 조회가 필요 없다.
#
# 사용법: project-sync.sh <보드노드ID> <이슈나PR노드ID> [상태이름]
set -euo pipefail

PROJECT_ID="${1:?보드 노드 ID 를 지정해야 한다}"
CONTENT_ID="${2:?이슈 또는 PR 노드 ID 를 지정해야 한다}"
TARGET="${3:-}"

# 보드에 올린다. 이미 있으면 기존 항목 ID 를 그대로 돌려주므로 여러 번 불러도 안전하다.
ITEM_ID=$(gh api graphql -f query='
  mutation($p:ID!, $c:ID!){
    addProjectV2ItemById(input:{projectId:$p, contentId:$c}){ item { id } }
  }' -f p="$PROJECT_ID" -f c="$CONTENT_ID" --jq '.data.addProjectV2ItemById.item.id')

if [ -z "$ITEM_ID" ] || [ "$ITEM_ID" = "null" ]; then
  echo "::error::보드에 등록하지 못했다."
  exit 1
fi
echo "보드 항목: ${ITEM_ID}"

if [ -z "$TARGET" ]; then
  echo "옮길 상태가 지정되지 않았다. 등록만 하고 끝낸다."
  exit 0
fi

FIELD=$(gh api graphql -f query='
  query($p:ID!){
    node(id:$p){ ... on ProjectV2 {
      field(name:"Status"){ ... on ProjectV2SingleSelectField { id options { id name } } }
    } }
  }' -f p="$PROJECT_ID")

FIELD_ID=$(printf '%s' "$FIELD" | jq -r '.data.node.field.id')
OPTION_ID=$(printf '%s' "$FIELD" | jq -r --arg t "$TARGET" \
  '.data.node.field.options[] | select(.name==$t) | .id')

if [ -z "$OPTION_ID" ] || [ "$OPTION_ID" = "null" ]; then
  echo "::error::Status 에 '${TARGET}' 옵션이 없다. 보드 설정을 확인해야 한다."
  printf '%s' "$FIELD" | jq -r '.data.node.field.options[].name' | sed 's/^/  있는 옵션: /'
  exit 1
fi

gh api graphql -f query='
  mutation($p:ID!, $i:ID!, $f:ID!, $o:String!){
    updateProjectV2ItemFieldValue(input:{
      projectId:$p, itemId:$i, fieldId:$f, value:{singleSelectOptionId:$o}
    }){ projectV2Item { id } }
  }' -f p="$PROJECT_ID" -f i="$ITEM_ID" -f f="$FIELD_ID" -f o="$OPTION_ID" >/dev/null

echo "상태 변경: → ${TARGET}"
