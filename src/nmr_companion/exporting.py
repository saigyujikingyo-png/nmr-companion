"""Revision-bound scientific tables and figures; originals remain authoritative."""

from base64 import b64encode
import csv
from html import escape
from io import BytesIO, StringIO
import json
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .errors import NmrError
from .media import reference_png
from .store import canonical_json

W, H = 1200, 720
INK, TEAL, RED = "#173043", "#097c86", "#b13c70"


class Figure:
    def __init__(self, title, subtitle):
        self.image = Image.new("RGB", (W, H), "white")
        self.draw = ImageDraw.Draw(self.image)
        self.svg = ['<rect width="1200" height="720" fill="white"/>']
        self.text(40, 22, title[:130], size=21)
        self.text(40, 54, subtitle[:180], size=13)

    def text(self, x, y, value, *, size=14, color=INK):
        value = str(value)
        self.draw.text((x, y), value, font=ImageFont.load_default(size=size), fill=color)
        self.svg.append(
            f'<text x="{x:.3f}" y="{y + size:.3f}" font-size="{size}" fill="{color}">{escape(value)}</text>'
        )

    def line(self, points, color=INK, width=2):
        if len(points) < 2:
            return
        self.draw.line(points, fill=color, width=width)
        pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in points)
        self.svg.append(
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{width}"/>'
        )

    def rect(self, box, color=INK, fill=None):
        x1, y1, x2, y2 = box
        self.draw.rectangle(box, outline=color, fill=fill, width=2)
        self.svg.append(
            f'<rect x="{x1:.3f}" y="{y1:.3f}" width="{x2 - x1:.3f}" height="{y2 - y1:.3f}" fill="{fill or "none"}" stroke="{color}" stroke-width="2"/>'
        )

    def paste(self, image, box):
        x, y, width, height = box
        resized = image.resize((width, height), Image.Resampling.NEAREST)
        self.image.paste(resized, (x, y))
        data = BytesIO()
        resized.save(data, format="PNG")
        encoded = b64encode(data.getvalue()).decode("ascii")
        self.svg.append(
            f'<image x="{x}" y="{y}" width="{width}" height="{height}" href="data:image/png;base64,{encoded}"/>'
        )

    def outputs(self):
        output = BytesIO()
        self.image.save(output, format="PNG")
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720"><g font-family="Arial,sans-serif">'
            + "".join(self.svg)
            + "</g></svg>"
        )
        return {".png": output.getvalue(), ".svg": svg}


def provenance(p, oid, state="current"):
    pending, seen, acquired = [oid], set(), set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in p.spectra or current in p.grids or current in p.tables:
            acquired.add(current)
        else:
            try:
                obj = p.object(current)
            except NmrError:
                continue  # Removed evidence stays stale; it cannot acquire a new provenance.
            pending.extend(getattr(obj, "source_versions", {}))
    associated = [s for s in p.samples.values() if acquired.intersection(s.object_ids)]
    roles = ", ".join(f"{s.name} ({s.role})" for s in associated) or "sample role unspecified"
    return f"revision {p.revision} | {oid} | {state} | {roles}"


def axes(fig, xs, ys, xlabel, ylabel, box=(95, 100, 1135, 600), reverse=False):
    x1, y1, x2, y2 = box
    xmin, xmax = float(min(xs)), float(max(xs))
    ymin, ymax = float(min(0, min(ys))), float(max(0, max(ys)))
    span = ymax - ymin or 1.0
    ymin -= span * 0.08
    ymax += span * 0.12
    xspan = xmax - xmin or 1.0

    def px(x):
        v = (float(x) - xmin) / xspan
        return x1 + (1 - v if reverse else v) * (x2 - x1)

    def py(y):
        return y2 - (float(y) - ymin) / (ymax - ymin) * (y2 - y1)

    fig.line([(x1, y1), (x1, y2), (x2, y2)], "#7f909d", 1)
    fig.line([(x1, py(0)), (x2, py(0))], "#d2dde2", 1)
    for x in np.linspace(xmin, xmax, 7):
        fig.text(px(x) - 15, y2 + 8, f"{x:.4g}", size=12)
    for y in np.linspace(ymin, ymax, 5):
        fig.text(8, py(y) - 8, f"{y:.4g}", size=11)
    fig.text(x1 + (x2 - x1) / 2 - 40, y2 + 33, xlabel)
    fig.text(x1, y1 - 22, ylabel, size=12)
    return px, py


