"""Drawing helpers on top of PyMuPDF.

Text goes through insert_htmlbox, which shapes Arabic, Urdu, Bengali and
Devanagari correctly (Pillow without libraqm does not). Every page carries a
SPECIMEN watermark so no output can be mistaken for a real document.
"""

from __future__ import annotations

import html
import io
import math
import os
import random
import re
import unicodedata
from pathlib import Path

import pymupdf

FONT_DIR = Path(os.environ.get("FRAUDGEN_FONT_DIR", "C:/Windows/Fonts"))

# family name -> font file (must exist in FONT_DIR)
FONTS = {
    "sans": "arial.ttf", "sansb": "arialbd.ttf",
    "indic": "Nirmala.ttf", "indicb": "NirmalaB.ttf",
    "serif": "times.ttf", "serifb": "timesbd.ttf",
    "mono": "cour.ttf", "ocr": "OCRAEXT.TTF",
    "alt": "georgia.ttf", "calibri": "calibri.ttf", "tahoma": "tahoma.ttf",
}

_ARCHIVE: pymupdf.Archive | None = None


def archive() -> pymupdf.Archive:
    global _ARCHIVE
    if _ARCHIVE is None:
        missing = [f for f in FONTS.values() if not (FONT_DIR / f).exists()]
        if missing:
            raise FileNotFoundError(
                f"Fonts missing from {FONT_DIR}: {missing}. Set FRAUDGEN_FONT_DIR."
            )
        _ARCHIVE = pymupdf.Archive(str(FONT_DIR))
    return _ARCHIVE


CSS = "".join(f"@font-face{{font-family:{k};src:url({v});}}" for k, v in FONTS.items()) + """
* { font-family: sans, indic; margin: 0; padding: 0; }
b, .b { font-family: sansb, indicb; font-weight: bold; }
.lbl { color: #4a4a4a; }
.rtl { text-align: right; }
table { border-collapse: collapse; width: 100%; }
td, th { padding: 2px 3px; vertical-align: top; }
th { font-family: sansb, indicb; text-align: left; border-bottom: 1px solid #333; }
.num { text-align: right; }
"""

esc = html.escape

MM = 72 / 25.4  # points per millimetre


def mm(v: float) -> float:
    return v * MM


class Page:
    """Thin wrapper so document builders read like layout code."""

    def __init__(self, doc: pymupdf.Document, width: float, height: float):
        self.page = doc.new_page(width=width, height=height)
        self.w, self.h = width, height

    def html(self, rect: tuple[float, float, float, float], body: str, size: float = 8,
             color: str = "#111", family: str | None = None, align: str = "left",
             rtl: bool = False) -> None:
        fam = f"font-family:{family};" if family else ""
        d = " dir='rtl'" if rtl else ""
        if rtl:  # MuPDF mirrors text-align inside an RTL block: "left" lands on the right
            align = {"left": "right", "right": "left"}.get(align, align)
        markup = (f"<div{d} style='font-size:{size}px;color:{color};{fam}text-align:{align};'>"
                  f"{body}</div>")
        self.page.insert_htmlbox(pymupdf.Rect(*rect), markup, css=CSS, archive=archive())

    def text(self, rect, value: str, **kw) -> None:
        self.html(rect, esc(value), **kw)

    def rect(self, rect, fill=None, color=None, width: float = 0.5, radius=None,
             opacity: float = 1.0) -> None:
        self.page.draw_rect(pymupdf.Rect(*rect), color=color, fill=fill, width=width,
                            radius=radius, fill_opacity=opacity, stroke_opacity=opacity)

    def line(self, p1, p2, color=(0.3, 0.3, 0.3), width: float = 0.5) -> None:
        self.page.draw_line(pymupdf.Point(*p1), pymupdf.Point(*p2), color=color, width=width)

    def guilloche(self, rng: random.Random, color=(0.75, 0.82, 0.9), lines: int = 14,
                  rect=None) -> None:
        """Sine-wave security background, varied per document."""
        x0, y0, x1, y1 = rect or (0, 0, self.w, self.h)
        amp = (y1 - y0) / (lines * 1.4)
        phase, freq = rng.uniform(0, 6.28), rng.uniform(2.5, 5.5)
        for i in range(lines):
            base = y0 + (i + 0.5) * (y1 - y0) / lines
            pts = [
                pymupdf.Point(x, base + amp * math.sin(freq * 2 * math.pi * (x - x0) / (x1 - x0) + phase + i * 0.6))
                for x in [x0 + k * (x1 - x0) / 120 for k in range(121)]
            ]
            self.page.draw_polyline(pts, color=color, width=0.35)

    def portrait(self, rect, seed: int) -> None:
        """Neutral silhouette in place of a photo. No real faces are used."""
        x0, y0, x1, y1 = rect
        shade = 0.78 + (seed % 7) * 0.02
        self.rect(rect, fill=(shade, shade, shade + 0.03), color=(0.5, 0.5, 0.5))
        cx, w, h = (x0 + x1) / 2, x1 - x0, y1 - y0
        self.page.draw_circle(pymupdf.Point(cx, y0 + h * 0.36), w * 0.2, fill=(0.55, 0.55, 0.6), color=None)
        # shoulders: upper half of an ellipse sitting on the frame's bottom edge
        rx, ry = w * 0.4, h * 0.38
        pts = [pymupdf.Point(cx + rx * math.cos(math.pi * k / 40), y1 - ry * math.sin(math.pi * k / 40))
               for k in range(41)]
        self.page.draw_polyline(pts + [pts[0]], fill=(0.55, 0.55, 0.6), color=None)
        self.rect(rect, color=(0.5, 0.5, 0.5))  # re-stroke border over the oval

    def mrz(self, lines: list[str], y: float, size: float | None = None) -> None:
        n = len(lines[0])
        size = size or (self.w - mm(8)) / (n * 0.62)
        for i, ln in enumerate(lines):
            self.html((mm(4), y + i * size * 1.25, self.w - mm(2), y + (i + 1) * size * 1.25 + 4),
                      esc(ln).replace(" ", "&nbsp;"), size=size, family="ocr")

    def image(self, rect, png_bytes: bytes) -> None:
        self.page.insert_image(pymupdf.Rect(*rect), stream=png_bytes)

    def specimen(self, label: str = "SPECIMEN · SYNTHETIC TEST DATA · NOT VALID",
                 footer_top: bool = False) -> None:
        """Diagonal watermark plus a footer line on every page."""
        size = max(self.w, self.h) / 24
        angle = math.degrees(math.atan2(self.h, self.w))
        cx, cy = self.w / 2, self.h / 2
        text_w = pymupdf.get_text_length("SPECIMEN", fontname="helv", fontsize=size * 2.2)
        mat = pymupdf.Matrix(-angle)
        self.page.insert_text(pymupdf.Point(cx - text_w / 2, cy + size * 0.7), "SPECIMEN",
                              fontname="helv", fontsize=size * 2.2, color=(0.85, 0.1, 0.1),
                              fill_opacity=0.16, morph=(pymupdf.Point(cx, cy), mat))
        fs = min(7.0, max(4.0, self.h / 70))
        y = fs + 1.5 if footer_top else self.h - 2.5
        self.page.insert_text(pymupdf.Point(4, y), label, fontname="helv",
                              fontsize=fs, color=(0.8, 0.1, 0.1))


