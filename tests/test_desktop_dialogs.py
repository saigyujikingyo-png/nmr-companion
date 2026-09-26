"""Offscreen Qt command editing, using independent synthetic object identities."""

from copy import deepcopy
import os

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from nmr_companion.commands import COMMAND, OPERATIONS
from nmr_companion.desktop.dialogs import CommandDialog, get_command
from nmr_companion.models import Analysis, Grid, Integral, Project, Spectrum, Table
from nmr_companion.evidence_models import Attachment, Crosspeak, Peaklabel, Sample, Structure


@pytest.fixture(scope="session")
def qtapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def release_native_dialogs(qtapp):
    yield
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, CommandDialog):
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtapp.processEvents()


@pytest.fixture
def project():
    p = Project(id="dialog_fixture", name="Synthetic widget fixtures", revision=9)
    for i in range(5):
        p.spectra[f"t{i}"] = Spectrum(
            id=f"t{i}",
            name="Repeated display name",
            axis=[0.0, 2.0, 4.0, 6.0, 8.0, 10.0],
            real=[-2.0, -1.0, 0.0, 0.2, 1.0, 0.0],
            imag=[0.0] * 6,
            axis_unit="ppm",
            domain="frequency",
            nucleus="1H",
            metadata={"synthetic": True},
        )
    for oid in ("carbon", "dept"):
        p.spectra[oid] = Spectrum(
            id=oid,
            name=oid,
            axis=[0.0, 50.0, 100.0],
            real=[0.0, -2.0, 1.0],
            axis_unit="ppm",
            domain="frequency",
            nucleus="13C",
        )
    p.spectra["raw"] = Spectrum(
        id="raw",
        name="Synthetic FID",
        axis=[0.0, 0.001, 0.002],
        real=[1.0, 0.5, -0.1],
        imag=[0.0, 0.2, 0.1],
        axis_unit="s",
        domain="time",
        nucleus="1H",
    )
    p.tables["delays"] = Table(
        id="delays",
        name="Unsorted delays with replicas",
        columns=["delay", "sigma"],
        rows=[
            {"delay": t, "sigma": s}
            for t, s in (
                ("1000", "0.01"),
                ("10", "0.02"),
                ("10", "0.03"),
                ("250", "0.04"),
                ("500", "0.05"),
            )
        ],
    )
    p.tables["other_table"] = Table(
        id="other_table",
        name="Other acquisition",
        columns=["delay", "sigma"],
        rows=[{"delay": "999", "sigma": "0.9"} for _ in range(5)],
    )
    p.grids["grid"] = Grid(
        id="grid",
        name="Synthetic HSQC",
        x=[8.0, 4.0, 0.0],
        y=[10.0, 30.0, 60.0],
        z=[[1.0, 2.0, -1.0], [0.0, -4.0, 2.0], [3.0, 0.0, -2.0]],
        nuclei=["1H", "13C"],
        metadata={"experiment": "HSQC"},
    )
    for oid, lower, upper, area in (
        ("product", 1.0, 2.0, 3.0),
        ("standard", 7.0, 8.0, 6.0),
        ("recovered", 4.0, 5.0, 2.0),
    ):
        p.integrals[oid] = Integral(
            id=oid,
            name=oid,
            spectrum_id="t0",
            spectrum_version=1,
            lower=lower,
            upper=upper,
            area=area,
        )
    p.samples["root"] = Sample(id="root", name="Initial material", role="synthetic")
    p.samples["own"] = Sample(
        id="own",
        name="Product A",
        role="own",
        object_ids=[f"t{i}" for i in range(5)] + ["grid"],
        conditions={"solvent": "D2O", "temperature_k": 298.0},
        reference="Declared reference",
    )
    p.samples["reference"] = Sample(
        id="reference",
        name="Reference condition",
        role="reference",
        object_ids=["t1"],
        conditions={"additives": [{"name": "Synthetic additive", "concentration_mol_l": 0.01}]},
    )
    for oid, sid, ppm in (("label_a", "t0", 2.0), ("label_b", "t1", 2.1)):
        p.peaklabels[oid] = Peaklabel(
            id=oid, spectrum_id=sid, ppm=ppm, label=oid, intensity=-1.0, source_versions={sid: 1}
        )
    p.crosspeaks["cross"] = Crosspeak(
        id="cross",
        grid_id="grid",
        x_ppm=4.0,
        y_ppm=30.0,
        label="Negative observation",
        intensity=-4.0,
        source_versions={"grid": 1},
    )
    p.structures["candidate"] = Structure(
        id="candidate",
        name="Manual candidate",
        sample_id="own",
        atoms=[
            {
                "id": "C1",
                "label": "C-a",
                "element": "C",
                "x": 0.0,
                "y": 0.0,
                "stereo": "R proposed",
            },
            {"id": "O1", "label": "O-a", "element": "O", "x": 1.0, "y": 0.0},
        ],
        bonds=[{"a": "C1", "b": "O1", "order": 1.0, "stereo": "wedge"}],
        evidence_ids=["label_a"],
        source_versions={"own": 1, "label_a": 1},
    )
    p.attachments["pdf"] = Attachment(
        id="pdf",
        name="Synthetic two-page reference",
        sample_id="reference",
        source_role="reference",
        category="nmr_reference",
        source_id="a" * 64,
        media_type="application/pdf",
        pages=2,
        width=300.0,
        height=200.0,
        source_versions={"reference": 1},
    )
    for oid, sid in (("fit_left", "t0"), ("fit_right", "t1")):
        # Read-only, schema-valid UI identities; no numerical fit is claimed here.
        p.analyses[oid] = Analysis(
            id=oid,
            name=oid,
            kind="relaxation",
            source_versions={sid: 1},
            parameters={},
            result={
                "model": "T1",
                "status": "ok",
                "time_s": [0.0, 1.0, 2.0, 3.0],
                "signals": [-1.0, 0.1, 0.5, 0.8],
                "predicted": [-1.0, 0.1, 0.5, 0.8],
                "residuals": [0.0] * 4,
                "parameters": {},
                "T_s": 0.5,
                "u_T_s": None,
                "uncertainty_method": "synthetic UI fixture",
                "warnings": [],
                "diagnostics": {},
            },
        )
    return p


