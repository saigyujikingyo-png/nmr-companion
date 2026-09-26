"""Joint-batch scientific commands; all writes run inside Store.mutate."""

from bisect import bisect_left, bisect_right
import math
from pathlib import Path
import numpy as np
from .errors import NmrError
from .evidence_models import Sample, Structure, Crosspeak, Peaklabel, Attachment, Annotation
from .store import identifier
from .models import Source
from . import numerics as n


def require(collection, oid, what="Object"):
    if oid not in collection:
        raise NmrError("NOT_FOUND", what + " does not exist.")
    return collection[oid]


def versions(p, ids):
    out = {}
    for oid in dict.fromkeys(ids):
        obj = p.object(oid)
        if getattr(obj, "state", "current") != "current":
            raise NmrError("STALE_EVIDENCE", "Refresh stale evidence before using it.")
        out[oid] = obj.version
    return out


def cycle(p, target, sources):
    pending = list(sources)
    seen = set()
    while pending:
        oid = pending.pop()
        if oid == target:
            raise NmrError("EVIDENCE_CYCLE", "Evidence cannot cite itself transitively.")
        if oid in seen:
            continue
        seen.add(oid)
        obj = p.object(oid)
        pending.extend(getattr(obj, "source_versions", {}))


def put(service, p, collection, cls, key, c, source_ids, extra=None):
    old = collection.get(c.get(key))
    if c.get(key) and old is None:
        raise NmrError("NOT_FOUND", "The object selected for editing no longer exists.")
    oid = old.id if old else identifier(cls.__name__.lower())
    cycle(p, oid, source_ids)
    data = {
        k: v
        for k, v in c.items()
        if k in cls.model_fields and k not in ("id", "version", "state", "source_versions")
    }
    data.update(extra or {})
    obj = cls(
        id=oid,
        version=old.version + 1 if old else 1,
        source_versions=versions(p, source_ids),
        **data,
    )
    collection[oid] = obj
    service.invalidate(p, [oid])
    return [oid], []


def grid_semantics(experiment, nuclei):
    if experiment == "COSY" and nuclei == ["1H", "1H"]:
        return
    if (
        experiment == "HSQC"
        and len(nuclei) == 2
        and "1H" in nuclei
        and any(x in nuclei for x in ("13C", "15N"))
    ):
        return
    raise NmrError(
        "GRID_AXES", "Confirm explicit COSY 1H/1H or HSQC 1H/13C or 1H/15N axes before assigning."
    )


def acquired_ids(p, obj):
    if hasattr(obj, "spectrum_id"):
        return {obj.spectrum_id}
    if hasattr(obj, "grid_id"):
        return {obj.grid_id}
    result = set()
    pending = list(getattr(obj, "source_versions", {}))
    seen = set()
    while pending:
        oid = pending.pop()
        if oid in seen:
            continue
        seen.add(oid)
        if oid in p.spectra or oid in p.grids:
            result.add(oid)
        else:
            pending.extend(getattr(p.object(oid), "source_versions", {}))
    return result


