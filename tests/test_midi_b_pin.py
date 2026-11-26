"""The MIDI-B scorer pin must be a full commit hash and match the docs."""

import re
from pathlib import Path

from experiments import midi_b

ROOT = Path(__file__).resolve().parent.parent


def test_scorer_is_pinned_to_a_full_commit_hash():
    assert re.fullmatch(r"[0-9a-f]{40}", midi_b.SCORER_COMMIT)


def test_protocol_and_schema_state_the_same_pin():
    protocol = (ROOT / "docs" / "protocol.md").read_text(encoding="utf-8")
    schema = (ROOT / "docs" / "results_schema.md").read_text(encoding="utf-8")
    assert midi_b.SCORER_COMMIT in protocol and midi_b.SCORER_COMMIT in schema
    assert midi_b.DATASET_DOI in protocol
    assert midi_b.DATASET_ACCESS_DATE in protocol


def test_midi_b_row_has_no_record_markers_left():
    protocol = (ROOT / "docs" / "protocol.md").read_text(encoding="utf-8")
    assert "[RECORD" not in protocol
