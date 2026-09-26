"""Regressions for independently reviewed provenance, matching and migration defects.

All acquisition data and schema-1 files are generated in the test's own tmp_path.
The tests exercise public service operations and the actual exported artifacts.
"""

from contextlib import closing, contextmanager
import csv
import gc
import hashlib
from io import BytesIO, StringIO
import json
import math
import sqlite3
from uuid import uuid4
from xml.etree import ElementTree
import zipfile

import pytest

from nmr_companion.errors import NmrError
from nmr_companion.models import Spectrum, Table
from nmr_companion.service import Service


def edit(service, operation, **arguments):
    return service.apply(
        service.read().revision,
        "review_" + uuid4().hex,
        {"op": operation, **arguments},
    )


def export_files(service, revision):
    artifact = service.export(revision)
    metadata, data = service.store.artifact(artifact.id)
    assert metadata.revision == revision
    assert hashlib.sha256(data).hexdigest() == metadata.sha256
    with zipfile.ZipFile(BytesIO(data)) as bundle:
        return {name: bundle.read(name) for name in bundle.namelist()}


def read_csv(data):
    reader = csv.DictReader(StringIO(data.decode("utf-8")))
    records = list(reader)
    assert reader.fieldnames is not None
    assert len(reader.fieldnames) == len(set(reader.fieldnames))
    return reader.fieldnames, records


