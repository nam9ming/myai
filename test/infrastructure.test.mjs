import test from "node:test";
import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

test("프리뷰 빌드는 기존 산출물을 지우고 공개 시제품 HTML만 내보낸다", (t) => {
  const root = mkdtempSync(join(tmpdir(), "myai-build-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const dir of ["scripts", "docs/reference", "dist", "data/private"]) {
    mkdirSync(join(root, dir), { recursive: true });
  }
  const html = "<!doctype html><html lang=\"ko\"><body>가상 자료 시제품</body></html>";
  writeFileSync(join(root, "docs/reference/meeting-demo.html"), html);
  writeFileSync(join(root, "dist/old.html"), "지난 빌드");
  writeFileSync(join(root, ".env"), "PRIVATE_VALUE=local-only");
  writeFileSync(join(root, "data/private/source.txt"), "비공개 원문");
  copyFileSync(new URL("../scripts/build.mjs", import.meta.url), join(root, "scripts/build.mjs"));

  execFileSync(process.execPath, [join(root, "scripts/build.mjs")]);

  assert.deepEqual(readdirSync(join(root, "dist")), ["index.html"]);
  assert.equal(readFileSync(join(root, "dist/index.html"), "utf8"), html);
  assert.equal(readFileSync(join(root, "data/private/source.txt"), "utf8"), "비공개 원문");
});

test("린트는 Git 제외 자료를 읽지 않고 공개 파일의 토큰 패턴을 거부한다", (t) => {
  const root = mkdtempSync(join(tmpdir(), "myai-lint-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "scripts"));
  mkdirSync(join(root, ".venv"));
  execFileSync("git", ["init", "--quiet", root]);
  writeFileSync(join(root, ".gitignore"), ".env\n.venv/\n");
  const token = "ghp_" + "x".repeat(40);
  writeFileSync(join(root, ".env"), token);
  writeFileSync(join(root, ".venv/invalid.js"), "this is invalid JS !!!");
  copyFileSync(new URL("../scripts/lint.mjs", import.meta.url), join(root, "scripts/lint.mjs"));
  const lint = () => spawnSync(process.execPath, [join(root, "scripts/lint.mjs")], { encoding: "utf8" });

  const clean = lint();
  assert.equal(clean.status, 0, clean.stderr);

  writeFileSync(join(root, "public.md"), token);
  const leaked = lint();
  assert.equal(leaked.status, 1);
  assert.match(leaked.stderr, /public\.md: GitHub/);
});
