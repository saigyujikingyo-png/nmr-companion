"""Small dependency-free SVG renderer. Processing always uses the complete arrays."""

from html import escape
import numpy as np


def spectrum_svg(spectrum, integrals, revision):
    x, y = np.asarray(spectrum.axis), np.asarray(spectrum.real)
    width, height, left, right, top, bottom = 1000, 420, 65, 25, 45, 60
    xmin, xmax = float(x.min()), float(x.max())
    ymin, ymax = float(min(0, y.min())), float(max(0, y.max()))
    span = ymax - ymin or 1
    ymin -= span * 0.08
    ymax += span * 0.1

    def px(v):
        f = (float(v) - xmin) / (xmax - xmin)
        return left + (1 - f if spectrum.axis_unit == "ppm" else f) * (width - left - right)

    def py(v):
        return height - bottom - (float(v) - ymin) / (ymax - ymin) * (height - top - bottom)

    # Bucket extrema retain narrow peaks; no scientific values are downsampled.
    keep = {0, len(x) - 1}
    for ids in np.array_split(np.arange(len(x)), min(len(x), 1600)):
        if len(ids):
            keep.update([int(ids[np.argmin(y[ids])]), int(ids[np.argmax(y[ids])])])
    points = " ".join(f"{px(x[i]):.3f},{py(y[i]):.3f}" for i in sorted(keep))
    ticks = []
    for value in np.linspace(xmin, xmax, 9):
        ticks.append(f'<text x="{px(value):.2f}" y="386" text-anchor="middle">{value:.3g}</text>')
    regions = []
    for integral in integrals:
        if integral.spectrum_id == spectrum.id:
            a, b = sorted([px(integral.lower), px(integral.upper)])
            regions.append(
                f'<rect x="{a:.2f}" y="45" width="{b - a:.2f}" height="315" fill="#f59e0b" opacity=".15"/>'
            )
            regions.append(
                f'<text x="{(a + b) / 2:.2f}" y="62" text-anchor="middle">{integral.area:.4g}</text>'
            )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="#fff"/>'
        '<g font-family="Arial,sans-serif" font-size="13" fill="#16283b">'
        f'<text x="65" y="25">{escape(spectrum.name)} · revision {revision}</text>'
        + "".join(regions)
        + f'<path d="M65 {py(0):.3f}H975" stroke="#bdc8d0"/>'
        + f'<polyline points="{points}" fill="none" stroke="#127c82" stroke-width="1.2"/>'
        + "".join(ticks)
        + f'<text x="500" y="412" text-anchor="middle">{escape(spectrum.axis_unit)}</text>'
        "</g></svg>"
    )
