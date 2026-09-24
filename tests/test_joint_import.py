"""A complete synthetic physical workflow, independent of the built-in demonstration."""

import math
import pytest
from nmr_companion.service import Service


def test_dx_csv_import_t2_mapping_exclusion_and_reopened_export(tmp_path):
    inputs = tmp_path / "paired-export"
    inputs.mkdir()
    # Intentionally unsorted and with a genuine replicate; CSV stores echo intervals.
    elapsed = [1.2, 0.04, 0.15, 0.3, 0.6, 0.9, 0.15, 2.0]
    (inputs / "delays.csv").write_text(
        "tau_ms\n" + "\n".join(str(t * 500) for t in elapsed) + "\n", encoding="utf-8"
    )
    for i, t in enumerate(elapsed):
        amplitude = 0.12 + 2.4 * math.exp(-t / 0.42)
        (inputs / f"trace-{i:02}.dx").write_text(
            "##TITLE=Synthetic T2 trace\n##JCAMP-DX=5.00\n##DATA TYPE=NMR SPECTRUM\n"
            "##.OBSERVE NUCLEUS=1H\n##XUNITS=PPM\n##YUNITS=ARBITRARY UNITS\n"
            "##FIRSTX=3\n##LASTX=5\n##NPOINTS=5\n##XYPOINTS=(XY..XY)\n"
            f"3,0 3.5,0 4,{amplitude:.16g} 4.5,0 5,0\n##END=\n",
            encoding="utf-8",
        )
    service = Service(tmp_path / "relaxation.nmrproj")
    service.create("Synthetic DX/CSV")
    service.apply(0, "import-series", {"op": "import", "path": str(inputs)})
    project = service.read()
    assert len(project.spectra) == 8 and len(project.tables) == 1
    # Replicate files have identical bytes but must retain both original filenames.
    assert len(project.sources) == 8
    assert sum(len(source.names) for source in project.sources.values()) == 9
    assert any(
        set(source.names) == {"trace-02.dx", "trace-06.dx"} for source in project.sources.values()
    )
    spectra = sorted(project.spectra.values(), key=lambda s: s.name)
    receipt = service.apply(
        1,
        "fit-series",
        {
            "op": "fit",
            "spectrum_ids": [s.id for s in spectra],
            "table_id": next(iter(project.tables)),
            "row_indices": list(range(8)),
            "delay_column": "tau_ms",
            "time_unit": "ms",
            "model": "T2",
            "time_basis": "echo_interval",
            "delay_multiplier": 2,
            "lower": 3.5,
            "upper": 4.5,
            "excluded_indices": [0],
            "purpose": "quick_check",
        },
    )
    result = service.read().analyses[receipt.object_ids[0]].result
    assert result["T_s"] == pytest.approx(0.42, rel=1e-6)
    assert result["parameters"]["C"] == pytest.approx(0.06, abs=1e-7)
    assert result["time_s"] == pytest.approx(elapsed[1:])
    assert result["mapping"][0]["excluded"]
    assert result["mapping"][6]["row_index"] == 6
    assert any("quick check" in warning for warning in result["warnings"])
    assert any("REPEATED" in warning for warning in result["warnings"])
    assert Service(service.store.path).read().analyses[receipt.object_ids[0]].result == result


def test_import_objects_bind_to_their_own_bytes_and_keep_equal_hash_labels(tmp_path):
    folder = tmp_path / "inputs"
    folder.mkdir()
    (folder / "first.csv").write_text("delay\n1\n", encoding="utf-8")
    (folder / "replicate.csv").write_text("delay\n1\n", encoding="utf-8")
    (folder / "different.csv").write_text("delay\n3\n", encoding="utf-8")
    service = Service(tmp_path / "binding.nmrproj")
    service.create("Binding")
    service.apply(0, "import", {"op": "import", "path": str(folder)})
    project = service.read()
    tables = {table.name: table for table in project.tables.values()}
    assert len(project.sources) == 2
    assert tables["first.csv"].id != tables["replicate.csv"].id
    assert tables["first.csv"].source_ids == tables["replicate.csv"].source_ids
    assert tables["first.csv"].source_ids != tables["different.csv"].source_ids
    for table in tables.values():
        assert len(table.source_ids) == 1
        assert table.name in project.sources[table.source_ids[0]].names
