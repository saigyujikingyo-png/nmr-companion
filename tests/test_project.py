from concurrent.futures import ThreadPoolExecutor
import hashlib
from io import BytesIO
import json
import zipfile

import pytest
from pydantic import ValidationError
from nmr_companion.api import SPECS, dispatch
from nmr_companion.errors import NmrError
from nmr_companion.models import Spectrum
from nmr_companion.service import Service


@pytest.fixture
def project(tmp_path):
    service = Service(tmp_path / "experiment.nmrproj")
    service.create("Synthetic validation")
    service.apply(0, "demo", {"op": "demo"})
    return service


def apply(service, request, command):
    return service.apply(service.read().revision, request, command)


def integral(service, sid, lo, hi, request):
    return apply(
        service, request, {"op": "integrate", "spectrum_id": sid, "lower": lo, "upper": hi}
    ).object_ids[0]


def test_exactly_once_conflict_and_reopen(project):
    revision = project.read().revision
    sid = next(iter(project.read().spectra))
    command = {"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3}
    first = project.apply(revision, "stable-request", command)
    second = project.apply(revision, "stable-request", command)
    assert second.replayed and first.revision == second.revision
    assert len(project.read().integrals) == 1
    with pytest.raises(NmrError, match="different command") as failure:
        project.apply(revision, "stable-request", {**command, "upper": 2.4})
    assert failure.value.code == "REQUEST_ID_REUSED"
    with pytest.raises(NmrError) as failure:
        project.apply(revision, "stale-request", command)
    assert failure.value.code == "REVISION_CONFLICT"
    assert failure.value.current_revision == first.revision
    reopened = Service(project.store.path)
    assert reopened.read() == project.read()
    assert reopened.store.request("stable-request") == first


def test_two_frontends_one_revision(project):
    sid = next(iter(project.read().spectra))
    revision = project.read().revision
    command = {"op": "integrate", "spectrum_id": sid, "lower": 1, "upper": 3}

    def edit(request):
        try:
            return Service(project.store.path).apply(revision, request, command).revision
        except NmrError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(edit, ["human", "agent"]))
    assert sorted(map(str, results)) == sorted([str(revision + 1), "REVISION_CONFLICT"])
    assert len(project.read().integrals) == 1


def test_joint_organic_physical_verticals(project):
    p = project.read()
    sid = next(iter(p.spectra))
    product = integral(project, sid, 1.7, 2.3, "product")
    standard = integral(project, sid, 6.7, 7.3, "standard")
    result = apply(
        project,
        "yield",
        {
            "op": "yield",
            "product_integral_id": product,
            "standard_integral_id": standard,
            "product_protons": 3,
            "standard_protons": 6,
            "standard_mol": 0.001,
            "limiting_mol": 0.001,
        },
    )
    analysis = project.read().analyses[result.object_ids[0]]
    # Synthetic equal molar amount: peak amplitudes 3 and 6, same line shape.
    assert analysis.result["yield_percent"] == pytest.approx(100, abs=1e-4)
    table = next(iter(p.tables))
    ids = list(p.spectra)[1:]
    fit = apply(
        project,
        "t1",
        {
            "op": "fit",
            "spectrum_ids": ids,
            "table_id": table,
            "row_indices": list(range(8)),
            "delay_column": "delay_ms",
            "time_unit": "ms",
            "model": "T1",
            "lower": 3.7,
            "upper": 4.3,
        },
    )
    fit_result = project.read().analyses[fit.object_ids[0]]
    assert fit_result.result["T_s"] == pytest.approx(0.5, rel=1e-7)
    assert min(fit_result.result["signals"]) < 0 < max(fit_result.result["signals"])
    assert fit_result.result["diagnostics"]["normalization"] == "none"
    assert fit_result.result["u_T_s"] is not None


