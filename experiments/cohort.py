"""
Synthetic study cohort for experiments E3 and E7 (docs/protocol.md, section 2).

Protocol spec: 100 synthetic patients with 3 to 5 studies each, at least 20
children under 2 years and at least 5 patients over 90 at their first study,
seed 20261125. Every person and identifier is invented (Faker + seeded RNG).

Unlike `dicom-deid synth` (which tests the pipeline against messy archives),
this cohort exists to measure linkage and age, so it adds what that needs:
infants, over-90s, several studies per patient, size and weight, and a
ground-truth manifest of the true values. Folder names are opaque (p000/s0),
so no name appears in a path.

The manifest holds the synthetic identifiers by design (it is the answer
key). It is written next to the files under data/experiments/, which is
git-ignored, and is regenerated from the seed rather than committed.

Usage:
    python experiments/cohort.py [--out data/experiments/cohort] [--seed 20261125]
"""

import argparse
import json
import random
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

from dicom_deid.dicom_deid import age_string
from dicom_deid.synthetic import (
    DESCRIPTIONS, HOSPITALS, MANUFACTURERS, MODALITIES, REFERENCE_DATE, _emirates_id, _instance, _uid,
)

PROTOCOL_SEED = 20261125
N_PATIENTS = 100
N_CHILDREN_UNDER_2 = 20
N_OVER_90 = 5
STUDIES_PER_PATIENT = (3, 5)
IMAGE_SIZE = 32  # pixels are noise; small keeps the cohort quick to build

DEFAULT_OUT = Path("data/experiments/cohort")


def _age_days(rng: random.Random, group: str) -> int:
    """Age in days at the first study, by group."""
    if group == "child":
        return rng.randint(0, 2 * 365 - 1)
    if group == "over90":
        return rng.randint(int(90 * 365.25) + 1, int(98 * 365.25))
    return rng.randint(int(18 * 365.25), int(89 * 365.25))


def _size_weight(rng: random.Random, group: str) -> tuple[str, str]:
    if group == "child":
        return f"{rng.uniform(0.45, 0.90):.2f}", f"{rng.uniform(2.5, 13.0):.1f}"
    return f"{rng.uniform(1.45, 1.95):.2f}", f"{rng.uniform(42.0, 115.0):.1f}"


def generate_cohort(out_dir: Path = DEFAULT_OUT, seed: int = PROTOCOL_SEED,
                    patients: int = N_PATIENTS) -> dict:
    """Write the cohort under `out_dir` and return its ground-truth manifest."""
    fake = Faker()
    fake.seed_instance(seed)
    rng = random.Random(seed)
    out_dir = Path(out_dir)

    groups = ["child"] * N_CHILDREN_UNDER_2 + ["over90"] * N_OVER_90
    groups += ["adult"] * (patients - len(groups))
    rng.shuffle(groups)

    rows: list[dict] = []
    for pi, group in enumerate(groups):
        n_studies = rng.randint(*STUDIES_PER_PATIENT)
        gaps = [rng.randint(7, 365) for _ in range(n_studies - 1)]
        first_study = REFERENCE_DATE - timedelta(days=sum(gaps) + rng.randint(0, 3 * 365))
        dob = first_study - timedelta(days=_age_days(rng, group))
        person = {
            "first": fake.first_name(), "last": fake.last_name(), "sex": rng.choice("MF"),
            "mrn": f"MRN{pi:03d}{rng.randint(1000, 9999)}", "dob": dob,
            "address": fake.address().replace("\n", ", "), "phone": fake.numerify("+971-5#-###-####"),
            "national_id": _emirates_id(rng, dob.year),
        }
        size, weight = _size_weight(rng, group)

        study_date = first_study
        for si in range(n_studies):
            if si:
                study_date += timedelta(days=gaps[si - 1])
            modality = rng.choice(list(MODALITIES))
            body_part = rng.choice(MODALITIES[modality][1])
            study = {
                "uid": _uid("cohort", seed, pi, si), "date": study_date, "description": DESCRIPTIONS[body_part],
                "accession": f"ACC{pi:03d}{si}{rng.randint(1000, 9999)}", "study_id": str(rng.randint(1000, 9999)),
                "referrer": f"{fake.last_name()}^{fake.first_name()}^^Dr.",
                "performer": f"{fake.last_name()}^{fake.first_name()}",
                "operator": f"{fake.last_name()}^{fake.first_name()}",
                "hospital": rng.choice(HOSPITALS), "hospital_address": fake.address().replace("\n", ", "),
            }
            series = {
                "uid": _uid(study["uid"], 1), "modality": modality, "body_part": body_part, "number": 1,
                "manufacturer": rng.choice(MANUFACTURERS),
                "burned_in": rng.choice(["YES", None]) if modality == "US" else "NO",
            }
            ds = _instance(rng, person, study, series, 1, IMAGE_SIZE)
            ds.PatientAge = age_string(dob, study_date)
            ds.PatientSize, ds.PatientWeight = size, weight

            rel = f"p{pi:03d}/s{si}/IM0001"
            path = out_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            ds.save_as(path, enforce_file_format=True)
            rows.append({
                "file": rel, "patient": pi, "group": group, "patient_id": person["mrn"],
                "birth_date": dob.isoformat(), "study_date": study_date.isoformat(),
                "study_uid": study["uid"], "sex": person["sex"], "modality": modality,
                "recorded_age": ds.PatientAge, "size_m": size, "weight_kg": weight,
            })

    manifest = {
        "generator": "experiments/cohort.py", "seed": seed, "reference_date": REFERENCE_DATE.isoformat(),
        "patients": patients, "instances": rows,
    }
    (out_dir / "ground_truth.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=PROTOCOL_SEED)
    args = parser.parse_args(argv)
    manifest = generate_cohort(args.out, args.seed)
    print(f"{manifest['patients']} patients, {len(manifest['instances'])} studies -> {args.out}")
    if args.seed != PROTOCOL_SEED:
        print(f"note: seed {args.seed} is not the protocol seed {PROTOCOL_SEED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
