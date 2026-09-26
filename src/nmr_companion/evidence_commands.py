from typing import Literal
from pydantic import Field
from .domain import Model, Number, Positive, NonNegative, Fraction, Name, Identifier, Note
from .evidence_models import Atom, Bond, Conditions


class SampleCommand(Model):
    op: Literal["sample"]
    sample_id: Identifier | None = None
    name: Name
    role: Literal["own", "reference", "synthetic", "unknown"]
    object_ids: list[Identifier] = Field(default_factory=list, max_length=256)
    stage: Note = ""
    parent_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    transformation: Note = ""
    conditions: Conditions = Field(default_factory=Conditions)
    reference: Note = ""
    notes: Note = ""


class StructureCommand(Model):
    op: Literal["structure"]
    structure_id: Identifier | None = None
    name: Name
    sample_id: Identifier
    atoms: list[Atom] = Field(min_length=1, max_length=256)
    bonds: list[Bond] = Field(default_factory=list, max_length=512)
    description: Note = ""
    alternative_group: str = Field(default="", max_length=200)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=64)
    status: Literal["proposed", "confirmed"] = "proposed"


class CrosspeakCommand(Model):
    op: Literal["crosspeak"]
    crosspeak_id: Identifier | None = None
    grid_id: Identifier
    x_ppm: Number
    y_ppm: Number
    label: Name


class GridMetadata(Model):
    op: Literal["grid_metadata"]
    grid_id: Identifier
    experiment: Literal["COSY", "HSQC"]
    nuclei: list[Literal["1H", "13C", "15N"]] = Field(min_length=2, max_length=2)
    reference: Name


class PeakLabelCommand(Model):
    op: Literal["peak_label"]
    peaklabel_id: Identifier | None = None
    spectrum_id: Identifier
    ppm: Number
    label: Name
    multiplicity: str | None = Field(default=None, max_length=100)
    protons: Positive | None = None


class Normalize(Model):
    op: Literal["normalize"]
    name: Name = "Relative proton integration"
    reference_integral_id: Identifier
    reference_protons: Positive
    integral_ids: list[Identifier] = Field(min_length=1, max_length=256)


class Attach(Model):
    op: Literal["attach"]
    path: str = Field(min_length=1, max_length=4096)
    name: Name | None = None
    sample_id: Identifier
    source_role: Literal["own", "reference"]
    category: Literal["nmr_reference", "IR", "HRMS", "optical_rotation", "other"]
    notes: Note = ""


class Annotate(Model):
    op: Literal["annotate"]
    annotation_id: Identifier | None = None
    attachment_id: Identifier
    page: int = Field(default=1, ge=1, le=1000)
    x: Fraction
    y: Fraction
    width: Fraction = Field(gt=0)
    height: Fraction = Field(gt=0)
    label: Name
    observation: Note = ""
    approximate_ppm: Number | None = None
    reading_uncertainty_ppm: NonNegative | None = None


class Compare(Model):
    op: Literal["compare"]
    name: Name
    metric: Literal["T_s", "chemical_shift_ppm"]
    left_id: Identifier
    right_id: Identifier
    left_sample_id: Identifier
    right_sample_id: Identifier
    signal_label: Name
    correspondence: Name
    independent_uncertainties: bool = False


class Dept(Model):
    op: Literal["dept"]
    carbon_spectrum_id: Identifier
    dept_spectrum_id: Identifier
    carbon_prominence: Positive
    dept_prominence: Positive
    tolerance_ppm: Positive = Field(le=5)
    reference_convention: Literal["positive_ch_ch3", "negative_ch_ch3"]
    reference: Name
    name: Name = "DEPT-135 / carbon evidence"


EVIDENCE_OPERATIONS = [
    SampleCommand,
    StructureCommand,
    CrosspeakCommand,
    GridMetadata,
    PeakLabelCommand,
    Normalize,
    Attach,
    Annotate,
    Compare,
    Dept,
]
