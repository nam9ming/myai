// 의존성 없는 최소 린트.
// Git 제외 자료를 빼고 JS 문법과 비밀값 패턴을 검사한다.
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const SELF = join(ROOT, "scripts/lint.mjs");

const SECRET_PATTERNS = [
  [/\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{30,}/, "GitHub 토큰으로 보이는 문자열"],
  [/\bsk-ant-[A-Za-z0-9_-]{30,}/, "Anthropic API 키로 보이는 문자열"],
  [/\bsk-(?:(?:proj-|svcacct-)[A-Za-z0-9_-]{30,}|[A-Za-z0-9]{40,})/, "OpenAI API 키로 보이는 문자열"],
  [/discord(?:app)?\.com\/api\/webhooks\/[0-9]{10,}\//, "Discord webhook URL"],
];

const files = execFileSync("git", ["ls-files", "--cached", "--others", "--exclude-standard", "-z"], {
  cwd: ROOT,
  encoding: "utf8",
}).split("\0").filter(Boolean).map((file) => join(ROOT, file)).filter(existsSync);
const errors = [];

for (const file of files) {
  const rel = relative(ROOT, file);
  const ext = extname(file);

  if (ext === ".mjs" || ext === ".js") {
    try {
      execFileSync(process.execPath, ["--check", file], { stdio: "pipe" });
    } catch (err) {
      errors.push(`${rel}: 문법 오류\n${err.stderr?.toString().trim()}`);
    }
  }

  if (![".mjs", ".js", ".yml", ".yaml", ".json", ".md", ".html", ".sh"].includes(ext)) continue;
  const text = readFileSync(file, "utf8");

  if (file !== SELF) {
    for (const [pattern, label] of SECRET_PATTERNS) {
      if (pattern.test(text)) errors.push(`${rel}: ${label}이 커밋에 포함됨`);
    }
  }
}

if (errors.length) {
  console.error("lint 실패:");
  for (const e of errors) console.error("  - " + e);
  process.exit(1);
}
console.log(`lint ok (${files.length}개 파일 검사)`);