FIT_COMMAND = {
    "op": "fit",
    "name": "Explicit echo mapping",
    "spectrum_ids": ["t3", "t0", "t4", "t1", "t2"],
    "table_id": "delays",
    "row_indices": [3, 1, 2, 4, 0],
    "delay_column": "delay",
    "sigma_column": "sigma",
    "time_unit": "ms",
    "model": "T2",
    "time_basis": "echo_interval",
    "delay_multiplier": 2.0,
    "lower": 1.0,
    "upper": 3.0,
    "excluded_indices": [2],
    "purpose": "quick_check",
}
YIELD_COMMAND = {
    "op": "yield",
    "product_integral_id": "product",
    "standard_integral_id": "standard",
    "product_protons": 3.0,
    "standard_protons": 6.0,
    "standard_mol": 0.00036,
    "limiting_mol": 0.001,
    "stoichiometric_factor": 1.0,
    "name": "Synthetic yield inputs",
    "recovered_integral_id": "recovered",
    "recovered_protons": 2.0,
    "u_product_area": 0.0,
    "u_standard_area": None,
    "u_recovered_area": 0.02,
    "u_standard_mol": 0.000002,
    "u_limiting_mol": None,
}


def commands(project):
    structure = project.structures["candidate"].model_dump(
        include={
            "name",
            "sample_id",
            "atoms",
            "bonds",
            "description",
            "alternative_group",
            "evidence_ids",
            "status",
        }
    )
    return [
        {"op": "import", "path": "synthetic-input.zip", "bruker_processing_numbers": [1, 3]},
        {"op": "demo"},
        {
            "op": "integrate",
            "integral_id": "product",
            "spectrum_id": "t0",
            "name": "Edited region",
            "lower": 1.2,
            "upper": 1.8,
        },
        {
            "op": "process",
            "spectrum_id": "t0",
            "method": "baseline",
            "regions": [[0.0, 0.5], [9.0, 10.0]],
        },
        {"op": "peaks", "spectrum_id": "t0", "prominence": 0.2},
        YIELD_COMMAND,
        FIT_COMMAND,
        {
            "op": "assign",
            "sample_id": "own",
            "candidate_id": "candidate",
            "sample": "Product A",
            "candidate": "Manual candidate",
            "atom": "C1 / H-a",
            "atom_ids": ["C1"],
            "observation": "Explicit synthetic correlation",
            "evidence_ids": ["cross", "label_a"],
            "status": "proposed",
        },
        {"op": "remove", "object_id": "label_a"},
        {"op": "undo", "target_revision": 2},
        {
            "op": "sample",
            "name": "Stage B",
            "role": "own",
            "object_ids": ["t1", "grid", "delays"],
            "parent_ids": ["root"],
            "stage": "product",
            "transformation": "Supplied reaction context",
            "reference": "Frequency reference",
            "notes": "Separate provenance",
            "conditions": {
                "solvent": None,
                "temperature_k": 298.15,
                "additives": [
                    {
                        "name": "Additive A",
                        "concentration_mol_l": None,
                        "notes": "Amount unavailable",
                    },
                    {"name": "Additive B", "concentration_mol_l": 0.01, "notes": "Explicit amount"},
                ],
            },
        },
        {"op": "structure", "structure_id": "candidate", **structure},
        {"op": "crosspeak", "grid_id": "grid", "x_ppm": 2.0, "y_ppm": 30.0, "label": "H-a/C-a"},
        {
            "op": "grid_metadata",
            "grid_id": "grid",
            "experiment": "HSQC",
            "nuclei": ["15N", "1H"],
            "reference": "Explicit axis confirmation",
        },
        {
            "op": "peak_label",
            "peaklabel_id": "label_a",
            "spectrum_id": "t0",
            "ppm": 2.0,
            "label": "H-a revised",
            "multiplicity": None,
            "protons": 3.0,
        },
        {
            "op": "normalize",
            "reference_integral_id": "standard",
            "reference_protons": 6.0,
            "integral_ids": ["recovered", "product", "standard"],
        },
        {
            "op": "attach",
            "path": "synthetic-reference.pdf",
            "name": None,
            "sample_id": "reference",
            "source_role": "reference",
            "category": "IR",
            "notes": "Supplied external evidence",
        },
        {
            "op": "annotate",
            "attachment_id": "pdf",
            "page": 2,
            "x": 0.1,
            "y": 0.2,
            "width": 0.3,
            "height": 0.4,
            "label": "Approximate reference reading",
            "observation": "Manual image observation",
            "approximate_ppm": 0.0,
            "reading_uncertainty_ppm": 0.05,
        },
        {
            "op": "compare",
            "name": "Conditions A/B",
            "metric": "T_s",
            "left_id": "fit_left",
            "right_id": "fit_right",
            "left_sample_id": "own",
            "right_sample_id": "reference",
            "signal_label": "H-a",
            "correspondence": "Same assigned signal in separate conditions",
            "independent_uncertainties": False,
        },
        {
            "op": "dept",
            "carbon_spectrum_id": "carbon",
            "dept_spectrum_id": "dept",
            "carbon_prominence": 0.1,
            "dept_prominence": 0.2,
            "tolerance_ppm": 0.12,
            "reference_convention": "negative_ch_ch3",
            "reference": "Explicit synthetic phase convention",
        },
    ]


