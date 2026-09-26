from typing import Annotated, Literal, Union
from pydantic import Field, TypeAdapter
from .domain import Model, Name, Identifier, Number, Positive, NonNegative
from .evidence_commands import EVIDENCE_OPERATIONS


class Import(Model):
    op: Literal["import"]
    path: str = Field(min_length=1, max_length=4096)
    bruker_processing_numbers: list[Annotated[int, Field(strict=True, ge=1, le=999999)]] | None = (
        Field(default=None, min_length=1, max_length=64)
    )


class Demo(Model):
    op: Literal["demo"]


class Integrate(Model):
    op: Literal["integrate"]
    spectrum_id: Identifier
    name: Name = "Integral"
    lower: Number
    upper: Number
    integral_id: Identifier | None = None


class Process(Model):
    op: Literal["process"]
    spectrum_id: Identifier
    method: Literal["fft", "phase", "baseline", "reference"]
    ph0_deg: Number = 0
    ph1_deg: Number = 0
    pivot_ppm: Number = 0
    regions: list[tuple[Number, Number]] = Field(default_factory=list, max_length=32)
    reference_shift_ppm: Number = 0
    zero_fill_factor: Literal[1, 2, 4] = 2
    line_broadening_hz: Number = Field(default=0.3, ge=0, le=100)


class Peaks(Model):
    op: Literal["peaks"]
    spectrum_id: Identifier
    prominence: Positive


class Yield(Model):
    op: Literal["yield"]
    product_integral_id: Identifier
    standard_integral_id: Identifier
    product_protons: Positive
    standard_protons: Positive
    standard_mol: Positive
    limiting_mol: Positive
    stoichiometric_factor: Positive = 1.0
    name: Name = "Internal-standard yield"
    recovered_integral_id: Identifier | None = None
    recovered_protons: Positive | None = None
    u_product_area: NonNegative | None = None
    u_standard_area: NonNegative | None = None
    u_recovered_area: NonNegative | None = None
    u_standard_mol: NonNegative | None = None
    u_limiting_mol: NonNegative | None = None


class Fit(Model):
    op: Literal["fit"]
    spectrum_ids: list[Identifier] = Field(min_length=4, max_length=64)
    table_id: Identifier
    row_indices: list[int] = Field(min_length=4, max_length=64)
    delay_column: str = Field(min_length=1, max_length=200)
    sigma_column: str | None = None
    time_unit: Literal["s", "ms", "us"]
    model: Literal["T1", "T2"]
    time_basis: Literal["elapsed", "echo_interval"] = "elapsed"
    delay_multiplier: Positive | None = None
    lower: Number
    upper: Number
    excluded_indices: list[int] = Field(default_factory=list, max_length=60)
    purpose: Literal["analysis", "quick_check"] = "analysis"
    name: Name = "Relaxation analysis"


class Assign(Model):
    op: Literal["assign"]
    assignment_id: Identifier | None = None
    sample_id: Identifier | None = None
    candidate_id: Identifier | None = None
    atom_ids: list[Identifier] = Field(default_factory=list, max_length=256)
    sample: Name
    atom: Name
    candidate: Name
    observation: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=64)
    status: Literal["proposed", "confirmed"] = "proposed"


class Remove(Model):
    op: Literal["remove"]
    object_id: Identifier


class Undo(Model):
    op: Literal["undo"]
    target_revision: int = Field(ge=0)


OP_MODELS = [
    Import,
    Demo,
    Integrate,
    Process,
    Peaks,
    Yield,
    Fit,
    Assign,
    Remove,
    Undo,
    *EVIDENCE_OPERATIONS,
]
Command = Annotated[Union[tuple(OP_MODELS)], Field(discriminator="op")]
COMMAND = TypeAdapter(Command)
OPERATIONS = {c.model_fields["op"].annotation.__args__[0]: c for c in OP_MODELS}
