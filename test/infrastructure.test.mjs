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

  for (const [value, label] of [
    [token, /public\.md: GitHub/],
    ["sk-" + "proj-" + "x".repeat(80), /public\.md: OpenAI/],
    ["sk-" + "svcacct-" + "x".repeat(80), /public\.md: OpenAI/],
    ["sk-" + "x".repeat(48), /public\.md: OpenAI/],
  ]) {
    writeFileSync(join(root, "public.md"), value);
    const leaked = lint();
    assert.equal(leaked.status, 1);
    assert.match(leaked.stderr, label);
  }
});

test("사실 전용 상세 예제의 계산값·근거·출처 불일치를 거부한다", async (t) => {
  const root = mkdtempSync(join(tmpdir(), "myai-contracts-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "contracts/examples"), { recursive: true });
  mkdirSync(join(root, "backend/examples"), { recursive: true });
  const folder = new URL("../contracts/examples/", import.meta.url);
  for (const name of readdirSync(folder)) copyFileSync(new URL(name, folder), join(root, "contracts/examples", name));
  copyFileSync(new URL("../contracts/validate_examples.py", import.meta.url), join(root, "contracts/validate_examples.py"));
  copyFileSync(new URL("../backend/examples/reviewed-import.json", import.meta.url), join(root, "backend/examples/reviewed-import.json"));
  const file = join(root, "contracts/examples/event-facts-response.json");
  const original = readFileSync(file, "utf8");
  const validate = () => spawnSync("python3", [join(root, "contracts/validate_examples.py")], { encoding: "utf8" });
  assert.equal(validate().status, 0);
  for (const [label, mutate] of [
    ["I02 계산값", (event) => { event.classification = "candidate"; }],
    ["잘못된 인용", (event) => { event.evidence[0].quote = "원문에 없는 문장"; }],
    ["미상과 빈 배열 혼동", (event) => { event.exceptions = []; }],
    ["미등록 문서 버전", (event) => { event.source_refs[0].document_version_id = "00000000-0000-4000-8000-000000000000"; }],
    ["FieldValue 상태", (event) => { event.field_values.exceptions.knowledge = "invalid_enum"; }],
    ["FieldValue 필수 키", (event) => { delete event.field_values.exceptions.reason; }],
    ["FieldValue 필드 누락", (event) => { delete event.field_values.exceptions; }],
    ["생애 상태 근거", (event) => { event.lifecycle_evidence_ids = ["missing-evidence"]; }],
    ["취소 근거 누락", (event) => { event.lifecycle = "cancelled"; event.lifecycle_evidence_ids = []; }],
    ["snapshot UUID", (_, envelope) => { envelope.snapshot_id = "invalid-id"; }],
    ["revision UUID", (event) => { event.revision_id = "invalid-id"; }],
    ["응답 시각", (_, envelope) => { envelope.generated_at = "invalid-time"; }],
  ]) {
    await t.test(label, () => {
      const broken = JSON.parse(original);
      mutate(broken.data.event, broken);
      writeFileSync(file, JSON.stringify(broken));
      assert.equal(validate().status, 1);
    });
  }
});
