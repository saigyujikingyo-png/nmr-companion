"""Analytic references independent of the project/service implementation."""

import json

import numpy as np
import pytest

from nmr_companion.errors import NmrError
from nmr_companion.numerics import (
    baseline,
    calculate_yield,
    detect_peaks,
    fit_relaxation,
    integrate,
    phase,
    process_fid,
)


def assert_finite_json(value):
    json.dumps(value, allow_nan=False)


@pytest.mark.parametrize("descending", [False, True])
def test_signed_integral_has_exact_interpolated_boundaries(descending):
    x = np.arange(-3.0, 4.0)
    y = 2 * x - 3
    if descending:
        x, y = x[::-1], y[::-1]
    result = integrate(x, y, -1.25, 2.25)
    # Antiderivative x*x-3*x at boundaries, neither boundary is a sample point.
    assert result["area"] == pytest.approx(-7.0)
    assert result["unit"] == "intensity*ppm"
    assert_finite_json(result)


@pytest.mark.parametrize(
    "x,y,lo,hi",
    [
        ([0, 0, 1], [1, 2, 3], 0, 1),
        ([0, 2, 1], [1, 2, 3], 0, 1),
        ([0, 1], [1, np.nan], 0, 1),
        ([0, 1], [1, 2], -0.1, 1),
        ([0, 1], [1, 2], 0.5, 0.5),
        ([0, 1], [1], 0, 1),
    ],
)
def test_integral_rejects_invalid_support(x, y, lo, hi):
    with pytest.raises(NmrError):
        integrate(x, y, lo, hi)


def test_signed_peaks_preserve_negative_dept_observations():
    result = detect_peaks([5, 4, 3, 2, 1, 0], [0, 4, 0, -3, 0, 0], 1)
    assert sorted((p["ppm"], p["intensity"]) for p in result) == [(2, -3), (4, 4)]


def test_fft_maps_analytic_complex_tone_to_documented_ppm():
    count, dwell, frequency = 64, 0.001, 125.0
    fid = np.exp(2j * np.pi * frequency * np.arange(count) * dwell)
    result = process_fid(fid.real, fid.imag, dwell, 100.0, 4.0, 1, 0.0)
    peak = int(np.argmax(result["real"]))
    assert result["axis"][peak] == pytest.approx(5.25)
    assert result["real"][peak] == pytest.approx(count)
    assert max(abs(v) for v in result["imag"]) < 1e-11
    assert np.all(np.diff(result["axis"]) < 0)
    assert_finite_json(result)


def test_zero_filling_and_broadening_match_independent_geometric_sum():
    count, dwell, lb = 16, 0.002, 2.0
    result = process_fid(np.ones(count), np.zeros(count), dwell, 80, 4.7, 4, lb)
    center = int(np.argmin(np.abs(np.asarray(result["axis"]) - 4.7)))
    ratio = np.exp(-np.pi * lb * dwell)
    expected = (1 - ratio**count) / (1 - ratio)
    assert len(result["axis"]) == 64
    assert result["real"][center] == pytest.approx(expected)
    assert result["metadata"]["normalization"] == "unscaled_forward_fft"


def test_phase_has_explicit_pivot_and_full_span_linear_term():
    result = phase([2, 1, 0], [1, 1, 1], [0, 0, 0], 0, 180, 1)
    assert result["real"] == pytest.approx([0, 1, 0], abs=1e-14)
    assert result["imag"] == pytest.approx([1, 0, -1], abs=1e-14)
    with pytest.raises(NmrError):
        phase([0, 1], [1, 1], None, 0, 0, 0)


def test_affine_baseline_uses_only_selected_windows():
    x = np.arange(11.0)
    y = 2 * x + 5
    y[4:7] += [2, 7, 2]
    result = baseline(x[::-1], y[::-1], [[0, 2], [8, 10]])
    expected = np.zeros(11)
    expected[4:7] = [2, 7, 2]
    assert result["real"] == pytest.approx(expected[::-1], abs=1e-12)
    assert result["metadata"]["baseline_point_count"] == 6
    with pytest.raises(NmrError):
        baseline(x, y, [[4.1, 4.9]])


