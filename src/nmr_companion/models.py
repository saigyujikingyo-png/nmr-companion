from __future__ import annotations

from typing import Annotated, Literal
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .errors import NmrError

Number = Annotated[float, Field(allow_inf_nan=False, strict=True)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False, strict=True)]
Name = Annotated[str, Field(min_length=1, max_length=200)]
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")]
Vector = Annotated[list[Number], Field(min_length=2, max_length=262144)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Source(Model):
    names: list[Name] = Field(default_factory=list)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: Name
    size: int = Field(ge=0, le=33554432)


class Spectrum(Model):
    id: Identifier
    version: int = Field(default=1, ge=1)
    name: Name
    axis: Vector
    real: Vector
    imag: Vector | None = None
    axis_unit: Literal["ppm", "s"]
    domain: Literal["frequency", "time"]
    nucleus: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)
    history: list[dict[str, JsonValue]] = Field(default_factory=list)

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.axis) != len(self.real) or (
            self.imag is not None and len(self.imag) != len(self.real)
        ):
            raise ValueError("axis and signal lengths must match")
        diff = np.diff(self.axis)
        if not (np.all(diff > 0) or np.all(diff < 0)):
            raise ValueError("axis must be strictly monotonic")
        if (self.domain, self.axis_unit) not in [("frequency", "ppm"), ("time", "s")]:
            raise ValueError("domain and axis unit disagree")
        return self


class Grid(Model):
    id: Identifier
    version: int = 1
    name: Name
    x: Vector
    y: Vector
    z: list[list[Number]]
    nuclei: list[str | None] = Field(min_length=2, max_length=2)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def dimensions(self):
        if len(self.x) * len(self.y) > 1000000:
            raise ValueError("grid exceeds one million cells")
        if len(self.z) != len(self.y) or any(len(row) != len(self.x) for row in self.z):
            raise ValueError("z rows correspond to y; columns correspond to x")
        for axis in (self.x, self.y):
            diff = np.diff(axis)
            if not (np.all(diff > 0) or np.all(diff < 0)):
                raise ValueError("grid axes must be strictly monotonic")
        return self


class Table(Model):
    id: Identifier
    version: int = 1
    name: Name
    columns: list[str] = Field(min_length=1, max_length=128)
    rows: list[dict[str, str]] = Field(max_length=10000)
    source_ids: list[str] = Field(default_factory=list)


class Integral(Model):
    id: Identifier
    version: int = 1
    spectrum_id: Identifier
    spectrum_version: int
    name: Name
    lower: Number
    upper: Number
    area: Number
    unit: Literal["intensity*ppm"] = "intensity*ppm"


class Analysis(Model):
    id: Identifier
    version: int = 1
    name: Name
    kind: Literal["yield", "relaxation", "peaks"]
    state: Literal["current", "stale"] = "current"
    source_versions: dict[str, int]
    parameters: dict[str, JsonValue]
    result: dict[str, JsonValue]

    @model_validator(mode="after")
    def scientific_result(self):
        self.result = (
            SCIENTIFIC_RESULTS[self.kind].model_validate(self.result).model_dump(mode="json")
        )
        return self


class Assignment(Model):
    id: Identifier
    version: int = 1
    sample: Name
    atom: Name
    candidate: Name
    observation: str = Field(min_length=1, max_length=4000)
    evidence_ids: list[Identifier] = Field(min_length=1, max_length=64)
    source_versions: dict[str, int]
    status: Literal["proposed", "confirmed"] = "proposed"
    state: Literal["current", "stale"] = "current"


class Project(Model):
    schema_version: Literal[1] = 1
    id: Identifier
    name: Name
    revision: int = Field(ge=0)
    sources: dict[str, Source] = Field(default_factory=dict)
    spectra: dict[str, Spectrum] = Field(default_factory=dict)
    grids: dict[str, Grid] = Field(default_factory=dict)
    tables: dict[str, Table] = Field(default_factory=dict)
    integrals: dict[str, Integral] = Field(default_factory=dict)
    analyses: dict[str, Analysis] = Field(default_factory=dict)
    assignments: dict[str, Assignment] = Field(default_factory=dict)

    def object(self, object_id: str):
        for collection in (
            self.spectra,
            self.grids,
            self.tables,
            self.integrals,
            self.analyses,
            self.assignments,
        ):
            if object_id in collection:
                return collection[object_id]
        raise NmrError("NOT_FOUND", "Object does not exist in this project.")


class Receipt(Model):
    request_id: Identifier
    operation: str
    project_id: Identifier
    revision: int
    object_ids: list[Identifier] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    replayed: bool = False


class Failure(Model):
    code: str
    message: str
    recoverable: bool = True
    current_revision: int | None = None


class Artifact(Model):
    id: Identifier
    revision: int
    name: Name
    media_type: str
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    uri: str


class Peak(Model):
    ppm: Number
    intensity: Number
    polarity: Literal["positive", "negative"]


class PeakResult(Model):
    peaks: list[Peak] = Field(max_length=262144)
    method: str


class YieldResult(Model):
    yield_percent: Positive
    method: str
    assumptions: list[str]


class TraceMapping(Model):
    spectrum_id: Identifier
    row_index: int = Field(ge=0)
    delay: Number
    area: Number
    excluded: bool


class RelaxationResult(Model):
    model: Literal["T1", "T2"]
    status: Literal["ok", "warning", "unidentifiable"]
    time_s: list[Number] = Field(min_length=1, max_length=4096)
    signals: list[Number] = Field(min_length=1, max_length=4096)
    predicted: list[Number] = Field(max_length=4096)
    residuals: list[Number] = Field(max_length=4096)
    parameters: dict[str, Number]
    T_s: Positive | None
    u_T_s: Number | None = Field(ge=0)
    uncertainty_method: str
    warnings: list[str]
    diagnostics: dict[str, JsonValue]
    mapping: list[TraceMapping] = Field(default_factory=list, max_length=64)
    purpose: Literal["analysis", "quick_check"] = "analysis"
    assumptions: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def scientific_semantics(self):
        count = len(self.time_s)
        if (
            len(self.signals) != count
            or len(self.predicted) not in (0, count)
            or len(self.residuals) != len(self.predicted)
        ):
            raise ValueError("fit observation and prediction dimensions disagree")
        if any(t < 0 for t in self.time_s):
            raise ValueError("elapsed times cannot be negative")
        if self.status == "unidentifiable" and (self.T_s is not None or self.u_T_s is not None):
            raise ValueError("unidentifiable fits cannot report a relaxation time or uncertainty")
        if self.status != "unidentifiable" and (self.T_s is None or len(self.predicted) != count):
            raise ValueError("identified fits require a positive time and complete predictions")
        if self.parameters:
            expected = (
                {"A", "B", "k_s_inverse"} if self.model == "T1" else {"C", "A", "k_s_inverse"}
            )
            if set(self.parameters) != expected or self.parameters["k_s_inverse"] <= 0:
                raise ValueError("fit parameters must match the declared physical model")
        return self


SCIENTIFIC_RESULTS = {"peaks": PeakResult, "yield": YieldResult, "relaxation": RelaxationResult}