def test_edit_invalidates_derived_results_and_undo_restores(project):
    p = project.read()
    sid = next(iter(p.spectra))
    a = integral(project, sid, 1.7, 2.3, "product")
    b = integral(project, sid, 6.7, 7.3, "standard")
    receipt = apply(
        project,
        "yield",
        {
            "op": "yield",
            "product_integral_id": a,
            "standard_integral_id": b,
            "product_protons": 3,
            "standard_protons": 6,
            "standard_mol": 1,
            "limiting_mol": 1,
        },
    )
    aid = receipt.object_ids[0]
    assignment = apply(
        project,
        "assign",
        {
            "op": "assign",
            "sample": "A",
            "atom": "H1",
            "candidate": "candidate A",
            "observation": "Integral evidence",
            "evidence_ids": [aid],
            "status": "confirmed",
        },
    )
    saved = project.read()
    apply(
        project,
        "edit-region",
        {"op": "integrate", "integral_id": a, "spectrum_id": sid, "lower": 1.8, "upper": 2.1},
    )
    p = project.read()
    assert p.analyses[aid].state == "stale"
    assert p.assignments[assignment.object_ids[0]].state == "stale"
    apply(project, "undo", {"op": "undo", "target_revision": saved.revision})
    reopened = project.read()
    assert reopened.revision == saved.revision + 2
    assert reopened.integrals[a] == saved.integrals[a]
    assert reopened.analyses[aid].state == "current"
    assert project.store.request("edit-region").revision == saved.revision + 1


def test_reference_preserves_region_identity_and_area(project):
    p = project.read()
    sid = next(iter(p.spectra))
    iid = integral(project, sid, 1.7, 2.3, "product")
    original = project.read().integrals[iid]
    apply(
        project,
        "reference",
        {"op": "process", "spectrum_id": sid, "method": "reference", "reference_shift_ppm": 0.5},
    )
    shifted = project.read().integrals[iid]
    assert shifted.lower == pytest.approx(2.2)
    assert shifted.area == pytest.approx(original.area, rel=1e-12)
    assert shifted.version == original.version + 1
    assert shifted.spectrum_version == 2


def test_missing_inputs_and_processed_fft_have_no_effect(project):
    p = project.read()
    sid = next(iter(p.spectra))
    for command in [
        {"op": "yield"},
        {"op": "process", "spectrum_id": sid, "method": "fft"},
        {"op": "integrate", "spectrum_id": sid, "lower": True, "upper": 4},
    ]:
        with pytest.raises(NmrError):
            apply(project, "bad", command)
        assert project.read() == p
    assert project.store.path.exists()


def test_mapping_does_not_guess_delay_units_or_echo_time(project):
    p = project.read()
    c = {
        "op": "fit",
        "spectrum_ids": list(p.spectra)[1:],
        "row_indices": list(range(8)),
        "table_id": next(iter(p.tables)),
        "delay_column": "delay_ms",
        "time_unit": "ms",
        "model": "T2",
        "time_basis": "echo_interval",
        "lower": 3.7,
        "upper": 4.3,
    }
    with pytest.raises(NmrError) as failure:
        apply(project, "ambiguous", c)
    assert failure.value.code == "AMBIGUOUS_TIME"
    assert project.read() == p
    with pytest.raises(NmrError):
        apply(project, "badmapping", {**c, "row_indices": [0] * 8, "delay_multiplier": 2})
    with pytest.raises(NmrError):
        apply(project, "badunit", {**c, "time_unit": "unknown", "delay_multiplier": 2})


def test_archive_is_one_revision_and_integrity_checked(project):
    p = project.read()
    artifact = project.export(p.revision)
    meta, raw = project.store.artifact(artifact.id)
    assert hashlib.sha256(raw).hexdigest() == meta.sha256
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["revision"] == p.revision
        assert json.loads(archive.read("project.json")) == p.model_dump(mode="json")
        for name, entry in manifest["files"].items():
            payload = archive.read(name)
            assert len(payload) == entry["size"]
            assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        svg = archive.read(f"figures/{next(iter(p.spectra))}.svg").decode()
        assert "revision 1" in svg
    assert project.read().revision == p.revision


def test_export_preserves_original_and_old_revision(tmp_path):
    from nmr_companion.formats import load_input

    path = tmp_path / "delays.csv"
    original = b"delay_ms,value\r\n10,2\r\n20,-1\r\n"
    path.write_bytes(original)
    assert load_input(path)["tables"]
    s = Service(tmp_path / "p.nmrproj")
    s.create("Original preservation")
    s.apply(0, "import", {"op": "import", "path": str(path)})
    path.write_text("changed source", encoding="utf-8")
    digest = hashlib.sha256(original).hexdigest()
    artifact = s.export(1)
    _, raw = s.store.artifact(artifact.id)
    with zipfile.ZipFile(BytesIO(raw)) as archive:
        assert archive.read("originals/" + digest) == original
    assert digest in s.read().sources