@pytest.mark.parametrize("operation", tuple(OPERATIONS))
def test_each_scientific_operation_has_native_fields_and_preserves_prefill(
    qtapp, project, operation
):
    initial = next(c for c in commands(project) if c["op"] == operation)
    original_initial, original_project = deepcopy(initial), project.model_dump()
    dialog = CommandDialog(operation, project, initial=initial)
    actual = dialog.command()
    assert actual["op"] == operation
    for field, value in initial.items():
        assert actual[field] == value, field
    assert COMMAND.validate_python(actual).model_dump(mode="json") == actual
    assert initial == original_initial
    assert project.model_dump() == original_project
    assert dialog.windowTitle()
    assert not dialog.isVisible()
    dialog.deleteLater()


def test_fit_mapping_preserves_explicit_order_replicates_exclusions_and_original_preview(
    qtapp, project
):
    dialog = CommandDialog("fit", project, initial=FIT_COMMAND)
    rows = dialog.fields["mapping"]
    assert [rows.cell(i, "delay").text() for i in range(5)] == ["250", "10", "10", "500", "1000"]
    assert [rows.cell(i, "sigma").text() for i in range(5)] == [
        "0.04",
        "0.02",
        "0.03",
        "0.05",
        "0.01",
    ]
    assert [rows.cell(i, "row_number").text() for i in range(5)] == ["4", "2", "3", "5", "1"]
    assert rows.cell(2, "excluded").isChecked()
    assert dialog.command() == FIT_COMMAND
    rows.cell(0, "row_number").setText("2")
    with pytest.raises(ValueError, match="only once"):
        dialog.command()
    rows.cell(0, "row_number").setText("4")
    rows.cell(0, "excluded").setChecked(True)
    with pytest.raises(ValueError, match="four included"):
        dialog.command()


