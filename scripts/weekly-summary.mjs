// 지난 7일 활동을 갑이 읽을 수 있는 언어로 요약한다.
// API 키가 없으면 원본 목록을 그대로 낸다. 어떤 경우에도 리포트는 나간다.
import { readFileSync } from "node:fs";

const KEY = process.env.ANTHROPIC_API_KEY;
const MODEL = process.env.ANTHROPIC_MODEL || "claude-opus-5";
const SINCE = process.env.SINCE || "지난 7일";
const REPO = process.env.GITHUB_REPOSITORY || "(저장소)";

const load = (path) => {
  try {
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return [];
  }
};

const merged = load("/tmp/prs.json");
const closed = load("/tmp/issues.json");
const open = load("/tmp/open.json");

const list = (items, empty) =>
  items.length ? items.map((i) => `- #${i.number} ${i.title}`).join("\n") : `- ${empty}`;

const raw = `## 주간 개발 리포트 · ${REPO}
기준: ${SINCE} 이후

**머지된 PR (${merged.length}건)**
${list(merged, "없음")}

**완료된 이슈 (${closed.length}건)**
${list(closed, "없음")}

**진행 중 이슈 (${open.length}건)**
${list(open, "없음")}`;

if (!KEY || (merged.length === 0 && closed.length === 0)) {
  console.log(raw);
  process.exit(0);
}

const prompt = `아래는 한 주간의 개발 활동 기록이다. 이걸 개발자가 아닌 발주처 담당자가 읽을 주간 보고로 다시 써라.

${raw}

작성 규칙:
- 한국어. 디스코드에 그대로 올릴 마크다운.
- 기술 용어를 쓰지 않는다. "리팩터링", "머지", "PR" 같은 말 대신 무엇이 가능해졌는지로 쓴다.
- 첫 줄은 "## 주간 개발 리포트 · ${REPO}" 로 쓴다.
- 구성: 이번 주 완료된 것 / 진행 중인 것 / 다음 주 예정.
- 없는 사실을 지어내지 않는다. 기록에 없으면 "해당 없음"이라고 쓴다.
- 전체 1500자 이내.`;

try {
  const res = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 1500,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!res.ok) throw new Error(`API 응답 ${res.status}`);
  const data = await res.json();
  const text = (data.content ?? []).filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
  console.log(text || raw);
} catch (err) {
  console.log(raw);
  console.log(`\n_요약 생성 실패로 원본을 전송함: ${err.message}_`);
}
