"""Generate the synthetic fraud-detection test dataset.

    python generate.py                       # default set into ./test_dataset
    python generate.py --variants 3          # 3 people / statements / shipments per region
    python generate.py --seed 7 --out D:/tmp/ds --overwrite
    python generate.py --sections fraud --cases ID01,BK04,TR02
    python generate.py --custom examples/custom_cases_uae.json   # only your own cases (see HOWTO.md)

Output (see README.md for details):
    01_pristine_digital/   native PDFs with text layer + MT940/CAMT.053/OFX/MT700/CII
    02_scanned_physical/   image-only PDFs, 300 DPI greyscale, skewed, noisy
    03_mobile_captures/    JPEG phone photos: perspective, glare, low light, blur
    04_adversarial_fraud/  one folder per fraud / edge case with case.json
    manifest.csv           one row per file with label and expected result

Same seed + same as-of date + same fonts = same documents.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
import zlib
from datetime import date
from pathlib import Path

from fraudgen import banking as B
from fraudgen import custom as C
from fraudgen import degrade as D
from fraudgen import fraud as F
from fraudgen import identity as I
from fraudgen import people as P
from fraudgen import render as R
from fraudgen import trade as T

HERE = Path(__file__).resolve().parent
TIERS = ["01_pristine_digital", "02_scanned_physical", "03_mobile_captures", "04_adversarial_fraud"]
ID_REGIONS = ["UAE", "UK", "US", "PK", "IN", "BD", "AU", "NZ", "DE", "FR", "ES"]
FOLDER = {"DE": "EU", "FR": "EU", "ES": "EU", "NL": "EU"}
FIELDS = ["file", "tier", "category", "region", "doc_type", "label", "case_id", "expected_result",
          "expected_findings", "ground_truth", "notes"]


def _seed(name: str) -> int:
    return zlib.crc32(name.encode())


def _row(path: Path, tier: str, category: str, region: str, doc_type: str, gt: Path, notes: str = "") -> dict:
    return {"file": path, "tier": tier, "category": category, "region": region, "doc_type": doc_type,
            "label": "genuine", "case_id": "", "expected_result": "pass", "expected_findings": "",
            "ground_truth": gt, "notes": notes}


def gen_identity(root: Path, as_of: date, seed: int, variants: int, rows: list, cache: dict) -> None:
    for region in ID_REGIONS:
        for v in range(variants):
            rng = random.Random(f"{seed}-id-{region}-{v}")
            p = P.make_person(region, rng, as_of, v)
            cache[(region, v)] = p
            folder = root / TIERS[0] / "identity" / FOLDER.get(region, region)
            for doc in I.build_region_docs(p, rng, as_of):
                stem = doc.doc_type if doc.doc_type.startswith(region.lower() + "_") else f"{region.lower()}_{doc.doc_type}"
                path = folder / f"{stem}_{v + 1:02d}.pdf"
                I.render_id(doc, path, _seed(path.name))
                gt = path.with_suffix(".json")
                F.write_json(gt, F.id_truth(doc))
                rows.append(_row(path, TIERS[0], "identity", FOLDER.get(region, region), doc.doc_type, gt))


def gen_bank(root: Path, as_of: date, seed: int, variants: int, rows: list, cache: dict) -> None:
    bucket = 0
    for code, bank in B.BANKS.items():
        holder_region = {"UAE": "UAE", "UK": "UK", "US": "US", "PK": "PK", "IN": "IN", "BD": "BD", "AU": "AU",
                         "NZ": "NZ", "DE": "DE", "FR": "FR", "NL": "NL"}[code]
        for v in range(variants):
            rng = random.Random(f"{seed}-bank-{code}-{v}")
            # same holder as the identity documents, so genuine cross-document checks line up
            p = cache.get((holder_region, v)) or P.make_person(holder_region, rng, as_of, v)
            st = B.make_statement(bank, p.full_name, p.address, rng, as_of, bucket % 9)
            bucket += 1
            path = root / TIERS[0] / "bank_statements" / FOLDER.get(code, code) / f"{code.lower()}_statement_{v + 1:02d}.pdf"
            B.render_statement(st, path)
            gt = path.with_suffix(".json")
            F.write_json(gt, st.truth())
            rows.append(_row(path, TIERS[0], "bank_statement", bank.region, "bank_statement", gt,
                             f"balance bucket {st.truth()['balance_bucket']}"))
            for f in B.write_bank_files(st, path):
                rows.append(_row(f, TIERS[0], "bank_statement", bank.region,
                                 "bank_statement_" + f.suffixes[0].lstrip("."), gt))


def gen_trade(root: Path, as_of: date, seed: int, variants: int, rows: list) -> None:
    for scenario in T.SCENARIOS:
        for v in range(variants):
            ctx = F.Ctx(as_of, seed)
            sh, st = F._ship(ctx, scenario, f"pristine-{scenario}-{v}", seq=v + 1)
            folder = root / TIERS[0] / "trade" / f"{scenario}_{v + 1:02d}"
            for path, kind, truth in F.emit_shipment(sh, folder):
                gt = path.with_suffix("").with_suffix(".json") if path.suffix != ".pdf" else path.with_suffix(".json")
                if path.suffix == ".pdf":
                    F.write_json(gt, truth)
                rows.append(_row(path, TIERS[0], "trade", scenario, kind, gt))
            sp = folder / "seller_statement.pdf"
            for path, kind, truth in F.emit_statement(st, sp):
                if path.suffix == ".pdf":
                    F.write_json(sp.with_suffix(".json"), truth)
                rows.append(_row(path, TIERS[0], "trade", scenario, kind, sp.with_suffix(".json"),
                                 "seller's own account; holder and account must match the invoice"))


def gen_degraded(root: Path, seed: int, rows: list) -> None:
    pristine = [r for r in rows if r["tier"] == TIERS[0] and Path(r["file"]).suffix == ".pdf"]
    for i, r in enumerate(pristine, 1):
        src = Path(r["file"])
        rel = src.relative_to(root / TIERS[0])
        rng = random.Random(f"{seed}-degrade-{rel.as_posix()}")
        with R.pymupdf.open(str(src)) as d:
            card = d[0].rect.width < 400
        # scanned tier: 300 DPI image-only PDF
        pages = R.rasterize(src, 300)
        scans = []
        fx_all = []
        for im in pages:
            s, fx = D.scan(im, rng, card)
            scans.append(s)
            fx_all.append(fx)
        out = root / TIERS[1] / rel
        D.image_pdf(scans, out)
        F.write_json(out.with_suffix(".json"), {"source": (TIERS[0] + "/" + rel.as_posix()),
                                                 "ground_truth": Path(r["ground_truth"]).relative_to(root).as_posix(),
                                                 "pages": fx_all})
        rows.append(dict(r, file=out, tier=TIERS[1], notes="image-only PDF, no text layer"))
        # mobile tier: one JPEG per page (cards at 300 DPI, A4 at 150 DPI to keep phone-like sizes)
        for n, im in enumerate(pages if card else R.rasterize(src, 150), 1):
            m, fx = D.mobile(im, rng)
            jpg = root / TIERS[2] / rel.parent / f"{rel.stem}_p{n}.jpg"
            D.save_jpeg(m, jpg)
            F.write_json(jpg.with_suffix(".json"), {"source": (TIERS[0] + "/" + rel.as_posix()), "page": n,
                                                     "ground_truth": Path(r["ground_truth"]).relative_to(root).as_posix(),
                                                     "capture": fx})
            rows.append(dict(r, file=jpg, tier=TIERS[2], notes=", ".join(k for k in fx if k != "perspective_corners")))
        print(f"  degraded {i}/{len(pristine)}: {rel.as_posix()}", flush=True)


def write_manifest(root: Path, rows: list, path: Path | None = None) -> Path:
    path = path or root / "manifest.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["tier"], str(r["file"]))):
            out = dict(r)
            for k in ("file", "ground_truth"):
                out[k] = Path(out[k]).relative_to(root).as_posix() if out[k] else ""
            w.writerow(out)
    return path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=HERE / "test_dataset")
    ap.add_argument("--seed", type=int, default=20261013)
    ap.add_argument("--as-of", type=date.fromisoformat, default=date(2026, 10, 13),
                    help="reference 'today' for expiry and statement periods (YYYY-MM-DD)")
    ap.add_argument("--variants", type=int, default=1, help="people / statements / shipments per region")
    ap.add_argument("--sections", default=None,
                    help="comma list of identity,bank,trade,degraded,fraud (default: all of them, "
                         "or none when --custom is given)")
    ap.add_argument("--cases", default="", help="only these fraud case ids, e.g. ID01,BK04")
    ap.add_argument("--overwrite", action="store_true", help="delete existing tier folders in --out first")
    ap.add_argument("--custom", type=Path, help="JSON file of your own cases (HOWTO.md). Alone, it adds "
                    "only those cases under 04_adversarial_fraud/custom/ and leaves the rest untouched")
    a = ap.parse_args(argv)

    root: Path = a.out.resolve()
    if a.sections:
        sections = set(a.sections.split(","))
    else:
        sections = set() if a.custom else {"identity", "bank", "trade", "degraded", "fraud"}
    if a.custom is not None:
        sections.add("custom")
        if not a.custom.exists():
            print(f"custom spec not found: {a.custom}", file=sys.stderr)
            return 2
    if sections - {"custom"}:
        existing = [t for t in TIERS if (root / t).exists()]
        if existing and not a.overwrite:
            print(f"{root} already has {existing}. Use --overwrite or another --out.", file=sys.stderr)
            return 2
        for t in existing:
            shutil.rmtree(root / t)
    root.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    cache: dict = {}
    if "identity" in sections:
        print("identity documents ...", flush=True)
        gen_identity(root, a.as_of, a.seed, a.variants, rows, cache)
    if "bank" in sections:
        print("bank statements ...", flush=True)
        gen_bank(root, a.as_of, a.seed, a.variants, rows, cache)
    if "trade" in sections:
        print("trade documents ...", flush=True)
        gen_trade(root, a.as_of, a.seed, a.variants, rows)
    if "degraded" in sections:
        print("scanned + mobile tiers ...", flush=True)
        gen_degraded(root, a.seed, rows)
    if "fraud" in sections:
        print("adversarial + edge cases ...", flush=True)
        only = {c.strip() for c in a.cases.split(",") if c.strip()} or None
        rows += F.run_cases(root / TIERS[3], a.as_of, a.seed, only)
    if "custom" in sections:
        print(f"custom cases from {a.custom} ...", flush=True)
        try:
            custom_rows = C.run_custom(a.custom, root / TIERS[3], a.as_of, a.seed)
        except C.SpecError as e:
            print(f"error in custom spec: {e}", file=sys.stderr)
            return 2
        rows += custom_rows
    if sections == {"custom"}:
        m = write_manifest(root, rows, root / TIERS[3] / "custom" / "manifest_custom.csv")
    else:
        m = write_manifest(root, rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["tier"]] = counts.get(r["tier"], 0) + 1
    print(f"\n{len(rows)} files -> {root}")
    for t in TIERS:
        print(f"  {t}: {counts.get(t, 0)}")
    print(f"  manifest: {m.relative_to(root).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