def extrema_indices(y, bins=2000):
    values = np.asarray(y)
    keep = {0, len(values) - 1}
    for idx in np.array_split(np.arange(len(values)), min(len(values), bins)):
        keep.update((int(idx[np.argmin(values[idx])]), int(idx[np.argmax(values[idx])])))
    return sorted(keep)


def spectrum_figure(p, s):
    fig = Figure(s.name, provenance(p, s.id))
    px, py = axes(
        fig,
        s.axis,
        s.real,
        s.axis_unit,
        "Intensity (arbitrary units)",
        reverse=s.axis_unit == "ppm",
    )
    for i in p.integrals.values():
        if i.spectrum_id == s.id:
            a, b = sorted((px(i.lower), px(i.upper)))
            fig.rect((a, 105, b, 595), "#dfa221")
            fig.text(a, 108, f"{i.name[:20]}: {i.area:.5g}", size=11, color="#a56c00")
    fig.line([(px(s.axis[i]), py(s.real[i])) for i in extrema_indices(s.real)], TEAL, 1)
    for label in p.peaklabels.values():
        if label.spectrum_id == s.id:
            fig.line(
                [
                    (px(label.ppm), py(label.intensity)),
                    (px(label.ppm), max(130, py(label.intensity) - 30)),
                ],
                RED,
                1,
            )
            fig.text(
                px(label.ppm) + 3,
                max(110, py(label.intensity) - 48),
                f"{label.label[:18]} {label.ppm:.4g} [{label.state}]",
                size=11,
                color=RED,
            )
    fig.text(
        40,
        680,
        "Signed full-resolution numerical arrays are in spectra/*.csv; display retains bucket extrema.",
        size=12,
    )
    return fig


def grid_figure(p, g):
    fig = Figure(g.name, provenance(p, g.id))
    xmin, xmax = min(g.x), max(g.x)
    ymin, ymax = min(g.y), max(g.y)
    cols, rows = 520, 250
    ix = np.minimum(cols - 1, ((xmax - np.asarray(g.x)) / (xmax - xmin) * cols).astype(int))
    iy = np.minimum(rows - 1, ((np.asarray(g.y) - ymin) / (ymax - ymin) * rows).astype(int))
    indices = (iy[:, None] * cols + ix[None, :]).ravel()
    pos = np.zeros(rows * cols)
    neg = np.zeros(rows * cols)
    z = np.asarray(g.z).ravel()
    np.maximum.at(pos, indices, np.maximum(z, 0))
    np.maximum.at(neg, indices, np.maximum(-z, 0))
    scale = max(float(pos.max()), float(neg.max())) or 1
    image = np.full((rows, cols * 2, 3), 255, dtype=np.uint8)
    # Two half-cells preserve positive and negative extrema in the same bin.
    for offset, values, color in ((0, pos, (9, 124, 134)), (1, neg, (177, 60, 112))):
        weight = np.sqrt(values / scale).reshape(rows, cols, 1)
        image[:, offset::2, :] = np.rint(255 * (1 - weight) + np.asarray(color) * weight).astype(
            np.uint8
        )
    fig.paste(Image.fromarray(image), (95, 100, 1040, 500))
    fig.rect((95, 100, 1135, 600), "#7f909d")

    def px(x):
        return 95 + (xmax - x) / (xmax - xmin) * 1040

    def py(y):
        return 100 + (y - ymin) / (ymax - ymin) * 500

    for x in np.linspace(xmin, xmax, 7):
        fig.text(px(x) - 15, 611, f"{x:.4g}", size=12)
    for y in np.linspace(ymin, ymax, 7):
        fig.text(18, py(y) - 5, f"{y:.4g}", size=12)
    fig.text(510, 641, f"x: {g.nuclei[0] or 'unknown'} (ppm)")
    fig.text(95, 79, f"y: {g.nuclei[1] or 'unknown'} (ppm), increasing downward", size=12)
    for c in p.crosspeaks.values():
        if c.grid_id == g.id:
            x, y = px(c.x_ppm), py(c.y_ppm)
            fig.line([(x - 5, y), (x + 5, y)], INK, 1)
            fig.line([(x, y - 5), (x, y + 5)], INK, 1)
            fig.text(x + 6, y + 3, f"{c.label[:18]} [{c.state}]", size=11)
    fig.text(
        40,
        680,
        "Teal: positive; magenta: negative. Separate extrema per display bin; square-root visual scale.",
        size=12,
    )
    return fig


