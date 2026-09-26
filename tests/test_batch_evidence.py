from io import BytesIO
import zipfile
import pytest
from nmr_companion.service import Service
from nmr_companion.errors import NmrError
from nmr_companion.api import dispatch


def apply(s, op, **kw):
    return s.apply(s.read().revision, f"request_{s.read().revision}", {"op": op, **kw})


def setup(tmp_path):
    s = Service(tmp_path / "joint.nmrproj")
    s.create("Joint batch synthetic")
    apply(s, "demo")
    return s


def test_sample_structure_normalization_and_transitive_stale(tmp_path):
    s = setup(tmp_path)
    sid = next(iter(s.read().spectra))
    sample = apply(
        s,
        "sample",
        name="Product A",
        role="synthetic",
        object_ids=[sid],
        stage="product",
        conditions={"solvent": "CDCl3"},
    ).object_ids[0]
    label = apply(s, "peak_label", spectrum_id=sid, ppm=2.0, label="H-a", protons=3.0).object_ids[0]
    structure = apply(
        s,
        "structure",
        name="Candidate A",
        sample_id=sample,
        atoms=[
            {"id": "C1", "label": "C1", "element": "C", "x": 0.3, "y": 0.5},
            {"id": "O1", "label": "O1", "element": "O", "x": 0.7, "y": 0.5},
        ],
        bonds=[{"a": "C1", "b": "O1", "order": 1}],
        evidence_ids=[label],
    ).object_ids[0]
    assignment = apply(
        s,
        "assign",
        sample="Product A",
        atom="C1/H-a",
        candidate="Candidate A",
        sample_id=sample,
        candidate_id=structure,
        atom_ids=["C1"],
        observation="Synthetic bookkeeping evidence, not a determined structure",
        evidence_ids=[label],
        status="proposed",
    ).object_ids[0]
    a = apply(s, "integrate", spectrum_id=sid, lower=1.7, upper=2.3).object_ids[0]
    b = apply(s, "integrate", spectrum_id=sid, lower=6.7, upper=7.3).object_ids[0]
    norm = apply(
        s, "normalize", reference_integral_id=b, reference_protons=6.0, integral_ids=[a, b]
    ).object_ids[0]
    p = s.read()
    assert [r["relative_protons"] for r in p.analyses[norm].result["integrals"]] == pytest.approx(
        [3, 6], abs=1e-4
    )
    original = p.spectra[sid].real
    apply(s, "peak_label", peaklabel_id=label, spectrum_id=sid, ppm=2.02, label="H-a revised")
    p = s.read()
    assert p.structures[structure].state == "stale"
    assert p.assignments[assignment].state == "stale"
    assert p.spectra[sid].real == original
    assert p.samples[sample].role == "synthetic"
    reply = dispatch(s, "nmr_read", {"object_id": structure})
    assert reply["ok"] and reply["data"]["object_type"] == "structure"
    artifact = s.export(p.revision)
    _, data = s.store.artifact(artifact.id)
    with zipfile.ZipFile(BytesIO(data)) as z:
        out = tmp_path / "reopened.nmrproj"
        out.write_bytes(z.read("project.nmrproj"))
        assert "tables/assignments.csv" in z.namelist()
    assert Service(out).read() == s.read()


def test_sample_cycles_and_confirmed_without_evidence_roll_back(tmp_path):
    s = setup(tmp_path)
    sid = apply(s, "sample", name="A", role="own").object_ids[0]
    p = s.read()
    with pytest.raises(NmrError):
        apply(s, "sample", sample_id=sid, name="A", role="own", parent_ids=[sid])
    assert s.read() == p
    with pytest.raises(NmrError):
        apply(
            s,
            "structure",
            name="Unsupported certainty",
            sample_id=sid,
            atoms=[{"id": "C1", "label": "C1", "element": "C", "x": 0.5, "y": 0.5}],
            status="confirmed",
        )
    assert s.read() == p
