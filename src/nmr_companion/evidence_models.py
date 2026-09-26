"""Measured observations, sample identities and reviewable interpretations."""

from typing import Literal
from pydantic import Field, model_validator
from .domain import Model, Number, Positive, NonNegative, Fraction, Name, Identifier, Note


class Additive(Model):
    name: Name
    concentration_mol_l: NonNegative | None = None
    notes: Note = ""


class Conditions(Model):
    solvent: Name | None = None
    temperature_k: Positive | None = None
    additives: list[Additive] = Field(default_factory=list, max_length=32)


class Sample(Model):
    id: Identifier
    version: int = Field(default=1, ge=1)
    name: Name
    role: Literal["own", "reference", "synthetic", "unknown"]
    object_ids: list[Identifier] = Field(default_factory=list, max_length=256)
    stage: Note = ""
    parent_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    transformation: Note = ""
    conditions: Conditions = Field(default_factory=Conditions)
    reference: Note = ""
    notes: Note = ""


class Evidence(Model):
    id: Identifier
    version: int = Field(default=1, ge=1)
    source_versions: dict[Identifier, int] = Field(max_length=256)
    state: Literal["current", "stale"] = "current"


class Atom(Model):
    id: Identifier
    label: Name
    element: str = Field(pattern=r"^[A-Z][a-z]?$")
    x: Number = Field(ge=-10000, le=10000)
    y: Number = Field(ge=-10000, le=10000)
    stereo: str = Field(default="", max_length=100)


class Bond(Model):
    a: Identifier
    b: Identifier
    order: Number
    stereo: Literal["none", "wedge", "hash", "either"] = "none"

    @model_validator(mode="after")
    def valid(self):
        if self.a == self.b or self.order not in (1, 1.5, 2, 3):
            raise ValueError("A bond needs distinct atoms and order 1, 1.5, 2 or 3")
        return self


class Structure(Evidence):
    name: Name
    sample_id: Identifier
    atoms: list[Atom] = Field(min_length=1, max_length=256)
    bonds: list[Bond] = Field(default_factory=list, max_length=512)
    description: Note = ""
    alternative_group: str = Field(default="", max_length=200)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=64)
    status: Literal["proposed", "confirmed"] = "proposed"

    @model_validator(mode="after")
    def graph(self):
        ids = [a.id for a in self.atoms]
        if len(set(ids)) != len(ids):
            raise ValueError("Atom IDs must be unique")
        seen = set()
        for b in self.bonds:
            pair = tuple(sorted((b.a, b.b)))
            if b.a not in ids or b.b not in ids or pair in seen:
                raise ValueError("Bonds must reference existing atoms without duplicate pairs")
            seen.add(pair)
        if self.status == "confirmed" and not self.evidence_ids:
            raise ValueError("Confirmed interpretations require explicit evidence")
        return self


class Crosspeak(Evidence):
    grid_id: Identifier
    x_ppm: Number
    y_ppm: Number
    label: Name
    intensity: Number
    observation_method: Literal["nearest original grid point"] = "nearest original grid point"


class Peaklabel(Evidence):
    spectrum_id: Identifier
    ppm: Number
    label: Name
    intensity: Number
    multiplicity: str | None = Field(default=None, max_length=100)
    protons: Positive | None = None
    observation_method: Literal["manual position; original-array interpolation"] = (
        "manual position; original-array interpolation"
    )


class Attachment(Evidence):
    name: Name
    sample_id: Identifier
    source_role: Literal["own", "reference"]
    category: Literal["nmr_reference", "IR", "HRMS", "optical_rotation", "other"]
    source_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["application/pdf", "image/png", "image/jpeg", "image/webp"]
    pages: int = Field(ge=1, le=1000)
    width: Positive
    height: Positive
    notes: Note = ""


class Annotation(Evidence):
    attachment_id: Identifier
    page: int = Field(ge=1, le=1000)
    x: Fraction
    y: Fraction
    width: Fraction = Field(gt=0)
    height: Fraction = Field(gt=0)
    label: Name
    observation: Note = ""
    approximate_ppm: Number | None = None
    reading_uncertainty_ppm: NonNegative | None = None
    origin: Literal["image_annotation_not_numeric_spectrum"] = (
        "image_annotation_not_numeric_spectrum"
    )

    @model_validator(mode="after")
    def bounds(self):
        if self.x + self.width > 1 + 1e-12 or self.y + self.height > 1 + 1e-12:
            raise ValueError("Annotation must lie within its page")
        if self.approximate_ppm is None and self.reading_uncertainty_ppm is not None:
            raise ValueError("Reading uncertainty requires an approximate reading")
        return self


class NormalizedIntegral(Model):
    integral_id: Identifier
    signed_area: Number
    relative_protons: Number


class NormalizationResult(Model):
    reference_integral_id: Identifier
    reference_protons: Positive
    integrals: list[NormalizedIntegral] = Field(min_length=1, max_length=256)
    unit: Literal["relative proton count"] = "relative proton count"
    method: Literal["explicit same-spectrum proton reference"] = (
        "explicit same-spectrum proton reference"
    )
    assumptions: list[Note]


class ComparisonResult(Model):
    metric: Literal["T_s", "chemical_shift_ppm"]
    unit: Literal["s", "ppm"]
    left: Number
    right: Number
    difference: Number
    ratio: Number | None
    u_left: NonNegative | None
    u_right: NonNegative | None
    u_difference: NonNegative | None
    u_ratio: NonNegative | None
    signal_label: Name
    correspondence: Note
    left_sample_id: Identifier
    right_sample_id: Identifier
    left_conditions: Conditions
    right_conditions: Conditions
    reference_conventions: list[Note] = Field(min_length=2, max_length=2)
    uncertainty_method: Note
    assumptions: list[Note]
    warnings: list[Note]


class DeptRow(Model):
    carbon_ppm: Number
    dept_ppm: Number | None
    dept_intensity: Number | None
    interpretation: Literal["CH_or_CH3", "CH2", "no_DEPT_signal", "ambiguous"]
    matched_candidates: int = Field(ge=0)
    competing_carbon_candidates: int = Field(default=0, ge=0)


class DeptResult(Model):
    rows: list[DeptRow] = Field(max_length=262144)
    reference_convention: Literal["positive_ch_ch3", "negative_ch_ch3"]
    tolerance_ppm: Positive
    reference: Note
    method: Literal["signed DEPT-135 to 13C peak matching"] = "signed DEPT-135 to 13C peak matching"
    interpretation_status: Literal["proposed"] = "proposed"
    assumptions: list[Note]
    warnings: list[Note]


COLLECTIONS = ("samples", "structures", "crosspeaks", "peaklabels", "attachments", "annotations")
DERIVED_COLLECTIONS = ("structures", "crosspeaks", "peaklabels", "attachments", "annotations")
