"""Give the fonts a family name of at most 31 characters so OpenConsole can find them.

conhost keeps the face name in a 32-character buffer (LF_FACESIZE, incl. the NUL). A longer
family like "IosevkaKaliph Nerd Font Mono Cell" (33) is stored cut off ("...Mono Ce"), AtlasEngine
cannot find a font with that name and silently falls back to Consolas.

Usage:  python shorten_names.py <in-dir-or-file> <out-dir> [-j JOBS]
            [--old-prefix "IosevkaKaliph Nerd Font Mono" --new-prefix "IosevkaKaliph NFM"]
Needs:  pip install fonttools

Speed: only the 'name' table is rewritten, every other table (glyf, post, cmap, ...) is copied
byte for byte, and the fonts are processed in parallel (-j, default: number of CPU cores).

By default the Nerd Fonts naming convention is applied to whatever family the font has, so Cell
and non-Cell files (and any other variant) can be processed in the same run:
    "Nerd Font Mono"  -> "NFM"      "Nerd Font Propo" -> "NFP"      "Nerd Font" -> "NF"
--old-prefix / --new-prefix (given together) replace that with a plain text substitution.

"Condensed" is always shortened to "Cond". In these builds the width is part of the style name
(family "IosevkaKaliph Nerd Font Mono", style "Condensed ExtraBold Oblique"), so it is moved into
the family; otherwise Condensed and normal width would share one family name:
    family "IosevkaKaliph Nerd Font Mono"       style "Regular"                    -> "IosevkaKaliph NFM" / "Regular"
    family "IosevkaKaliph Nerd Font Mono"       style "Condensed ExtraBold Oblique" -> "IosevkaKaliph NFM Cond" / "ExtraBold Oblique"
    family "IosevkaKaliph Nerd Font Mono Cell"  style "Condensed"                  -> "IosevkaKaliph NFM Cond Cell" / "Regular"

Output files are named after the PostScript name inside each font, e.g. IosevkaKaliphNFM-Regular.ttf,
IosevkaKaliphNFMCond-ExtraBoldOblique.ttf or IosevkaKaliphNFMCondCell-Regular.ttf.

Only the family name (name ID 16) has to fit in 31 characters. Style names (ID 17) are kept in
full, and the legacy family (ID 1) is "<family> <style>" without a length limit; it only matters
to GDI-era apps.
"""
import argparse, os, pathlib, re, struct
from concurrent.futures import ProcessPoolExecutor
from fontTools.ttLib import TTFont

# Longest first, so "Nerd Font Mono" is handled before the bare "Nerd Font".
NERD = [("Nerd Font Mono", "NFM"), ("Nerd Font Propo", "NFP"), ("Nerd Font", "NF")]
RIBBI = {"Regular", "Bold", "Italic", "Bold Italic"}


def clean(s):
    """Collapse runs of whitespace and trim the ends."""
    return re.sub(r"\s+", " ", s).strip()


def shorten_family(fam, old_prefix, new_prefix):
    if old_prefix:
        return fam.replace(old_prefix, new_prefix, 1)
    for long, short in NERD:
        fam = fam.replace(long, short)
    return fam


def get(n, i):
    r = n.getName(i, 3, 1, 0x409) or n.getName(i, 1, 0, 0)
    return r.toUnicode() if r else None


def setall(n, i, text):
    n.removeNames(nameID=i)
    n.setName(text, i, 3, 1, 0x409)
    n.setName(text, i, 1, 0, 0)


def process(job):
    """Rename one font. Returns (file name, legacy id1, legacy id2, lines to print)."""
    path, out_dir, old_prefix, new_prefix = job
    p = pathlib.Path(path)
    lines = []
    f = TTFont(p)
    n = f["name"]
    # fsSelection sits at byte 62 of the OS/2 table. Reading it from the raw data means the OS/2
    # table is never decoded, so saving does not drag in cmap/post (post alone took seconds).
    sel = struct.unpack(">H", f.reader["OS/2"][62:64])[0]
    bold, ital = bool(sel & 32), bool(sel & 1)

    has16 = get(n, 16) is not None
    orig_fam = clean(get(n, 16) or get(n, 1))
    sty = clean(get(n, 17) or get(n, 2))
    fam = clean(shorten_family(orig_fam, old_prefix, new_prefix).replace("Condensed", "Cond"))
    if fam == orig_fam:
        lines.append(f"  note: {p.name}: family '{fam}' was not changed (no match found)")

    # In these builds the width lives in the style ("Condensed ExtraBold Oblique"), so the family
    # is the same for every width. Move it into the family, like the Cell builds already have it.
    words = sty.split()
    moved = "Condensed" in words
    if moved:
        words.remove("Condensed")
        fam_words = fam.split()
        if "Cond" not in fam_words:
            # "... NFM Cell" -> "... NFM Cond Cell", anything else just gets "Cond" appended
            fam_words.insert(len(fam_words) - 1 if fam_words[-1] == "Cell" else len(fam_words), "Cond")
        fam = " ".join(fam_words)
        sty = " ".join(words) or "Regular"

    if not has16 and not moved and sty in RIBBI:     # plain RIBBI font
        id1, id2 = fam, sty
    else:                                            # needs its own legacy family
        # drop the style words already expressed by the legacy Regular/Bold/Italic bits
        words = [w for w in sty.split() if w not in ("Regular", "Bold", "Italic")]
        id1 = " ".join([fam] + words)
        id2 = "Bold Italic" if bold and ital else "Bold" if bold else "Italic" if ital else "Regular"
        setall(n, 16, fam); setall(n, 17, sty)

    setall(n, 1, id1); setall(n, 2, id2)
    full = fam if sty == "Regular" else f"{fam} {sty}"
    setall(n, 4, full)
    # PostScript name = Family-Style (no spaces); the output filename uses the same string.
    ps = re.sub(r"[^A-Za-z0-9-]", "", f"{fam.replace(' ', '')}-{sty.replace(' ', '')}")[:63]
    setall(n, 6, ps); setall(n, 3, f"{ps};shortened")
    f.save(pathlib.Path(out_dir) / f"{ps}.ttf")
    f.close()
    flag = "" if len(fam) <= 31 else "  <-- family still >31"
    lines.append(f"{p.name} -> {ps}.ttf: family '{fam}' ({len(fam)}), legacy '{id1}' / {id2}{flag}")
    return p.name, id1, id2, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--old-prefix", help="text to replace in the family name (use with --new-prefix)")
    ap.add_argument("--new-prefix", help="replacement text (use with --old-prefix)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1,
                    help="fonts to process in parallel (default: number of CPU cores)")
    a = ap.parse_args()
    if bool(a.old_prefix) != bool(a.new_prefix):
        ap.error("--old-prefix and --new-prefix must be given together")

    src = pathlib.Path(a.src)
    files = [src] if src.is_file() else sorted(src.glob("*.ttf"))
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    jobs = [(str(p), str(out), a.old_prefix, a.new_prefix) for p in files]

    seen = {}
    with ProcessPoolExecutor(max_workers=max(1, a.jobs)) as ex:
        for name, id1, id2, lines in ex.map(process, jobs):
            for line in lines:
                print(line, flush=True)
            key = (id1, id2)
            if key in seen:
                print(f"  !! legacy name clash: {name} and {seen[key]} -> {key}", flush=True)
            seen[key] = name


if __name__ == "__main__":
    main()
