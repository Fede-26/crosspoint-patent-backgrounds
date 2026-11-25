#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10", "numpy>=1.26"]
# ///
"""Generate e-reader wallpapers from old public-domain patent drawings taken from
Wikimedia Commons.

Every wallpaper is rendered from the source scan once per target device, so each
size gets its own layout and line weight instead of a rescaled copy:

  crosspoint    480x800    2-bit grayscale BMP, palette 0/85/170/255 (the panel's
                           native levels). CrossPoint draws it without further
                           dithering (lib/GfxRenderer/Bitmap.cpp: "1-bit and
                           2-bit are always native").
  kindle-pw11   1236x1648  2-bit indexed PNG for the Kindle Paperwhite 11th gen (KOReader).
  kindle-pw12   1264x1680  2-bit indexed PNG for the Kindle Paperwhite 12th gen.
                           Every target goes to --out/<target>/ (default docs/files),
                           which is also the folder the GitHub Pages site serves.

The Kindle files are PNG, not BMP, because KOReader's screensaver folder only lists
gif, jpeg, jpg, png, svg, tif, tiff and webp files. An indexed PNG with 4 entries is
also much smaller than a BMP.

Existing wallpapers are kept: the pages already listed in --out/credits.csv are never
re-selected and their files are never overwritten. New ones are appended until
--count wallpapers exist in total. Downloads are kept in --cache, so nothing is fetched
twice.

Usage:
    uv run genera_sfondi.py                       # up to 400 wallpapers, all targets
    uv run genera_sfondi.py --targets crosspoint  # only the 480x800 BMPs
    uv run genera_sfondi.py --white 200 --gamma 0.8 --no-dither
    uv run genera_sfondi.py --help                # every option

Then copy the files of docs/files/crosspoint into /.sleep/ on the microSD card and set
Settings > Display > Sleep Screen = Custom. For KOReader, copy the PNG files of your
Kindle model into a folder and select it under Screen saver > Wallpaper > Screensaver folder.
"""

import argparse
import csv
import json
import random
import re
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

API = "https://commons.wikimedia.org/w/api.php"
# The Wikimedia User-Agent policy asks for a name, a version and a contact (URL or
# email): clients without a contact get stricter rate limits (429).
# Pass the contact with --contact; by default no personal data is sent.
USER_AGENT = "sticky-wallpapers/0.1 (personal script) python-urllib"

# Categories with technical drawings, and how deep to explore their subcategories.
# "Patent drawings" has depth 0: its subcategories include "Clothing patents" and
# "Design patents", which are not technical drawings and are very large.
CATEGORIES = [
    ("Patent drawings in the National Archives and Records Administration", 1),
    ("United States patent drawings", 1),
    ("Aviation patent drawings", 0),
    ("Electronics patent drawings", 0),
    ("Patent drawings", 0),
]

# 1280 is one of the standard Commons thumbnail widths: arbitrary widths can be
# rejected. It is still more than twice the CrossPoint resolution.
THUMB_WIDTH = 1280
LEVELS = (0, 85, 170, 255)  # native gray levels of the SSD1677 panel in CrossPoint

YEAR_RE = re.compile(r"\b(1[78]\d\d|19\d\d)\b")
PAGE_RE = re.compile(r"\(page (\d+)\)")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Target:
    name: str
    width: int
    height: int
    fmt: str  # "bmp" or "png"
    # Source pixels of the line-thickening filter. The CrossPoint render shrinks the
    # scan by about 0.4x, so thin lines need thickening; the Kindle renders are close
    # to 1:1 (or enlarged) and keep the original line weight.
    thicken: int
    # Shown by the gallery site (docs/index.html reads them from docs/devices.json).
    label: str     # device name
    software: str  # the software that shows the sleep screen
    note: str


KOREADER_NOTE = ("PNG files for KOReader. Use Sleep screen \u2192 Wallpaper \u2192 Custom images \u2192 Choose random image folder "
                 "and select the folder with these files.")