def test_changing_delay_table_clears_pairing_and_never_guesses_units(qtapp, project):
    dialog = CommandDialog("fit", project, initial=FIT_COMMAND)
    combo = dialog.fields["table_id"]
    combo.setCurrentIndex(combo.findData("other_table"))
    rows = dialog.fields["mapping"]
    assert [rows.cell(i, "row_number").text() for i in range(5)] == [""] * 5
    assert [rows.cell(i, "delay").text() for i in range(5)] == [""] * 5
    assert dialog.fields["delay_column"].currentData() is None
    with pytest.raises(ValueError, match="explicit selection"):
        dialog.command()
    new_dialog = CommandDialog("fit", project, initial={"table_id": "delays"})
    assert new_dialog.fields["time_unit"].currentData() is None
    assert new_dialog.fields["time_basis"].currentData() is None
    assert new_dialog.fields["mapping"].table.rowCount() == 0


@pytest.mark.parametrize(
    "key,value,match",
    [
        ("time_unit", None, "Original delay unit"),
        ("delay_multiplier", None, "multiplier"),
        ("delay_multiplier", "-2", "greater than 0"),
        ("upper", "nan", "NaN"),
    ],
)
def test_invalid_fit_values_remain_rejected_before_acceptance(qtapp, project, key, value, match):
    dialog = CommandDialog("fit", project, initial=FIT_COMMAND)
    field = dialog.fields[key]
    if key == "time_unit":
        field.setCurrentIndex(0)
    else:
        field.setText("" if value is None else value)
    with pytest.raises(ValueError, match=match):
        dialog.command()
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.error_label.isHidden()
    assert match.lower() in dialog.error_label.text().lower()


def test_yield_unavailable_and_zero_uncertainties_are_distinct(qtapp, project):
    dialog = CommandDialog("yield", project, initial=YIELD_COMMAND)
    assert dialog.command() == YIELD_COMMAND
    assert dialog.fields["u_product_area"].text() == "0.0"
    assert dialog.fields["u_standard_area"].text() == ""
    dialog.fields["u_standard_area"].setText("1e-5")
    dialog.fields["u_product_area"].clear()
    actual = dialog.command()
    assert actual["u_standard_area"] == 0.00001
    assert actual["u_product_area"] is None
    assert actual["u_limiting_mol"] is None
    dialog.fields["u_standard_area"].setText("-0.1")
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        dialog.command()
    dialog.fields["u_standard_area"].clear()
    dialog.fields["recovered_protons"].clear()
    with pytest.raises(ValueError, match="both"):
        dialog.command()


