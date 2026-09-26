"""Installed-runtime check, isolated from user projects and preferences."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from .service import Service


def run():
    with TemporaryDirectory(prefix="nmr-self-test-") as directory:
        s = Service(Path(directory) / "check.nmrproj")
        s.create("Synthetic runtime check")
        s.apply(0, "self_test_demo", {"op": "demo"})
        p = s.read()
        ids = [v.id for v in p.spectra.values() if v.metadata.get("delay_s") is not None]
        table = next(iter(p.tables))
        receipt = s.apply(
            1,
            "self_test_fit",
            {
                "op": "fit",
                "table_id": table,
                "spectrum_ids": ids,
                "row_indices": list(range(8)),
                "delay_column": "delay_ms",
                "time_unit": "ms",
                "model": "T1",
                "lower": 3.7,
                "upper": 4.3,
            },
        )
        fit = s.read().analyses[receipt.object_ids[0]]
        if abs(fit.result["T_s"] - 0.5) > 1e-5:
            raise RuntimeError("Synthetic relaxation check failed.")
        artifact = s.export(2)
        s.store.artifact(artifact.id)
        return json.dumps(
            {
                "ok": True,
                "scope": "isolated synthetic runtime, numerical fit and export",
                "T_s": fit.result["T_s"],
                "artifact_bytes": artifact.size,
            }
        )
