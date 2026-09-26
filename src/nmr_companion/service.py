from __future__ import annotations
import csv
import hashlib
import sqlite3
from io import BytesIO, StringIO
from pathlib import PurePosixPath
import zipfile

import numpy as np
from . import numerics as n
from pydantic import ValidationError
from .commands import COMMAND
from .errors import NmrError
from .models import Analysis, Artifact, Assignment, Grid, Integral, Source, Spectrum, Table
from .store import Store, canonical_json, identifier


class Service:
    def __init__(self, path):
        self.store = Store(path)

    def create(self, name):
        return self.store.create(name)

    def read(self, revision=None):
        return self.store.read(revision)

    @staticmethod
    def invalidate(project, changed):
        pending = set(changed)
        while pending:
            next_ids = set()
            from .evidence_models import DERIVED_COLLECTIONS

            derived = [*project.analyses.values(), *project.assignments.values()]
            for collection in DERIVED_COLLECTIONS:
                derived.extend(getattr(project, collection).values())
            for item in derived:
                if item.state == "current" and pending.intersection(item.source_versions):
                    item.state = "stale"
                    item.version += 1
                    next_ids.add(item.id)
            pending = next_ids

    def apply(self, expected_revision: int, request_id: str, command: dict):
        try:
            command = COMMAND.validate_python(command).model_dump(mode="json")
            # Preserve fingerprints of legacy commands when all additive fields are absent.
            additions = {
                "import": ("bruker_processing_numbers",),
                "assign": ("sample_id", "candidate_id", "atom_ids"),
                "yield": (
                    "recovered_integral_id",
                    "recovered_protons",
                    "u_product_area",
                    "u_standard_area",
                    "u_recovered_area",
                    "u_standard_mol",
                    "u_limiting_mol",
                ),
            }
            for key in additions.get(command["op"], ()):
                if command.get(key) is None or command.get(key) == []:
                    command.pop(key, None)
            if (
                not isinstance(expected_revision, int)
                or isinstance(expected_revision, bool)
                or expected_revision < 0
            ):
                raise NmrError(
                    "INVALID_ARGUMENT", "Expected revision must be a nonnegative integer."
                )
            from .models import Receipt

            Receipt(
                request_id=request_id,
                operation=command["op"],
                project_id="validation",
                revision=expected_revision,
            )
            return self.store.mutate(
                expected_revision, request_id, command, lambda p, db: self._execute(p, db, command)
            )
        except ValidationError as exc:
            issue = exc.errors(include_input=False)[0]
            location = ".".join(map(str, issue["loc"]))
            raise NmrError("INVALID_ARGUMENT", f"{location}: {issue['msg']}") from exc

    def _execute(self, p, db, c):
        op = c["op"]
        from .evidence import execute

        extended = execute(self, p, db, c)
        if extended is not None:
            return extended
        if op == "import":
            from .formats import load_input

            options = (
                {"bruker_processing_numbers": c["bruker_processing_numbers"]}
                if c.get("bruker_processing_numbers") is not None
                else {}
            )
            bundle = load_input(c["path"], **options)
            sources = {}
            for original in bundle["originals"]:
                name = original["name"].replace("\\", "/")
                if PurePosixPath(name).is_absolute() or ".." in PurePosixPath(name).parts:
                    raise NmrError("UNSAFE_NAME", "Original source name is unsafe.")
                digest = self.store.preserve_original(db, original["data"])
                if digest in p.sources:
                    if name not in p.sources[digest].names:
                        p.sources[digest].names.append(name)
                else:
                    p.sources[digest] = Source(
                        sha256=digest, name=name, names=[name], size=len(original["data"])
                    )
                sources[name] = digest
            ids = []
            for collection, key, cls, prefix in (
                (p.spectra, "spectra", Spectrum, "spectrum"),
                (p.grids, "grids", Grid, "grid"),
                (p.tables, "tables", Table, "table"),
            ):
                for data in bundle.get(key, []):
                    name = data.get("metadata", {}).get("source_name", data["name"])
                    if name not in sources and "members/" + name in sources:
                        name = "members/" + name
                    if name not in sources:
                        raise NmrError(
                            "SOURCE_BINDING", "Imported object has no matching original source."
                        )
                    explicit_sources = data.pop("source_names", None)
                    dependencies = [name]
                    if explicit_sources is not None:
                        for dependency in explicit_sources:
                            dependency = dependency.replace("\\", "/")
                            if dependency not in sources and "members/" + dependency in sources:
                                dependency = "members/" + dependency
                            if dependency not in sources:
                                raise NmrError(
                                    "SOURCE_BINDING", "A processed data dependency is missing."
                                )
                            dependencies.append(dependency)
                    source_path = PurePosixPath(name)
                    if data.get("metadata", {}).get("format") == "bruker":
                        if source_path.name == "fid":
                            dependencies.append(str(source_path.with_name("acqus")))
                        elif source_path.name == "1r":
                            dependencies.extend(
                                [
                                    str(source_path.with_name("procs")),
                                    str(source_path.with_name("1i")),
                                    str(source_path.parent.parent.parent / "acqus"),
                                ]
                            )
                    bound = list(dict.fromkeys(sources[n] for n in dependencies if n in sources))
                    obj = cls(id=identifier(prefix), source_ids=bound, **data)
                    collection[obj.id] = obj
                    ids.append(obj.id)
            if not ids:
                raise NmrError("EMPTY_IMPORT", "No supported data was found.")
            return ids, bundle["warnings"]
        if op == "demo":
            if p.spectra or p.tables:
                raise NmrError(
                    "DEMO_REQUIRES_EMPTY", "Use an empty project for the synthetic demonstration."
                )
            axis = np.linspace(0, 10, 2049)

            def peak(mu):
                return np.exp(-0.5 * ((axis - mu) / 0.045) ** 2)

            organic = Spectrum(
                id=identifier("spectrum"),
                name="Synthetic organic mixture",
                axis=axis.tolist(),
                real=(3 * peak(2) + 2 * peak(4) + 6 * peak(7)).tolist(),
                axis_unit="ppm",
                domain="frequency",
                nucleus="1H",
                metadata={"synthetic": True, "purpose": "software demonstration"},
            )
            p.spectra[organic.id] = organic
            table = Table(
                id=identifier("table"), name="Synthetic delays", columns=["delay_ms"], rows=[]
            )
            ids = [organic.id]
            for i, time_s in enumerate([0.01, 0.05, 0.15, 0.3, 0.6, 1.0, 1.6, 2.5]):
                s = Spectrum(
                    id=identifier("spectrum"),
                    name=f"Synthetic T1 trace {i + 1}",
                    axis=axis.tolist(),
                    real=((1 - 2 * np.exp(-time_s / 0.5)) * peak(4)).tolist(),
                    axis_unit="ppm",
                    domain="frequency",
                    nucleus="1H",
                    metadata={
                        "synthetic": True,
                        "delay_s": time_s,
                        "purpose": "software demonstration",
                    },
                )
                p.spectra[s.id] = s
                table.rows.append({"delay_ms": str(time_s * 1000)})
                ids.append(s.id)
            p.tables[table.id] = table
            return ids + [table.id], [
                "Synthetic demonstration only; these are not experimental results."
            ]
        if op == "integrate":
            s = self._frequency(p, c["spectrum_id"])
            result = n.integrate(s.axis, s.real, c["lower"], c["upper"])
            old = p.integrals.get(c["integral_id"]) if c["integral_id"] else None
            if c["integral_id"] and old is None:
                raise NmrError("NOT_FOUND", "Integral does not exist.")
            obj = Integral(
                id=old.id if old else identifier("integral"),
                version=old.version + 1 if old else 1,
                spectrum_id=s.id,
                spectrum_version=s.version,
                name=c["name"],
                lower=c["lower"],
                upper=c["upper"],
                area=result["area"],
            )
            p.integrals[obj.id] = obj
            self.invalidate(p, [obj.id])
            return [obj.id], []
        if op == "process":
            s = p.spectra.get(c["spectrum_id"])
            if s is None:
                raise NmrError("NOT_FOUND", "Spectrum does not exist.")
            method = c["method"]
            if method == "fft":
                if s.domain != "time":
                    raise NmrError(
                        "ALREADY_PROCESSED", "Fourier transformation requires a time-domain FID."
                    )
                required = ["dwell_s", "obs_mhz", "carrier_ppm"]
                if any(s.metadata.get(key) is None for key in required):
                    raise NmrError(
                        "MISSING_SAMPLING", "FFT needs measured dwell_s, obs_mhz and carrier_ppm."
                    )
                result = n.process_fid(
                    s.real,
                    s.imag,
                    **{key: s.metadata[key] for key in required},
                    zero_fill_factor=c["zero_fill_factor"],
                    line_broadening_hz=c["line_broadening_hz"],
                )
                s.axis, s.real, s.imag = result["axis"], result["real"], result["imag"]
                s.domain, s.axis_unit = "frequency", "ppm"
            else:
                self._frequency(p, s.id)
                if method == "phase":
                    if s.imag is None:
                        raise NmrError(
                            "NO_COMPLEX_DATA", "Phase correction requires preserved imaginary data."
                        )
                    result = n.phase(
                        s.axis, s.real, s.imag, c["ph0_deg"], c["ph1_deg"], c["pivot_ppm"]
                    )
                    s.real, s.imag = result["real"], result["imag"]
                elif method == "baseline":
                    result = n.baseline(s.axis, s.real, c["regions"])
                    s.real = result["real"]
                else:
                    shift = c["reference_shift_ppm"]
                    s.axis = [x + shift for x in s.axis]
                    result = {"metadata": {"reference_shift_ppm": shift}}
                    for integral in p.integrals.values():
                        if integral.spectrum_id == s.id:
                            integral.lower += shift
                            integral.upper += shift
            s.version += 1
            s.history.append(
                {"operation": method, "parameters": c, "details": result.get("metadata", {})}
            )
            changed = [s.id]
            for integral in p.integrals.values():
                if integral.spectrum_id == s.id:
                    integral.area = n.integrate(s.axis, s.real, integral.lower, integral.upper)[
                        "area"
                    ]
                    integral.spectrum_version = s.version
                    integral.version += 1
                    changed.append(integral.id)
            self.invalidate(p, changed)
            return [s.id], []
        if op == "peaks":
            s = self._frequency(p, c["spectrum_id"])
            result = {
                "peaks": n.detect_peaks(s.axis, s.real, c["prominence"]),
                "method": "signed local extrema with explicit prominence",
            }
            return self._analysis(p, "peaks", "Peak candidates", [s.id], c, result), []
        if op == "yield":
            a, b = (
                p.integrals.get(c[key]) for key in ("product_integral_id", "standard_integral_id")
            )
            if a is None or b is None:
                raise NmrError("NOT_FOUND", "Select existing product and standard integrals.")
            if a.spectrum_id != b.spectrum_id:
                raise NmrError(
                    "DIFFERENT_SPECTRA", "Internal-standard yield requires one acquired spectrum."
                )
            if max(a.lower, b.lower) < min(a.upper, b.upper):
                raise NmrError("OVERLAP", "Product and standard regions overlap.")
            result = n.calculate_yield(
                a.area,
                b.area,
                c["product_protons"],
                c["standard_protons"],
                c["standard_mol"],
                c["limiting_mol"],
                c["stoichiometric_factor"],
            )
            from .evidence import extend_yield
            from .models import YieldResult

            try:
                canonical_json(result)
                YieldResult.model_validate(result)
            except (ValueError, TypeError) as exc:
                raise NmrError(
                    "OUTPUT_VALIDATION", "Yield backend returned an invalid scientific result."
                ) from exc

            extra_sources = extend_yield(p, c, result, a, b)
            return self._analysis(
                p, "yield", c["name"], [a.id, b.id, *extra_sources], c, result
            ), []
        if op == "fit":
            table = p.tables.get(c["table_id"])
            if table is None:
                raise NmrError("NOT_FOUND", "Delay table does not exist.")
            if len(c["row_indices"]) != len(c["spectrum_ids"]):
                raise NmrError("SERIES_MAPPING", "Each spectrum needs an explicit table row.")
            if len(set(c["row_indices"])) != len(c["row_indices"]) or len(
                set(c["spectrum_ids"])
            ) != len(c["spectrum_ids"]):
                raise NmrError(
                    "SERIES_MAPPING",
                    "Rows and spectra may each be mapped only once; replicated delays use separate rows.",
                )
            if any(i < 0 or i >= len(table.rows) for i in c["row_indices"]):
                raise NmrError("SERIES_MAPPING", "A row index is outside the table.")
            if len(set(c["excluded_indices"])) != len(c["excluded_indices"]) or any(
                i < 0 or i >= len(c["spectrum_ids"]) for i in c["excluded_indices"]
            ):
                raise NmrError(
                    "SERIES_MAPPING", "Exclusions must identify unique mapped positions."
                )
            times, signals, sigma, mapping = [], [], [], []
            for pos, (sid, row_index) in enumerate(zip(c["spectrum_ids"], c["row_indices"])):
                s = self._frequency(p, sid)
                row = table.rows[row_index]
                try:
                    t = float(row[c["delay_column"]])
                    sig = float(row[c["sigma_column"]]) if c["sigma_column"] else None
                except (KeyError, ValueError, TypeError) as exc:
                    raise NmrError(
                        "TABLE_VALUE", "A mapped delay or sigma value is missing or nonnumeric."
                    ) from exc
                area = n.integrate(s.axis, s.real, c["lower"], c["upper"])["area"]
                excluded = pos in c["excluded_indices"]
                mapping.append(
                    {
                        "spectrum_id": sid,
                        "row_index": row_index,
                        "delay": t,
                        "area": area,
                        "excluded": excluded,
                    }
                )
                if not excluded:
                    times.append(t)
                    signals.append(area)
                    if sig is not None:
                        sigma.append(sig)
            result = n.fit_relaxation(
                times,
                signals,
                c["time_unit"],
                c["model"],
                sigma=sigma or None,
                time_basis=c["time_basis"],
                delay_multiplier=c["delay_multiplier"],
            )
            nuclei = {p.spectra[sid].nucleus for sid in c["spectrum_ids"] if p.spectra[sid].nucleus}
            if len(nuclei) > 1:
                raise NmrError("SERIES_NUCLEUS", "Relaxation traces must observe one nucleus.")
            result["assumptions"] = [
                "All mapped traces have comparable acquisition and intensity scales.",
                "The shared region represents the same assigned signal in every trace.",
                "Reported standard uncertainty excludes acquisition and preparation systematics.",
            ]
            result["mapping"] = mapping
            result["purpose"] = c["purpose"]
            if c["purpose"] == "quick_check":
                result["warnings"] = result.get("warnings", []) + [
                    "Preliminary quick check; not an analysis-quality acquisition."
                ]
            return self._analysis(
                p, "relaxation", c["name"], [table.id, *c["spectrum_ids"]], c, result
            ), result.get("warnings", [])
        if op == "assign":
            from .evidence import versions, cycle, require

            evidence = list(c["evidence_ids"])
            if c.get("sample_id"):
                require(p.samples, c["sample_id"], "Sample")
                evidence.append(c["sample_id"])
            if c.get("candidate_id"):
                candidate = require(p.structures, c["candidate_id"], "Candidate structure")
                if c.get("sample_id") != candidate.sample_id:
                    raise NmrError(
                        "ASSIGNMENT_SAMPLE",
                        "Candidate and assignment must refer to the same explicit sample.",
                    )
                if not set(c.get("atom_ids", [])).issubset({a.id for a in candidate.atoms}):
                    raise NmrError(
                        "ASSIGNMENT_ATOM", "Assignment atoms must exist in the selected structure."
                    )
                evidence.append(candidate.id)
            elif c.get("atom_ids"):
                raise NmrError(
                    "ASSIGNMENT_ATOM", "Atom identities require a selected candidate structure."
                )
            sources = versions(p, evidence)
            old = p.assignments.get(c["assignment_id"]) if c["assignment_id"] else None
            if c["assignment_id"] and old is None:
                raise NmrError("NOT_FOUND", "Assignment does not exist.")
            if old:
                cycle(p, old.id, sources)
            if any(getattr(p.object(oid), "state", "current") == "stale" for oid in sources):
                raise NmrError("STALE_EVIDENCE", "Refresh stale evidence before using it.")
            a = Assignment(
                id=old.id if old else identifier("assignment"),
                version=old.version + 1 if old else 1,
                source_versions=sources,
                sample_id=c.get("sample_id"),
                candidate_id=c.get("candidate_id"),
                atom_ids=c.get("atom_ids", []),
                **{
                    key: c[key]
                    for key in (
                        "sample",
                        "atom",
                        "candidate",
                        "observation",
                        "evidence_ids",
                        "status",
                    )
                },
            )
            p.assignments[a.id] = a
            self.invalidate(p, [a.id])
            return [a.id], []
        if op == "remove":
            oid = c["object_id"]
            p.object(oid)
            # Preserve acquired spectra, matrices and tables. Derived annotations are removable.
            found = False
            for collection in (
                p.integrals,
                p.analyses,
                p.assignments,
                p.structures,
                p.crosspeaks,
                p.peaklabels,
                p.annotations,
            ):
                if oid in collection:
                    del collection[oid]
                    found = True
            if not found:
                raise NmrError(
                    "SOURCE_IMMUTABLE", "Imported source objects cannot be deleted in this alpha."
                )
            self.invalidate(p, [oid])
            return [oid], []
        raise NmrError("UNSUPPORTED_OPERATION", "Unknown operation.")

    @staticmethod
    def _frequency(p, sid):
        s = p.spectra.get(sid)
        if s is None:
            raise NmrError("NOT_FOUND", "Spectrum does not exist.")
        if s.domain != "frequency":
            raise NmrError(
                "REQUIRES_FREQUENCY", "This operation requires a frequency-domain spectrum."
            )
        return s

    @staticmethod
    def _analysis(p, kind, name, sources, parameters, result):
        # Explicitly reject nonfinite backend results before they can be committed.
        try:
            canonical_json(result)
        except (ValueError, TypeError) as exc:
            raise NmrError(
                "OUTPUT_VALIDATION", "Numerical backend returned invalid JSON values."
            ) from exc
        if kind == "yield" and not isinstance(result.get("yield_percent"), (int, float)):
            raise NmrError("OUTPUT_VALIDATION", "Yield backend returned an invalid result.")
        if kind == "relaxation":
            required = {
                "model",
                "status",
                "T_s",
                "u_T_s",
                "uncertainty_method",
                "warnings",
                "time_s",
                "signals",
                "predicted",
                "residuals",
                "parameters",
                "diagnostics",
            }
            if not required.issubset(result):
                raise NmrError("OUTPUT_VALIDATION", "Fit backend returned an incomplete result.")
        obj = Analysis(
            id=identifier("analysis"),
            name=name,
            kind=kind,
            source_versions={sid: p.object(sid).version for sid in sources},
            parameters=parameters,
            result=result,
        )
        p.analyses[obj.id] = obj
        return [obj.id]

    def export(self, revision: int) -> Artifact:
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            p = self.store.read_from(db, revision)
            output = BytesIO()
            entries = {}

            def add(archive, name, value):
                data = value.encode("utf-8") if isinstance(value, str) else value
                archive.writestr(name, data)
                entries[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

            with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                add(archive, "project.json", p.model_dump_json(indent=2))
                add(archive, "project.nmrproj", self._snapshot_database(db, p.revision))
                for digest in p.sources:
                    row = db.execute(
                        "SELECT data FROM originals WHERE sha256=?", (digest,)
                    ).fetchone()
                    if row is None or hashlib.sha256(row[0]).hexdigest() != digest:
                        raise NmrError(
                            "SOURCE_INTEGRITY", "An original source is missing or corrupt."
                        )
                    add(archive, f"originals/{digest}", row[0])
                for s in p.spectra.values():
                    buffer = StringIO(newline="")
                    writer = csv.writer(buffer)
                    writer.writerow([s.axis_unit, "real", "imag", "revision", "spectrum_id"])
                    for i, x in enumerate(s.axis):
                        writer.writerow(
                            [
                                x,
                                s.real[i],
                                s.imag[i] if s.imag is not None else "",
                                p.revision,
                                s.id,
                            ]
                        )
                    add(archive, f"spectra/{s.id}.csv", buffer.getvalue())
                from .exporting import export_entries

                for entry_name, entry_data in export_entries(p, db).items():
                    add(archive, entry_name, entry_data)
                add(
                    archive,
                    "manifest.json",
                    canonical_json(
                        {
                            "schema_version": 1,
                            "project_id": p.id,
                            "revision": p.revision,
                            "files": entries,
                            "claim": "Files generated from the named revision; host delivery is separate.",
                        }
                    ),
                )
            data = output.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            artifact = Artifact(
                id=identifier("artifact"),
                revision=p.revision,
                name=f"nmr-project-r{p.revision}.zip",
                media_type="application/zip",
                size=len(data),
                sha256=digest,
                uri="",
            )
            artifact.uri = f"nmr://artifacts/{artifact.id}"
            db.execute(
                "INSERT INTO artifacts VALUES(?,?,?)",
                (artifact.id, artifact.model_dump_json(), data),
            )
            db.commit()
            return artifact

    @staticmethod
    def _snapshot_database(db, revision):
        """An actual reopenable project, excluding later revisions and recursive exports."""
        import json

        snapshot = sqlite3.connect(":memory:")
        try:
            for table in ("snapshots", "requests", "originals", "artifacts"):
                sql = db.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
                ).fetchone()[0]
                snapshot.execute(sql)
            originals = set()
            for rev, payload in db.execute(
                "SELECT revision,payload FROM snapshots WHERE revision<=?", (revision,)
            ):
                snapshot.execute("INSERT INTO snapshots VALUES(?,?)", (rev, payload))
                originals.update(json.loads(payload)["sources"])
            for request, fingerprint, receipt in db.execute(
                "SELECT id,fingerprint,receipt FROM requests"
            ):
                if json.loads(receipt)["revision"] <= revision:
                    snapshot.execute(
                        "INSERT INTO requests VALUES(?,?,?)", (request, fingerprint, receipt)
                    )
            for digest in originals:
                row = db.execute("SELECT data FROM originals WHERE sha256=?", (digest,)).fetchone()
                if row is None or hashlib.sha256(row[0]).hexdigest() != digest:
                    raise NmrError("SOURCE_INTEGRITY", "An original source is missing or corrupt.")
                snapshot.execute("INSERT INTO originals VALUES(?,?)", (digest, row[0]))
            snapshot.execute("PRAGMA user_version=2")
            snapshot.commit()
            return snapshot.serialize()
        finally:
            snapshot.close()