def new_doc() -> pymupdf.Document:
    return pymupdf.open()


# MuPDF's ToUnicode maps are lossy for this use: Arial shares one glyph between
# space/U+00A0, hyphen/U+00AD and middle dot/U+A78F and picks the rarer code
# point, and shaped Arabic/Urdu glyphs map to presentation forms (U+FB50-FEFF).
# The map is rebuilt so extracted text reads like normal Unicode. Shaped Indic
# conjuncts have no single code point and stay unreliable (documented in README).
_SHARED_GLYPH = {" ": " ", "­": "-", "ꞏ": "·"}
_HEX = re.compile(r"<([0-9a-fA-F]+)>")


def _u16(hexstr: str) -> str:
    return bytes.fromhex(hexstr).decode("utf-16-be", errors="replace")


def _parse_cmap(cmap: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
        toks = _HEX.findall(block)
        for src, dst in zip(toks[0::2], toks[1::2]):
            out[src.lower()] = _u16(dst)
    for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
        for line in re.findall(r"<[0-9a-fA-F]+>\s*<[0-9a-fA-F]+>\s*(?:\[[^\]]*\]|<[0-9a-fA-F]+>)", block):
            lo, hi, *rest = _HEX.findall(line)
            width, a, b = len(lo), int(lo, 16), int(hi, 16)
            if "[" in line:
                for k, dst in zip(range(a, b + 1), rest):
                    out[f"{k:0{width}x}"] = _u16(dst)
            else:
                base = _u16(rest[0])
                for k in range(a, b + 1):
                    out[f"{k:0{width}x}"] = base[:-1] + chr(ord(base[-1]) + k - a)
    return out


def _clean(text: str) -> str:
    text = "".join(_SHARED_GLYPH.get(c, c) for c in text)
    return "".join(unicodedata.normalize("NFKC", c) if 0xFB50 <= ord(c) <= 0xFEFF else c for c in text)


_CMAP_HEAD = ("/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
              "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
              "/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n")
_CMAP_TAIL = "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"


def _fix_tounicode(doc: pymupdf.Document) -> None:
    done: set[int] = set()
    for x in range(1, doc.xref_length()):
        kind, val = doc.xref_get_key(x, "ToUnicode")
        if kind != "xref":
            continue
        sx = int(val.split()[0])
        if sx in done:
            continue
        done.add(sx)
        cmap = doc.xref_stream(sx).decode("latin-1")
        mapping = {k: _clean(v) for k, v in _parse_cmap(cmap).items()}
        if not mapping:
            continue
        space = re.search(r"begincodespacerange(.*?)endcodespacerange", cmap, re.S)
        parts = [_CMAP_HEAD, "1 begincodespacerange\n",
                 (space.group(1).strip() if space else "<0000> <FFFF>"), "\nendcodespacerange\n"]
        items = sorted(mapping.items())
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            parts.append(f"{len(chunk)} beginbfchar\n")
            parts += [f"<{k}> <{v.encode('utf-16-be').hex()}>\n" for k, v in chunk]
            parts.append("endbfchar\n")
        parts.append(_CMAP_TAIL)
        doc.update_stream(sx, "".join(parts).encode("latin-1"))


def save(doc: pymupdf.Document, path: Path, metadata: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {"producer": "fraudgen synthetic document generator", "creator": "fraudgen",
            "title": path.stem, "subject": "SPECIMEN - synthetic test data"}
    meta.update(metadata or {})
    doc.set_metadata(meta)
    doc.subset_fonts()  # each HTML box embeds whole fonts; subsetting takes a statement from ~12 MB to ~100 KB
    _fix_tounicode(doc)
    doc.save(str(path), garbage=4, deflate=True)
    doc.close()


def pdf417_png(data: str, columns: int = 12) -> bytes:
    import pdf417gen

    img = pdf417gen.render_image(pdf417gen.encode(data, columns=columns, security_level=3),
                                 scale=2, ratio=3, padding=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def rasterize(pdf_path: Path, dpi: int) -> list:
    """Return one PIL image per page."""
    from PIL import Image

    out = []
    with pymupdf.open(str(pdf_path)) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=dpi)
            out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out
