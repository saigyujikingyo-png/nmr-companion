import hashlib
import json
import sqlite3

from nmr_companion.service import Service
from nmr_companion.store import canonical_json


def test_schema_one_read_is_unchanged_upgrade_backup_replay_and_undo(tmp_path):
    path = tmp_path / "legacy.nmrproj"
    service = Service(path)
    service.create("Legacy")
    service.apply(0, "old_demo", {"op": "demo"})
    sid = next(iter(service.read().spectra))
    old_command = {
        "op": "assign",
        "assignment_id": None,
        "sample": "A",
        "atom": "Ha",
        "candidate": "Candidate",
        "observation": "Old evidence",
        "evidence_ids": [sid],
        "status": "proposed",
    }
    service.apply(1, "old_assignment", old_command)
    with sqlite3.connect(path) as db:
        for rev, raw in db.execute("SELECT revision,payload FROM snapshots").fetchall():
            p = json.loads(raw)
            p["schema_version"] = 1
            for key in (
                "samples",
                "structures",
                "crosspeaks",
                "peaklabels",
                "attachments",
                "annotations",
            ):
                p.pop(key)
            for a in p["assignments"].values():
                for key in ("sample_id", "candidate_id", "atom_ids"):
                    a.pop(key)
            db.execute("UPDATE snapshots SET payload=? WHERE revision=?", (canonical_json(p), rev))
        fingerprint = hashlib.sha256(
            canonical_json({"expected_revision": 1, "command": old_command}).encode()
        ).hexdigest()
        db.execute("UPDATE requests SET fingerprint=? WHERE id='old_assignment'", (fingerprint,))
        db.execute("PRAGMA user_version=1")
    with sqlite3.connect(path) as db:
        before = db.execute("SELECT payload FROM snapshots ORDER BY revision").fetchall()
    assert service.read().schema_version == 1
    assert not list(tmp_path.glob("*.backup"))
    replay = service.apply(1, "old_assignment", old_command)
    assert replay.replayed and replay.revision == 2
    assert not list(tmp_path.glob("*.backup"))
    receipt = service.apply(
        2,
        "upgrade_sample",
        {"op": "sample", "name": "New sample", "role": "own", "object_ids": [sid]},
    )
    assert receipt.revision == 3 and service.read().schema_version == 2
    backups = list(tmp_path.glob("*.backup"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT payload FROM snapshots ORDER BY revision").fetchall() == before
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert Service(backups[0]).read().revision == 2
    service.apply(3, "undo_upgrade", {"op": "undo", "target_revision": 2})
    assert service.read().schema_version == 2 and not service.read().samples
    assert len(list(tmp_path.glob("*.backup"))) == 1
