# Patent sleep screens for CrossPoint

Sleep-screen wallpapers for [CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader) on the Seeed reTerminal Sticky, made from old public-domain patent drawings.

![Preview](anteprima.png)

## Installing on CrossPoint

The files in `sleep/` are 480x800, 2-bit grayscale BMPs. That is the native screen size, so CrossPoint draws them directly, without converting or caching them.

1. Turn off the device and put its microSD card in your computer.
2. In the root of the card, create a folder named `.sleep`. Finder refuses names that start with a dot, so either create it from a terminal (`mkdir /Volumes/<card>/.sleep`) or name the folder `sleep`, which CrossPoint also accepts.
3. Copy the `patent_*.bmp` files from `sleep/` into that folder. You do not need `credits.csv` on the card.
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

## Regenerating

The script needs [uv](https://docs.astral.sh/uv/). It downloads drawings from Wikimedia Commons into `cache/`, keeps only public-domain or CC0 sheets up to 1940 (`--max-year`), and writes 480x800 2-bit grayscale BMPs (4 gray levels):

```sh
uv run genera_sfondi.py                         # 100 wallpapers, default settings
uv run genera_sfondi.py --count 30 --white 200 --thicken 5
uv run genera_sfondi.py --help                  # all options
```

Main options:

- `--count`: number of wallpapers.
- `--white`, `--black-pct`, `--gamma`: contrast.
- `--zoom`, `--margin`, `--trim`: how much of the screen the drawing fills.
- `--thicken`: line thickening before the downscale, so thin lines stay black.
- `--bits`: 2 for 4 gray levels, 1 for black and white.
- `--contact`: your email or URL, added to the User-Agent. The [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy) asks automated clients to include contact information.

Commons page IDs listed in `esclusi.txt`, next to the `--out` folder, are skipped.

## Credits

The drawings come from [Wikimedia Commons](https://commons.wikimedia.org/). Most are scans published by the U.S. National Archives (NARA) and the Digital Public Library of America (DPLA). Every source file is marked as public domain on Commons, so no attribution is legally required.

`sleep/credits.csv` lists, for each wallpaper, the Commons title, year, license and source page. The processed images only change contrast, size and line weight.

## License

The script `genera_sfondi.py` is released under the [MIT License](LICENSE).

The images (`sleep/*.bmp` and `anteprima.png`) keep the status of their sources, which are in the public domain. To the extent that the processing adds any copyright of its own, the author waives it under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
