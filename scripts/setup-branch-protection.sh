#!/usr/bin/env bash
# main 브랜치 보호를 적용한다. 여러 번 실행해도 결과는 같다.
set -euo pipefail

REPO="${1:-nam9ming/myai}"
BRANCH="${2:-main}"

echo "브랜치 보호 적용: ${REPO} → ${BRANCH}"

cat > /tmp/protection.json <<'JSON'
{
  "required_status_checks": {
    "strict": false,
    "contexts": ["check"]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 1
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON

gh api -X PUT "repos/${REPO}/branches/${BRANCH}/protection" \
  -H "Accept: application/vnd.github+json" \
  --input /tmp/protection.json > /dev/null

echo "적용 완료:"
echo "  - PR 없이 main 직접 push 불가"
echo "  - CI(check) 통과해야 머지 가능"
echo "  - 승인 1인 필요 (새 커밋이 오면 기존 승인은 무효화)"
echo "  - 강제 push / 브랜치 삭제 불가"
echo "  - 미해결 리뷰 코멘트가 있으면 머지 불가"
echo
echo "관리자는 우회 가능(enforce_admins=false). 팀원이 늘면 true로 바꾼다."