def fit_figure(p, a):
    r = a.result
    fig = Figure(a.name, provenance(p, a.id, a.state))
    time = r["time_s"]
    signals = r["signals"]
    predicted = r["predicted"]
    residuals = r["residuals"]
    px, py = axes(
        fig,
        time,
        signals + (predicted or []),
        "Elapsed time (s)",
        "Signed integrated signal",
        box=(95, 110, 1135, 410),
    )
    if predicted:
        # Continuous curve of the declared model, not a new fit.
        q = r["parameters"]
        t = np.linspace(min(time), max(time), 500)
        y = (
            q["A"] - q["B"] * np.exp(-q["k_s_inverse"] * t)
            if r["model"] == "T1"
            else q["C"] + q["A"] * np.exp(-q["k_s_inverse"] * t)
        )
        fig.line([(px(x), py(v)) for x, v in zip(t, y)], TEAL, 2)
    for x, y in zip(time, signals):
        fig.rect((px(x) - 3, py(y) - 3, px(x) + 3, py(y) + 3), RED, RED)
    if residuals:
        rx, ry = axes(
            fig,
            time,
            residuals,
            "Elapsed time (s)",
            "Residual (observed - predicted)",
            box=(95, 500, 1135, 610),
        )
        for x, y in zip(time, residuals):
            fig.rect((rx(x) - 2, ry(y) - 2, rx(x) + 2, ry(y) + 2), RED, RED)
    fig.text(
        40, 669, f"{r['model']} | {r['status']} | T = {r['T_s']} s | u(T) = {r['u_T_s']} s", size=12
    )
    fig.text(
        40,
        692,
        "Standard uncertainty is conditional on the model; warnings, exclusions and trace mapping are in analysis JSON/CSV.",
        size=11,
    )
    return fig


def structure_figure(p, s):
    sample = p.samples[s.sample_id]
    fig = Figure(
        s.name, f"revision {p.revision} | {sample.name} ({sample.role}) | {s.status} | {s.state}"
    )
    xs = [a.x for a in s.atoms]
    ys = [a.y for a in s.atoms]
    span = max(max(xs) - min(xs), max(ys) - min(ys), 1)
    center = ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2)
    positions = {
        a.id: (600 + (a.x - center[0]) / span * 600, 345 + (a.y - center[1]) / span * 440)
        for a in s.atoms
    }
    for b in s.bonds:
        start, end = positions[b.a], positions[b.b]
        dx, dy = end[0] - start[0], end[1] - start[1]
        length = math.hypot(dx, dy) or 1
        nx, ny = -dy / length, dx / length
        if b.stereo in ("wedge", "hash"):
            for i in range(1, 13):
                f = i / 13
                x, y = start[0] + f * dx, start[1] + f * dy
                half = 7 * f
                if b.stereo == "wedge" or i % 2 == 0:
                    fig.line(
                        [(x - half * nx, y - half * ny), (x + half * nx, y + half * ny)],
                        INK,
                        3 if b.stereo == "wedge" else 1,
                    )
        else:
            orders = 1 if b.order == 1.5 else int(b.order)
            for offset in range(orders):
                shift = (offset - (orders - 1) / 2) * 5
                fig.line(
                    [
                        (start[0] + shift * nx, start[1] + shift * ny),
                        (end[0] + shift * nx, end[1] + shift * ny),
                    ],
                    INK,
                    2,
                )
            if b.order == 1.5 or b.stereo == "either":
                fig.text(
                    (start[0] + end[0]) / 2 + 4,
                    (start[1] + end[1]) / 2,
                    "aromatic" if b.order == 1.5 else "unspecified",
                    size=11,
                )
    for atom in s.atoms:
        x, y = positions[atom.id]
        fig.rect((x - 8, y - 5, x + 50, y + 36), "white", "white")
        fig.text(x, y, f"{atom.element} {atom.label[:20]}", size=17)
        if atom.stereo:
            fig.text(x, y + 23, atom.stereo[:40], size=11, color=RED)
    fig.text(40, 639, s.description[:150], size=12)
    fig.text(
        40,
        665,
        f"Alternative group: {s.alternative_group or 'none'} | Evidence: {', '.join(s.evidence_ids)}",
        size=11,
    )
    fig.text(
        40,
        691,
        "User-authored interpretation; atom/bond/stereochemistry records remain editable in the project.",
        size=12,
    )
    return fig


