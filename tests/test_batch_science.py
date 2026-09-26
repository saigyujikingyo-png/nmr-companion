import math
from io import BytesIO
import json
import zipfile

import numpy as np
import pytest
from PIL import Image

from nmr_companion.errors import NmrError
from nmr_companion.models import Spectrum
from nmr_companion.service import Service
from nmr_companion.media import reference_png


def apply(s, op, **kw):
    return s.apply(s.read().revision, f"case_{s.read().revision}", {"op": op, **kw})


def project(tmp_path):
    s = Service(tmp_path / "science.nmrproj")
    s.create("Synthetic acceptance")
    apply(s, "demo")
    return s


def test_yield_recovery_and_shared_standard_uncertainty(tmp_path):
    s = project(tmp_path)
    sid = next(iter(s.read().spectra))
    ids = []
    for lo, hi in ((1.7, 2.3), (6.7, 7.3), (3.7, 4.3)):
        ids.append(apply(s, "integrate", spectrum_id=sid, lower=lo, upper=hi).object_ids[0])
    p = s.read()
    areas = [p.integrals[i].area for i in ids]
    command = dict(
        product_integral_id=ids[0],
        standard_integral_id=ids[1],
        recovered_integral_id=ids[2],
        product_protons=3.0,
        standard_protons=6.0,
        recovered_protons=2.0,
        standard_mol=0.00036,
        limiting_mol=0.001,
    )
    plain = apply(s, "yield", **command).object_ids[0]
    r = s.read().analyses[plain].result
    assert [r["yield_percent"], r["recovered_percent"], r["mass_balance_percent"]] == pytest.approx(
        [36, 36, 72], abs=1e-5
    )
    assert r["u_yield_percent"] is None
    measured = apply(
        s,
        "yield",
        **command,
        u_product_area=areas[0] * 0.01,
        u_standard_area=areas[1] * 0.01,
        u_recovered_area=areas[2] * 0.01,
        u_standard_mol=0.00036 * 0.02,
        u_limiting_mol=0.001 * 0.03,
    ).object_ids[0]
    r = s.read().analyses[measured].result
    assert r["u_yield_percent"] == pytest.approx(36 * math.sqrt(0.0015), abs=1e-5)
    assert r["u_mass_balance_percent"] == pytest.approx(
        math.sqrt(2 * (36 * 0.01) ** 2 + 72**2 * 0.0014), abs=1e-5
    )
    assert r["u_mass_balance_percent"] > math.hypot(r["u_yield_percent"], r["u_recovered_percent"])
    apply(s, "integrate", integral_id=ids[2], spectrum_id=sid, lower=3.8, upper=4.2)
    assert s.read().analyses[measured].state == "stale"
    with pytest.raises(NmrError, match="both"):
        apply(s, "yield", **{**command, "recovered_protons": None})


def test_reference_pdf_image_annotations_and_revision_export(tmp_path):
    s = project(tmp_path)
    sample = apply(
        s, "sample", name="External reference", role="reference", stage="characterization"
    ).object_ids[0]
    for extension, fmt in (("png", "PNG"), ("pdf", "PDF")):
        path = tmp_path / ("synthetic-reference." + extension)
        im = Image.new("RGB", (300, 180), "white")
        im.save(path, format=fmt)
        attached = apply(
            s, "attach", path=str(path), sample_id=sample, source_role="reference", category="HRMS"
        ).object_ids[0]
        annotation = apply(
            s,
            "annotate",
            attachment_id=attached,
            x=0.1,
            y=0.2,
            width=0.3,
            height=0.2,
            label="Manually read region",
            approximate_ppm=3.42,
            reading_uncertainty_ppm=0.05,
        ).object_ids[0]
        p = s.read()
        a = p.attachments[attached]
        assert a.pages == 1 and a.category == "HRMS"
        assert p.annotations[annotation].origin == "image_annotation_not_numeric_spectrum"
        assert len(p.spectra) == 9  # attaching a document never invents a numerical spectrum
        assert reference_png(path.read_bytes(), a.media_type).startswith(b"\x89PNG")
        with pytest.raises(NmrError):
            apply(
                s,
                "annotate",
                attachment_id=attached,
                page=2,
                x=0.1,
                y=0.1,
                width=0.2,
                height=0.2,
                label="wrong page",
            )
    before = s.read()
    artifact = s.export(before.revision)
    _, raw = s.store.artifact(artifact.id)
    with zipfile.ZipFile(BytesIO(raw)) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        names = z.namelist()
        assert any(n.startswith("figures/attachment_") and n.endswith(".svg") for n in names)
        assert len(json.loads(z.read("reference-preview-coverage.json"))) == 2
        for a in before.attachments.values():
            assert (
                z.read("originals/" + a.source_id)
                == (
                    tmp_path
                    / (
                        "synthetic-reference.pdf"
                        if a.media_type == "application/pdf"
                        else "synthetic-reference.png"
                    )
                ).read_bytes()
            )
        out = tmp_path / "reopened.nmrproj"
        out.write_bytes(z.read("project.nmrproj"))
    assert Service(out).read() == before


