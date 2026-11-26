"""
Pinned MIDI-B references for experiments E1 and E2(a) (docs/protocol.md, 2).

Every script that fetches or calls the MIDI-B scoring script must take the
commit from here, never a branch name, so each score can be reproduced with
the exact scorer the protocol froze. The values are also written to run.json
(see docs/results_schema.md).
"""

SCORER_REPOSITORY = "https://github.com/CBIIT/MIDI_validation_script"
SCORER_COMMIT = "ccc0939317d5ffd14edda33bc04641490d6f2254"

DATASET_DOI = "10.7937/cf2p-aw56"
DATASET_VERSION = "1"
DATASET_ACCESS_DATE = "2026-07-02"


def scorer_run_fields() -> dict:
    """The `scorer` field and MIDI-B dataset identity for run.json."""
    return {
        "scorer": {"repository": SCORER_REPOSITORY, "commit": SCORER_COMMIT},
        "dataset_ref": {"doi": DATASET_DOI, "version": DATASET_VERSION,
                        "access_date": DATASET_ACCESS_DATE},
    }