def test_yield_uses_moles_proton_counts_and_explicit_stoichiometry():
    result = calculate_yield(1.08, 6, 3, 6, 0.001, 0.001)
    assert result["yield_percent"] == pytest.approx(36)
    assert calculate_yield(1.08, 6, 3, 6, 0.001, 0.001, 2)["yield_percent"] == pytest.approx(18)
    assert result["assumptions"]
    assert_finite_json(result)


@pytest.mark.parametrize("index,bad", [(0, -1), (1, 0), (2, 0), (4, None), (5, np.inf)])
def test_yield_invalid_input_has_no_invented_result(index, bad):
    args = [1, 2, 1, 2, 0.001, 0.001]
    args[index] = bad
    with pytest.raises(NmrError):
        calculate_yield(*args)


def test_t1_preserves_sign_order_duplicates_and_unit_equivalence():
    times = np.array([2.4, 0, 0.4, 1.5, 0.1, 0.8, 0.4, 4.0])
    signal = 3 - 6 * np.exp(-times / 0.7)
    result = fit_relaxation(times, signal, "s", "T1")
    millis = fit_relaxation(times * 1000, signal, "ms", "T1")
    assert result["status"] in {"ok", "warning"}
    assert result["T_s"] == pytest.approx(0.7, rel=1e-7)
    assert millis["T_s"] == pytest.approx(result["T_s"], rel=1e-9)
    assert result["signals"][1] == -3
    assert result["time_s"] == times.tolist()
    assert result["predicted"] == pytest.approx(signal, abs=1e-9)
    assert any("REPEATED" in warning for warning in result["warnings"])
    assert_finite_json(result)


def test_t2_offset_echo_multiplier_and_independent_covariance():
    times = np.array([0, 0.03, 0.08, 0.2, 0.5, 0.9, 1.5, 2.5])
    signal = -2 + 5 * np.exp(-times / 0.4)
    sigma = np.full(len(times), 0.1)
    result = fit_relaxation(
        times / 2, signal, "s", "T2", sigma, time_basis="echo_interval", delay_multiplier=2
    )
    assert result["T_s"] == pytest.approx(0.4, rel=1e-8)
    assert result["parameters"]["C"] == pytest.approx(-2, abs=1e-8)
    # Independent Jacobian in physical [C, A, k], not the optimizer scaling.
    decay = np.exp(-times / 0.4)
    jac = np.column_stack([np.ones(len(times)), decay, -5 * times * decay]) / sigma[:, None]
    covariance = np.linalg.inv(jac.T @ jac)
    expected = np.sqrt(covariance[2, 2]) / (1 / 0.4) ** 2
    assert result["u_T_s"] == pytest.approx(expected, rel=1e-6)
    assert result["uncertainty_method"] == "linearized_covariance_absolute_sigma"
    assert_finite_json(result)


def test_noisy_t2_residual_scaled_standard_uncertainty():
    times = np.linspace(0, 3, 20)
    noise = np.array(
        [
            0.02,
            -0.01,
            0.03,
            -0.02,
            0,
            0.01,
            -0.02,
            0.02,
            -0.01,
            0.01,
            -0.02,
            0.01,
            0.02,
            -0.01,
            0,
            0.01,
            -0.02,
            0.02,
            -0.01,
            0,
        ]
    )
    signals = 0.4 + 4 * np.exp(-times / 0.8) + noise
    result = fit_relaxation(times, signals, "s", "T2")
    assert result["T_s"] == pytest.approx(0.8, abs=0.02)
    assert 0 < result["u_T_s"] < 0.02
    assert result["uncertainty_method"] == "linearized_covariance_residual_scaled"
    assert result["signals"] == signals.tolist()
    assert np.asarray(result["residuals"]) == pytest.approx(signals - result["predicted"])


