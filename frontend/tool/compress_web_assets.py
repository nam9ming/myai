"""공용 서버 설정 변경 없이 브라우저에서 풀어 읽을 초기 자산을 생성한다."""
from pathlib import Path
import gzip
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "build/web").resolve()
for name in ["main.dart.js", "canvaskit/canvaskit.wasm", "canvaskit/chromium/canvaskit.wasm"]:
    source = root / name
    data = source.read_bytes()
    compressed = gzip.compress(data, compresslevel=9, mtime=0)
    assert gzip.decompress(compressed) == data
    source.with_suffix(source.suffix + ".gz").write_bytes(compressed)
    print(f"{name}: {len(data):,} -> {len(compressed):,} bytes")
