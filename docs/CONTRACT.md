# Alpha implementation contract
Version 1. First batch covers organic and physical chemistry together.
A developer alpha establishes working vertical slices; it does not certify
every manual case or instrument format.

## Numerical seam (owned by numerical contributor)
All functions raise NmrError(code, message) on invalid input; no NaN/Infinity.
JSON-compatible returns, finite float64 calculations, explicit units.
- integrate(axis, real, lower, upper) -> dict: area, lower, upper, unit="intensity*ppm".
  Sort a strictly monotonic axis, interpolate boundaries, preserve signed values;
  reject out-of-range, duplicate axes, reversed/empty bounds.
- detect_peaks(axis, real, prominence) -> list[dict] with ppm, intensity.
- process_fid(real, imag, dwell_s, obs_mhz, carrier_ppm, zero_fill_factor=2,
  line_broadening_hz=0.3) -> dict axis, real, imag, metadata.
  Explicit Fourier/sign convention; test against independent analytic signals.
- phase(axis, real, imag, ph0_deg, ph1_deg, pivot_ppm) -> dict real, imag, metadata.
- baseline(axis, real, regions) -> dict real, metadata. Regions list of [lo,hi],
  affine fit using only specified baseline windows, reject insufficient support.
- calculate_yield(product_area, standard_area, product_protons, standard_protons,
  standard_mol, limiting_mol, stoichiometric_factor=1.0) -> dict yield_percent,
  method, assumptions. Validate all positive and finite; no inferred stoichiometry.
- fit_relaxation(times, signals, time_unit, model, sigma=None,
  time_basis="elapsed", delay_multiplier=None) -> dict with model, status,
  time_s, signals, predicted, residuals, parameters, T_s, u_T_s,
  uncertainty_method, warnings, diagnostics.
  model is T1 or T2; T1 A-B*exp(-k*t), T2 C+A*exp(-k*t), k>0.
  T1 retains negative and zero signals. No per-trace normalization.
  Require explicit unit s/ms/us. T2 time_basis elapsed or echo_interval;
  echo_interval requires positive explicit multiplier. Unknown time basis fails.
  T_s may be null when unidentifiable; standard uncertainty is not a confidence
  interval. Diagnose flat, undersampled, repeated delays, ill-conditioned fits.
  T1 A and B positive, T2 A positive; C unrestricted. Respect signed integrals.
No learned model, paid inference or native Mnova dependency.

## Import seam (owned by format contributor)
load_input(path: str | Path) -> dict:
  spectra: list of {name, axis, real, imag, axis_unit, domain, nucleus, metadata};
  grids: list of {name, x, y, z, nuclei, metadata};
  tables: list of {name, columns: list[str], rows: list[dict[str,str]]};
  originals: list of {name: relative safe path, data: bytes};
  warnings: list[str].
Names are display names, not IDs. All originals are copied into project storage.
Spectrum domain frequency has ppm axis; time domain has s. Float64 finite,
monotonic axis and dimensions validated by core. Never silently FFT processed data.
Support qualified 1D JCAMP-DX, delimited CSV, Bruker 1D raw and processed directories;
support a zip wrapper with traversal/symlink/size/ratio checks. Processed 2D may be
included if verified. Raw 2D or unsupported JCAMP encoding must fail explicitly.
Bruker raw metadata: dwell_s, obs_mhz, carrier_ppm, group_delay and correction
provenance; nmrglue may correct documented digital filtering once before returning
FID. Stage and reader version retained. Limits: 32 MiB per original, 128 MiB
total input, 64 traces, 262144 points/trace, 1 million grid cells.
No online downloading, manual crawling or private fixtures in this repository.

## Coordinator-owned project/service seam
Spectrum has generated stable id plus version and import fields.
Project schema 1 contains spectra, grids, tables, integrals, series, analyses,
assignments and source manifests. Sources are immutable SHA-256 original blobs.
SQLite stores atomic snapshots, commands, responses and artifacts.
Mutation takes expected_revision and unique request_id. Replay of identical
payload returns its original receipt; different payload under that ID fails;
stale writes fail with current_revision and no changes.
Undo creates a new revision with a prior snapshot, preserving all old snapshots.
An integration or source edit marks dependent scientific analyses/assignments
stale. Fits and yield consume identified source objects and capture versions.
Human web and MCP tools call the same service. No hidden agent-only data model.
Operation-specific typed input/result validation is required behind compact tools.
Exports are immutable files from one named revision with size and SHA-256.
Public error: code, message, recoverable, current_revision where applicable.
No silent raw-path disclosure or binary/array dumping in normal MCP summaries.
