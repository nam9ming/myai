// PR 변경분을 읽어 1차 코드리뷰 코멘트를 만든다.
// 실패해도 PR을 막지 않는다. 리뷰는 보조 수단이고 판단은 사람이 한다.
import { readFileSync } from "node:fs";

const KEY = process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.ANTHROPIC_MODEL || "claude-sonnet-5";
const MAX_DIFF = 60_000;

function bail(reason) {
  console.log(`_AI 리뷰를 생성하지 못했다: ${reason}_`);
  process.exit(0);
}

const diffPath = process.argv[2];
if (!KEY) bail("ANTHROPIC_API_KEY 없음");
if (!diffPath) bail("변경분 파일 경로가 전달되지 않음");

let diff = "";
try {
  diff = readFileSync(diffPath, "utf8");
} catch (err) {
  bail(`변경분을 읽지 못함 (${err.code})`);
}
if (!diff.trim()) bail("변경분이 비어 있음");

let truncated = false;
if (diff.length > MAX_DIFF) {
  diff = diff.slice(0, MAX_DIFF);
  truncated = true;
}

let rules = "";
try {
  rules = readFileSync(new URL("../CLAUDE.md", import.meta.url), "utf8");
} catch {
  rules = "(규칙 파일 없음)";
}

const prompt = `너는 이 저장소의 1차 코드리뷰어다. 아래 팀 규칙과 변경분을 읽고 리뷰를 작성해라.

<팀_규칙>
${rules}
</팀_규칙>

<변경분>
${diff}
</변경분>
${truncated ? "\n(변경분이 커서 앞부분만 전달되었다.)\n" : ""}
작성 규칙:
- 한국어로 쓴다.
- 근거 없는 칭찬은 쓰지 않는다.
- 지적 하나당 한 줄. 형식: \`파일:줄 — 문제. 해결.\`
- 심각도 순으로 정렬한다. 버그·보안 > 규칙 위반 > 단순화.
- 포맷팅 취향은 의미가 바뀌지 않으면 적지 않는다.
- 지적할 것이 없으면 "지적 사항 없음"이라고만 쓴다.
- 마지막 줄에 "사람 리뷰어가 확인할 것:" 으로 시작하는 한 줄을 덧붙인다.`;

let res;
try {
  res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 2000,
      messages: [{ role: "user", content: prompt }],
    }),
  });
} catch (err) {
  bail(`API 호출 실패 (${err.message})`);
}

if (!res.ok) bail(`API 응답 ${res.status}`);

const data = await res.json();
const text = (data.content ?? []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
if (!text) bail("응답이 비어 있음");

console.log("### AI 1차 코드리뷰\n");
console.log(text);
console.log(`\n---\n\`${MODEL}\` 자동 생성. 최종 승인은 사람 리뷰어가 한다.`);
