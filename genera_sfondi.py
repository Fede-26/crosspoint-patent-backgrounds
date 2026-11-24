#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pillow>=10", "numpy>=1.26"]
# ///
"""Genera sfondi di sospensione per CrossPoint sul Seeed Sticky partendo da vecchi
disegni di brevetto di pubblico dominio presi da Wikimedia Commons.

Uscita: BMP 480x800 (verticale) a 2 bit con palette di 4 grigi 0/85/170/255, cioè
i livelli nativi del pannello, oppure a 1 bit (bianco e nero) con --bits 1.
CrossPoint li disegna senza ulteriore dithering
(lib/GfxRenderer/Bitmap.cpp: "1-bit and 2-bit are always native").

Uso:
    uv run genera_sfondi.py                       # 100 sfondi in ./sleep
    uv run genera_sfondi.py --count 40 --seed 7   # altra selezione
    uv run genera_sfondi.py --white 200 --gamma 0.8 --no-dither
    uv run genera_sfondi.py --help                # tutti i controlli

Poi copia i .bmp nella cartella /.sleep/ della microSD e imposta
Settings > Display > Sleep Screen = Custom.
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
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

API = "https://commons.wikimedia.org/w/api.php"
# La User-Agent policy di Wikimedia chiede nome, versione e un contatto (URL o
# email): i client senza contatto ricevono limiti di frequenza più severi (429).
# Il contatto si passa con --contact; per default non si inviano dati personali.
USER_AGENT = "sticky-wallpapers/0.1 (personal script) python-urllib"

# Categorie con disegni tecnici e profondità delle sottocategorie da esplorare.
# "Patent drawings" ha profondità 0: le sue sottocategorie includono "Clothing
# patents" e "Design patents", che non sono disegni tecnici e sono molto grandi.
CATEGORIES = [
    ("Patent drawings in the National Archives and Records Administration", 1),
    ("United States patent drawings", 1),
    ("Aviation patent drawings", 0),
    ("Electronics patent drawings", 0),
    ("Patent drawings", 0),
]

WIDTH, HEIGHT = 480, 800
# 1280 è una delle larghezze standard delle miniature Commons: le larghezze arbitrarie
# possono essere rifiutate. È comunque più del doppio della risoluzione finale.
THUMB_WIDTH = 1280
LEVELS = (0, 85, 170, 255)  # livelli nativi del pannello SSD1677 in CrossPoint

YEAR_RE = re.compile(r"\b(1[78]\d\d|19\d\d)\b")
PAGE_RE = re.compile(r"\(page (\d+)\)")
TAG_RE = re.compile(r"<[^>]+>")


# --------------------------------------------------------------------------- Commons


def http_get(url: str, retries: int = 6) -> bytes:
    """GET con attesa e nuovo tentativo su 429 e 5xx.

    Commons limita la frequenza delle richieste e risponde 429 quando la si supera.
    Si rispetta Retry-After se presente, altrimenti l'attesa raddoppia a ogni tentativo.
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
            print(f"    HTTP {exc.code}, riprovo tra {wait} s", flush=True)
            time.sleep(wait)
    raise AssertionError("non raggiungibile")


def api_get(params: dict) -> dict:
    query = urllib.parse.urlencode({**params, "format": "json", "formatversion": 2})
    data = json.loads(http_get(f"{API}?{query}"))
    time.sleep(0.5)  # richieste in serie e distanziate, come chiede l'etichetta API di Wikimedia
    return data


def api_all(params: dict):
    """Itera su tutte le pagine di risultati seguendo il campo 'continue'."""
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
            # Design patents (forme estetiche) e vestiario non sono disegni tecnici;
            # i "Patent Case Files" sono fascicoli di testo (oltre 13.000 file).
            if any(word in m["title"].lower() for word in ("design", "clothing", "case files")):
                continue
            found += subcategories(m["title"].removeprefix("Category:"), depth - 1)
    return found


