import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";

// shortcut: 현재는 합성 HTML 시제품만 패키징하며, Flutter 구현 후 웹 빌드로 교체한다.
const html = readFileSync(new URL("../docs/reference/meeting-demo.html", import.meta.url));
const output = new URL("../dist/", import.meta.url);
rmSync(output, { recursive: true, force: true });
mkdirSync(output, { recursive: true });
writeFileSync(new URL("index.html", output), html);
console.log("build ok -> dist/index.html (가상 자료 HTML 시제품; 앱 빌드 아님)");