def test_samples_keep_roles_stages_additive_units_and_unknowns(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "sample")
    dialog = CommandDialog("sample", project, initial=initial)
    assert dialog.command()["conditions"] == {
        "solvent": None,
        "temperature_k": 298.15,
        "additives": [
            {"name": "Additive A", "concentration_mol_l": None, "notes": "Amount unavailable"},
            {"name": "Additive B", "concentration_mol_l": 0.01, "notes": "Explicit amount"},
        ],
    }
    table = dialog.fields["additives"]
    table.add_button.click()
    table.cell(2, "name").setText("Explicit zero")
    table.cell(2, "concentration_mol_l").setText("0")
    assert dialog.command()["conditions"]["additives"][2]["concentration_mol_l"] == 0.0
    table.table.selectRow(0)
    table.remove_button.click()
    assert [a["name"] for a in dialog.command()["conditions"]["additives"]] == [
        "Additive B",
        "Explicit zero",
    ]
    assert dialog.command()["object_ids"] == ["t1", "grid", "delays"]
    dialog.fields["transformation"].clear()
    with pytest.raises(ValueError, match="transformation"):
        dialog.command()


def test_structure_and_bond_editor_preserves_ids_and_rejects_deleted_endpoint(qtapp, project):
    initial = project.structures["candidate"].model_dump()
    dialog = CommandDialog("structure", project, initial=initial)
    command = dialog.command()
    assert command["structure_id"] == "candidate"
    assert command["atoms"] == initial["atoms"]
    assert command["bonds"] == [{"a": "C1", "b": "O1", "order": 1.0, "stereo": "wedge"}]
    atoms, bonds = dialog.fields["atoms"], dialog.fields["bonds"]
    atoms.cell(0, "x").setText("2.75")
    assert dialog.command()["atoms"][0]["id"] == "C1"
    assert dialog.command()["atoms"][0]["x"] == 2.75
    atoms.cell(1, "id").setText("O_revised")
    assert bonds.cell(0, "b").currentData() == "O1"
    assert "Unavailable" in bonds.cell(0, "b").currentText()
    with pytest.raises(ValueError, match="no longer available"):
        dialog.command()
    bonds.cell(0, "b").setCurrentIndex(bonds.cell(0, "b").findData("O_revised"))
    assert dialog.command()["bonds"][0]["b"] == "O_revised"
    atoms.add_button.click()
    first_id = atoms.cell(2, "id").text()
    atoms.cell(2, "label").setText("Added atom")
    assert dialog.command()["atoms"][2]["id"] == first_id
    assert first_id not in {"C1", "O1", "O_revised"}


def test_candidate_confirmation_and_atom_identity_validation(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "structure")
    dialog = CommandDialog("structure", project, initial=initial)
    dialog.fields["atoms"].cell(1, "id").setText("C1")
    with pytest.raises(ValueError):
        dialog.command()
    dialog = CommandDialog(
        "structure", project, initial={**initial, "status": "confirmed", "evidence_ids": []}
    )
    with pytest.raises(ValueError, match="supporting observations"):
        dialog.command()


def test_assignment_links_exact_saved_atoms_and_keeps_proposed_status(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "assign")
    dialog = CommandDialog("assign", project, initial=initial)
    command = dialog.command()
    assert command["sample_id"] == "own"
    assert command["candidate_id"] == "candidate"
    assert command["atom_ids"] == ["C1"]
    assert command["evidence_ids"] == ["cross", "label_a"]
    assert command["status"] == "proposed"
    combo = dialog.fields["sample_id"]
    combo.setCurrentIndex(combo.findData("reference"))
    with pytest.raises(ValueError, match="same explicit sample"):
        dialog.command()


