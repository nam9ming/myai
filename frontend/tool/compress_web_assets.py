"""공용 서버 설정 변경 없이 브라우저에서 풀어 읽을 초기 자산을 생성한다."""
from pathlib import Path
import gzip
import hashlib
import json
import re
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "build/web").resolve()
versions = {}
for name in ["main.dart.js", "canvaskit/canvaskit.wasm", "canvaskit/chromium/canvaskit.wasm"]:
    source = root / name
    data = source.read_bytes()
    compressed = gzip.compress(data, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == data
    source.with_suffix(source.suffix + ".gz").write_bytes(compressed)
    versions[name + ".gz"] = hashlib.sha256(compressed).hexdigest()[:16]
    print(f"{name}: {len(data):,} -> {len(compressed):,} bytes")

bootstrap = root / "flutter_bootstrap.js"
text = bootstrap.read_text(encoding="utf-8")
text, count = re.subn(
    r"/\*__YEOGI_STARTUP_ASSETS__\*/\s*\{[^;]*?\}",
    lambda _: "/*__YEOGI_STARTUP_ASSETS__*/ " + json.dumps(versions, separators=(",", ":")),
    text,
)
assert count == 1, "초기 로더의 자산 버전 표시를 찾지 못했습니다."
bootstrap.write_text(text, encoding="utf-8")
