import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const completed = {
  status: "completed",
  output: [
    { type: "reasoning", summary: [] },
    { type: "message", content: [
      { type: "output_text", text: "processing/matching.py:12 — 경계값 오류. 비교 조건 수정." },
      { type: "output_text", text: "사람 리뷰어가 확인할 것: 날짜 경계." },
    ] },
  ],
};

function review(t, options = {}) {
  const root = mkdtempSync(join(tmpdir(), "myai-review-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const diff = join(root, "pr.diff");
  const request = join(root, "request.json");
  const mock = join(root, "fetch.mjs");
  writeFileSync(diff, options.diff ?? "+ changed_line\n");
  writeFileSync(mock, `
    import { writeFileSync } from "node:fs";
    globalThis.fetch = async (url, options) => {
      writeFileSync(${JSON.stringify(request)}, JSON.stringify({ url, method: options.method, headers: options.headers, body: JSON.parse(options.body) }));
      ${options.networkError ? 'throw new TypeError("network unavailable");' : `return new Response(${JSON.stringify(options.raw ?? JSON.stringify(options.response ?? completed))}, { status: ${options.status ?? 200} });`}
    };
  `);
  const result = spawnSync(process.execPath, ["--import", mock, fileURLToPath(new URL("../scripts/ai-review.mjs", import.meta.url)), diff], {
    encoding: "utf8",
    env: { ...process.env, OPENAI_API_KEY: options.key ?? "test-key", OPENAI_MODEL: options.model ?? "", ANTHROPIC_API_KEY: "" },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, "");
  return { ...result, request: existsSync(request) ? JSON.parse(readFileSync(request, "utf8")) : null };
}

test("OpenAI Responses에 인증·검토 지시·diff를 보내고 여러 텍스트 블록을 출력한다", (t) => {
  const result = review(t);
  assert.equal(result.request.url, "https://api.openai.com/v1/responses");
  assert.equal(result.request.method, "POST");
  assert.equal(result.request.headers.Authorization, "Bearer test-key");
  assert.equal(result.request.body.model, "gpt-6.1-sol");
  assert.equal(result.request.body.store, false);
  assert.equal(result.request.body.input, "+ changed_line\n");
  assert.match(result.request.body.instructions, /팀 작업 규칙/);
  assert.match(result.stdout, /### AI 1차 코드리뷰/);
  assert.match(result.stdout, /processing\/matching.py:12/);
  assert.match(result.stdout, /사람 리뷰어가 확인할 것: 날짜 경계/);
  assert.match(result.stdout, /gpt-6\.1-sol/);
  assert.doesNotMatch(result.stdout, /test-key/);
});

test("설정한 OpenAI 모델을 사용한다", (t) => {
  const result = review(t, { model: "configured-review-model" });
  assert.equal(result.request.body.model, "configured-review-model");
  assert.match(result.stdout, /configured-review-model/);
});

test("키나 diff가 없으면 API를 호출하지 않는다", async (t) => {
  for (const [options, message] of [[{ key: "" }, /OPENAI_API_KEY 없음/], [{ diff: "  \n" }, /변경분이 비어 있음/]]) {
    await t.test(message.source, (t) => {
      const result = review(t, options);
      assert.equal(result.request, null);
      assert.match(result.stdout, message);
    });
  }
});

test("긴 diff는 제한하고 부분 검토임을 알린다", (t) => {
  const result = review(t, { diff: "x".repeat(60_001) + "OMITTED_END" });
  assert.equal(result.request.body.input.length, 60_000);
  assert.doesNotMatch(JSON.stringify(result.request.body), /OMITTED_END/);
  assert.match(result.stdout, /앞 60000자/);
});

test("API 오류·잘못된 응답·미완료 응답을 성공 리뷰로 표시하지 않는다", async (t) => {
  const cases = [
    [{ status: 401 }, /API 응답 401/],
    [{ status: 429 }, /API 응답 429/],
    [{ networkError: true }, /API 호출 실패/],
    [{ raw: "not-json" }, /API 응답 형식 오류/],
    [{ response: { status: "incomplete", output: completed.output } }, /응답이 완료되지 않음/],
    [{ response: { status: "completed", output: [] } }, /응답이 비어 있음/],
  ];
  for (const [options, message] of cases) {
    await t.test(message.source, (t) => {
      const result = review(t, options);
      assert.match(result.stdout, message);
      assert.doesNotMatch(result.stdout, /### AI 1차 코드리뷰|test-key/);
    });
  }
});