def seed_review_spectra(service):
    # The two carbon maxima are exactly 10.00 and 10.16 ppm. The sole DEPT
    # maximum at 10.08 ppm is independently within 0.1 ppm of both carbons.
    carbon_axis = [9.90, 9.96, 10.00, 10.04, 10.08, 10.12, 10.16, 10.20, 10.24]
    spectra = [
        Spectrum(
            id="proton",
            name="Synthetic quantitative proton spectrum",
            axis=[0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            real=[0.0, 0.0, 3.0, 0.0, 6.0, 0.0, 0.0],
            domain="frequency",
            axis_unit="ppm",
            nucleus="1H",
            metadata={"synthetic": True},
        ),
        Spectrum(
            id="carbon",
            name="Synthetic competing carbon peaks",
            axis=carbon_axis,
            real=[0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            domain="frequency",
            axis_unit="ppm",
            nucleus="13C",
            metadata={"synthetic": True},
        ),
        Spectrum(
            id="dept",
            name="Synthetic single DEPT observation",
            axis=carbon_axis,
            real=[0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            domain="frequency",
            axis_unit="ppm",
            nucleus="13C",
            metadata={"synthetic": True},
        ),
    ]

    def seed(project, _database):
        project.spectra.update({spectrum.id: spectrum for spectrum in spectra})
        return [spectrum.id for spectrum in spectra], []

    service.store.mutate(0, "seed_review_spectra", {"op": "test_fixture"}, seed)


def create_analysis(service, kind):
    if kind == "dept":
        return edit(
            service,
            "dept",
            carbon_spectrum_id="carbon",
            dept_spectrum_id="dept",
            carbon_prominence=0.2,
            dept_prominence=0.2,
            tolerance_ppm=0.1,
            reference_convention="positive_ch_ch3",
            reference="Synthetic declared phase reference for regression testing",
        ).object_ids[0]
    product = edit(
        service, "integrate", spectrum_id="proton", name="Product", lower=1.0, upper=3.0
    ).object_ids[0]
    standard = edit(
        service, "integrate", spectrum_id="proton", name="Standard", lower=3.0, upper=5.0
    ).object_ids[0]
    if kind == "normalization":
        return edit(
            service,
            "normalize",
            reference_integral_id=standard,
            reference_protons=6.0,
            integral_ids=[product, standard],
        ).object_ids[0]
    return edit(
        service,
        "yield",
        product_integral_id=product,
        standard_integral_id=standard,
        product_protons=3.0,
        standard_protons=6.0,
        standard_mol=0.001,
        limiting_mol=0.001,
    ).object_ids[0]


@pytest.mark.parametrize("kind", ["dept", "normalization", "yield"])
def test_stale_analysis_csv_keeps_identity_evidence_versions_and_export_revision(tmp_path, kind):
    service = Service(tmp_path / "stale-results.nmrproj")
    service.create("Synthetic stale export regression")
    seed_review_spectra(service)
    analysis_id = create_analysis(service, kind)
    original = service.read().analyses[analysis_id]
    assert original.state == "current"

    # A real upstream edit, rather than assigning state='stale' in the fixture.
    edit(
        service,
        "process",
        spectrum_id="carbon" if kind == "dept" else "proton",
        method="reference",
        reference_shift_ppm=0.01,
    )
    snapshot = service.read()
    stale = snapshot.analyses[analysis_id]
    assert stale.state == "stale"
    assert stale.source_versions == original.source_versions
    assert any(
        snapshot.object(source_id).version > recorded_version
        for source_id, recorded_version in stale.source_versions.items()
    )

    # Export an older named revision after a later edit: provenance must describe
    # the exported state, not whichever project revision happens to be latest.
    edit(service, "sample", name="Later unrelated sample", role="unknown")
    assert service.read().revision > snapshot.revision
    files = export_files(service, snapshot.revision)
    fields, rows = read_csv(files[f"tables/{analysis_id}.csv"])
    assert rows
    assert {"analysis_id", "state", "source_versions", "project_id", "revision"} <= set(fields)
    for row in rows:
        assert row["analysis_id"] == analysis_id
        assert row["state"] == "stale"
        assert row["project_id"] == snapshot.id
        assert int(row["revision"]) == snapshot.revision
        assert json.loads(row["source_versions"]) == original.source_versions
    assert json.loads(files["manifest.json"])["revision"] == snapshot.revision


def test_one_dept_peak_cannot_independently_confirm_two_nearby_carbon_peaks(tmp_path):
    service = Service(tmp_path / "competing-dept.nmrproj")
    service.create("Synthetic many-to-one DEPT regression")
    seed_review_spectra(service)
    analysis_id = create_analysis(service, "dept")
    rows = service.read().analyses[analysis_id].result["rows"]

    assert len(rows) == 2
    assert sorted(row["carbon_ppm"] for row in rows) == pytest.approx([10.00, 10.16])
    for row in rows:
        assert row["interpretation"] == "ambiguous"
        assert row["matched_candidates"] == 1
        assert row["competing_carbon_candidates"] == 2
        assert row["dept_ppm"] is None
        assert row["dept_intensity"] is None


def test_imported_reserved_columns_cannot_replace_export_provenance(tmp_path):
    source_values = {
        "project_id": "source-project-is-not-system-provenance",
        "revision": "999999",
        "analysis_id": "source-analysis-id",
        "state": "source-state",
        "source_versions": '{"source-evidence":999}',
        "sample_provenance": "source-role-text",
        "source.project_id": "already-prefixed-source-column",
    }
    source = tmp_path / "reserved-columns.csv"
    with source.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(source_values))
        writer.writeheader()
        writer.writerow(source_values)

    service = Service(tmp_path / "reserved-columns.nmrproj")
    service.create("Synthetic CSV provenance regression")
    edit(service, "import", path=str(source))
    snapshot = service.read()
    assert len(snapshot.tables) == 1
    table = next(iter(snapshot.tables.values()))
    assert table.rows == [source_values]

    files = export_files(service, snapshot.revision)
    fields, rows = read_csv(files[f"tables/{table.id}.csv"])
    assert len(rows) == 1
    assert rows[0]["project_id"] == snapshot.id
    assert int(rows[0]["revision"]) == snapshot.revision
    assert fields.count("project_id") == fields.count("revision") == 1
    for key, value in source_values.items():
        assert rows[0]["source." + key] == value
    assert "analysis_id" not in fields
    assert "state" not in fields
    assert "source_versions" not in fields
    assert "sample_provenance" not in fields
    # The original user file and its exact source records remain intact.
    assert service.read().tables[table.id].rows == [source_values]
    preserved = list(service.read().sources)
    assert len(preserved) == 1
    assert files[f"originals/{preserved[0]}"] == source.read_bytes()


def create_legacy_file(path):
    """An independent schema-1 fixture, not a current project silently downgraded."""
    payload = {
        "schema_version": 1,
        "id": "legacy_review_project",
        "name": "Synthetic legacy project",
        "revision": 0,
        **{
            name: {}
            for name in (
                "sources",
                "spectra",
                "grids",
                "tables",
                "integrals",
                "analyses",
                "assignments",
            )
        },
    }
    with closing(sqlite3.connect(path)) as database:
        database.executescript(
            "CREATE TABLE snapshots(revision INTEGER PRIMARY KEY, payload TEXT NOT NULL);"
            "CREATE TABLE requests(id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT NOT NULL);"
            "CREATE TABLE originals(sha256 TEXT PRIMARY KEY, data BLOB NOT NULL);"
            "CREATE TABLE artifacts(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, data BLOB NOT NULL);"
        )
        database.execute("INSERT INTO snapshots VALUES(0,?)", (json.dumps(payload),))
        database.execute("PRAGMA user_version=1")
        database.commit()
    return payload


@contextmanager
def without_automatic_gc():
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if was_enabled:
            gc.enable()


@pytest.mark.parametrize(
    ("command", "error_code"),
    [
        ({"op": "integrate", "spectrum_id": "missing", "lower": 0.0, "upper": 1.0}, "NOT_FOUND"),
        ({"op": "undo", "target_revision": 0}, "INVALID_UNDO"),
    ],
)
def test_failed_schema_one_mutation_leaves_no_published_or_partial_backup(
    tmp_path, command, error_code
):
    path = tmp_path / "failed-upgrade.nmrproj"
    legacy = create_legacy_file(path)
    service = Service(path)
    with without_automatic_gc():
        with pytest.raises(NmrError) as failure:
            service.apply(0, "failed_schema_upgrade", command)
        # These are semantic failures inside the transaction, after schema-1
        # backup preparation, rather than early input-schema rejection.
        assert failure.value.code == error_code
        assert not list(tmp_path.glob("*.backup.partial"))
        assert not list(tmp_path.glob("*.backup"))
        with closing(sqlite3.connect(path)) as database:
            assert database.execute("PRAGMA user_version").fetchone()[0] == 1
            assert (
                json.loads(database.execute("SELECT payload FROM snapshots").fetchone()[0])
                == legacy
            )
            assert database.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


def test_upgraded_source_and_backup_can_be_renamed_immediately_without_gc(tmp_path):
    path = tmp_path / "successful-upgrade.nmrproj"
    legacy = create_legacy_file(path)
    service = Service(path)
    with without_automatic_gc():
        receipt = service.apply(
            0,
            "successful_schema_upgrade",
            {"op": "sample", "name": "First schema-2 sample", "role": "own"},
        )
        assert receipt.revision == 1
        assert service.read().schema_version == 2
        backups = list(tmp_path.glob("*.backup"))
        assert len(backups) == 1
        assert not list(tmp_path.glob("*.backup.partial"))

        # On Windows these immediately fail for leaked SQLite connections.
        # Keep the Service alive, with automatic GC disabled, throughout.
        moved_source = path.rename(tmp_path / "renamed-source.nmrproj")
        moved_backup = backups[0].rename(tmp_path / "renamed-rollback.nmrproj")
        assert service.store.path == path.resolve()
        assert not path.exists() and not backups[0].exists()
        for target, version, revision in ((moved_source, 2, 1), (moved_backup, 1, 0)):
            with closing(sqlite3.connect(target)) as database:
                assert database.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert database.execute("PRAGMA user_version").fetchone()[0] == version
                assert (
                    database.execute("SELECT MAX(revision) FROM snapshots").fetchone()[0]
                    == revision
                )
                assert (
                    json.loads(
                        database.execute(
                            "SELECT payload FROM snapshots WHERE revision=0"
                        ).fetchone()[0]
                    )
                    == legacy
                )


def test_fit_figure_resolves_sample_roles_through_its_source_versions(tmp_path):
    service = Service(tmp_path / "fit-provenance.nmrproj")
    service.create("Synthetic fit provenance regression")
    times = [0.0, 0.1, 0.2, 0.4, 0.8, 1.2, 1.8, 2.5]
    trace_ids = [f"trace_{index}" for index in range(len(times))]

    def seed(project, _database):
        for trace_id, delay in zip(trace_ids, times):
            amplitude = 1.0 - 2.0 * math.exp(-delay / 0.5)
            project.spectra[trace_id] = Spectrum(
                id=trace_id,
                name=trace_id,
                axis=[3.0, 3.5, 4.0, 4.5, 5.0],
                real=[0.0, 0.0, amplitude, 0.0, 0.0],
                domain="frequency",
                axis_unit="ppm",
                nucleus="1H",
                metadata={"synthetic": True},
            )
        project.spectra["unrelated"] = project.spectra[trace_ids[0]].model_copy(
            update={"id": "unrelated", "name": "Unrelated trace"}
        )
        project.tables["delays"] = Table(
            id="delays",
            name="Synthetic elapsed times",
            columns=["elapsed_s"],
            rows=[{"elapsed_s": str(delay)} for delay in times],
        )
        return [*trace_ids, "unrelated", "delays"], []

    service.store.mutate(0, "seed_fit_sources", {"op": "test_fixture"}, seed)
    for name, role, spectrum_id in (
        ("Owned trace", "own", trace_ids[0]),
        ("Reference trace", "reference", trace_ids[1]),
        ("Unrelated sample", "synthetic", "unrelated"),
    ):
        edit(service, "sample", name=name, role=role, object_ids=[spectrum_id])
    fit_id = edit(
        service,
        "fit",
        spectrum_ids=trace_ids,
        table_id="delays",
        row_indices=list(range(len(times))),
        delay_column="elapsed_s",
        time_unit="s",
        model="T1",
        lower=3.5,
        upper=4.5,
    ).object_ids[0]
    snapshot = service.read()
    analysis = snapshot.analyses[fit_id]
    assert set(trace_ids) <= set(analysis.source_versions)
    assert analysis.result["T_s"] == pytest.approx(0.5, rel=1e-6)
    files = export_files(service, snapshot.revision)
    svg = ElementTree.fromstring(files[f"figures/{fit_id}.svg"])
    text = " ".join(element.text or "" for element in svg.iter("{http://www.w3.org/2000/svg}text"))
    assert "Owned trace (own)" in text
    assert "Reference trace (reference)" in text
    assert "sample role unspecified" not in text
    assert "Unrelated sample" not in text
    assert f"revision {snapshot.revision}" in text
    assert fit_id in text


def test_empty_peak_export_keeps_revision_and_analysis_provenance(tmp_path):
    service = Service(tmp_path / "empty-peaks.nmrproj")
    service.create("Synthetic empty peak result")
    edit(service, "demo")
    sid = next(iter(service.read().spectra))
    aid = edit(service, "peaks", spectrum_id=sid, prominence=100.0).object_ids[0]
    project = service.read()
    assert project.analyses[aid].result["peaks"] == []
    files = export_files(service, project.revision)
    fields, rows = read_csv(files[f"tables/{aid}.csv"])
    assert len(rows) == 1 and rows[0]["result_count"] == "0"
    assert "ppm" not in fields and "intensity" not in fields
    assert rows[0]["analysis_id"] == aid
    assert rows[0]["project_id"] == project.id
    assert rows[0]["revision"] == str(project.revision)
    assert rows[0]["state"] == "current"
    assert json.loads(rows[0]["source_versions"]) == {sid: 1}
    assert json.loads(files[f"analyses/{aid}.json"])["result"]["peaks"] == []
