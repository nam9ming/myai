import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const cases = [
  ["같은 시민 공개본의 목록·상세 생성 시각이 다르면 계약 검증이 실패한다", (value) => { value.data.created_at = "2026-11-16T18:00:00Z"; }, "citizen-list-response.json"],
  ["시민 상세가 목록과 다른 공개본이면 계약 검증이 실패한다", (value) => { value.snapshot_id = "90000000-0000-4000-8000-000000000001"; }],
  ["미확인 최초 이력에 이전 상태를 만들면 계약 검증이 실패한다", (value) => { value.data.history.entries[0].before = {}; }],
  ["시민 공개 이력에 비공개 검토자를 추가하면 계약 검증이 실패한다", (value) => { value.data.history.entries[0].actor = "synthetic-reviewer"; }],
  ["남은 이력이 없는데 다음 페이지 커서를 만들면 계약 검증이 실패한다", (value) => { value.data.history.window.next_before_version = 1; }],
  ["조회 불가 이력에 정상 페이지와 항목을 남기면 계약 검증이 실패한다", (value) => { value.data.history.status = "unavailable"; }],
  ["시민 추출의 원문 인용이 다르면 계약 검증이 실패한다", (value) => { value.evidence[0].quote = "다른 합성 인용"; }, "citizen-ai-extraction.json"],
  ["시민 추출이 다른 문서를 참조하면 계약 검증이 실패한다", (value) => { value.document_version_id = "90000000-0000-4000-8000-000000000001"; }, "citizen-ai-extraction.json"],
  ["시민 추출 비용의 중복 값은 계약 검증이 실패한다", (value) => { value.items[0].cost = { value: ["합성 비용", "합성 비용"], knowledge: "known", evidence_ids: ["e1"], reason: null }; }, "citizen-ai-extraction.json"],
  ["시민 추출 분류 미상을 미기재로 바꾸면 계약 검증이 실패한다", (value) => { value.items[0].categories = { value: null, knowledge: "not_stated", evidence_ids: [], reason: "분야 미상" }; }, "citizen-ai-extraction.json"],
  ["시민 추출 비용의 상태와 근거 키가 없으면 계약 검증이 실패한다", (value) => { value.items[0].cost = { value: null }; }, "citizen-ai-extraction.json"],
  ["시민 추출 known 제목이 공백이면 계약 검증이 실패한다", (value) => { value.items[0].title.value = "   "; }, "citizen-ai-extraction.json"],
];

for (const [name, mutate, file = "citizen-detail-response.json"] of cases) {
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
    const detail = join(root, "contracts/examples", file);
    const value = JSON.parse(readFileSync(detail, "utf8"));
    mutate(value);
    writeFileSync(detail, JSON.stringify(value));
    const invalid = check();
    assert.equal(invalid.status, 1, invalid.stderr);
  });
}
