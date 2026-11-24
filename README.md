# Patent sleep screens for CrossPoint

Sleep-screen wallpapers for [CrossPoint Reader](https://github.com/crosspoint-reader/crosspoint-reader) on the Seeed reTerminal Sticky, made from old public-domain patent drawings.

![Preview](anteprima.png)

## Usage

Copy the BMP files from `sleep/` to `/.sleep/` on the microSD card, then set **Sleep Screen** to **Custom**. CrossPoint picks a random file at each sleep.

On macOS, Finder and `cp` create `._*` files on the card, and CrossPoint shows them as invalid BMPs. Remove them after copying:

```sh
dot_clean -m /Volumes/<card>/.sleep
```

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

Commons page IDs listed in `esclusi.txt`, next to the `--out` folder, are skipped.

## Credits

`sleep/credits.csv` lists the Commons title, year, license and source URL of each drawing.
