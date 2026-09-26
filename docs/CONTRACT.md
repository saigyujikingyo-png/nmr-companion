# Prerelease implementation contract
Version 2. First batch covers organic and physical chemistry together.
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
load_input(path: str | Path, *, bruker_processing_numbers: list[int] | None = None) -> dict:
  spectra: list of {name, axis, real, imag, axis_unit, domain, nucleus, metadata};
  grids: list of {name, x, y, z, nuclei, metadata, source_names};
  tables: list of {name, columns: list[str], rows: list[dict[str,str]]};
  originals: list of {name: relative safe path, data: bytes};
  warnings: list[str].
Names are display names, not IDs. All originals are copied into project storage.
Spectrum domain frequency has ppm axis; time domain has s. Float64 finite,
monotonic axis and dimensions validated by core. Never silently FFT processed data.
Support qualified 1D JCAMP-DX, delimited CSV, Bruker 1D raw and processed directories;
support a zip wrapper with traversal/symlink/size/ratio checks. Qualified processed
Bruker 2rr and COSY/HSQC JSON are included as specified in PROCESSED_2D_FORMATS.md. Raw 2D or unsupported JCAMP encoding must fail explicitly.
Bruker raw metadata: dwell_s, obs_mhz, carrier_ppm, group_delay and correction
provenance; nmrglue may correct documented digital filtering once before returning
FID. Stage and reader version retained. Limits: 32 MiB per original, 128 MiB
total input, 64 traces, 262144 points/trace, 1 million grid cells.
No online downloading, manual crawling or private fixtures in this repository.

## Coordinator-owned project/service seam
Spectrum has generated stable id plus version and import fields.
Project schema 2 contains spectra, grids, tables, integrals, analyses, assignments,
samples, structures, crosspeaks, peaklabels, attachments, annotations and source
manifests. A fitted series stores stable trace IDs, explicit table row mapping,
physical time convention, shared region and exclusions in its analysis parameters
and result mapping. Schema 1 is read-compatible, with backup-before-upgrade writes. Sources are immutable SHA-256 original blobs.
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


## Joint-batch evidence and delivery
See BATCH_ONE_CONTRACT.md for the additive command and object seam. Normalization
records relative proton values without modifying arrays. Yield/recovery propagates
explicit standard uncertainties and shared-standard covariance. Sample and
evidence versions drive transitive stale marking; evidence cycles are rejected.
DEPT matches require uniqueness in both directions. Structure status is explicit
human review, not automatic chemical proof.

Every generated analysis CSV includes analysis ID, state, source versions, project
revision and sample provenance. Source-table columns are prefixed with source. to
prevent collision with generated provenance. Exact source bytes and column names
remain in original blobs and the editable project. Numeric grids retain signs,
axis/nucleus identity and source dependencies.

Reference previews use serialized PDFium calls and bounded image decoding.
Authenticated HTTP exposes preserved originals and bounded PNG pages; references
never become numeric spectra. Export includes PNG/SVG figures and up to 32 selected
reference-page previews with an explicit coverage manifest; every original remains
included. Long nmr_read analysis tables are explicitly truncated at 64 rows; the
archive provides full values. Host receipt and file readback establish delivery.

## Explicit local file delivery

`nmr_export` accepts an optional absolute `destination` ending in `.zip`. Its
parent directory must already exist. The destination and its ancestors cannot
be symlinks or Windows reparse points. Existing files are rejected before export;
publication uses a temporary file and never replaces an existing destination.
The successful typed result includes `local_path`, byte size and SHA-256 after
reading the saved file back. With no destination, `local_path` is null and the
ordinary MCP resource link remains available. Do not equate a resource URI or
browser download request with verified file delivery. After uncertain completion,
inspect the named file and its hash before asking for another export.

An analysis with zero result rows exports a provenance-only CSV row with
`result_count=0`; it does not invent a peak or measurement. The exact empty result
array remains in the analysis JSON. This keeps an empty result attributable to
its project, revision, analysis, source versions and review state.