def test_condition_comparison_requires_actual_correspondence_and_propagates_stale(tmp_path):
    s = project(tmp_path)
    p = s.read()
    ids = [v.id for v in p.spectra.values() if "delay_s" in v.metadata]
    table = next(iter(p.tables))
    # Two explicitly different acquisitions with independently defined synthetic T values.
    extra = [p.spectra[i].model_copy(deep=True) for i in ids]

    def seed(q, db):
        for k, v in enumerate(extra):
            v.id = f"second_{k}"
            factor = 1 - 2 * np.exp(-v.metadata["delay_s"] / 1.0)
            axis = np.asarray(v.axis)
            v.real = (factor * np.exp(-0.5 * ((axis - 4) / 0.045) ** 2)).tolist()
            q.spectra[v.id] = v
        return [v.id for v in extra], []

    s.store.mutate(p.revision, "second_acquisition", {"op": "fixture"}, seed)
    fits = []
    samples = []
    for k, traces in enumerate((ids, [v.id for v in extra])):
        samples.append(
            apply(
                s,
                "sample",
                name=f"Condition {k}",
                role="synthetic",
                object_ids=traces,
                reference="Synthetic common frequency reference",
                conditions={
                    "solvent": "CDCl3" if not k else "D2O",
                    "temperature_k": 298.15,
                    "additives": [
                        {"name": "Test additive", "concentration_mol_l": float(k) * 0.01}
                    ],
                },
            ).object_ids[0]
        )
        fits.append(
            apply(
                s,
                "fit",
                spectrum_ids=traces,
                table_id=table,
                row_indices=list(range(8)),
                delay_column="delay_ms",
                time_unit="ms",
                model="T1",
                lower=3.7,
                upper=4.3,
                purpose="quick_check" if k else "analysis",
            ).object_ids[0]
        )
    command = dict(
        name="Condition comparison",
        metric="T_s",
        left_id=fits[0],
        right_id=fits[1],
        left_sample_id=samples[0],
        right_sample_id=samples[1],
        signal_label="H4",
        correspondence="Same synthetic Gaussian at 4 ppm",
        independent_uncertainties=True,
    )
    comparison = apply(s, "compare", **command).object_ids[0]
    r = s.read().analyses[comparison].result
    assert [r["left"], r["right"], r["difference"], r["ratio"]] == pytest.approx(
        [0.5, 1, 0.5, 2], abs=1e-6
    )
    assert r["unit"] == "s" and r["right_conditions"]["solvent"] == "D2O"
    assert r["u_difference"] is not None
    assert any("quick check" in w for w in r["warnings"])
    with pytest.raises(NmrError, match="associate"):
        apply(s, "compare", **{**command, "right_sample_id": samples[0]})
    apply(
        s,
        "sample",
        sample_id=samples[1],
        name="Corrected condition",
        role="synthetic",
        object_ids=[v.id for v in extra],
        conditions={"solvent": "D2O", "temperature_k": 299.15},
    )
    assert s.read().analyses[comparison].state == "stale"


