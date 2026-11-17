"""공개 자산의 원본 보존과 포스터 글꼴 파생본 해시를 검사한다."""
from pathlib import Path
import hashlib
import json

root = Path(__file__).resolve().parent.parent
manifest = json.loads((root / "assets/prototype/SOURCE_MANIFEST.json").read_text(encoding="utf-8"))
count = 0
for entry in manifest["source_files"]:
    if entry["path"].startswith("reference-prototype/assets/"):
        data = (root / "assets/posters" / Path(entry["path"]).name).read_bytes()
        assert len(data) == entry["bytes"], entry["path"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["path"]
        count += 1
fixture = (root / "assets/prototype/notices.json").read_bytes()
assert hashlib.sha256(fixture).hexdigest() == manifest["derived_fixture_sha256"]
data = json.loads(fixture)
assert len(data["items"]) == 16 and data["anchor"] == "2026-11-16"
serif = json.loads((root / "assets/fonts/SERIF-SUBSET.json").read_text(encoding="utf-8"))
assert hashlib.sha256((root / "assets/fonts/NotoSerifKR.ttf").read_bytes()).hexdigest() == serif["subset_sha256"]
assert (root / "assets/fonts/OFL.txt").is_file()
assert (root / "assets/fonts/OFL-NotoSerifKR.txt").is_file()
print(f"PASS: {count} original SVG files, 16 fixtures, font subset and licenses")

body = json.loads((root / "assets/fonts/BODY-COMPRESSION.json").read_text(encoding="utf-8"))
assert hashlib.sha256((root / "assets/fonts/NotoSansKR.ttf").read_bytes()).hexdigest() == body["source_sha256"]
assert hashlib.sha256((root / "assets/fonts/NotoSansKR.woff2").read_bytes()).hexdigest() == body["output_sha256"]
print(f"PASS: lossless body WOFF2 {body['output_bytes']} bytes; {body['glyphs']} characters")
