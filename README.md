# Patent sleep screens for e-readers

**Gallery and downloads: <https://fede-26.github.io/ereader-patent-wallpapers/>**

400 sleep-screen wallpapers made from old public-domain patent drawings. They work with [CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader) on the Xteink X4 and the Seeed reTerminal Sticky, with [KOReader](https://koreader.rocks/) on Kindle, and with any e-reader that can show a custom image as its sleep screen.

![Preview](anteprima.png)

## Formats

Every wallpaper is rendered from the source scan once per size, so each size has its own layout and line weight. All files use 4 gray levels (2 bits per pixel).

| Device | Size | Format | Where |
| --- | --- | --- | --- |
| Xteink X4 / Seeed Sticky (CrossPoint) | 480x800 | BMP | `docs/files/crosspoint/` |
| Kindle Paperwhite 11th gen (KOReader) | 1236x1648 | PNG | `docs/files/kindle-pw11/` |
| Kindle Paperwhite 12th gen (KOReader) | 1264x1680 | PNG | `docs/files/kindle-pw12/` |

The PNG files are indexed PNGs with a 4-entry gray palette, the smallest standard layout for 4 gray levels: about 60 KB each at Kindle size, against about 6 MB for a Kindle-size BMP. The 480x800 BMPs are 96 KB each.

**KOReader does not list BMP files.** Checking its source (`master` branch, November 2026), the screensaver folder only accepts files with the extensions gif, jpeg, jpg, png, svg, tif, tiff and webp ([`image_ext` in `documentregistry.lua`](https://github.com/koreader/koreader/blob/master/frontend/document/documentregistry.lua), used by [`screensaver.lua`](https://github.com/koreader/koreader/blob/master/frontend/ui/screensaver.lua)). For KOReader use the PNG files.

## Installing on CrossPoint

The files in `docs/files/crosspoint/` are 480x800, 2-bit grayscale BMPs (400 of them). That is the native screen size, so CrossPoint draws them directly, without converting or caching them.

1. Turn off the device and put its microSD card in your computer.
2. In the root of the card, create a folder named `.sleep`. Finder refuses names that start with a dot, so either create it from a terminal (`mkdir /Volumes/<card>/.sleep`) or name the folder `sleep`, which CrossPoint also accepts.
3. Copy the `patent_*.bmp` files from `docs/files/crosspoint/` into that folder. You do not need `credits.csv` on the card.
4. On macOS, remove the `._*` files that Finder and `cp` create next to each copy. CrossPoint lists them as invalid BMPs:

   ```sh
   dot_clean -m /Volumes/<card>/.sleep
   ```

5. Eject the card, put it back in the device and turn it on.
6. Open **Settings → Display** and set:
   - **Sleep Screen** to **Custom**, or to **Cover + Custom** to show the book cover while you are reading.
   - **Sleep Screen Cover Filter** to **None**. **Contrast** and **Inverted** draw the images in black and white only.

CrossPoint picks a random wallpaper each time the device sleeps. A file named `sleep.bmp` in the root of the card takes priority over the folder, so remove it if you have one.

To see `.sleep` in the CrossPoint file browser, enable hidden files under **Settings → System**.

## Installing on KOReader

1. Download the files for your screen size from the [gallery](https://fede-26.github.io/ereader-patent-wallpapers/), either one by one or all as a zip, and unzip them.
2. Copy the PNG files into a folder on the device, for example `koreader/screensaver/`.
3. In KOReader open **Sleep screen → Wallpaper → Custom images → Choose random image folder** and select that folder (menu names from KOReader `master`; older versions may use different wording, for example "Screensaver").

KOReader scales images to the screen, so a file of the wrong size still works, but the right size is sharper and avoids bands.

## Regenerating

The script needs [uv](https://docs.astral.sh/uv/). It downloads drawings from Wikimedia Commons into `cache/`, keeps only public-domain or CC0 sheets up to 1940 (`--max-year`), and writes the 2-bit grayscale files for every target:

```sh
uv run genera_sfondi.py                          # up to 400 wallpapers, all targets
uv run genera_sfondi.py --targets crosspoint     # only the 480x800 BMPs
uv run genera_sfondi.py --count 500              # add 100 more to the existing 400
uv run genera_sfondi.py --help                   # all options
```

Each target goes to its own folder, `docs/files/<target>/`, next to `docs/files/credits.csv`. `docs/` is also what the GitHub Pages gallery serves (GitHub Pages can publish only the repository root or a folder named `docs`).

After generating, `uv run build_site.py` makes the gallery thumbnails and `docs/data.json`; the list of devices in `docs/devices.json` is written by `genera_sfondi.py` itself.

Existing wallpapers are kept: the pages already listed in `docs/files/credits.csv` are never selected again and their files are never overwritten. A new run only appends wallpapers until `--count` is reached, and only renders files that are missing, so adding a target or resuming an interrupted run is quick. Downloads stay in `cache/`, so no drawing is fetched twice. To start from scratch, empty `docs/files/` (credits included).

Main options:

- `--targets`: which of `crosspoint`, `kindle-pw11`, `kindle-pw12` to render.
- `--count`: total number of wallpapers, existing ones included.
- `--white`, `--black-pct`, `--gamma`: contrast.
- `--zoom`, `--margin`, `--trim`: how much of the screen the drawing fills.
- `--thicken`: line thickening before the downscale of the 480x800 renders, so thin lines stay black. The Kindle renders are close to the scan's resolution and are not thickened.
- `--dither`: Floyd-Steinberg dithering on the PNGs. It makes them larger. The CrossPoint BMPs are dithered unless you pass `--no-dither`.
- `--contact`: your email or URL, added to the User-Agent. The [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) asks automated clients to include contact information.

Commons page IDs listed in `esclusi.txt`, next to the script, are skipped.

## Other screen sizes

If your e-reader has a different screen, [open an issue](../../issues/new?template=new-screen-size.yml) with the model, the screen size in pixels (width x height, portrait) and the image format its sleep screen accepts. The same form is linked from the gallery. I render the set for the new size and add it to the gallery.

You can also add a screen yourself: add an entry to `TARGETS` in `genera_sfondi.py` (name, size, format, a label and a short note for the gallery) and run the script. It renders only the missing files and rewrites `docs/devices.json`, which the gallery reads, so the new size shows up on the site without changing any other file. Run `uv run build_site.py` only when the set of wallpapers changes, to refresh the thumbnails and `docs/data.json`.

## Credits

The drawings come from [Wikimedia Commons](https://commons.wikimedia.org/). Most are scans published by the U.S. National Archives (NARA) and the Digital Public Library of America (DPLA). Every source file is marked as public domain on Commons, so no attribution is legally required.

`docs/files/credits.csv` lists, for each wallpaper, the Commons title, year, license and source page. It applies to every size and format. The processed images only change contrast, size and line weight.

## License

The script `genera_sfondi.py` is released under the [MIT License](LICENSE).

The images (everything in `docs/files/`, the thumbnails in `docs/thumbs/` and `anteprima.png`) keep the status of their sources, which are in the public domain. To the extent that the processing adds any copyright of its own, the author waives it under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