@pytest.mark.parametrize(
    "times,signals",
    [
        ([0, 1, 2, 3, 4], [2, 2, 2, 2, 2]),
        ([0, 1, 2], [-1, 0, 1]),
        ([1, 1, 1, 1], [1, 2, 3, 4]),
        ([0, 1, 2, 3, 4, 5], [10, 9, 8, 7, 6, 5]),
    ],
)
def test_unidentifiable_series_never_returns_confident_relaxation(times, signals):
    result = fit_relaxation(times, signals, "s", "T2")
    assert result["status"] == "unidentifiable"
    assert result["T_s"] is None
    assert result["u_T_s"] is None
    assert result["warnings"]
    assert_finite_json(result)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"time_unit": "unknown"},
        {"time_basis": "tau"},
        {"time_basis": "echo_interval"},
        {"time_basis": "echo_interval", "delay_multiplier": 0},
        {"sigma": [0.1, 0, 0.1, 0.1]},
        {"model": "T3"},
    ],
)
def test_relaxation_rejects_ambiguous_time_and_weights(kwargs):
    args = {"times": [0, 1, 2, 3], "signals": [4, 2, 1, 0.5], "time_unit": "s", "model": "T2"}
    args.update(kwargs)
    with pytest.raises(NmrError):
        fit_relaxation(**args)


def test_multicomponent_known_noise_diagnoses_model_mismatch():
    times = np.linspace(0, 4, 30)
    signals = 1 + 3 * np.exp(-times / 0.12) + 3 * np.exp(-times / 1.5)
    result = fit_relaxation(times, signals, "s", "T2", sigma=np.full(30, 0.01))
    assert result["status"] == "warning"
    assert result["u_T_s"] is None
    assert any("MODEL_MISMATCH" in warning for warning in result["warnings"])
    assert_finite_json(result)


def test_strong_multicomponent_without_sigma_flags_structured_residuals():
    times = np.linspace(0, 4, 30)
    signals = 1 + 3 * np.exp(-times / 0.12) + 3 * np.exp(-times / 1.5)
    result = fit_relaxation(times, signals, "s", "T2")
    assert result["status"] == "warning"
    assert result["u_T_s"] is None
    assert any("MODEL_MISMATCH" in warning for warning in result["warnings"])


def test_short_window_does_not_report_a_resolved_time_constant():
    times = np.linspace(0, 0.001, 10)
    result = fit_relaxation(times, 2 + 3 * np.exp(-times / 2), "s", "T2")
    assert result["status"] == "unidentifiable"
    assert result["T_s"] is None and result["u_T_s"] is None
    assert any("UNIDENTIFIABLE" in warning for warning in result["warnings"])


def test_weighted_noisy_fit_matches_independent_profiled_rate_solution():
    from scipy.optimize import minimize_scalar

    times = np.linspace(0, 3, 10)
    sigma = np.linspace(0.03, 0.08, 10)
    noise = np.array([0.01, -0.02, 0.01, 0.03, -0.01, 0.02, -0.02, 0.01, -0.01, 0.01])
    signals = 1 + 4 * np.exp(-times / 0.7) + noise

    def independent_cost(log_rate):
        design = np.column_stack([np.ones(len(times)), np.exp(-np.exp(log_rate) * times)])
        coefficients = np.linalg.lstsq(design / sigma[:, None], signals / sigma, rcond=None)[0]
        return float(np.sum(((signals - design @ coefficients) / sigma) ** 2))

    optimum = minimize_scalar(
        independent_cost, bounds=(-5, 5), method="bounded", options={"xatol": 1e-12}
    )
    result = fit_relaxation(times, signals, "s", "T2", sigma)
    assert result["T_s"] == pytest.approx(np.exp(-optimum.x), rel=1e-6)
    decay = np.exp(-times / result["T_s"])
    jac = (
        np.column_stack([np.ones(len(times)), decay, -result["parameters"]["A"] * times * decay])
        / sigma[:, None]
    )
    cov = np.linalg.inv(jac.T @ jac)
    assert result["u_T_s"] == pytest.approx(np.sqrt(cov[2, 2]) * result["T_s"] ** 2, rel=1e-6)
    assert result["residuals"] == pytest.approx(signals - result["predicted"], abs=1e-14)


@pytest.mark.parametrize("kwargs", [{"model": []}, {"time_unit": []}, {"time_basis": []}])
def test_invalid_discriminators_raise_domain_error(kwargs):
    args = {"times": [0, 1, 2, 3], "signals": [4, 2, 1, 0.5], "time_unit": "s", "model": "T2"}
    args.update(kwargs)
    with pytest.raises(NmrError):
        fit_relaxation(**args)


def test_real_array_does_not_silently_discard_complex_component():
    with pytest.raises(NmrError):
        integrate([0, 1], np.array([1 + 4j, 2 + 5j]), 0, 1)
