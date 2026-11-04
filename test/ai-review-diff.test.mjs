import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const workflow = readFileSync(new URL("../.github/workflows/ai-review.yml", import.meta.url), "utf8");
const block = workflow.split("      - name: 변경분 추출\n")[1]?.split("\n      - name:")[0];
assert.ok(block, "diff 수집 workflow 단계가 있어야 한다");
const run = block.match(/        run: \|\n((?:          .*(?:\n|$))+)/)?.[1];
assert.ok(run, "실제 workflow Bash를 시험해야 한다");
const script = run.split("\n").filter((line) => line.startsWith("          "))
  .map((line) => line.slice(10)).join("\n").replaceAll("/tmp/pr.diff", '"$TEST_DIFF"');

function repository(t, count = 1) {
  const root = mkdtempSync(join(tmpdir(), "myai-diff-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = { ...process.env, GIT_CONFIG_GLOBAL: "/dev/null", GIT_CONFIG_NOSYSTEM: "1" };
  const git = (...args) => {
    const result = spawnSync("git", ["-c", "user.name=Test", "-c", "user.email=test@example.invalid",
      "-c", "commit.gpgsign=false", ...args], { cwd: root, env, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    return result.stdout.trim();
  };
  git("init", "-b", "main");
  writeFileSync(join(root, "seed.txt"), "base\n");
  git("add", "seed.txt");
  git("commit", "-m", "test: create base");
  const base = git("rev-parse", "HEAD");
  git("switch", "-c", "feature");
  const files = Array.from({ length: count }, (_, i) => `notice-${i}.txt`);
  for (const file of files) writeFileSync(join(root, file), "합성 공지\n");
  git("add", "--", ...files);
  git("commit", "-m", "test: add notices");
  const head = git("rev-parse", "HEAD");
  git("switch", "main");
  const tools = join(root, "tools");
  mkdirSync(tools);
  const gh = join(tools, "gh");
  writeFileSync(gh, "#!/usr/bin/env bash\nprintf 'HTTP 406: diff exceeded maximum files (300)\\n' >&2\nexit 1\n");
  chmodSync(gh, 0o700);
  const diff = join(root, "result.diff");
  return { root, git, base, head, execute(overrides = {}) {
    const result = spawnSync("bash", ["-c", script], { cwd: root, encoding: "utf8",
      env: { ...env, PATH: `${tools}:${env.PATH}`, BASE_SHA: base, HEAD_SHA: head,
        PR: "20", GITHUB_REPOSITORY: "example/project", TEST_DIFF: diff, ...overrides } });
    return { ...result, diff: existsSync(diff) ? readFileSync(diff, "utf8") : "" };
  } };
}

test("300파일 API 제한 없이301파일 전체를 신뢰된 checkout에서 비교한다", (t) => {
  const repo = repository(t, 301);
  const result = repo.execute();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.diff.match(/^diff --git /gm)?.length, 301);
  assert.equal(repo.git("rev-parse", "HEAD"), repo.base);
  assert.match(workflow, /ref: \$\{\{ github\.event\.repository\.default_branch \}\}/);
  assert.match(workflow, /fetch-depth: 0/);
  assert.match(workflow, /persist-credentials: false/);
  assert.match(block, /BASE_SHA: \$\{\{ github\.event\.pull_request\.base\.sha \}\}/);
  assert.match(block, /HEAD_SHA: \$\{\{ github\.event\.pull_request\.head\.sha \}\}/);
});

test("갈라진 base와 전진한 head 대신 이벤트 SHA의 PR 변경만 비교한다", (t) => {
  const repo = repository(t);
  repo.git("switch", "feature");
  writeFileSync(join(repo.root, "future.txt"), "later head\n");
  repo.git("add", "future.txt");
  repo.git("commit", "-m", "test: advance head");
  repo.git("switch", "main");
  writeFileSync(join(repo.root, "base-only.txt"), "later base\n");
  repo.git("add", "base-only.txt");
  repo.git("commit", "-m", "test: advance base");
  const base = repo.git("rev-parse", "HEAD");
  const result = repo.execute({ BASE_SHA: base });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.diff, /notice-0\.txt/);
  assert.doesNotMatch(result.diff, /future\.txt|base-only\.txt/);
  assert.equal(repo.git("rev-parse", "HEAD"), base);
});

test("외부 diff와 textconv를 실행하지 않는다", (t) => {
  const repo = repository(t);
  const marker = join(repo.root, "external-ran");
  const tool = join(repo.root, "poison.sh");
  writeFileSync(tool, "#!/usr/bin/env bash\nprintf 'PRIVATE_TOOL' > external-ran\nexit 99\n");
  chmodSync(tool, 0o700);
  repo.git("config", "diff.external", tool);
  repo.git("config", "diff.poison.textconv", tool);
  writeFileSync(join(repo.root, ".git/info/attributes"), "*.txt diff=poison\n");
  const result = repo.execute();
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.diff, /notice-0\.txt/);
  assert.equal(existsSync(marker), false);
  assert.doesNotMatch(result.diff, /PRIVATE_TOOL/);
});

test("필요한 commit이 없으면 빈 diff를 성공으로 표시하지 않는다", (t) => {
  const repo = repository(t);
  const result = repo.execute({ HEAD_SHA: "f".repeat(40) });
  assert.notEqual(result.status, 0);
  assert.equal(result.diff, "");
  assert.match(result.stderr, /[f]{40}/);
});
