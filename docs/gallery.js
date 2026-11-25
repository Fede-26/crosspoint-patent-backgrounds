"use strict";
const REPO = "Fede-26/ereader-patent-wallpapers";
const PAGE = 48; // cards added per click on "Show more"

// key: also the folder under files/ and the zip name in the release.
const DEVICES = [
  { key: "crosspoint", name: "CrossPoint", size: "480×800", ext: "bmp", zip: "crosspoint.zip",
    w: 480, h: 800, badge: "BMP",
    note: "reTerminal Sticky and other CrossPoint devices. Copy the BMPs into a folder named .sleep on the microSD card, then set Sleep Screen to Custom." },
  { key: "png-480x800", name: "KOReader", size: "480×800", ext: "png", zip: "png-480x800.zip",
    w: 480, h: 800, badge: "PNG",
    note: "PNG for KOReader (it does not list BMP files) or any e-reader with a 480×800 screen." },
  { key: "kindle-pw11", name: "Kindle Paperwhite 11th gen", size: "1236×1648", ext: "png", zip: "kindle-pw11.zip",
    w: 1236, h: 1648, badge: "PNG",
    note: "PNG for KOReader on this Kindle. Use Sleep screen → Wallpaper → Custom images → Choose random image folder." },
  { key: "kindle-pw12", name: "Kindle Paperwhite 12th gen", size: "1264×1680", ext: "png", zip: "kindle-pw12.zip",
    w: 1264, h: 1680, badge: "PNG",
    note: "PNG for KOReader on this Kindle. Use Sleep screen → Wallpaper → Custom images → Choose random image folder." },
];

const $ = (id) => document.getElementById(id);
let items = [];
let shown = [];
let visible = 0;
let device = DEVICES[0];
let current = -1; // index in `shown` of the wallpaper open in the lightbox

const fileUrl = (it) => `files/${device.key}/${it.id}.${device.ext}`;

function renderDevices() {
  const box = $("devices");
  box.textContent = "";
  for (const d of DEVICES) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "dev";
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", String(d === device));
    const ico = document.createElement("span");
    ico.className = "ico";
    ico.style.aspectRatio = `${d.w} / ${d.h}`;
    const text = document.createElement("span");
    const name = document.createElement("strong");
    name.textContent = d.name;
    const size = document.createElement("small");
    size.textContent = d.size;
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = d.badge;
    const col = document.createElement("span");
    col.style.display = "block";
    col.append(size, document.createElement("br"), badge);
    text.append(name, col);
    b.append(ico, text);
    b.addEventListener("click", () => { device = d; renderDevices(); renderDevice(); });
    box.append(b);
  }
}

function renderDevice() {
  $("device-note").textContent = device.note;
  $("zip-link").href = `https://github.com/${REPO}/releases/latest/download/${device.zip}`;
  $("zip-link").textContent = `Download all ${items.length} for ${device.name}, zip`;
  // Card download links depend on the device.
  for (const a of document.querySelectorAll("[data-dl]")) a.href = fileUrl(items[a.dataset.dl]);
  if ($("lightbox").open) openLightbox(current);
}

function card(it) {
  const idx = items.indexOf(it);
  const el = document.createElement("article");
  el.className = "card";
  const open = document.createElement("button");
  open.type = "button";
  open.className = "thumb";
  open.setAttribute("aria-label", `Preview: ${it.title}`);
  const img = document.createElement("img");
  img.src = `thumbs/${it.id}.webp`;
  img.alt = "";
  img.loading = "lazy";
  img.width = 300; img.height = 500;
  open.append(img);
  open.addEventListener("click", () => openLightbox(shown.indexOf(it)));
  const meta = document.createElement("div");
  meta.className = "meta";
  const t = document.createElement("div");
  t.className = "title"; t.textContent = it.title; t.title = it.title;
  const y = document.createElement("div");
  y.className = "year"; y.textContent = it.year;
  const links = document.createElement("div");
  links.className = "links";
  const dl = document.createElement("a");
  dl.className = "dl"; dl.textContent = "Download"; dl.setAttribute("download", ""); dl.dataset.dl = String(idx); dl.href = fileUrl(it);
  const src = document.createElement("a");
  src.textContent = "Source"; src.href = it.source; src.rel = "noopener";
  links.append(dl, src);
  meta.append(t, y, links);
  el.append(open, meta);
  return el;
}

function more() {
  const grid = $("grid");
  for (const it of shown.slice(visible, visible + PAGE)) grid.append(card(it));
  visible = Math.min(visible + PAGE, shown.length);
  $("more").hidden = visible >= shown.length;
}

function applyFilters() {
  const q = $("q").value.trim().toLowerCase();
  const dec = $("decade").value;
  shown = items.filter((it) =>
    (!q || it.title.toLowerCase().includes(q)) && (!dec || Math.floor(it.year / 10) * 10 === +dec));
  $("grid").textContent = "";
  visible = 0;
  $("count").textContent = `${shown.length} of ${items.length} wallpapers`;
  more();
}

function openLightbox(i) {
  if (i < 0 || i >= shown.length) return;
  current = i;
  const it = shown[i];
  $("lb-img").src = fileUrl(it);
  $("lb-img").alt = it.title;
  $("lb-title").textContent = `${it.title} (${it.year}) · ${device.name} ${device.size}`;
  $("lb-dl").href = fileUrl(it);
  $("lb-prev").disabled = i === 0;
  $("lb-next").disabled = i === shown.length - 1;
  if (!$("lightbox").open) $("lightbox").showModal();
}

async function init() {
  $("repo-link").href = `https://github.com/${REPO}`;
  $("repo-link2").href = `https://github.com/${REPO}`;
  $("issue-link").href = `https://github.com/${REPO}/issues/new?template=new-screen-size.yml`;
  renderDevices();
  try {
    items = await (await fetch("data.json")).json();
  } catch (e) {
    $("count").textContent = "Could not load the wallpaper list.";
    return;
  }
  const decades = [...new Set(items.map((it) => Math.floor(it.year / 10) * 10))].sort();
  for (const d of decades) $("decade").add(new Option(`${d}s`, d));
  applyFilters();
  renderDevice();
}

$("q").addEventListener("input", applyFilters);
$("decade").addEventListener("change", applyFilters);
$("more").addEventListener("click", more);
$("lb-close").addEventListener("click", () => $("lightbox").close());
$("lb-prev").addEventListener("click", () => openLightbox(current - 1));
$("lb-next").addEventListener("click", () => openLightbox(current + 1));
$("lightbox").addEventListener("click", (e) => { if (e.target === $("lightbox")) $("lightbox").close(); });
document.addEventListener("keydown", (e) => {
  if (!$("lightbox").open) return;
  if (e.key === "ArrowLeft") openLightbox(current - 1);
  if (e.key === "ArrowRight") openLightbox(current + 1);
});
init();