def execute(service, p, db, c):
    op = c["op"]
    if op == "sample":
        old = p.samples.get(c["sample_id"])
        if c["sample_id"] and old is None:
            raise NmrError("NOT_FOUND", "Sample does not exist.")
        oid = old.id if old else identifier("sample")
        if len(set(c["object_ids"])) != len(c["object_ids"]) or len(set(c["parent_ids"])) != len(
            c["parent_ids"]
        ):
            raise NmrError("DUPLICATE_ID", "Sample associations must use unique identities.")
        for item in c["object_ids"]:
            if item not in p.spectra and item not in p.grids and item not in p.tables:
                raise NmrError(
                    "SAMPLE_DATA", "Associate acquired spectra, matrices or tables with a sample."
                )
        pending = list(c["parent_ids"])
        seen = set()
        while pending:
            parent = pending.pop()
            if parent == oid:
                raise NmrError("SAMPLE_CYCLE", "Sample transformations cannot form a cycle.")
            if parent not in seen:
                seen.add(parent)
                pending.extend(require(p.samples, parent, "Parent sample").parent_ids)
        if c["parent_ids"] and not c["transformation"].strip():
            raise NmrError(
                "TRANSFORMATION_CONTEXT", "Describe the transformation between samples/stages."
            )
        data = {k: v for k, v in c.items() if k in Sample.model_fields}
        p.samples[oid] = Sample(id=oid, version=old.version + 1 if old else 1, **data)
        service.invalidate(p, [oid])
        return [oid], []
    if op == "structure":
        require(p.samples, c["sample_id"], "Sample")
        return put(
            service,
            p,
            p.structures,
            Structure,
            "structure_id",
            c,
            [c["sample_id"], *c["evidence_ids"]],
        )
    if op == "grid_metadata":
        grid = require(p.grids, c["grid_id"], "Processed grid")
        grid_semantics(c["experiment"], c["nuclei"])
        metadata = dict(grid.metadata)
        metadata.setdefault("imported_nuclei", list(grid.nuclei))
        metadata.setdefault("imported_experiment", metadata.get("experiment"))
        history = list(metadata.get("axis_confirmations", []))
        history.append(
            {"experiment": c["experiment"], "nuclei": c["nuclei"], "reference": c["reference"]}
        )
        metadata.update(
            experiment=c["experiment"], axis_confirmations=history, axis_units=["ppm", "ppm"]
        )
        grid.metadata = metadata
        grid.nuclei = c["nuclei"]
        grid.version += 1
        service.invalidate(p, [grid.id])
        return [grid.id], [
            "Axis/experiment identification is explicit user-supplied metadata; original parameters remain preserved."
        ]
    if op == "crosspeak":
        grid = require(p.grids, c["grid_id"], "Processed grid")
        grid_semantics(grid.metadata.get("experiment"), grid.nuclei)
        if not min(grid.x) <= c["x_ppm"] <= max(grid.x) or not min(grid.y) <= c["y_ppm"] <= max(
            grid.y
        ):
            raise NmrError("GRID_BOUNDS", "Crosspeak coordinates must lie on the imported axes.")
        ix = int(np.argmin(np.abs(np.asarray(grid.x) - c["x_ppm"])))
        iy = int(np.argmin(np.abs(np.asarray(grid.y) - c["y_ppm"])))
        return put(
            service,
            p,
            p.crosspeaks,
            Crosspeak,
            "crosspeak_id",
            c,
            [grid.id],
            {"intensity": grid.z[iy][ix]},
        )
    if op == "peak_label":
        spectrum = service._frequency(p, c["spectrum_id"])
        if not min(spectrum.axis) <= c["ppm"] <= max(spectrum.axis):
            raise NmrError("SPECTRUM_BOUNDS", "Peak label must lie on the spectrum axis.")
        ids = np.argsort(spectrum.axis)
        intensity = float(
            np.interp(c["ppm"], np.asarray(spectrum.axis)[ids], np.asarray(spectrum.real)[ids])
        )
        return put(
            service,
            p,
            p.peaklabels,
            Peaklabel,
            "peaklabel_id",
            c,
            [spectrum.id],
            {"intensity": intensity},
        )
    if op == "normalize":
        ref = require(p.integrals, c["reference_integral_id"], "Reference integral")
        spectrum = service._frequency(p, ref.spectrum_id)
        if spectrum.nucleus != "1H" or ref.area <= 0:
            raise NmrError(
                "NORMALIZATION_REFERENCE",
                "Relative proton normalization requires a positive 1H reference integral.",
            )
        if len(set(c["integral_ids"])) != len(c["integral_ids"]):
            raise NmrError("DUPLICATE_ID", "Select each integral only once.")
        items = []
        for oid in c["integral_ids"]:
            integral = require(p.integrals, oid, "Integral")
            if integral.spectrum_id != ref.spectrum_id:
                raise NmrError(
                    "NORMALIZATION_SPECTRA",
                    "Relative proton normalization is confined to one 1H spectrum.",
                )
            items.append(
                {
                    "integral_id": oid,
                    "signed_area": integral.area,
                    "relative_protons": integral.area / ref.area * c["reference_protons"],
                }
            )
        result = {
            "reference_integral_id": ref.id,
            "reference_protons": c["reference_protons"],
            "integrals": items,
            "assumptions": [
                "Relative proton counts are not absolute concentration or purity.",
                "Original spectra and relaxation amplitudes are unchanged; do not substitute these ratios into relaxation fits.",
            ],
        }
        return service._analysis(
            p, "normalization", c["name"], [ref.id, *c["integral_ids"]], c, result
        ), []
    if op == "attach":
        require(p.samples, c["sample_id"], "Sample")
        path = Path(c["path"]).expanduser()
        try:
            with path.open("rb") as file:
                data = file.read(32 * 1024 * 1024 + 1)
        except OSError as exc:
            raise NmrError(
                "REFERENCE_FILE", "The selected reference file could not be read."
            ) from exc
        if not data or len(data) > 32 * 1024 * 1024:
            raise NmrError("REFERENCE_LIMIT", "Reference must be nonempty and at most 32 MiB.")
        from .media import inspect_reference

        metadata = inspect_reference(data)
        digest = service.store.preserve_original(db, data)
        if (
            digest not in p.sources
            and sum(s.size for s in p.sources.values()) + len(data) > 128 * 1024 * 1024
        ):
            raise NmrError("SOURCE_LIMIT", "Project originals exceed the 128 MiB limit.")
        if digest in p.sources:
            if path.name not in p.sources[digest].names:
                p.sources[digest].names.append(path.name)
        else:
            p.sources[digest] = Source(
                name=path.name, names=[path.name], sha256=digest, size=len(data)
            )
        return put(
            service,
            p,
            p.attachments,
            Attachment,
            "attachment_id",
            c,
            [c["sample_id"]],
            {"name": c["name"] or path.name, "source_id": digest, **metadata},
        )
    if op == "annotate":
        attachment = require(p.attachments, c["attachment_id"], "Reference attachment")
        if c["page"] > attachment.pages:
            raise NmrError("REFERENCE_PAGE", "The annotation page does not exist.")
        return put(service, p, p.annotations, Annotation, "annotation_id", c, [attachment.id])
    if op == "compare":
        left = p.object(c["left_id"])
        right = p.object(c["right_id"])
        if left.id == right.id:
            raise NmrError("COMPARISON_IDENTITY", "Choose two distinct observations.")
        samples = [
            require(p.samples, c[k], "Sample") for k in ("left_sample_id", "right_sample_id")
        ]
        versions(p, [left.id, right.id])
        for obj, sample in zip((left, right), samples):
            if not acquired_ids(p, obj) or not acquired_ids(p, obj).issubset(
                set(sample.object_ids)
            ):
                raise NmrError(
                    "SAMPLE_CORRESPONDENCE",
                    "Explicitly associate every measured source with its selected sample.",
                )
        warnings = []
        if c["metric"] == "T_s":
            if any(getattr(o, "kind", None) != "relaxation" for o in (left, right)):
                raise NmrError(
                    "COMPARISON_METRIC", "T_s comparison requires two relaxation analyses."
                )
            if left.result["model"] != right.result["model"]:
                raise NmrError("COMPARISON_MODEL", "Compare the same T1 or T2 model.")
            values = [o.result["T_s"] for o in (left, right)]
            uncertainty = [o.result["u_T_s"] for o in (left, right)]
            if any(v is None for v in values):
                raise NmrError(
                    "UNAVAILABLE_RESULT", "An unidentifiable fit cannot supply a time comparison."
                )
            for obj in (left, right):
                warnings.extend(obj.result.get("warnings", []))
            unit = "s"
        else:
            if not isinstance(left, Peaklabel) or not isinstance(right, Peaklabel):
                raise NmrError(
                    "COMPARISON_METRIC", "Shift comparison requires numeric peak labels."
                )
            a, b = (p.spectra[o.spectrum_id] for o in (left, right))
            if not a.nucleus or a.nucleus != b.nucleus:
                raise NmrError(
                    "COMPARISON_NUCLEUS",
                    "Shift comparisons require the same explicitly known nucleus.",
                )
            values = [left.ppm, right.ppm]
            uncertainty = [None, None]
            unit = "ppm"
        a, b = values
        ua, ub = uncertainty
        independent = c["independent_uncertainties"]
        comparable = independent and ua is not None and ub is not None
        ratio = b / a if unit == "s" else None
        result = {
            "metric": c["metric"],
            "unit": unit,
            "left": a,
            "right": b,
            "difference": b - a,
            "ratio": ratio,
            "u_left": ua,
            "u_right": ub,
            "u_difference": math.hypot(ua, ub) if comparable else None,
            "u_ratio": abs(ratio) * math.hypot(ua / a, ub / b)
            if comparable and ratio is not None
            else None,
            "signal_label": c["signal_label"],
            "correspondence": c["correspondence"],
            "left_sample_id": samples[0].id,
            "right_sample_id": samples[1].id,
            "left_conditions": samples[0].conditions.model_dump(),
            "right_conditions": samples[1].conditions.model_dump(),
            "reference_conventions": [s.reference for s in samples],
            "uncertainty_method": "first-order propagation of explicitly independent standard uncertainties"
            if comparable
            else "unavailable: missing input uncertainty or no independence declaration",
            "assumptions": [
                "Signal correspondence is explicitly supplied, not inferred from matching peak order.",
                "Statistical uncertainty excludes unquantified reference, preparation and acquisition effects.",
            ],
            "warnings": warnings,
        }
        if any(not s.reference.strip() for s in samples):
            result["warnings"].append("One or both reference conventions are unspecified.")
        if not comparable:
            result["warnings"].append("Comparison uncertainty is unavailable, not zero.")
        return service._analysis(
            p, "comparison", c["name"], [left.id, right.id, *[s.id for s in samples]], c, result
        ), []
    if op == "dept":
        carbon = service._frequency(p, c["carbon_spectrum_id"])
        dept = service._frequency(p, c["dept_spectrum_id"])
        if carbon.id == dept.id or carbon.nucleus != "13C" or dept.nucleus != "13C":
            raise NmrError(
                "DEPT_NUCLEUS",
                "Select distinct 13C and DEPT-135 carbon spectra with explicit nuclei.",
            )
        cp = n.detect_peaks(carbon.axis, carbon.real, c["carbon_prominence"])
        dp = sorted(
            n.detect_peaks(dept.axis, dept.real, c["dept_prominence"]), key=lambda p: p["ppm"]
        )
        if len(cp) > 4096 or len(dp) > 4096:
            raise NmrError(
                "PEAK_LIMIT",
                "Increase the explicit prominence; DEPT matching is limited to 4096 peaks per spectrum.",
            )
        positions = [p["ppm"] for p in dp]
        carbon_positions = sorted(p["ppm"] for p in cp)
        reverse_counts = {
            peak["ppm"]: bisect_right(carbon_positions, peak["ppm"] + c["tolerance_ppm"])
            - bisect_left(carbon_positions, peak["ppm"] - c["tolerance_ppm"])
            for peak in dp
        }
        rows = []
        for peak in cp:
            hits = dp[
                bisect_left(positions, peak["ppm"] - c["tolerance_ppm"]) : bisect_right(
                    positions, peak["ppm"] + c["tolerance_ppm"]
                )
            ]
            if len(hits) == 1 and reverse_counts[hits[0]["ppm"]] == 1:
                match = hits[0]
                positive = match["intensity"] > 0
                if c["reference_convention"] == "negative_ch_ch3":
                    positive = not positive
                interpretation = "CH_or_CH3" if positive else "CH2"
            else:
                match = None
                interpretation = "no_DEPT_signal" if not hits else "ambiguous"
            rows.append(
                {
                    "carbon_ppm": peak["ppm"],
                    "dept_ppm": match["ppm"] if match else None,
                    "dept_intensity": match["intensity"] if match else None,
                    "interpretation": interpretation,
                    "matched_candidates": len(hits),
                    "competing_carbon_candidates": max(
                        (reverse_counts[h["ppm"]] for h in hits), default=0
                    ),
                }
            )
        result = {
            "rows": rows,
            "reference_convention": c["reference_convention"],
            "tolerance_ppm": c["tolerance_ppm"],
            "reference": c["reference"],
            "assumptions": [
                "The supplied spectra concern the same sample or an explicitly justified reference.",
                "DEPT-135 polarity convention is user-declared and must be independently checked.",
            ],
            "warnings": [
                "Absent DEPT signal alone does not establish a quaternary carbon; sensitivity and overlap matter.",
                "Matching produces proposed evidence, not a confirmed structural assignment.",
            ],
        }
        return service._analysis(p, "dept", c["name"], [carbon.id, dept.id], c, result), []
    return None