def test_reference_annotation_page_rectangle_and_optional_reading(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "annotate")
    dialog = CommandDialog("annotate", project, initial=initial)
    actual = dialog.command()
    assert [actual[k] for k in ("page", "x", "y", "width", "height")] == [2, 0.1, 0.2, 0.3, 0.4]
    assert actual["approximate_ppm"] == 0.0
    dialog.fields["page"].setText("3")
    with pytest.raises(ValueError, match="page does not exist"):
        dialog.command()
    dialog.fields["page"].setText("2")
    dialog.fields["width"].setText("0.95")
    with pytest.raises(ValueError, match="inside its page"):
        dialog.command()
    dialog.fields["width"].setText("0.3")
    dialog.fields["approximate_ppm"].clear()
    with pytest.raises(ValueError, match="requires an approximate"):
        dialog.command()
    dialog.fields["reading_uncertainty_ppm"].clear()
    assert dialog.command()["approximate_ppm"] is None


@pytest.mark.parametrize("nuclei", [["1H", "15N"], ["15N", "1H"], ["1H", "13C"], ["13C", "1H"]])
def test_hsqc_explicit_axis_choices_are_never_swapped(qtapp, project, nuclei):
    initial = {
        "grid_id": "grid",
        "experiment": "HSQC",
        "nuclei": nuclei,
        "reference": "User-reviewed axes",
    }
    dialog = CommandDialog("grid_metadata", project, initial=initial)
    assert dialog.command() == {"op": "grid_metadata", **initial}
    experiment = dialog.fields["experiment"]
    experiment.setCurrentIndex(experiment.findData("COSY"))
    with pytest.raises(ValueError, match="compatible COSY/HSQC"):
        dialog.command()


def test_comparison_uses_observation_type_and_explicit_independence(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "compare")
    dialog = CommandDialog("compare", project, initial=initial)
    assert dialog.command() == initial
    assert "D2O" in " ".join(label.text() for label in dialog.findChildren(QLabel))
    assert dialog.fields["left_id"].findData("label_a") == -1
    dialog.fields["independent_uncertainties"].setChecked(True)
    assert dialog.command()["independent_uncertainties"] is True
    metric = dialog.fields["metric"]
    metric.setCurrentIndex(metric.findData("chemical_shift_ppm"))
    with pytest.raises(ValueError, match="no longer available"):
        dialog.command()
    for key, value in (("left_id", "label_a"), ("right_id", "label_b")):
        box = dialog.fields[key]
        box.setCurrentIndex(box.findData(value))
    assert dialog.command()["metric"] == "chemical_shift_ppm"
    assert dialog.command()["left_id"] == "label_a"
    assert dialog.command()["right_id"] == "label_b"


def test_dept_phase_convention_and_numeric_thresholds_are_explicit(qtapp, project):
    initial = next(c for c in commands(project) if c["op"] == "dept")
    dialog = CommandDialog("dept", project, initial=initial)
    actual = dialog.command()
    assert actual["reference_convention"] == "negative_ch_ch3"
    assert actual["carbon_prominence"] == 0.1
    assert actual["dept_prominence"] == 0.2
    assert actual["tolerance_ppm"] == 0.12
    assert dialog.fields["carbon_spectrum_id"].findData("t0") == -1
    dialog.fields["reference_convention"].setCurrentIndex(0)
    with pytest.raises(ValueError, match="phase convention"):
        dialog.command()


@pytest.mark.parametrize("text", ["0", "-1", "1, 1", "1.0", "True", "1,", "1000000"])
def test_processing_selection_rejects_ambiguous_or_invalid_input(qtapp, project, text):
    dialog = CommandDialog("import", project, initial={"path": "original.zip"})
    assert dialog.command()["bruker_processing_numbers"] is None
    dialog.fields["bruker_processing_numbers"].setText(text)
    with pytest.raises(ValueError):
        dialog.command()