def csv_bytes(rows, fields=None):
    rows = list(rows)
    fields = fields or list(dict.fromkeys(k for r in rows for k in r))
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()

    def cell(v):
        if isinstance(v, (dict, list)):
            return canonical_json(v)
        # Text is spreadsheet-safe; exact text remains in project.json.
        if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")):
            return "'" + v
        return v

    writer.writerows({k: cell(v) for k, v in row.items()} for row in rows)
    return output.getvalue().encode("utf-8")


def export_entries(p, db):
    entries = {}

    def table_bytes(rows, fields=None):
        records = []
        for row in rows:
            if "project_id" in row or "revision" in row:
                raise NmrError("EXPORT_COLUMNS", "Source columns must be namespaced before export.")
            records.append({"project_id": p.id, "revision": p.revision, **row})
        columns = (
            list(dict.fromkeys(["project_id", "revision", *(fields or [])]))
            if fields is not None or not records
            else None
        )
        return csv_bytes(records, columns)

    def figure(oid, fig):
        for suffix, data in fig.outputs().items():
            entries[f"figures/{oid}{suffix}"] = data

    for s in p.spectra.values():
        figure(s.id, spectrum_figure(p, s))
    for g in p.grids.values():
        figure(g.id, grid_figure(p, g))
        entries[f"grids/{g.id}.csv"] = table_bytes(
            (
                {"x_ppm": x, "y_ppm": y, "intensity": g.z[j][i]}
                for j, y in enumerate(g.y)
                for i, x in enumerate(g.x)
            ),
            ["x_ppm", "y_ppm", "intensity"],
        )
    for name in (
        "samples",
        "structures",
        "crosspeaks",
        "peaklabels",
        "attachments",
        "annotations",
        "integrals",
        "assignments",
    ):
        entries[f"tables/{name}.csv"] = table_bytes(
            [v.model_dump(mode="json") for v in getattr(p, name).values()],
            list(type(next(iter(getattr(p, name).values()))).model_fields)
            if getattr(p, name)
            else ["id"],
        )
    for table in p.tables.values():
        entries[f"tables/{table.id}.csv"] = table_bytes(
            [{"source." + key: value for key, value in row.items()} for row in table.rows],
            ["source." + key for key in table.columns],
        )
    for a in p.analyses.values():
        entries[f"analyses/{a.id}.json"] = a.model_dump_json(indent=2)

        def analysis_table(rows):
            context = {
                "analysis_id": a.id,
                "state": a.state,
                "source_versions": a.source_versions,
                "sample_provenance": provenance(p, a.id, a.state),
            }
            records = [{**row, **context} for row in rows]
            if not records:
                # Keep an explicitly empty result attributable without inventing a peak.
                records = [{**context, "result_count": 0}]
            return table_bytes(records)

        rows = a.result.get("rows", a.result.get("peaks", a.result.get("integrals")))
        if rows is not None:
            entries[f"tables/{a.id}.csv"] = analysis_table(rows)
        elif a.kind == "relaxation":
            r = a.result
            figure(a.id, fit_figure(p, a))
            entries[f"tables/{a.id}.csv"] = analysis_table(
                [
                    {
                        "time_s": t,
                        "signal": r["signals"][i],
                        "predicted": r["predicted"][i] if r["predicted"] else None,
                        "residual": r["residuals"][i] if r["residuals"] else None,
                        "state": a.state,
                    }
                    for i, t in enumerate(r["time_s"])
                ]
            )
            entries[f"tables/{a.id}-mapping.csv"] = analysis_table(
                [
                    {
                        **row,
                        "original_delay_unit": a.parameters["time_unit"],
                        "time_basis": a.parameters["time_basis"],
                        "delay_multiplier": a.parameters.get("delay_multiplier"),
                        "purpose": r["purpose"],
                        "state": a.state,
                    }
                    for row in r["mapping"]
                ]
            )
        else:
            entries[f"tables/{a.id}.csv"] = analysis_table([a.result])
    for structure in p.structures.values():
        figure(structure.id, structure_figure(p, structure))
    coverage = []
    rendered = 0
    for attachment in p.attachments.values():
        row = db.execute(
            "SELECT data FROM originals WHERE sha256=?", (attachment.source_id,)
        ).fetchone()
        if row is None:
            raise NmrError("SOURCE_INTEGRITY", "Reference original is missing.")
        pages = {1, *[a.page for a in p.annotations.values() if a.attachment_id == attachment.id]}
        for page in sorted(pages):
            if rendered >= 32:
                coverage.append(
                    {
                        "attachment_id": attachment.id,
                        "page": page,
                        "preview": "omitted: 32-page export preview limit",
                    }
                )
                continue
            png = reference_png(row[0], attachment.media_type, page)
            with Image.open(BytesIO(png)) as image:
                fig = Figure(
                    attachment.name,
                    f"revision {p.revision} | {attachment.source_role} | {attachment.category} | page {page} | {attachment.state}",
                )
                scale = min(1040 / image.width, 535 / image.height)
                width, height = round(image.width * scale), round(image.height * scale)
                fig.paste(image, (80, 90, width, height))
            for a in p.annotations.values():
                if a.attachment_id == attachment.id and a.page == page:
                    x, y = 80 + a.x * width, 90 + a.y * height
                    fig.rect((x, y, x + a.width * width, y + a.height * height), RED)
                    fig.text(x, max(80, y - 18), f"{a.label[:40]} [{a.state}]", size=12, color=RED)
            fig.text(
                40,
                675,
                "Reference annotation only; image readings are not full-resolution numerical spectra.",
                size=12,
            )
            figure(f"{attachment.id}-page-{page}", fig)
            coverage.append({"attachment_id": attachment.id, "page": page, "preview": "rendered"})
            rendered += 1
    entries["reference-preview-coverage.json"] = json.dumps(coverage, indent=2)
    entries["READ_ME.txt"] = (
        f"NMR Companion revision {p.revision}\n"
        "project.nmrproj reopens with complete revision history up to this revision.\n"
        "Originals are stored by SHA-256; project.json binds filenames and source IDs.\n"
        "Figures use original numerical observations and are labeled by revision/state.\n"
        "Grid signs use separate display extrema; no display reduction alters scientific arrays.\n"
        "Samples distinguish own, reference, synthetic and unknown roles. Do not infer provenance.\n"
        "Image/PDF readings remain annotations, not numeric spectra. See preview coverage JSON.\n"
        "Stale interpretations are retained and labeled; refresh before scientific use.\n"
        "CSV text starting spreadsheet formulas is prefixed with an apostrophe; exact text stays in JSON.\n"
        "Statistical uncertainties are conditional; unavailable does not mean zero.\n"
    )
    return entries
