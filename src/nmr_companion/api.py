"""Host-neutral validated tool API; HTTP and MCP call the same dispatcher."""

from typing import Generic, Literal, TypeVar
from pydantic import Field, JsonValue, ValidationError, model_validator
from .commands import OPERATIONS
from .errors import NmrError
from .models import Artifact, Failure, Identifier, Model, Name, Receipt, SCIENTIFIC_RESULTS
from .service import Service
from .store import canonical_json


class Summary(Model):
    project_id: Identifier
    name: Name
    revision: int
    spectra: int
    grids: int
    tables: int
    integrals: int
    analyses: int
    assignments: int
    samples: int = 0
    structures: int = 0
    crosspeaks: int = 0
    peaklabels: int = 0
    attachments: int = 0
    annotations: int = 0
    objects: list[dict[str, str | int]]


class ProjectInput(Model):
    action: Literal["status", "create"] = "status"
    name: Name | None = None


class ReadInput(Model):
    object_id: Identifier


class EditInput(Model):
    expected_revision: int = Field(ge=0)
    request_id: Identifier
    command: dict[str, JsonValue] = Field(max_length=32)


class RequestInput(Model):
    request_id: Identifier


class ExportInput(Model):
    revision: int = Field(ge=0)
    destination: str | None = Field(default=None, min_length=1, max_length=4096)


class ExportView(Artifact):
    local_path: str | None = None


class HelpInput(Model):
    operation: str | None = None


class ObjectView(Model):
    object_id: Identifier
    object_type: Literal[
        "spectrum",
        "grid",
        "table",
        "integral",
        "analysis",
        "assignment",
        "sample",
        "structure",
        "crosspeak",
        "peaklabel",
        "attachment",
        "annotation",
    ]
    version: int
    # Validated against the underlying project model before serialization.
    # Spectrum/grid arrays are omitted: scientific operations use full arrays in the service.
    data: dict[str, JsonValue]


class HelpView(Model):
    schema_version: Literal[1] = 1
    operations: list[str]
    selected_operation: str | None
    input_schema: dict[str, JsonValue] | None
    result_schema: dict[str, JsonValue]
    scientific_result_schema: dict[str, JsonValue] | None
    notes: list[str]


T = TypeVar("T")


class Reply(Model, Generic[T]):
    ok: bool
    data: T | None = None
    error: Failure | None = None

    @model_validator(mode="after")
    def branch_semantics(self):
        if self.ok and (self.data is None or self.error is not None):
            raise ValueError("success requires data and no error")
        if not self.ok and (self.error is None or self.data is not None):
            raise ValueError("failure requires an error and no success data")
        return self


SPECS = {
    "nmr_project": (
        ProjectInput,
        Reply[Summary],
        "Create or inspect the configured local project. Import files with nmr_edit.",
    ),
    "nmr_read": (
        ReadInput,
        Reply[ObjectView],
        "Read a stable object's metadata, integrals, assignments or scientific analysis. Full arrays stay local.",
    ),
    "nmr_edit": (
        EditInput,
        Reply[Receipt],
        "Apply a validated operation atomically. Use nmr_help for operation schemas; refresh after revision conflicts.",
    ),
    "nmr_request": (
        RequestInput,
        Reply[Receipt],
        "Reconcile a request with uncertain completion before retrying. Returns its original committed receipt.",
    ),
    "nmr_export": (
        ExportInput,
        Reply[ExportView],
        "Generate a revision ZIP with originals, editable state, CSV and SVG/PNG figures. An optional absolute destination saves a new .zip file without overwriting; return its local_path as a host file link.",
    ),
    "nmr_help": (
        HelpInput,
        Reply[HelpView],
        "Discover compact operation-specific schemas, units and limitations on demand.",
    ),
}


def summary(project):
    objects = []
    for kind in (
        "spectra",
        "grids",
        "tables",
        "integrals",
        "analyses",
        "assignments",
        "samples",
        "structures",
        "crosspeaks",
        "peaklabels",
        "attachments",
        "annotations",
    ):
        for obj in getattr(project, kind).values():
            objects.append(
                {
                    "id": obj.id,
                    "type": kind,
                    "name": getattr(obj, "name", getattr(obj, "atom", "")),
                    "version": obj.version,
                }
            )
    return Summary(
        project_id=project.id,
        name=project.name,
        revision=project.revision,
        objects=objects,
        **{
            k: len(getattr(project, k))
            for k in (
                "spectra",
                "grids",
                "tables",
                "integrals",
                "analyses",
                "assignments",
                "samples",
                "structures",
                "crosspeaks",
                "peaklabels",
                "attachments",
                "annotations",
            )
        },
    )