def test_dept_signed_matching_and_ambiguity(tmp_path):
    s = Service(tmp_path / "dept.nmrproj")
    s.create("DEPT synthetic")
    x = np.linspace(0, 100, 10001)

    def peak(mu):
        return np.exp(-0.5 * ((x - mu) / 0.02) ** 2)

    def seed(p, db):
        for oid, y in (
            ("carbon", peak(10) + peak(20) + peak(40) + peak(60)),
            ("dept", peak(10) - peak(20) + peak(59.95) + peak(60.05)),
        ):
            p.spectra[oid] = Spectrum(
                id=oid,
                name=oid,
                axis=x.tolist(),
                real=y.tolist(),
                axis_unit="ppm",
                domain="frequency",
                nucleus="13C",
                metadata={"synthetic": True},
            )
        return ["carbon", "dept"], []

    s.store.mutate(0, "seed", {"op": "fixture"}, seed)
    kwargs = dict(
        carbon_spectrum_id="carbon",
        dept_spectrum_id="dept",
        carbon_prominence=0.2,
        dept_prominence=0.2,
        tolerance_ppm=0.12,
        reference_convention="positive_ch_ch3",
        reference="Synthetic independently declared DEPT-135 phase",
    )
    aid = apply(s, "dept", **kwargs).object_ids[0]
    rows = s.read().analyses[aid].result["rows"]
    assert [r["interpretation"] for r in rows] == [
        "CH_or_CH3",
        "CH2",
        "no_DEPT_signal",
        "ambiguous",
    ]
    assert rows[1]["dept_intensity"] < 0
    second = apply(s, "dept", **{**kwargs, "reference_convention": "negative_ch_ch3"}).object_ids[0]
    assert s.read().analyses[second].result["rows"][0]["interpretation"] == "CH2"


def test_structure_transform_alternatives_cycles_and_remove(tmp_path):
    s = project(tmp_path)
    spectrum = next(iter(s.read().spectra))
    parent = apply(
        s, "sample", name="Diol", role="synthetic", stage="starting material"
    ).object_ids[0]
    child = apply(
        s,
        "sample",
        name="Acetal",
        role="own",
        stage="product",
        parent_ids=[parent],
        transformation="Synthetic context test: diol to cyclic acetal",
        object_ids=[spectrum],
    ).object_ids[0]
    observation = apply(s, "peak_label", spectrum_id=spectrum, ppm=2.0, label="Ha").object_ids[0]
    structures = []
    for stereo in ("R", "S"):
        structures.append(
            apply(
                s,
                "structure",
                sample_id=child,
                name=f"Candidate {stereo}",
                alternative_group="stereo alternatives",
                atoms=[
                    {
                        "id": "C1",
                        "label": "C1",
                        "element": "C",
                        "x": 0.0,
                        "y": 0.0,
                        "stereo": stereo,
                    }
                ],
                evidence_ids=[observation],
            ).object_ids[0]
        )
    assignment = apply(
        s,
        "assign",
        sample="Acetal",
        sample_id=child,
        candidate="Candidate R",
        candidate_id=structures[0],
        atom="C1",
        atom_ids=["C1"],
        observation="User-reviewed bookkeeping fixture",
        status="confirmed",
        evidence_ids=[observation],
    ).object_ids[0]
    current = s.read()
    assert current.assignments[assignment].status == "confirmed"
    assert current.structures[structures[1]].status == "proposed"
    with pytest.raises(NmrError, match="itself"):
        data = current.structures[structures[0]].model_dump()
        apply(
            s,
            "structure",
            structure_id=structures[0],
            sample_id=child,
            name="Circular evidence",
            atoms=data["atoms"],
            evidence_ids=[assignment],
        )
    apply(s, "remove", object_id=observation)
    now = s.read()
    assert now.assignments[assignment].state == "stale"
    assert now.structures[structures[0]].state == "stale"
    apply(s, "undo", target_revision=current.revision)
    restored = s.read()
    assert restored.structures == current.structures
