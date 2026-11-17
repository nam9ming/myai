import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const cases = [
  ["시민 상세가 목록과 다른 공개본이면 계약 검증이 실패한다", (value) => { value.snapshot_id = "90000000-0000-4000-8000-000000000001"; }],
  ["미확인 최초 이력에 이전 상태를 만들면 계약 검증이 실패한다", (value) => { value.data.history.entries[0].before = {}; }],
  ["시민 공개 이력에 비공개 검토자를 추가하면 계약 검증이 실패한다", (value) => { value.data.history.entries[0].actor = "synthetic-reviewer"; }],
];

for (const [name, mutate] of cases) {
  test(name, (t) => {
    const root = mkdtempSync(join(tmpdir(), "myai-citizen-contract-"));
    t.after(() => rmSync(root, { recursive: true, force: true }));
    mkdirSync(join(root, "contracts"));
    mkdirSync(join(root, "backend/examples"), { recursive: true });
    cpSync(new URL("../contracts/examples", import.meta.url), join(root, "contracts/examples"), { recursive: true });
    for (const file of ["reviewed-import.json", "citizen-reviewed-import.json"]) {
      copyFileSync(new URL(`../backend/examples/${file}`, import.meta.url), join(root, "backend/examples", file));
    }
    const script = join(root, "contracts/validate_examples.py");
    copyFileSync(new URL("../contracts/validate_examples.py", import.meta.url), script);
    const check = () => spawnSync("python3", [script], { encoding: "utf8" });
    const valid = check();
    assert.equal(valid.status, 0, valid.stderr);
    const detail = join(root, "contracts/examples/citizen-detail-response.json");
    const value = JSON.parse(readFileSync(detail, "utf8"));
    mutate(value);
    writeFileSync(detail, JSON.stringify(value));
    const invalid = check();
    assert.equal(invalid.status, 1, invalid.stderr);
  });
}