def test_native_object_choices_keep_stable_ids_and_missing_selection(qtapp, project):
    dialog = CommandDialog(
        "integrate", project, initial={"spectrum_id": "t3", "lower": 1.0, "upper": 2.0}
    )
    assert dialog.command()["spectrum_id"] == "t3"
    assert dialog.fields["spectrum_id"].currentText().endswith("t3")
    missing = CommandDialog(
        "integrate", project, initial={"spectrum_id": "deleted_trace", "lower": 1.0, "upper": 2.0}
    )
    assert missing.fields["spectrum_id"].currentData() == "deleted_trace"
    with pytest.raises(ValueError, match="no longer available"):
        missing.command()
    removal = CommandDialog("remove", project)
    assert removal.fields["object_id"].findData("t0") == -1
    assert removal.fields["object_id"].findData("pdf") == -1
    assert removal.fields["object_id"].findData("label_a") >= 0


def test_normalization_selection_preserves_signed_input_arrays(qtapp, project):
    before = deepcopy(project.spectra["t0"].real)
    initial = next(c for c in commands(project) if c["op"] == "normalize")
    dialog = CommandDialog("normalize", project, initial=initial)
    assert dialog.command()["integral_ids"] == ["recovered", "product", "standard"]
    assert project.spectra["t0"].real == before
    assert min(before) < 0
    selected = dialog.fields["integral_ids"]
    for row in range(selected.count()):
        item = selected.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == "product":
            item.setCheckState(Qt.CheckState.Unchecked)
    assert dialog.command()["integral_ids"] == ["recovered", "standard"]


def test_get_command_requires_explicit_acceptance_and_never_mutates_project(
    qtapp, project, monkeypatch
):
    before = project.model_dump()
    monkeypatch.setattr(CommandDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    assert get_command("demo", project) is None

    def accept_dialog(dialog):
        dialog.accept()
        return dialog.result()

    monkeypatch.setattr(CommandDialog, "exec", accept_dialog)
    assert get_command("demo", project) == {"op": "demo"}
    assert get_command("fit", project) is None
    assert project.model_dump() == before


def test_empty_project_opens_every_native_form_without_auto_data(qtapp):
    p = Project(id="empty", name="Empty", revision=0)
    for operation in OPERATIONS:
        dialog = CommandDialog(operation, p)
        if operation == "demo":
            assert dialog.command() == {"op": "demo"}
        else:
            with pytest.raises(ValueError):
                dialog.command()
        dialog.deleteLater()
    assert not p.spectra and not p.samples and p.revision == 0


def test_modal_accept_cancel_cycles_release_parented_dialogs(qtapp, project, monkeypatch):
    from PySide6.QtWidgets import QDialogButtonBox, QWidget

    parent = QWidget()
    destroyed = []
    accepting = True

    def interact(dialog):
        dialog.destroyed.connect(lambda: destroyed.append(True))
        button = (
            QDialogButtonBox.StandardButton.Ok
            if accepting
            else QDialogButtonBox.StandardButton.Cancel
        )
        dialog.buttons.button(button).click()
        return dialog.result()

    monkeypatch.setattr(CommandDialog, "exec", interact)
    for index in range(24):
        accepting = index % 2 == 0
        result = get_command("demo", project, parent)
        assert result == ({"op": "demo"} if accepting else None)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert parent.findChildren(CommandDialog) == []
        assert len(destroyed) == index + 1
    parent.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_primary_action_and_invalid_field_feedback_are_visible_and_specific(qtapp, project):
    from PySide6.QtWidgets import QDialogButtonBox

    fit = CommandDialog("fit", project, initial=FIT_COMMAND)
    assert fit.buttons.button(QDialogButtonBox.StandardButton.Ok).text() == "Fit mapped traces"
    dialog = CommandDialog("yield", project, initial=YIELD_COMMAND)
    dialog.fields["u_standard_area"].setText("-0.1")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert not dialog.error_label.isHidden()
    assert dialog.error_label.text().startswith("Please correct the following:")
    assert "u_standard_area" in dialog.error_label.text()
    assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "Standard uncertainties"
    dialog.fields["u_standard_area"].setText("0.1")
    dialog.accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.error_label.isHidden()
