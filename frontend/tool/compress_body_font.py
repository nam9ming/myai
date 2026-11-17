"""본문 가변 글꼴을 글자 손실 없이 WOFF2로 압축한다. fonttools[woff]==4.68.0 필요."""
from pathlib import Path
import hashlib
import json
from fontTools.ttLib import TTFont

root = Path(__file__).resolve().parent.parent
source = root / "assets/fonts/NotoSansKR.ttf"
output = source.with_suffix(".woff2")
font = TTFont(source)
font.flavor = "woff2"
font.save(output)
compressed = TTFont(output)
assert compressed.getBestCmap() == TTFont(source).getBestCmap()
assert compressed["fvar"].compile(compressed) == TTFont(source)["fvar"].compile(TTFont(source))
record = {
    "source": "NotoSansKR.ttf",
    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "output": "NotoSansKR.woff2",
    "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "source_bytes": source.stat().st_size,
    "output_bytes": output.stat().st_size,
    "glyphs": len(font.getBestCmap()),
    "scope": "전체 글자와 가변 굵기 축을 보존한 WOFF2 압축",
    "tool": "fonttools[woff] 4.68.0",
    "license": "OFL.txt",
}
(output.parent / "BODY-COMPRESSION.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(record, ensure_ascii=False))