def category_files(category: str, limit: int) -> list[dict]:
    """Primi 'limit' file della categoria. Alcune serie NARA superano i 25.000 file:
    elencarle tutte richiederebbe centinaia di richieste lente."""
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
    """Anno dalla data originale; in mancanza, dal titolo. Il primo trovato vince."""
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
    """Elenco dei file delle categorie, salvato su disco: le esecuzioni successive
    non interrogano più l'API, che è lenta e limitata in frequenza."""
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
        print(f"  [{n}/{len(cats)}] {cat}: {len(seen)} file finora", flush=True)
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
        # Solo fogli verticali: un foglio orizzontale in 480x800 resterebbe minuscolo.
        if info["height"] < info["width"] or info["height"] < 1000:
            continue
        # Le versioni "(cropped)" duplicano un foglio intero già presente.
        if "cropped" in page["title"].lower():
            continue
        page["year"] = year
        keep.append(page)

    # Un solo foglio per brevetto. Nei set DPLA le pagine pari sono i retri dei
    # fogli, quasi vuoti; i set NARA hanno un identificativo diverso per foglio.
    # La chiave è il titolo senza la parte "- DPLA -"/"- NARA -" e il numero di pagina;
    # vince la pagina più bassa, cioè il primo foglio con il disegno d'insieme.
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
    """URL di una miniatura di larghezza standard, mai dell'originale.

    Gli originali su upload.wikimedia.org ricevono spesso 429 anche a ritmo basso,
    le miniature no. Commons non ingrandisce, quindi la larghezza è la più grande
    fra quelle standard minore dell'originale; 500 basta per uno schermo largo 480.
    """
    if info["width"] > THUMB_WIDTH:
        return info["thumburl"]
    width = 960 if info["width"] > 960 else 500
    path = urllib.parse.urlparse(info["url"]).path  # /wikipedia/commons/a/ab/Nome.ext
    head, _, name = path.rpartition("/")
    thumb = f"{width}px-{name}"
    if name.lower().endswith((".tif", ".tiff")):
        thumb = f"lossy-page1-{width}px-{name}.jpg"  # i TIFF hanno miniature JPEG
    elif name.lower().endswith((".pdf", ".djvu")):
        thumb = f"page1-{width}px-{name}.jpg"  # prima pagina del documento
    return f"https://upload.wikimedia.org{head.replace('/commons/', '/commons/thumb/', 1)}/{name}/{thumb}"


def download(page: dict, cache: Path) -> Path:
    info = page["imageinfo"][0]
    url = thumb_url(info)
    path = cache / f"{page['pageid']}{Path(urllib.parse.urlparse(url).path).suffix.lower()}"
    if not path.exists():
        # Pochi tentativi: un errore su un singolo file non deve bloccare il lotto.
        path.write_bytes(http_get(url, retries=2))
        time.sleep(0.5)  # cortesia verso i server Commons
    return path


# --------------------------------------------------------------------- elaborazione