def dispatch(service: Service, name: str, arguments: dict):
    if name not in SPECS:
        raise NmrError("UNKNOWN_TOOL", "Tool is not part of this server.")
    input_model, output_model, _ = SPECS[name]
    try:
        args = input_model.model_validate(arguments)
        if name == "nmr_project":
            if args.action == "create":
                if args.name is None:
                    raise NmrError("INVALID_ARGUMENT", "A project name is required.")
                data = summary(service.create(args.name))
            else:
                data = summary(service.read())
        elif name == "nmr_edit":
            data = service.apply(args.expected_revision, args.request_id, args.command)
        elif name == "nmr_request":
            data = service.store.request(args.request_id)
        elif name == "nmr_export":
            if args.destination is None:
                data = ExportView(**service.export(args.revision).model_dump())
            else:
                from .delivery import export_file

                artifact, path = export_file(service, args.revision, args.destination)
                data = ExportView(**artifact.model_dump(), local_path=str(path))
        elif name == "nmr_help":
            if args.operation is not None and args.operation not in OPERATIONS:
                raise NmrError("UNKNOWN_OPERATION", "Select an operation listed in nmr_help.")
            data = HelpView(
                operations=list(OPERATIONS),
                selected_operation=args.operation,
                input_schema=OPERATIONS[args.operation].model_json_schema()
                if args.operation
                else None,
                result_schema=Receipt.model_json_schema(),
                scientific_result_schema=SCIENTIFIC_RESULTS[
                    {
                        "fit": "relaxation",
                        "yield": "yield",
                        "peaks": "peaks",
                        "normalize": "normalization",
                        "compare": "comparison",
                        "dept": "dept",
                    }[args.operation]
                ].model_json_schema()
                if args.operation in {"fit", "yield", "peaks", "normalize", "compare", "dept"}
                else None,
                notes=[
                    "Mutation result is a durable receipt; read its object IDs for scientific results.",
                    "Numerical full-resolution arrays never pass through an LLM.",
                    "Time unit and row mapping must be explicit. Signed T1 spectra are preserved.",
                    "Uncertainty is a fitted parameter standard uncertainty, not a confidence interval.",
                    "Source/region edits mark derived analyses and assignments stale.",
                    "This developer alpha does not certify untested formats or hosts.",
                ],
            )
        else:
            project = service.read()
            obj = project.object(args.object_id)
            body = obj.model_dump(mode="json")
            kind = type(obj).__name__.lower()
            if kind == "spectrum":
                body.update(
                    {"points": len(obj.axis), "axis_bounds": [min(obj.axis), max(obj.axis)]}
                )
                for key in ("axis", "real", "imag"):
                    body.pop(key, None)
            if kind == "grid":
                body["shape"] = [len(obj.y), len(obj.x)]
                for key in ("x", "y", "z"):
                    body.pop(key, None)
            if kind == "table":
                body["total_rows"] = len(body["rows"])
                body["rows"] = body["rows"][:64]
            if kind == "analysis":
                truncated = {}
                for key in ("peaks", "rows", "integrals"):
                    values = body["result"].get(key)
                    if isinstance(values, list) and len(values) > 64:
                        truncated[key] = {"total": len(values), "returned": 64}
                        body["result"][key] = values[:64]
                if truncated:
                    body["result_truncation"] = truncated
                    body["full_data"] = "Export this revision for complete scientific tables."
            data = ObjectView(object_id=obj.id, object_type=kind, version=obj.version, data=body)
        reply = output_model(ok=True, data=data)
    except (NmrError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            issue = exc.errors(include_input=False)[0]
            message = ".".join(map(str, issue["loc"])) + ": " + issue["msg"]
            failure = Failure(code="INVALID_ARGUMENT", message=message)
        else:
            failure = Failure(
                code=exc.code, message=exc.message, current_revision=exc.current_revision
            )
        reply = output_model(ok=False, error=failure)
    except Exception:
        reply = output_model(
            ok=False,
            error=Failure(
                code="EXECUTION_FAILED",
                message="Operation failed. Reopen the project and reconcile its request ID before retrying.",
                recoverable=False,
            ),
        )
    # Roundtrip validates actual JSON (including finite values) before delivery.
    result = reply.model_dump(mode="json")
    output_model.model_validate_json(canonical_json(result))
    return result