# To support another screen, add an entry here and run the script: it renders only the
# missing files, and the gallery lists the new entry without further changes.
TARGETS = {
    "crosspoint": Target("crosspoint", 480, 800, "bmp", 3, "Xteink X4 / Seeed Sticky", "CrossPoint",
                         "Copy the BMPs into a folder named .sleep on the microSD card, then set Sleep Screen "
                         "to Custom."),
    "kindle-pw11": Target("kindle-pw11", 1236, 1648, "png", 0, "Kindle Paperwhite 11th gen", "KOReader",
                          KOREADER_NOTE),
    "kindle-pw12": Target("kindle-pw12", 1264, 1680, "png", 0, "Kindle Paperwhite 12th gen", "KOReader",
                          KOREADER_NOTE),
}


# --------------------------------------------------------------------------- Commons


def http_get(url: str, retries: int = 6) -> bytes:
    """GET that waits and retries on 429 and 5xx.

    Commons rate-limits requests and answers 429 when the limit is exceeded.
    Retry-After is honored when present, otherwise the wait doubles at every attempt.
    """
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code != 429 and exc.code < 500 or attempt == retries - 1:
                raise
            retry_after = exc.headers.get("Retry-After", "")
            wait = int(retry_after) if retry_after.isdigit() else 5 * 2 ** attempt
            print(f"    HTTP {exc.code}, retrying in {wait} s", flush=True)
            time.sleep(wait)
    raise AssertionError("unreachable")


