"""Deterministic one-dimensional NMR operations with explicit conventions.

All inputs use arbitrary, consistent intensity units. None of these operations
normalizes individual traces. Uncertainty from a fitted model is a local,
linearized standard uncertainty; it does not include acquisition systematics.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.optimize import least_squares
from scipy.signal import find_peaks
from scipy.stats import chi2

from .errors import NmrError

MAX_POINTS = 262_144
MAX_SERIES_POINTS = 4096


def _number(value, name, *, positive=False, nonnegative=False):
    if isinstance(value, (bool, str, bytes)):
        raise NmrError("INVALID_NUMBER", f"{name} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NmrError("INVALID_NUMBER", f"{name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise NmrError("NONFINITE_INPUT", f"{name} must be finite.")
    if positive and number <= 0:
        raise NmrError("INVALID_NUMBER", f"{name} must be positive.")
    if nonnegative and number < 0:
        raise NmrError("INVALID_NUMBER", f"{name} must be nonnegative.")
    return number


def _vector(values, name, *, minimum=2, maximum=MAX_POINTS):
    try:
        unconverted = np.asarray(values)
        if np.iscomplexobj(unconverted):
            raise NmrError(
                "INVALID_ARRAY", f"{name} must be real; supply imaginary values separately."
            )
        array = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise NmrError("INVALID_ARRAY", f"{name} must be a numeric vector.") from exc
    if array.ndim != 1 or not minimum <= array.size <= maximum:
        raise NmrError("INVALID_ARRAY", f"{name} needs {minimum} to {maximum} points.")
    if not np.all(np.isfinite(array)):
        raise NmrError("NONFINITE_INPUT", f"{name} must contain only finite values.")
    return array


def _paired(axis, real):
    x, y = _vector(axis, "axis"), _vector(real, "real")
    if x.size != y.size:
        raise NmrError("SHAPE_MISMATCH", "Axis and intensities must have the same length.")
    # Compare adjacent values without subtraction, which can overflow.
    if not (np.all(x[1:] > x[:-1]) or np.all(x[1:] < x[:-1])):
        raise NmrError("INVALID_AXIS", "Axis must be strictly monotonic without duplicates.")
    return x, y


def _check_result(array):
    if not np.all(np.isfinite(array)):
        raise NmrError("NUMERICAL_RANGE", "The calculation exceeded finite float64 range.")
    return array


def _range(x, lower, upper):
    lo, hi = _number(lower, "lower"), _number(upper, "upper")
    if lo >= hi:
        raise NmrError("INVALID_BOUNDS", "Bounds must satisfy lower < upper.")
    if lo < float(np.min(x)) or hi > float(np.max(x)):
        raise NmrError("OUTSIDE_AXIS", "Bounds must lie inside the observed axis.")
    return lo, hi


def integrate(axis, real, lower, upper):
    """Exact integral of the piecewise-linear trace, with signed intensities."""
    x, y = _paired(axis, real)
    lo, hi = _range(x, lower, upper)
    if x[0] > x[-1]:
        x, y = x[::-1], y[::-1]
    interior = (x > lo) & (x < hi)
    xx = np.concatenate(([lo], x[interior], [hi]))
    yy = np.concatenate(([np.interp(lo, x, y)], y[interior], [np.interp(hi, x, y)]))
    with np.errstate(over="ignore", invalid="ignore"):
        area = float(np.trapezoid(yy, xx))
    _check_result(area)
    return {"area": area, "lower": lo, "upper": hi, "unit": "intensity*ppm"}


def detect_peaks(axis, real, prominence):
    """Find positive maxima and negative minima; endpoints are not peaks."""
    x, y = _paired(axis, real)
    threshold = _number(prominence, "prominence", positive=True)
    positive, _ = find_peaks(y, prominence=threshold)
    negative, _ = find_peaks(-y, prominence=threshold)
    indices = sorted(
        {int(i) for i in positive if y[i] > 0} | {int(i) for i in negative if y[i] < 0}
    )
    return [
        {
            "ppm": float(x[i]),
            "intensity": float(y[i]),
            "polarity": "positive" if y[i] > 0 else "negative",
        }
        for i in indices
    ]


def process_fid(
    real, imag, dwell_s, obs_mhz, carrier_ppm, zero_fill_factor=2, line_broadening_hz=0.3
):
    """Forward DFT: exp(+2*pi*i*f*t) appears at carrier_ppm + f/obs_mhz.

    The output is descending in ppm. The forward FFT is unscaled. The first
    point is not half-weighted, and no digital-filter correction is applied here;
    an importer must document any correction it performed before this call.
    """
    re, im = _vector(real, "real"), _vector(imag, "imag")
    if re.size != im.size:
        raise NmrError("SHAPE_MISMATCH", "FID real and imaginary lengths differ.")
    dwell = _number(dwell_s, "dwell_s", positive=True)
    obs = _number(obs_mhz, "obs_mhz", positive=True)
    carrier = _number(carrier_ppm, "carrier_ppm")
    lb = _number(line_broadening_hz, "line_broadening_hz", nonnegative=True)
    factor = _number(zero_fill_factor, "zero_fill_factor", positive=True)
    if not factor.is_integer() or factor > 16 or re.size * factor > MAX_POINTS:
        raise NmrError(
            "ARRAY_LIMIT", "Zero filling needs an integer factor <= 16 and <= 262144 points."
        )
    count = int(re.size * factor)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        time = np.arange(re.size, dtype=np.float64) * dwell
        window = np.exp(-np.pi * lb * time)
        transformed = np.fft.fftshift(np.fft.fft((re + 1j * im) * window, n=count))
        frequencies = np.fft.fftshift(np.fft.fftfreq(count, d=dwell))
        axis = carrier + frequencies / obs
    _check_result(time)
    _check_result(transformed)
    _check_result(axis)
    if not np.all(axis[1:] > axis[:-1]):
        raise NmrError(
            "NUMERICAL_RANGE", "Frequency spacing cannot be represented at this carrier."
        )
    return {
        "axis": axis[::-1].tolist(),
        "real": transformed.real[::-1].tolist(),
        "imag": transformed.imag[::-1].tolist(),
        "metadata": {
            "method": "exponential_window_then_forward_fft",
            "frequency_convention": "exp(+2*pi*i*f*t) -> carrier_ppm + f_hz/obs_mhz",
            "normalization": "unscaled_forward_fft",
            "axis_unit": "ppm",
            "dwell_s": dwell,
            "obs_mhz": obs,
            "carrier_ppm": carrier,
            "input_points": int(re.size),
            "output_points": count,
            "zero_fill_factor": int(factor),
            "line_broadening_hz": lb,
            "window": "exp(-pi*line_broadening_hz*time_s)",
            "digital_filter_correction": "none_in_this_operation",
        },
    }


def phase(axis, real, imag, ph0_deg, ph1_deg, pivot_ppm):
    """Multiply by exp(+i*phi), with ph1 spanning increasing-ppm full width."""
    x, re = _paired(axis, real)
    im = _vector(imag, "imag")
    if im.size != re.size:
        raise NmrError("SHAPE_MISMATCH", "Real and imaginary lengths differ.")
    ph0, ph1 = _number(ph0_deg, "ph0_deg"), _number(ph1_deg, "ph1_deg")
    pivot = _number(pivot_ppm, "pivot_ppm")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        span = float(np.max(x) - np.min(x))
        angle = np.deg2rad(ph0 + ph1 * (x - pivot) / span)
        result = (re + 1j * im) * np.exp(1j * angle)
    _check_result(span)
    _check_result(result)
    return {
        "real": result.real.tolist(),
        "imag": result.imag.tolist(),
        "metadata": {
            "method": "complex_phase_rotation",
            "ph0_deg": ph0,
            "ph1_deg": ph1,
            "pivot_ppm": pivot,
            "span_ppm": span,
            "convention": "exp(+i*pi/180*(ph0+ph1*(ppm-pivot)/span))",
        },
    }


def baseline(axis, real, regions):
    """Subtract an affine baseline fitted only to observed points in windows."""
    x, y = _paired(axis, real)
    if not isinstance(regions, (list, tuple)) or not 1 <= len(regions) <= 64:
        raise NmrError("INVALID_REGIONS", "Provide 1 to 64 explicit baseline windows.")
    mask = np.zeros(x.size, dtype=bool)
    bounds = []
    for region in regions:
        if not isinstance(region, (list, tuple)) or len(region) != 2:
            raise NmrError("INVALID_REGIONS", "Each baseline window needs [lower, upper].")
        lo, hi = _range(x, *region)
        bounds.append([lo, hi])
        mask |= (x >= lo) & (x <= hi)
    if int(np.sum(mask)) < 3:
        raise NmrError(
            "INSUFFICIENT_BASELINE", "At least three observed baseline points are required."
        )
    # Center/scale to keep the fit independent of the displayed offset.
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        center = float(x[mask][0] / 2 + x[mask][-1] / 2)
        width = float(np.max(x[mask]) - np.min(x[mask]))
        xx = (x - center) / width
    _check_result(xx)
    _check_result(width)
    if width <= 0:
        raise NmrError("INSUFFICIENT_BASELINE", "Baseline windows have no usable span.")
    intensity_scale = max(float(np.max(np.abs(y[mask]))), np.finfo(float).tiny)
    design = np.column_stack((np.ones(int(np.sum(mask))), xx[mask]))
    try:
        coefficients, _, rank, _ = np.linalg.lstsq(design, y[mask] / intensity_scale, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise NmrError("BASELINE_FAILED", "The selected baseline fit did not converge.") from exc
    if rank != 2:
        raise NmrError("INSUFFICIENT_BASELINE", "Baseline points cannot identify an affine model.")
    with np.errstate(over="ignore", invalid="ignore"):
        corrected = y - intensity_scale * (coefficients[0] + coefficients[1] * xx)
        intercept = float(coefficients[0] * intensity_scale)
        slope = float(coefficients[1] * intensity_scale / width)
    _check_result(corrected)
    _check_result([intercept, slope])
    return {
        "real": corrected.tolist(),
        "metadata": {
            "method": "affine_selected_windows",
            "regions": bounds,
            "baseline_point_count": int(np.sum(mask)),
            "center_ppm": center,
            "intercept_at_center": intercept,
            "slope_per_ppm": slope,
        },
    }


def calculate_yield(
    product_area,
    standard_area,
    product_protons,
    standard_protons,
    standard_mol,
    limiting_mol,
    stoichiometric_factor=1.0,
):
    """Quantitative internal-standard yield; factor is product mol per limiting mol."""
    values = [
        _number(product_area, "product_area", positive=True),
        _number(standard_area, "standard_area", positive=True),
        _number(product_protons, "product_protons", positive=True),
        _number(standard_protons, "standard_protons", positive=True),
        _number(standard_mol, "standard_mol", positive=True),
        _number(limiting_mol, "limiting_mol", positive=True),
        _number(stoichiometric_factor, "stoichiometric_factor", positive=True),
    ]
    pa, sa, pp, sp, sm, lm, sf = values
    log_yield = (
        math.log(pa)
        - math.log(sa)
        - math.log(pp)
        + math.log(sp)
        + math.log(sm)
        - math.log(lm)
        - math.log(sf)
        + math.log(100)
    )
    try:
        value = math.exp(log_yield)
    except OverflowError as exc:
        raise NmrError("NUMERICAL_RANGE", "Yield exceeds finite float64 range.") from exc
    if not math.isfinite(value) or value == 0:
        raise NmrError("NUMERICAL_RANGE", "Yield is outside representable float64 range.")
    return {
        "yield_percent": value,
        "method": "100*(product_area/product_protons)/(standard_area/standard_protons)"
        "*standard_mol/(limiting_mol*stoichiometric_factor)",
        "assumptions": [
            "Areas share one intensity scale and represent nonoverlapping quantitative regions.",
            "Proton counts, standard amount, limiting amount and stoichiometry are supplied explicitly.",
            "Acquisition, relaxation, standard purity and baseline support quantitative integration.",
            "No uncertainty is calculated without measurement and preparation uncertainties.",
        ],
    }


def _fit_result(model, time, signals, warnings, diagnostics, **updates):
    result = {
        "model": model,
        "status": "unidentifiable",
        "time_s": time.tolist(),
        "signals": signals.tolist(),
        "predicted": [],
        "residuals": [],
        "parameters": {},
        "T_s": None,
        "u_T_s": None,
        "uncertainty_method": "unavailable_unidentifiable",
        "warnings": warnings,
        "diagnostics": diagnostics,
    }
    result.update(updates)
    return result


def fit_relaxation(
    times, signals, time_unit, model, sigma=None, time_basis="elapsed", delay_multiplier=None
):
    """Fit one constrained exponential without reordering or normalizing observations.

    Identifiability diagnostics are conservative numerical gates, not a validated
    instrument-specific acquisition protocol. Replicates are independent weighted
    observations; no averaging or silent exclusion takes place.
    """
    if not isinstance(model, str) or model not in {"T1", "T2"}:
        raise NmrError("INVALID_MODEL", "Model must be T1 or T2.")
    unit_scales = {"s": 1.0, "ms": 0.001, "us": 0.000001}
    if not isinstance(time_unit, str) or time_unit not in unit_scales:
        raise NmrError("UNKNOWN_TIME_UNIT", "Time unit must explicitly be s, ms or us.")
    if not isinstance(time_basis, str) or time_basis not in {"elapsed", "echo_interval"}:
        raise NmrError("UNKNOWN_TIME_BASIS", "Time basis must be elapsed or echo_interval.")
    multiplier = 1.0
    if time_basis == "echo_interval":
        if model != "T2" or delay_multiplier is None:
            raise NmrError("AMBIGUOUS_TIME", "T2 echo intervals require an explicit multiplier.")
        multiplier = _number(delay_multiplier, "delay_multiplier", positive=True)
    elif delay_multiplier is not None:
        if _number(delay_multiplier, "delay_multiplier", positive=True) != 1:
            raise NmrError("AMBIGUOUS_TIME", "Elapsed times must not receive an extra multiplier.")
    time = _vector(times, "times", minimum=1, maximum=MAX_SERIES_POINTS)
    y = _vector(signals, "signals", minimum=1, maximum=MAX_SERIES_POINTS)
    if time.size != y.size:
        raise NmrError("SHAPE_MISMATCH", "Times and signals must have the same length.")
    if np.any(time < 0):
        raise NmrError("INVALID_TIME", "Relaxation times cannot be negative.")
    with np.errstate(over="ignore", invalid="ignore", under="ignore"):
        converted = time * unit_scales[time_unit] * multiplier
    _check_result(converted)
    if np.any((time > 0) & (converted == 0)):
        raise NmrError("NUMERICAL_RANGE", "Time conversion underflowed.")
    time = converted
    sig = None
    if sigma is not None:
        sig = _vector(sigma, "sigma", minimum=1, maximum=MAX_SERIES_POINTS)
        if sig.size != y.size or np.any(sig <= 0):
            raise NmrError(
                "INVALID_SIGMA", "Sigma needs one positive standard deviation per signal."
            )
    unique = int(np.unique(time).size)
    warnings = []
    diagnostics = {
        "n_observations": int(y.size),
        "n_unique_delays": unique,
        "degrees_of_freedom": int(y.size - 3),
        "time_unit_input": time_unit,
        "time_basis": time_basis,
        "delay_multiplier": multiplier,
        "normalization": "none",
        "condition_number": None,
        "reduced_chi_square": None,
        "rms_residual": None,
        "observed_span_over_T": None,
        "uncertainty_kind": "standard_uncertainty_not_confidence_interval",
        "weighting": "known_independent_sigma" if sig is not None else "unweighted_equal_variance",
        "covariance_assumptions": "independent residuals, adequate model, local linear approximation",
        "identifiability_thresholds": {
            "minimum_distinct_delays": 4,
            "maximum_scaled_condition": 1e8,
            "minimum_observed_span_over_T": 0.02,
        },
    }
    if unique < y.size:
        warnings.append("REPEATED_DELAYS: replicate observations retained separately.")
    if y.size < 4 or unique < 4:
        warnings.append(
            "UNDERSAMPLED: need at least four distinct delays for this three-parameter fit."
        )
        return _fit_result(model, time, y, warnings, diagnostics)
    scale_y = float(np.max(np.abs(y)))
    if scale_y == 0:
        warnings.append("FLAT_SIGNAL: no relaxation amplitude is observed.")
        return _fit_result(model, time, y, warnings, diagnostics)
    yy = y / scale_y
    if float(np.ptp(yy)) <= 1e-10:
        warnings.append("FLAT_SIGNAL: changes are negligible relative to the signal scale.")
        return _fit_result(model, time, y, warnings, diagnostics)
    scale_t = float(np.max(time))
    tt = time / scale_t
    weights = np.ones_like(yy) if sig is None else sig / scale_y
    if not np.all(np.isfinite(weights)) or np.any(weights <= 0):
        raise NmrError("NUMERICAL_RANGE", "Signal-to-uncertainty scale is not representable.")

    def prediction(p):
        exp = np.exp(-p[2] * tt)
        return p[0] - p[1] * exp if model == "T1" else p[0] + p[1] * exp

    def residual(p):
        return (prediction(p) - yy) / weights

    def jacobian(p):
        exp = np.exp(-p[2] * tt)
        direction = -1 if model == "T1" else 1
        return (
            np.column_stack((np.ones_like(tt), direction * exp, -direction * p[1] * tt * exp))
            / weights[:, None]
        )

    if model == "T1":
        first = max(float(np.max(yy)), 0.05)
        second = max(first - float(yy[np.argmin(tt)]), 0.1)
        lower = [0, 0, 1e-7]
    else:
        first, second = float(np.min(yy)), max(float(np.ptp(yy)), 0.1)
        lower = [-np.inf, 0, 1e-7]
    fitted = []
    for rate in (0.1, 1.0, 10.0):
        try:
            candidate = least_squares(
                residual,
                [first, second, rate],
                jac=jacobian,
                bounds=(lower, [np.inf, np.inf, 1e4]),
                x_scale="jac",
                max_nfev=2000,
                ftol=1e-11,
                xtol=1e-11,
                gtol=1e-11,
            )
        except (ValueError, FloatingPointError, np.linalg.LinAlgError):
            continue
        if candidate.success and math.isfinite(candidate.cost) and np.all(np.isfinite(candidate.x)):
            fitted.append(candidate)
    if not fitted:
        warnings.append("FIT_FAILED: bounded optimization did not converge.")
        return _fit_result(model, time, y, warnings, diagnostics)
    fit = min(fitted, key=lambda candidate: candidate.cost)
    params = fit.x
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        predicted = prediction(params) * scale_y
        residuals = y - predicted
        rate_physical = float(params[2] / scale_t)
        relaxation_time = float(scale_t / params[2])
        span_ratio = float(params[2] * np.ptp(tt))
        rms = float(np.linalg.norm(residuals / scale_y) / math.sqrt(y.size) * scale_y)
    _check_result(predicted)
    _check_result(residuals)
    _check_result([rate_physical, relaxation_time, span_ratio, rms])
    parameters = (
        {"A": float(params[0] * scale_y), "B": float(params[1] * scale_y)}
        if model == "T1"
        else {"C": float(params[0] * scale_y), "A": float(params[1] * scale_y)}
    )
    parameters["k_s_inverse"] = rate_physical
    _check_result(list(parameters.values()))
    diagnostics["observed_span_over_T"] = span_ratio
    diagnostics["rms_residual"] = rms
    result = _fit_result(
        model,
        time,
        y,
        warnings,
        diagnostics,
        predicted=predicted.tolist(),
        residuals=residuals.tolist(),
        parameters=parameters,
    )
    jac = jacobian(params)
    column_norm = np.linalg.norm(jac, axis=0)
    identifiable = bool(np.all(column_norm > 0) and np.all(np.isfinite(jac)))
    condition = None
    if identifiable:
        try:
            singular = np.linalg.svd(jac / column_norm, compute_uv=False)
            condition = float(singular[0] / singular[-1]) if singular[-1] > 0 else None
        except np.linalg.LinAlgError:
            identifiable = False
    if condition is not None and math.isfinite(condition):
        diagnostics["condition_number"] = condition
    else:
        identifiable = False
    if not identifiable or condition > 1e8:
        identifiable = False
        warnings.append("ILL_CONDITIONED: the parameters cannot be separated numerically.")
    if span_ratio < 0.02 or params[2] <= 1.01e-7 or params[2] >= 0.99e4:
        identifiable = False
        warnings.append("RATE_UNIDENTIFIABLE: sampled curvature or rate range is insufficient.")
    if params[1] <= 1e-8 or (model == "T1" and params[0] <= 1e-8):
        identifiable = False
        warnings.append("BOUNDARY_AMPLITUDE: a required positive amplitude is unresolved.")
    if not identifiable:
        return result

    dof = y.size - 3
    weighted_rss = float(np.dot(fit.fun, fit.fun))
    if not math.isfinite(weighted_rss):
        warnings.append("UNCERTAINTY_UNAVAILABLE: weighted residual scale overflowed.")
        return result
    reduced = weighted_rss / dof
    if sig is not None:
        diagnostics["reduced_chi_square"] = reduced
    mismatch = bool(sig is not None and chi2.sf(weighted_rss, dof) < 0.01)
    # A trend in residuals is evidence to inspect the model, not a second model fit.
    ordered = residuals[np.argsort(time, kind="stable")] / scale_y
    relative_rms = rms / scale_y / float(np.ptp(yy))
    if y.size >= 8 and relative_rms > 0.005:
        if np.std(ordered[:-1]) > 0 and np.std(ordered[1:]) > 0:
            correlation = float(np.corrcoef(ordered[:-1], ordered[1:])[0, 1])
            if math.isfinite(correlation):
                diagnostics["residual_lag1_correlation"] = correlation
                mismatch |= correlation > 0.65
        # Few sign runs also reveal long systematic departures when one endpoint
        # dominates lag correlation. This is a screening heuristic after fitting,
        # not an exact hypothesis test for nonlinear fitted residuals.
        signs = np.sign(ordered[ordered != 0])
        n_positive, n_negative = int(np.sum(signs > 0)), int(np.sum(signs < 0))
        count = n_positive + n_negative
        if n_positive >= 5 and n_negative >= 5:
            runs = 1 + int(np.sum(signs[1:] != signs[:-1]))
            expected_runs = 1 + 2 * n_positive * n_negative / count
            variance = (
                2
                * n_positive
                * n_negative
                * (2 * n_positive * n_negative - count)
                / (count**2 * (count - 1))
            )
            z_runs = (runs - expected_runs) / math.sqrt(variance)
            diagnostics["residual_runs_z_screen"] = z_runs
            mismatch |= z_runs < -2.58
    if mismatch:
        warnings.append(
            "MODEL_MISMATCH: inspect residuals; a single exponential may be inadequate."
        )
    uncertainty = None
    uncertainty_method = "unavailable_model_mismatch" if mismatch else "unavailable_covariance"
    if not mismatch:
        try:
            # SVD avoids squaring the condition number when obtaining (J'J)^-1.
            _, singular, vt = np.linalg.svd(jac, full_matrices=False)
            covariance = (vt.T / singular**2) @ vt
            if sig is None:
                covariance *= reduced
            u_rate_scaled = math.sqrt(max(0.0, float(covariance[2, 2])))
            uncertainty = float((u_rate_scaled / params[2]) * relaxation_time)
            if not math.isfinite(uncertainty):
                uncertainty = None
            else:
                uncertainty_method = (
                    "linearized_covariance_residual_scaled"
                    if sig is None
                    else "linearized_covariance_absolute_sigma"
                )
        except (np.linalg.LinAlgError, ValueError, OverflowError, ZeroDivisionError):
            uncertainty = None
        if uncertainty is None:
            warnings.append("UNCERTAINTY_UNAVAILABLE: covariance could not be estimated.")
        elif uncertainty >= relaxation_time:
            warnings.append("HIGH_RELATIVE_UNCERTAINTY: fitted rate is not resolved precisely.")
            return result
    result.update(
        status="warning" if warnings else "ok",
        T_s=relaxation_time,
        u_T_s=uncertainty,
        uncertainty_method=uncertainty_method,
    )
    return result
