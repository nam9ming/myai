"""원본 SVG에서 사용하는 serif 글자만 남긴다. 앱 실행에는 Python이 필요하지 않다."""
from argparse import ArgumentParser
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET
from fontTools import subset
from fontTools.ttLib import TTFont

parser = ArgumentParser()
parser.add_argument("source", type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parent.parent
text = "".join(chr(c) for c in range(32, 127))
for path in sorted((root / "assets/posters").glob("*.svg")):
    for node in ET.parse(path).getroot().iter():
        if node.attrib.get("font-family") == "serif":
            text += "".join(node.itertext())
font = TTFont(args.source)
for record in font["name"].names:
    if record.nameID in (1, 4, 6, 16):
        record.string = "YeogiPosterSerif".encode(record.getEncoding())
options = subset.Options()
subsetter = subset.Subsetter(options=options)
subsetter.populate(text=text)
subsetter.subset(font)
output = root / "assets/fonts/NotoSerifKR.ttf"
font.save(output)
record = {
    "source": "https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifkr/NotoSerifKR%5Bwght%5D.ttf",
    "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
    "subset_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    "family": "YeogiPosterSerif",
    "tool": "fonttools 4.68.0",
    "scope": "원본 SVG의 serif text 및 ASCII. 제품 본문에는 사용하지 않는다.",
    "glyph_characters": "".join(sorted(set(text))),
    "license": "OFL-NotoSerifKR.txt",
}
(root / "assets/fonts/SERIF-SUBSET.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Poster font subset: {output.stat().st_size} bytes")