def extend_yield(p, c, result, a, b):
    recovered_id = c.get("recovered_integral_id")
    extra_sources = []
    recovered = None
    if bool(recovered_id) != (c.get("recovered_protons") is not None):
        raise NmrError(
            "RECOVERY_INPUT", "Recovered material requires both an integral and its proton count."
        )
    if recovered_id:
        recovered = require(p.integrals, recovered_id, "Recovered-material integral")
        if recovered.spectrum_id != a.spectrum_id:
            raise NmrError(
                "DIFFERENT_SPECTRA",
                "Recovered material and standard require one acquired spectrum.",
            )
        for other in (a, b):
            if max(other.lower, recovered.lower) < min(other.upper, recovered.upper):
                raise NmrError("OVERLAP", "Recovered material overlaps another quantified region.")
        rr = n.calculate_yield(
            recovered.area,
            b.area,
            c["recovered_protons"],
            c["standard_protons"],
            c["standard_mol"],
            c["limiting_mol"],
            1.0,
        )
        result["recovered_percent"] = rr["yield_percent"]
        result["mass_balance_percent"] = result["yield_percent"] + result["recovered_percent"]
        extra_sources.append(recovered.id)
    shared = [c.get(k) for k in ("u_standard_area", "u_standard_mol", "u_limiting_mol")]
    product_u = c.get("u_product_area")
    recovery_u = c.get("u_recovered_area")
    known = all(x is not None for x in shared)
    common = (
        sum((x / v) ** 2 for x, v in zip(shared, (b.area, c["standard_mol"], c["limiting_mol"])))
        if known
        else None
    )
    if known and product_u is not None:
        result["u_yield_percent"] = result["yield_percent"] * math.sqrt(
            (product_u / a.area) ** 2 + common
        )
    if known and recovery_u is not None and recovered is not None:
        result["u_recovered_percent"] = result["recovered_percent"] * math.sqrt(
            (recovery_u / recovered.area) ** 2 + common
        )
    if known and product_u is not None and recovered is not None and recovery_u is not None:
        result["u_mass_balance_percent"] = math.sqrt(
            (result["yield_percent"] * product_u / a.area) ** 2
            + (result["recovered_percent"] * recovery_u / recovered.area) ** 2
            + result["mass_balance_percent"] ** 2 * common
        )
    result["uncertainty_method"] = (
        "first-order propagation; supplied area/amount errors independent; shared standard/amount covariance retained for total"
        if known and product_u is not None
        else "unavailable: supply all applicable area and amount standard uncertainties"
    )
    result["assumptions"] += [
        "Unspecified input uncertainty remains unavailable; purity/acquisition/model systematics are not inferred."
    ]
    if result.get("mass_balance_percent", 0) > 100:
        result["assumptions"].append(
            "Product plus recovered material exceeds 100%; review assumptions and integration without clipping the result."
        )
    return extra_sources