def api_get(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    data = json.loads(http_get(f"{API}?{query}"))
    time.sleep(0.5)  # serial, spaced requests, as the Wikimedia API etiquette asks
    return data


def api_all(params: dict):
    """Iterate over every result page, following the 'continue' field."""
    cont: dict = {}
    while True:
        data = api_get({**params, **cont})
        yield data
        if "continue" not in data:
            return
        cont = data["continue"]


def subcategories(category: str, depth: int) -> list[str]:
    found = [category]
    if depth == 0:
        return found
    params = {"action": "query", "list": "categorymembers", "cmtype": "subcat",
              "cmtitle": f"Category:{category}", "cmlimit": 500}
    for data in api_all(params):
        for m in data["query"]["categorymembers"]:
            # Design patents (ornamental shapes) and clothing are not technical
            # drawings; "Patent Case Files" are text dossiers (over 13,000 files).
            if any(word in m["title"].lower() for word in ("design", "clothing", "case files")):
                continue
            found += subcategories(m["title"].removeprefix("Category:"), depth - 1)
    return found


def category_files(category: str, limit: int) -> list[dict]:
    """First 'limit' files of the category. Some NARA series exceed 25,000 files:
    listing them all would take hundreds of slow requests."""
    params = {
        "action": "query", "generator": "categorymembers", "gcmtype": "file",
        "gcmtitle": f"Category:{category}", "gcmlimit": 50,
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": THUMB_WIDTH,
        "iiextmetadatafilter": "DateTimeOriginal|LicenseShortName|ObjectName",
    }
    files = []
    for data in api_all(params):
        for page in data.get("query", {}).get("pages", []):
            if page.get("imageinfo"):
                files.append(page)
        if len(files) >= limit:
            break
    return files


def meta(info: dict, key: str) -> str:
    value = info.get("extmetadata", {}).get(key, {}).get("value", "")
    return TAG_RE.sub(" ", str(value))


def year_of(page: dict) -> int | None:
    """Year from the original date; failing that, from the title. First match wins."""
    info = page["imageinfo"][0]
    for text in (meta(info, "DateTimeOriginal"), page["title"], meta(info, "ObjectName")):
        match = YEAR_RE.search(text)
        if match:
            return int(match.group(1))
    return None


def is_free(info: dict) -> bool:
    lic = meta(info, "LicenseShortName").lower()
    return "public domain" in lic or "no restrictions" in lic or "cc0" in lic or lic.startswith("pd")


def list_commons(listing: Path, refresh: bool, per_category: int) -> list[dict]:
    """File list of the categories, saved to disk: later runs do not query the API
    again, which is slow and rate-limited."""
    if listing.exists() and not refresh:
        return json.loads(listing.read_text(encoding="utf-8"))
    seen: dict[int, dict] = {}
    cats: list[str] = []
    for cat, depth in CATEGORIES:
        cats += subcategories(cat, depth)
    cats = list(dict.fromkeys(cats))
    for n, cat in enumerate(cats, 1):
        for page in category_files(cat, per_category):
            seen.setdefault(page["pageid"], page)
        print(f"  [{n}/{len(cats)}] {cat}: {len(seen)} files so far", flush=True)
    pages = list(seen.values())
    listing.write_text(json.dumps(pages), encoding="utf-8")
    return pages


def candidates(pages: list[dict], max_year: int) -> list[dict]:
    seen = {page["pageid"]: page for page in pages}

    keep = []
    for page in seen.values():
        info = page["imageinfo"][0]
        year = year_of(page)
        if year is None or year > max_year or not is_free(info):
            continue
        # Portrait sheets only: a landscape sheet would stay tiny on a portrait screen.
        if info["height"] < info["width"] or info["height"] < 1000:
            continue
        # "(cropped)" versions duplicate a full sheet that is already present.
        if "cropped" in page["title"].lower():
            continue
        page["year"] = year
        keep.append(page)

    # One sheet per patent. In the DPLA sets the even pages are the backs of the
    # sheets, almost empty; the NARA sets have a different identifier for each sheet.
    # The key is the title without the "- DPLA -"/"- NARA -" part and the page number;
    # the lowest page wins, i.e. the first sheet, with the overview drawing.
    best: dict[str, dict] = {}
    for page in keep:
        key = re.split(r" - (?:DPLA|NARA) - ", page["title"])[0]
        key = PAGE_RE.sub("", key).strip().lower()
        match = PAGE_RE.search(page["title"])
        page["page_no"] = int(match.group(1)) if match else 1
        if key not in best or page["page_no"] < best[key]["page_no"]:
            best[key] = page
    return list(best.values())


def thumb_url(info: dict) -> str:
    """URL of a standard-width thumbnail, never of the original.

    The originals on upload.wikimedia.org often get 429 even at a low rate,
    the thumbnails do not. Commons does not enlarge, so the width is the largest
    standard one below the original's; 500 is enough for a 480-pixel-wide screen.
    """
    if info["width"] > THUMB_WIDTH:
        return info["thumburl"]
    width = 960 if info["width"] > 960 else 500
    path = urllib.parse.urlparse(info["url"]).path  # /wikipedia/commons/a/ab/Name.ext
    head, _, name = path.rpartition("/")
    thumb = f"{width}px-{name}"
    if name.lower().endswith((".tif", ".tiff")):
        thumb = f"lossy-page1-{width}px-{name}.jpg"  # TIFFs have JPEG thumbnails
    elif name.lower().endswith((".pdf", ".djvu")):
        thumb = f"page1-{width}px-{name}.jpg"  # first page of the document
    return f"https://upload.wikimedia.org{head.replace('/commons/', '/commons/thumb/', 1)}/{name}/{thumb}"


def download(page: dict, cache: Path) -> Path:
    info = page["imageinfo"][0]
    url = thumb_url(info)
    path = cache / f"{page['pageid']}{Path(urllib.parse.urlparse(url).path).suffix.lower()}"
    if not path.exists():
        # Few attempts: an error on a single file must not block the batch.
        path.write_bytes(http_get(url, retries=2))
        time.sleep(0.5)  # courtesy to the Commons servers
    return path


# ----------------------------------------------------------------------- processing


def flatten_paper(gray: np.ndarray) -> np.ndarray:
    """Bring the paper to white by dividing by an estimate of the background.

    The background is estimated with a maximum filter on a shrunk image: the drawing
    lines are thin and vanish, leaving yellowing, stains and scan shadows, which the
    division removes even when they are not uniform.
    """
    h, w = gray.shape
    small = Image.fromarray(gray).resize((max(w // 8, 1), max(h // 8, 1)), Image.BILINEAR)
    bg = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    bg = np.asarray(bg.resize((w, h), Image.BILINEAR), dtype=np.float32)
    return np.clip(gray.astype(np.float32) / np.maximum(bg, 1) * 255, 0, 255)


def stretch_contrast(img: np.ndarray, white: float, black_pct: float, gamma: float) -> np.ndarray:
    """Everything above 'white' becomes pure white; the darkest ink (percentile
    'black_pct' of the non-white pixels) becomes pure black. A gamma below 1
    darkens the midtones, i.e. thickens thin lines."""
    ink = img[img < white]
    black = np.percentile(ink, black_pct) if ink.size else 0
    black = min(black, white - 40)  # avoids an excessive stretch on nearly empty sheets
    norm = np.clip((img - black) / (white - black), 0, 1)
    return norm ** (1 / gamma) * 255 if gamma != 1 else norm * 255


def content_box(img: np.ndarray, trim: float, thr: float = 200) -> tuple[int, int, int, int] | None:
    """Bounding box of the content. On each side it drops the fraction 'trim' of the
    total ink: stains, dust and paper-edge residue sit at the margins and weigh
    little, so they do not widen the box."""
    mask = img < thr
    if not mask.any():
        return None

    def span(counts: np.ndarray) -> tuple[int, int]:
        cum = np.cumsum(counts)
        lo = int(np.searchsorted(cum, cum[-1] * trim))
        hi = int(np.searchsorted(cum, cum[-1] * (1 - trim)))
        return lo, hi + 1

    y0, y1 = span(mask.sum(axis=1))
    x0, x1 = span(mask.sum(axis=0))
    return x0, y0, x1, y1


def prepare(src: Path, opt: argparse.Namespace) -> Image.Image | None:
    """Flatten, stretch and crop the scan. Independent of the target size, so it runs
    once per source image. Returns None for sheets that are not line drawings."""
    gray = np.asarray(Image.open(src).convert("L"))
    if not opt.no_flatten:
        gray = flatten_paper(gray)
    img = stretch_contrast(gray.astype(np.float32), opt.white, opt.black_pct, opt.gamma)
    box = content_box(img, opt.trim)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    img = img[y0:y1, x0:x1]
    # Too much ink: photograph, model or dark scan, not a line drawing.
    # Too little: back of a sheet or blank page with only stains.
    ink = (img < 128).mean()
    if ink > opt.max_ink or ink < opt.min_ink:
        return None
    return Image.fromarray(img.astype(np.uint8))


def render(sheet: Image.Image, opt: argparse.Namespace, target: Target) -> Image.Image:
    # Sheet lines are 2-3 px wide and shrinking to 480x800 brings them under one
    # pixel: they would turn light gray, faded on the panel. The minimum filter widens
    # the ink before the downscale, so the lines stay black.
    if target.thicken > 1:
        sheet = sheet.filter(ImageFilter.MinFilter(target.thicken))
    # The margin is given for 480 px of width and scales with the screen.
    margin = round(opt.margin * target.width / 480)
    # zoom 0: the whole sheet fits. zoom 1: it fills the screen (cover) and the excess
    # sides are cropped. Intermediate values interpolate on a log scale, so 0.5 is
    # perceptually halfway.
    sx = (target.width - 2 * margin) / sheet.width
    sy = (target.height - 2 * margin) / sheet.height
    fit, cover = min(sx, sy), max(sx, sy)
    scale = fit * (cover / fit) ** opt.zoom
    sheet = sheet.resize((round(sheet.width * scale), round(sheet.height * scale)), Image.LANCZOS)
    canvas = Image.new("L", (target.width, target.height), 255)
    # With negative offsets paste crops: the sheet stays centered.
    canvas.paste(sheet, ((target.width - sheet.width) // 2, (target.height - sheet.height) // 2))
    return canvas


def quantize(img: Image.Image, dither: bool, levels: tuple[int, ...] = LEVELS) -> np.ndarray:
    """Reduce to the given levels, with or without Floyd-Steinberg dithering;
    returns the palette indices."""
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for level in levels for v in (level, level, level)] * (256 // len(levels)))
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    idx = np.asarray(img.convert("RGB").quantize(palette=palette, dither=mode))
    # The palette is repeated to fill 256 entries: map each index back to the valid range.
    return (idx % len(levels)).astype(np.uint8)


# ------------------------------------------------------------------------- BMP, PNG


def write_bmp(path: Path, idx: np.ndarray, bits: int = 2) -> None:
    """Uncompressed 1- or 2-bit BMP, rows bottom-up, first pixel in the high bits of
    each byte: the order read by CrossPoint's Bitmap::readNextRow."""
    levels = (0, 255) if bits == 1 else LEVELS
    h, w = idx.shape
    per_byte = 8 // bits
    row_bytes = (w * bits + 31) // 32 * 4
    groups = np.zeros((h, row_bytes * per_byte), dtype=np.uint8)
    groups[:, :w] = idx
    groups = groups.reshape(h, row_bytes, per_byte)
    packed = np.zeros((h, row_bytes), dtype=np.uint8)
    for i in range(per_byte):
        packed |= groups[..., i] << (8 - bits * (i + 1))
    pixels = packed[::-1].tobytes()

    palette = b"".join(bytes((v, v, v, 0)) for v in levels)  # BGRA
    offset = 14 + 40 + len(palette)
    header = struct.pack("<2sIHHI", b"BM", offset + len(pixels), 0, 0, offset)
    info = struct.pack("<IiiHHIIiiII", 40, w, h, 1, bits, 0, len(pixels), 2835, 2835,
                       len(levels), len(levels))
    path.write_bytes(header + info + palette + pixels)


def write_png(path: Path, idx: np.ndarray) -> None:
    """2-bit indexed PNG with a 4-entry gray palette, the smallest standard layout for
    4 gray levels. The palette is the same as the BMP's, so the two look alike."""
    img = Image.fromarray(idx, "P")
    img.putpalette([v for level in LEVELS for v in (level, level, level)])
    img.save(path, format="PNG", bits=2, optimize=True, compress_level=9)


def read_bmp(path: Path) -> np.ndarray:
    """Read back a BMP written by write_bmp and return the grays; used to check that
    the file decodes the way CrossPoint decodes it."""
    data = path.read_bytes()
    offset, = struct.unpack_from("<I", data, 10)
    _, w, h, planes, bits, comp = struct.unpack_from("<IiiHHI", data, 14)
    assert planes == 1 and bits in (1, 2) and comp == 0, (planes, bits, comp)
    lum = [data[54 + 4 * i] for i in range(2 ** bits)]
    row_bytes = (w * bits + 31) // 32 * 4
    rows = np.frombuffer(data, np.uint8, row_bytes * h, offset).reshape(h, row_bytes)[::-1]
    mask = (1 << bits) - 1
    shifts = range(8 - bits, -1, -bits)
    idx = np.stack([(rows >> s) & mask for s in shifts], axis=-1).reshape(h, -1)[:, :w]
    return np.take(lum, idx).astype(np.uint8)


def contact_sheet(paths: list[Path], out: Path, cols: int, divisor: int) -> None:
    if not paths:
        return
    cw, ch = TARGETS["crosspoint"].width // divisor, TARGETS["crosspoint"].height // divisor
    thumbs = [Image.fromarray(read_bmp(p)).resize((cw, ch), Image.LANCZOS) for p in paths]
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("L", (cols * (cw + 6), rows * (ch + 6)), 128)
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * (cw + 6) + 3, (i // cols) * (ch + 6) + 3))
    sheet.save(out, optimize=True)


# ----------------------------------------------------------------------------- main


def read_credits(path: Path) -> list[list[str]]:
    """Rows of an existing credits.csv, without the header (old Italian headers
    included: the rows are read by position)."""
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [row for row in list(csv.reader(f))[1:] if row]


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=400,
                    help="total number of wallpapers, existing ones included (default 400)")
    ap.add_argument("--targets", nargs="+", choices=sorted(TARGETS), default=list(TARGETS),
                    help="devices to render for (default: all)")
    ap.add_argument("--seed", type=int, default=1, help="change the seed for another selection")
    ap.add_argument("--max-year", type=int, default=1940,
                    help="discard patents newer than this year or without a date (default 1940)")
    ap.add_argument("--white", type=float, default=215,
                    help="white point 0-255: above it becomes pure white; lower = cleaner paper "
                         "but light lines are lost (default 215)")
    ap.add_argument("--black-pct", type=float, default=2,
                    help="percentile of the ink brought to pure black; higher = more contrast (default 2)")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="gamma of the midtones; < 1 darkens and thickens lines (default 1.0)")
    ap.add_argument("--margin", type=int, default=6,
                    help="minimum white border in pixels at 480 px of width; scaled for larger "
                         "screens (default 6)")
    ap.add_argument("--zoom", type=float, default=0.5,
                    help="0 = whole sheet with white bands, 1 = fills the screen cropping the sides "
                         "(default 0.5)")
    ap.add_argument("--trim", type=float, default=0.01,
                    help="fraction of ink ignored on each side when cropping; higher = "
                         "tighter crop (default 0.01)")
    ap.add_argument("--max-ink", type=float, default=0.30,
                    help="maximum fraction of dark pixels; above it the image is discarded as a photo "
                         "(default 0.30)")
    ap.add_argument("--min-ink", type=float, default=0.004,
                    help="minimum fraction of dark pixels; below it the sheet is discarded as empty "
                         "(default 0.004)")
    ap.add_argument("--thicken", type=int, choices=(0, 3, 5, 7), default=None,
                    help="thickens lines before the downscale of the 480x800 renders (filter side "
                         "in source pixels); higher = blacker, thicker lines, 0 = off (default 3). "
                         "The Kindle renders are never thickened")
    ap.add_argument("--dither", action="store_true",
                    help="Floyd-Steinberg dithering on the PNGs (the CrossPoint BMPs always use it "
                         "unless --no-dither); makes the files larger")
    ap.add_argument("--no-dither", action="store_true",
                    help="quantize the CrossPoint BMPs without dithering (sharper lines)")
    ap.add_argument("--no-flatten", action="store_true",
                    help="do not normalize the paper background (contrast stretch only)")
    ap.add_argument("--out", type=Path, default=here / "docs" / "files",
                    help="output folder: one subfolder per target, plus credits.csv (default docs/files)")
    ap.add_argument("--cache", type=Path, default=here / "cache", help="download folder")
    ap.add_argument("--contact", default="",
                    help="contact (URL or email) for the User-Agent, as Wikimedia asks; "
                         "reduces 429 rejections")
    ap.add_argument("--per-category", type=int, default=400,
                    help="maximum files listed per Commons category (default 400); "
                         "only applies with --refresh or on the first run")
    ap.add_argument("--refresh", action="store_true",
                    help="reread the file list from Commons instead of using the saved one")
    ap.add_argument("--preview-cols", type=int, default=20, help="columns of the preview image (default 20)")
    ap.add_argument("--preview-divisor", type=int, default=5,
                    help="thumbnail size in the preview, as 480x800 divided by this (default 5)")
    args = ap.parse_args()
    if args.contact:
        global USER_AGENT
        USER_AGENT = f"sticky-wallpapers/0.1 ({args.contact}) python-urllib"

    targets = [TARGETS[name] for name in args.targets]
    if args.thicken is not None:
        targets = [replace(t, thicken=args.thicken) if t.width == 480 else t for t in targets]

    def out_path(target: Target, stem: str) -> Path:
        return args.out / target.name / f"{stem}.{target.fmt}"

    for target in targets:
        out_path(target, "x").parent.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)

    pages = list_commons(args.cache / "listing.json", args.refresh, args.per_category)
    by_id = {page["pageid"]: page for page in pages}
    pool = candidates(pages, args.max_year)
    print(f"candidates after the filters: {len(pool)}")

    # Wallpapers from earlier runs come first and keep their file name: only the
    # missing target files are rendered for them.
    credits_path = args.out / "credits.csv"
    credits = read_credits(credits_path)[:args.count]
    jobs: list[tuple[str, dict]] = []  # (file stem, Commons page) of the existing wallpapers
    for row in credits:
        page = by_id.get(int(row[1]))
        if page is None:
            raise SystemExit(f"{row[0]}: page {row[1]} is not in the saved listing; run with --refresh")
        jobs.append((Path(row[0]).stem, page))
    used = {int(row[1]) for row in credits}
    random.Random(args.seed).shuffle(pool)
    pool = [page for page in pool if page["pageid"] not in used]

    # Some files always fail (for example persistent 429s on certain TIFFs): they are
    # remembered, so that each run does not waste minutes waiting on them.
    failed_list = args.cache / "falliti.txt"
    failed = set(failed_list.read_text().split()) if failed_list.exists() else set()
    # Manual exclusions: one pageid per line (the "pageid" column of credits.csv).
    excluded_list = here / "esclusi.txt"
    if excluded_list.exists():
        failed |= {line.split("#")[0].strip() for line in excluded_list.read_text().splitlines()}

    def write_credits() -> None:
        with open(credits_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows([["file", "pageid", "title", "year", "license", "source"], *credits])

    def process(stem: str, page: dict, existing: bool) -> bool:
        """Render the missing files of one wallpaper; False if the sheet is rejected.
        Existing wallpapers only get the files that are not on disk yet."""
        todo = [t for t in targets if not (existing and out_path(t, stem).exists())]
        if not todo:
            return True
        try:
            sheet = prepare(download(page, args.cache), args)
        except Exception as exc:  # a single broken image must not stop the batch
            if existing:
                raise
            print(f"  skipping {page['title']}: {exc}")
            with open(failed_list, "a") as f:
                f.write(f"{page['pageid']}\n")
            return False
        if sheet is None:
            if existing:
                raise SystemExit(f"{stem} no longer passes the filters: do not change them on an existing set")
            print(f"  discarded (blank or not a line drawing): {page['title']}")
            return False
        for target in todo:
            canvas = render(sheet, args, target)
            if target.fmt == "bmp":
                write_bmp(out_path(target, stem), quantize(canvas, not args.no_dither))
            else:
                write_png(out_path(target, stem), quantize(canvas, args.dither))
        return True

    for stem, page in jobs:
        process(stem, page, True)

    n_new = 0
    for page in pool:
        if len(credits) >= args.count:
            break
        if str(page["pageid"]) in failed:
            continue
        stem = f"patent_{len(credits) + 1:02d}"
        if not process(stem, page, False):
            continue
        info = page["imageinfo"][0]
        credits.append([f"{stem}.bmp", page["pageid"], page["title"].removeprefix("File:"), page["year"],
                        meta(info, "LicenseShortName").strip(), info["descriptionurl"]])
        write_credits()  # saved after every new wallpaper, so an interrupted run can resume
        n_new += 1
        print(f"{stem}  {page['year']}  {page['title'][5:80]}", flush=True)

    write_credits()
    # The gallery reads its list of devices from here, so it follows TARGETS.
    devices = [{"key": t.name, "label": t.label, "software": t.software, "size": f"{t.width}\u00d7{t.height}", "ext": t.fmt, "note": t.note}
               for t in TARGETS.values()]
    (args.out.parent / "devices.json").write_text(json.dumps(devices, ensure_ascii=False, indent=1), encoding="utf-8")
    made = [args.out / "crosspoint" / row[0] for row in credits]
    if all(p.exists() for p in made):  # the preview is drawn from the CrossPoint BMPs
        contact_sheet(made, here / "anteprima.png", args.preview_cols, args.preview_divisor)
    print(f"\n{len(credits)} wallpapers ({n_new} new) in {args.out}; preview in {here / 'anteprima.png'}")
    if len(credits) < args.count:
        print(f"WARNING: {args.count} requested, only {len(credits)} valid candidates found")


if __name__ == "__main__":
    main()
