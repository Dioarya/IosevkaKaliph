#!/usr/bin/env python3
"""Bake a Windows Terminal style cellWidth / cellHeight into a font.

Windows Terminal's font.cellWidth / font.cellHeight (as multiples of the font size) change the
size of the box each character sits in, without scaling the glyphs. This script does the same
thing inside the font file, so a plain conhost sees the same cell size.

Usage (Ubuntu / WSL):
    sudo apt install python3-fonttools
    python3 patch_cell_size.py /mnt/c/Windows/Fonts/consola.ttf --cell-width 0.5 --cell-height 1.0

What it does:
  * advance widths are scaled so the main (most common) advance becomes cell-width * unitsPerEm;
    wider glyphs (e.g. double-width) are scaled proportionally
  * glyph outlines keep their size and are re-centred in the new advance, except block, box
    drawing, braille and powerline glyphs, which are stretched to fill the new cell
  * hinting bytecode is removed (use --keep-hinting to keep it)
  * the line height becomes cell-height * unitsPerEm, split between ascent and descent in the
    font's existing proportion
  * the family is renamed (default suffix " Cell") so it installs next to the original

Limits: static TrueType-outline fonts only (glyf table). No variable fonts, no CFF/.otf, only
the first font of a .ttc. GPOS mark positioning and kerning are not adjusted.
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

from fontTools.ttLib import TTFont


def rename(font, suffix):
    name = font["name"]
    compact = suffix.replace(" ", "")
    for rec in list(name.names):
        text = rec.toUnicode()
        if rec.nameID in (1, 16, 4):
            name.setName(text + suffix, rec.nameID, rec.platformID, rec.platEncID, rec.langID)
        elif rec.nameID in (3, 6):
            name.setName(text + compact, rec.nameID, rec.platformID, rec.platEncID, rec.langID)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("font", type=Path)
    ap.add_argument("--cell-width", type=float, required=True, help="em multiple, e.g. 0.5")
    ap.add_argument("--cell-height", type=float, required=True, help="em multiple, e.g. 1.0")
    ap.add_argument("--suffix", default=" Cell", help="appended to the family name")
    ap.add_argument("--keep-hinting", action="store_true", help="keep hinting bytecode (may distort)")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()

    if args.cell_width <= 0 or args.cell_height <= 0:
        sys.exit("cell sizes must be positive")

    font = TTFont(args.font, fontNumber=0)
    if "fvar" in font:
        sys.exit("variable fonts are not supported; use a static instance")
    if "glyf" not in font:
        sys.exit("only TrueType-outline fonts (glyf table) are supported")

    glyf = font["glyf"]
    hmtx = font["hmtx"]
    hhea = font["hhea"]
    os2 = font["OS/2"]
    upm = font["head"].unitsPerEm

    # --- horizontal: new advances and per-glyph shifts ---
    advances = Counter(adv for adv, _ in hmtx.metrics.values() if adv > 0)
    if not advances:
        sys.exit("font has no glyphs with a nonzero advance")
    old_w = advances.most_common(1)[0][0]
    new_w = round(args.cell_width * upm)
    factor = new_w / old_w

    new_adv = {}
    shift = {}
    for gname, (adv, _lsb) in hmtx.metrics.items():
        if adv == 0:
            new_adv[gname] = 0
            shift[gname] = 0
        else:
            na = round(adv * factor)
            new_adv[gname] = na
            shift[gname] = round((na - adv) / 2)

    # --- vertical numbers needed for the stretched glyphs below ---
    cur_asc, cur_desc = os2.usWinAscent, os2.usWinDescent
    total = round(args.cell_height * upm)
    new_asc = round(total * cur_asc / (cur_asc + cur_desc))
    new_desc = total - new_asc
    fy = total / (cur_asc + cur_desc)

    # Glyphs that are meant to fill the whole cell (box drawing, blocks, braille, powerline)
    # are stretched to the new cell instead of just re-centred, like Windows Terminal's own
    # drawing of them. Everything else keeps its size.
    stretch = set()
    for cp, gname in font.getBestCmap().items():
        if 0x2500 <= cp <= 0x259F or 0x2800 <= cp <= 0x28FF or 0xE0B0 <= cp <= 0xE0BF:
            stretch.add(gname)
    for gname in stretch:
        shift[gname] = 0
    # Block elements are pure rectangles on eighths of the cell; snap them exactly so halves
    # are true halves (fonts often split them a little off-centre). Shades are left alone.
    blocks = {
        gname
        for cp, gname in font.getBestCmap().items()
        if 0x2580 <= cp <= 0x2590 or 0x2596 <= cp <= 0x259F
    }

    # Simple glyphs: translate (normal) or stretch (cell-filling) the outline.
    for gname in font.getGlyphOrder():
        g = glyf[gname]
        if g.numberOfContours <= 0:
            continue
        if gname in stretch:
            old_adv = hmtx.metrics[gname][0]
            fx = new_adv[gname] / old_adv if old_adv else 1.0
            coords = g.coordinates
            for i in range(len(coords)):
                x, y = coords[i]
                nx, ny = round(x * fx), round((y + cur_desc) * fy - new_desc)
                if gname in blocks:
                    nx = round(round(nx / new_adv[gname] * 8) / 8 * new_adv[gname])
                    ny = round(round((ny + new_desc) / total * 8) / 8 * total - new_desc)
                coords[i] = (nx, ny)
        elif shift[gname]:
            g.coordinates.translate((shift[gname], 0))
    # Composite glyphs: a component that is itself a shifted glyph already carries its own
    # shift, so only the difference needs to go into the offset.
    for gname in font.getGlyphOrder():
        g = glyf[gname]
        if g.numberOfContours >= 0:
            continue
        for c in g.components:
            if not (c.flags & 0x2):  # ARGS_ARE_XY_VALUES unset: point matching, leave alone
                continue
            if gname in stretch:
                old_adv = hmtx.metrics[gname][0]
                fx = new_adv[gname] / old_adv if old_adv else 1.0
                c.x = round(c.x * fx)
                c.y = round(c.y * fy)
            else:
                c.x += shift[gname] - shift.get(c.glyphName, 0)

    for gname in font.getGlyphOrder():
        g = glyf[gname]
        if g.numberOfContours == 0:
            hmtx.metrics[gname] = (new_adv[gname], 0)
            continue
        g.recalcBounds(glyf)
        hmtx.metrics[gname] = (new_adv[gname], g.xMin)

    nonzero = [a for a in new_adv.values() if a > 0]
    os2.xAvgCharWidth = round(sum(nonzero) / len(nonzero))

    # --- vertical metrics (numbers computed above) ---
    os2.usWinAscent = new_asc
    os2.usWinDescent = new_desc
    os2.sTypoAscender = new_asc
    os2.sTypoDescender = -new_desc
    os2.sTypoLineGap = 0
    hhea.ascent = new_asc
    hhea.descent = -new_desc
    hhea.lineGap = 0
    if os2.version >= 2:
        os2.version = max(os2.version, 4)
        os2.fsSelection |= 1 << 7  # USE_TYPO_METRICS

    # Tables that cache per-size metrics are stale after this.
    for tag in ("hdmx", "LTSH", "VDMX", "DSIG"):
        if tag in font:
            del font[tag]

    # Hinting bytecode assumes the original coordinates and metrics, so drop it. Text is then
    # unhinted, which is invisible with DirectWrite and a touch softer with GDI at small sizes.
    if not args.keep_hinting:
        from fontTools.ttLib.tables import ttProgram

        for gname in font.getGlyphOrder():
            g = glyf[gname]
            if hasattr(g, "program"):
                g.program = ttProgram.Program()
                g.program.fromBytecode(b"")
        for tag in ("fpgm", "prep", "cvt "):
            if tag in font:
                del font[tag]

    rename(font, args.suffix)

    out = args.output or Path(
        f"{args.font.stem}-{args.suffix.strip().replace(' ', '')}{args.font.suffix}"
    )
    font.save(out)
    print(f"upm {upm}: advance {old_w} -> {new_w} ({old_w / upm:.3f} -> {new_w / upm:.3f} em)")
    print(f"line height -> {total} ({args.cell_height} em), ascent {new_asc}, descent {new_desc}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
