# Initial developer checkpoint — 2026-09-24
Version: 0.1.0-alpha.1 (Python package 0.1.0a1). This is an implementation
checkpoint for the joint first batch, not completion of all laboratory cases.

Fresh local verification on Windows / CPython 3.12.14:
- `uv run pytest -q`: **91 passed**.
- `uv run ruff check .`: passed.
- `uv run ruff format --check src tests`: 18 files already formatted.
- `node --check src/nmr_companion/static/app.js`: passed.
- `uv build`: wheel and source archive built; all three static assets present in the wheel.
- Plugin manifest validator: passed using its temporary YAML validation dependency.

The tests exercise analytic integration/FFT/phase/baseline, signed peaks,
internal-standard yield, T1/T2 parameter recovery, independently profiled
weighted fitting/covariance, bad data and model diagnostics, qualified formats,
original-byte preservation and filename aliases, exact source binding,
transactions, concurrent frontends, idempotency, undo/reopen, output contracts
and real MCP stdio discovery/calls/resource bytes.

Interactive workbench evidence:
1. Loaded an explicitly synthetic organic + T1 demonstration through normal controls.
2. Defined product and standard regions; obtained the expected 100% yield.
3. Explicitly mapped eight spectra to delay rows; obtained T1 = 0.5 s, retaining
   negative areas and displaying residuals and covariance-method metadata.
4. Changed the product integral through a separate real MCP subprocess.
   The browser's stale write was rejected; the yield became stale.
5. Restored the earlier state as a new revision, restarted the runtime, reopened
   the project and loaded its saved analysis settings and eight row mappings.
6. Generated a named-revision export; independently read its bytes by hash,
   extracted its project database and reopened nine spectra and two current analyses.
   Browser download was requested without console errors, but the in-app download
   event was not observed; this route is **not accepted as completed delivery**.

One authorized private raw/processed Bruker example was checked locally by its
previous hash. The direction/reference of principal magnitude peaks agreed to
about 0.0002 ppm. This is limited axis evidence; it is not quantitative, phase,
native Mnova or broad instrument acceptance. No private fixture is included here.

Observed and fixed during this checkpoint:
- Cold Windows MCP invocation stalled while lazily loading the SciPy BLAS DLL
  after stdio threads were active. Scientific dependencies now initialize before
  request handling; the cold subprocess regression passes.
- Equal-byte replicate inputs lost one filename in a hash-keyed source manifest.
  Storage deduplicates bytes while retaining all names and separate trace IDs.
- Each object now binds to its own data/required metadata rather than every file
  in an imported bundle.
- ZIP separator checks now inspect original entry names consistently across platforms.

The dedicated cloud setup/profile is prepared. Saved Codex cloud-environment
creation and execution are not established by these local checks. The accessible
legacy environment-settings URL redirected to a workspace home page without an
environment creation entry. No account settings, caches or internal registrations
were changed to work around that.

CI run results, source Git references, package checksums and public delivery are
recorded separately when available. Named AI-host calls, Terra max benchmarking,
bundled installation, upgrades/removal and full first-batch acceptance remain open.