def flatten_paper(gray: np.ndarray) -> np.ndarray:
    """Porta la carta a bianco dividendo per una stima dello sfondo.

    Lo sfondo si stima con un filtro di massimo su un'immagine ridotta: le linee
    del disegno sono sottili e spariscono, restano ingiallimento, macchie e
    ombre di scansione, che la divisione elimina anche se non sono uniformi.
    """
    h, w = gray.shape
    small = Image.fromarray(gray).resize((max(w // 8, 1), max(h // 8, 1)), Image.BILINEAR)
    bg = small.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
    bg = np.asarray(bg.resize((w, h), Image.BILINEAR), dtype=np.float32)
    return np.clip(gray.astype(np.float32) / np.maximum(bg, 1) * 255, 0, 255)


def stretch_contrast(img: np.ndarray, white: float, black_pct: float, gamma: float) -> np.ndarray:
    """Tutto ciò che supera 'white' diventa bianco puro; l'inchiostro più scuro
    (percentile 'black_pct' dei pixel non bianchi) diventa nero puro. Una gamma
    minore di 1 scurisce i toni intermedi, cioè ispessisce le linee sottili."""
    ink = img[img < white]
    black = np.percentile(ink, black_pct) if ink.size else 0
    black = min(black, white - 40)  # evita uno stretch esagerato su fogli quasi vuoti
    norm = np.clip((img - black) / (white - black), 0, 1)
    return norm ** (1 / gamma) * 255 if gamma != 1 else norm * 255


def content_box(img: np.ndarray, trim: float, thr: float = 200) -> tuple[int, int, int, int] | None:
    """Riquadro del contenuto. Su ogni lato scarta la frazione 'trim' dell'inchiostro
    totale: macchie, polvere e residui del bordo della carta stanno ai margini e
    pesano poco, quindi non allargano il riquadro."""
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


def render(src: Path, opt: argparse.Namespace) -> Image.Image | None:
    gray = np.asarray(Image.open(src).convert("L"))
    if not opt.no_flatten:
        gray = flatten_paper(gray)
    img = stretch_contrast(gray.astype(np.float32), opt.white, opt.black_pct, opt.gamma)
    box = content_box(img, opt.trim)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    img = img[y0:y1, x0:x1]
    # Troppo inchiostro: fotografia, modello o scansione scura, non un disegno al tratto.
    # Troppo poco: retro del foglio o pagina bianca con sole macchie.
    ink = (img < 128).mean()
    if ink > opt.max_ink or ink < opt.min_ink:
        return None

    sheet = Image.fromarray(img.astype(np.uint8))
    # Le linee del foglio sono larghe 2-3 px e la riduzione a 480x800 le porta sotto
    # il pixel: diventerebbero grigio chiaro, sbiadite sul pannello. Il filtro di
    # minimo allarga l'inchiostro prima della riduzione, così le linee restano nere.
    if opt.thicken > 1:
        sheet = sheet.filter(ImageFilter.MinFilter(opt.thicken))
    # zoom 0: il foglio entra intero (fit). zoom 1: riempie lo schermo (cover) e i
    # lati in eccesso vengono tagliati. I valori intermedi interpolano in scala
    # logaritmica, così 0.5 è a metà strada percettivamente.
    sx = (WIDTH - 2 * opt.margin) / sheet.width
    sy = (HEIGHT - 2 * opt.margin) / sheet.height
    fit, cover = min(sx, sy), max(sx, sy)
    scale = fit * (cover / fit) ** opt.zoom
    sheet = sheet.resize((round(sheet.width * scale), round(sheet.height * scale)), Image.LANCZOS)
    canvas = Image.new("L", (WIDTH, HEIGHT), 255)
    # Con offset negativi paste ritaglia: il foglio resta centrato.
    canvas.paste(sheet, ((WIDTH - sheet.width) // 2, (HEIGHT - sheet.height) // 2))
    return canvas


def levels_for(bits: int) -> tuple[int, ...]:
    """1 bit: bianco e nero puro. 2 bit: i 4 grigi nativi del pannello."""
    return (0, 255) if bits == 1 else LEVELS


def quantize(img: Image.Image, dither: bool, bits: int) -> np.ndarray:
    """Riduce ai livelli di 'bits', con o senza dithering Floyd-Steinberg;
    restituisce gli indici della palette."""
    levels = levels_for(bits)
    palette = Image.new("P", (1, 1))
    palette.putpalette([v for level in levels for v in (level, level, level)] * (256 // len(levels)))
    mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    idx = np.asarray(img.convert("RGB").quantize(palette=palette, dither=mode))
    # La palette è ripetuta per riempire 256 voci: riporta ogni indice nell'intervallo valido.
    return (idx % len(levels)).astype(np.uint8)


# ------------------------------------------------------------------------------ BMP


def write_bmp(path: Path, idx: np.ndarray, bits: int) -> None:
    """BMP a 1 o 2 bit non compresso, righe dal basso, primo pixel nei bit alti di
    ogni byte: è l'ordine letto da Bitmap::readNextRow di CrossPoint."""
    levels = levels_for(bits)
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


def read_bmp(path: Path) -> np.ndarray:
    """Rilegge un BMP scritto da write_bmp e restituisce i grigi; serve a verificare
    che il file sia decodificabile come lo decodifica CrossPoint."""
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


def contact_sheet(paths: list[Path], out: Path, cols: int = 10) -> None:
    if not paths:
        return
    thumbs = [Image.fromarray(read_bmp(p)).resize((WIDTH // 4, HEIGHT // 4)) for p in paths]
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("L", (cols * (WIDTH // 4 + 6), rows * (HEIGHT // 4 + 6)), 128)
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * (t.width + 6) + 3, (i // cols) * (t.height + 6) + 3))
    sheet.save(out)


# ----------------------------------------------------------------------------- main


def main() -> None:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=100, help="numero di sfondi (default 100)")
    ap.add_argument("--seed", type=int, default=1, help="cambia il seme per un'altra selezione")
    ap.add_argument("--max-year", type=int, default=1940,
                    help="scarta brevetti più recenti di quest'anno o senza data (default 1940)")
    ap.add_argument("--white", type=float, default=215,
                    help="punto di bianco 0-255: sopra diventa bianco puro; più basso = carta più pulita "
                         "ma linee chiare perse (default 215)")
    ap.add_argument("--black-pct", type=float, default=2,
                    help="percentile dell'inchiostro portato a nero puro; più alto = più contrasto (default 2)")
    ap.add_argument("--gamma", type=float, default=1.0,
                    help="gamma dei toni intermedi; < 1 scurisce e ispessisce le linee (default 1.0)")
    ap.add_argument("--margin", type=int, default=6, help="bordo bianco minimo in pixel (default 6)")
    ap.add_argument("--zoom", type=float, default=0.5,
                    help="0 = foglio intero con bande bianche, 1 = riempie lo schermo tagliando i lati "
                         "(default 0.5)")
    ap.add_argument("--trim", type=float, default=0.01,
                    help="frazione di inchiostro ignorata su ogni lato nel ritaglio; più alta = "
                         "ritaglio più stretto (default 0.01)")
    ap.add_argument("--max-ink", type=float, default=0.30,
                    help="frazione massima di pixel scuri; oltre, l'immagine è scartata come foto (default 0.30)")
    ap.add_argument("--min-ink", type=float, default=0.004,
                    help="frazione minima di pixel scuri; sotto, il foglio è scartato come vuoto (default 0.004)")
    ap.add_argument("--thicken", type=int, choices=(0, 3, 5, 7), default=3,
                    help="ispessisce le linee prima della riduzione (lato del filtro in pixel "
                         "dell'originale); più alto = linee più nere e grosse, 0 = spento (default 3)")
    ap.add_argument("--bits", type=int, choices=(1, 2), default=2,
                    help="1 = bianco e nero puro (aggiornamento B/N di CrossPoint, nero pieno); "
                         "2 = 4 grigi (default 2)")
    ap.add_argument("--no-dither", action="store_true", help="quantizza senza dithering (linee più nette)")
    ap.add_argument("--no-flatten", action="store_true",
                    help="non normalizzare lo sfondo della carta (solo stretch del contrasto)")
    ap.add_argument("--out", type=Path, default=here / "sleep", help="cartella di uscita")
    ap.add_argument("--cache", type=Path, default=here / "cache", help="cartella dei download")
    ap.add_argument("--contact", default="",
                    help="contatto (URL o email) da mettere nello User-Agent, come chiede Wikimedia; "
                         "riduce i rifiuti 429")
    ap.add_argument("--per-category", type=int, default=400,
                    help="massimo di file elencati per categoria Commons (default 400); "
                         "vale solo con --refresh o al primo avvio")
    ap.add_argument("--refresh", action="store_true",
                    help="rilegge l'elenco dei file da Commons invece di usare quello salvato in cache")
    args = ap.parse_args()
    if args.contact:
        global USER_AGENT
        USER_AGENT = f"sticky-wallpapers/0.1 ({args.contact}) python-urllib"

    args.out.mkdir(parents=True, exist_ok=True)
    args.cache.mkdir(parents=True, exist_ok=True)
    for old in args.out.glob("patent_*.bmp"):
        old.unlink()  # evita che restino sfondi di una selezione precedente

    pool = candidates(list_commons(args.cache / "listing.json", args.refresh, args.per_category), args.max_year)
    print(f"candidati dopo i filtri: {len(pool)}")
    random.Random(args.seed).shuffle(pool)

    # Alcuni file danno sempre errore (ad esempio 429 persistenti su certi TIFF):
    # li si ricorda per non perdere minuti di attese a ogni esecuzione.
    failed_list = args.cache / "falliti.txt"
    failed = set(failed_list.read_text().split()) if failed_list.exists() else set()
    # Esclusioni manuali: un pageid per riga (colonna "pageid" di credits.csv).
    excluded_list = args.out.parent / "esclusi.txt"
    if excluded_list.exists():
        failed |= {line.split("#")[0].strip() for line in excluded_list.read_text().splitlines()}

    made: list[Path] = []
    credits = []
    for page in pool:
        if len(made) == args.count:
            break
        if str(page["pageid"]) in failed:
            continue
        try:
            canvas = render(download(page, args.cache), args)
        except Exception as exc:  # una singola immagine rotta non deve fermare il lotto
            print(f"  salto {page['title']}: {exc}")
            with open(failed_list, "a") as f:
                f.write(f"{page['pageid']}\n")
            continue
        if canvas is None:
            print(f"  scartato (vuoto o non al tratto): {page['title']}")
            continue
        path = args.out / f"patent_{len(made) + 1:02d}.bmp"
        write_bmp(path, quantize(canvas, not args.no_dither, args.bits), args.bits)
        made.append(path)
        info = page["imageinfo"][0]
        credits.append([path.name, page["pageid"], page["title"].removeprefix("File:"), page["year"],
                        meta(info, "LicenseShortName").strip(), info["descriptionurl"]])
        print(f"{path.name}  {page['year']}  {page['title'][5:80]}", flush=True)

    with open(args.out / "credits.csv", "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows([["file", "pageid", "titolo", "anno", "licenza", "fonte"], *credits])
    contact_sheet(made, args.out.parent / "anteprima.png")
    print(f"\n{len(made)} sfondi in {args.out}; anteprima in {args.out.parent / 'anteprima.png'}")
    if len(made) < args.count:
        print(f"ATTENZIONE: chiesti {args.count}, trovati solo {len(made)} candidati validi")


if __name__ == "__main__":
    main()
