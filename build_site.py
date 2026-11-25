#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10"]
# ///
"""Prepare the GitHub Pages gallery.

genera_sfondi.py writes the wallpapers to docs/files/<target>/ together with
docs/files/credits.csv. This script adds, from those files:

  docs/data.json         one entry per wallpaper: id, cleaned title, year, source page
  docs/thumbs/<id>.webp  preview shown in the gallery

index.html, style.css and gallery.js are written by hand and are not touched here.

Usage:
    uv run build_site.py
"""

import csv
import json
import re
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
DOCS = HERE / "docs"
FILES = DOCS / "files"
THUMB_SIZE = (300, 500)  # about 2x the size of a gallery card, for high-DPI screens


def clean_title(raw: str) -> str:
    """Commons file name -> readable title: drops the archive id, the page number, the
    extension and the 'Patent Drawing for' prefix that most NARA titles share."""
    title = re.split(r" - (?:DPLA|NARA) - ", raw)[0]
    title = re.sub(r"\.(jpe?g|png|tiff?|pdf)$", "", title, flags=re.I)
    title = re.sub(r"\s*\(page \d+\)", "", title)
    title = re.sub(r"^Patent Drawing for\s+", "", title, flags=re.I)
    return title.strip()


def main() -> None:
    with open(FILES / "credits.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]

    (DOCS / "thumbs").mkdir(parents=True, exist_ok=True)
    data = []
    for file, _pageid, title, year, _license, source in rows:
        stem = Path(file).stem
        data.append({"id": stem, "title": clean_title(title), "year": int(year), "source": source})
        thumb = DOCS / "thumbs" / f"{stem}.webp"
        if not thumb.exists():
            img = Image.open(FILES / "png-480x800" / f"{stem}.png").convert("L")
            img.thumbnail(THUMB_SIZE, Image.LANCZOS)
            img.save(thumb, quality=70, method=6)
    (DOCS / "data.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (DOCS / ".nojekyll").touch()  # no Jekyll processing: files are served as they are

    print(f"{len(data)} wallpapers: data and thumbnails in {DOCS}")


if __name__ == "__main__":
    main()