def test_spectrum_rejects_axes_and_nonfinite():
    base = dict(
        id="s1", name="Invalid", axis=[0, 1, 2], real=[1, 2, 3], axis_unit="ppm", domain="frequency"
    )
    for update in [
        {"axis": [0, 1, 1]},
        {"real": [1, 2]},
        {"real": [0, float("nan"), 2]},
        {"axis_unit": "s"},
    ]:
        with pytest.raises(ValidationError):
            Spectrum(**{**base, **update})


def test_source_deletion_and_overwrite_prohibited(project):
    p = project.read()
    with pytest.raises(NmrError):
        project.create("replacement")
    with pytest.raises(NmrError) as failure:
        apply(project, "delete", {"op": "remove", "object_id": next(iter(p.spectra))})
    assert failure.value.code == "SOURCE_IMMUTABLE"
    assert project.read() == p


def test_api_success_error_help_outputs_validate(project):
    import jsonschema

    cases = [
        ("nmr_project", {}),
        ("nmr_read", {"object_id": "absent"}),
        ("nmr_help", {"operation": "fit"}),
        ("nmr_edit", {"expected_revision": 1, "request_id": "bad", "command": {"op": "unknown"}}),
        ("nmr_request", {"request_id": "demo"}),
        ("nmr_export", {"revision": 999}),
    ]
    for name, args in cases:
        result = dispatch(project, name, args)
        jsonschema.validate(result, SPECS[name][1].model_json_schema())
        assert result["ok"] == (result["error"] is None)
    view = dispatch(project, "nmr_read", {"object_id": next(iter(project.read().spectra))})
    assert "real" not in view["data"]["data"]
    assert view["data"]["data"]["points"] == 2049


def test_failed_callback_cannot_commit_or_preserve_partial_source(project):
    old = project.read()

    def fail(p, db):
        project.store.preserve_original(db, b"never commit")
        p.name = "partial"
        raise NmrError("SIMULATED_FAILURE", "Interrupted before commit")

    with pytest.raises(NmrError):
        project.store.mutate(old.revision, "interrupted", {"op": "demo"}, fail)
    assert project.read() == old
    with project.store.connection() as db:
        assert db.execute("SELECT count(*) FROM originals").fetchone()[0] == 0
    with pytest.raises(NmrError):
        project.store.request("interrupted")


def test_export_database_reopens_and_preserves_undo_history(project, tmp_path):
    saved = project.read()
    sid = next(iter(saved.spectra))
    integral(project, sid, 1.7, 2.3, "later")
    artifact = project.export(saved.revision)
    _, data = project.store.artifact(artifact.id)
    with zipfile.ZipFile(BytesIO(data)) as archive:
        path = tmp_path / "delivered.nmrproj"
        path.write_bytes(archive.read("project.nmrproj"))
    reopened = Service(path)
    assert reopened.read() == saved
    assert reopened.store.request("demo").revision == 1
    with pytest.raises(NmrError):
        reopened.store.request("later")
    reopened.apply(1, "undo-in-export", {"op": "undo", "target_revision": 0})
    assert not reopened.read().spectra
    assert project.read().revision == 2


def test_invalid_backend_output_rolls_back_with_valid_error(project, monkeypatch):
    from nmr_companion import numerics

    sid = next(iter(project.read().spectra))
    a = integral(project, sid, 1.7, 2.3, "product")
    b = integral(project, sid, 6.7, 7.3, "standard")
    old = project.read()
    monkeypatch.setattr(numerics, "calculate_yield", lambda *args: {"yield_percent": float("nan")})
    result = dispatch(
        project,
        "nmr_edit",
        {
            "expected_revision": old.revision,
            "request_id": "bad-output",
            "command": {
                "op": "yield",
                "product_integral_id": a,
                "standard_integral_id": b,
                "product_protons": 3,
                "standard_protons": 6,
                "standard_mol": 1,
                "limiting_mol": 1,
            },
        },
    )
    assert not result["ok"] and result["error"]["code"] == "OUTPUT_VALIDATION"
    assert project.read() == old
