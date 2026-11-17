"""브라우저를 열지 않고 빌드의 로컬 정적 자산 경로를 확인한다."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.request import urlopen
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else "build/web").resolve()
paths = ["index.html", "flutter_bootstrap.js", "main.dart.js", "canvaskit/canvaskit.wasm", "assets/assets/fonts/NotoSansKR.woff2", "assets/assets/fonts/NotoSerifKR.ttf", "assets/assets/posters/books.svg"]
for path in paths:
    assert (root / path).is_file(), path
assert "A new Flutter project" not in (root / "index.html").read_text(encoding="utf-8")
assert "canvasKitBaseUrl" in (root / "flutter_bootstrap.js").read_text(encoding="utf-8")
server = ThreadingHTTPServer(("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(root)))
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    for path in paths:
        with urlopen(f"http://127.0.0.1:{server.server_port}/{path}", timeout=10) as response:
            assert response.status == 200
            assert response.read() == (root / path).read_bytes()
finally:
    server.shutdown()
    server.server_close()
    thread.join()
print("PASS: 7 static routes, local CanvasKit/fonts/SVG; no browser or screen control")
