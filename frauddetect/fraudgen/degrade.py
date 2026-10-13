"""Turn clean renders into flatbed scans and phone photos.

Each function returns the degraded image plus a dict describing exactly which
effects were applied, so a test can relate OCR failures to capture conditions.
"""

from __future__ import annotations

import io
import random
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


def _noise(img: Image.Image, sigma: float, rng: random.Random) -> Image.Image:
    arr = np.asarray(img).astype(np.float32)
    gen = np.random.default_rng(rng.randrange(1 << 31))
    arr += gen.normal(0, sigma, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def scan(img: Image.Image, rng: random.Random, card: bool) -> tuple[Image.Image, dict]:
    """300 DPI greyscale flatbed scan: skew, slight blur, sensor noise, dust."""
    g = img.convert("L")
    if card:  # cards are scanned on an A4-ish platen with white margins
        canvas = Image.new("L", (int(g.width * 2.2), int(g.height * 2.6)), 250)
        canvas.paste(g, (rng.randint(40, canvas.width - g.width - 40), rng.randint(40, canvas.height // 3)))
        g = canvas
    skew = round(rng.uniform(-3.0, 3.0), 2)
    g = g.rotate(skew, resample=Image.BICUBIC, expand=True, fillcolor=248)
    g = g.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 0.9)))
    g = ImageEnhance.Contrast(g).enhance(rng.uniform(0.85, 1.15))
    g = _noise(g, rng.uniform(3, 8), rng)
    d = ImageDraw.Draw(g)
    for _ in range(rng.randint(15, 60)):
        x, y = rng.randrange(g.width), rng.randrange(g.height)
        r = rng.choice([1, 1, 2])
        d.ellipse((x, y, x + r, y + r), fill=rng.randint(60, 140))
    return g, {"capture": "flatbed_scan", "dpi": 300, "greyscale": True, "skew_deg": skew}


def _perspective_coeffs(src: list[tuple[float, float]], dst: list[tuple[float, float]]) -> list[float]:
    """Coefficients for PIL's PERSPECTIVE transform (maps output dst -> input src)."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(dst, src):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs += [u, v]
    return np.linalg.solve(np.array(rows, float), np.array(rhs, float)).tolist()


def _table_texture(w: int, h: int, rng: random.Random) -> Image.Image:
    base = rng.choice([(120, 85, 55), (160, 160, 155), (60, 60, 65), (190, 175, 150)])
    gen = np.random.default_rng(rng.randrange(1 << 31))
    grain = gen.normal(0, 10, (h // 8 + 1, w // 8 + 1, 1))
    arr = np.clip(np.array(base, np.float32) + grain, 0, 255).astype(np.uint8)
    return Image.fromarray(arr).resize((w, h), Image.BILINEAR)


def mobile(img: Image.Image, rng: random.Random) -> tuple[Image.Image, dict]:
    """Phone photo of a document on a table: perspective, glare, low light, blur."""
    W = int(img.width * 1.35)
    H = int(img.height * 1.35)
    bg = _table_texture(W, H, rng).convert("RGB")
    mx, my = (W - img.width) / 2, (H - img.height) / 2
    j = lambda s: rng.uniform(-s, s)  # noqa: E731
    k = 0.09
    dst = [(mx + j(img.width * k), my + j(img.height * k)),
           (mx + img.width + j(img.width * k), my + j(img.height * k)),
           (mx + img.width + j(img.width * k), my + img.height + j(img.height * k)),
           (mx + j(img.width * k), my + img.height + j(img.height * k))]
    src = [(0, 0), (img.width, 0), (img.width, img.height), (0, img.height)]
    coeffs = _perspective_coeffs(src, dst)
    warped = img.convert("RGB").transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", img.size, 255).transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    bg.paste(warped, (0, 0), mask)
    out = bg
    fx: dict = {"capture": "mobile_photo", "perspective_corners": [[round(a), round(b)] for a, b in dst]}

    if rng.random() < 0.6:  # specular glare
        gx, gy = rng.randint(int(W * 0.2), int(W * 0.8)), rng.randint(int(H * 0.2), int(H * 0.8))
        rad = rng.randint(int(min(W, H) * 0.08), int(min(W, H) * 0.22))
        yy, xx = np.mgrid[0:H, 0:W]
        dist = np.sqrt((xx - gx) ** 2 + (yy - gy) ** 2)
        alpha = np.clip(1 - dist / rad, 0, 1) ** 1.6 * rng.uniform(0.6, 0.95)
        arr = np.asarray(out).astype(np.float32)
        arr = arr * (1 - alpha[..., None]) + 255 * alpha[..., None]
        out = Image.fromarray(arr.astype(np.uint8))
        fx["glare"] = {"centre": [gx, gy], "radius": rad}
    if rng.random() < 0.5:  # low light: darker, warm cast, more noise
        gamma = rng.uniform(1.4, 2.1)
        arr = (np.asarray(out).astype(np.float32) / 255) ** gamma * 255
        arr *= np.array([1.0, 0.93, 0.8])
        out = _noise(Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), rng.uniform(6, 14), rng)
        fx["low_light_gamma"] = round(gamma, 2)
    else:
        out = _noise(out, rng.uniform(2, 5), rng)
    if rng.random() < 0.4:  # hand shake
        out = out.filter(ImageFilter.BoxBlur(rng.uniform(1.0, 2.2)))
        fx["motion_blur"] = True
    return out, fx


def image_pdf(images: list[Image.Image], path: Path, quality: int = 70) -> None:
    """Image-only PDF (no text layer), like a scanner's PDF output."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=quality, dpi=(300, 300))
        w, h = im.width * 72 / 300, im.height * 72 / 300
        page = doc.new_page(width=w, height=h)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.set_metadata({"producer": "fraudgen synthetic scanner", "title": path.stem,
                      "subject": "SPECIMEN - synthetic test data"})
    doc.save(str(path), deflate=True)
    doc.close()


def save_jpeg(img: Image.Image, path: Path, quality: int = 80) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="JPEG", quality=quality)
