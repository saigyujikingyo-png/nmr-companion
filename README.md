# NMR Companion
A local, editable NMR workbench with one project shared by people and AI tools.
**0.1.0-alpha.1 is a developer preview, not a complete laboratory release.**

Organic and relaxation analysis are both in the first development batch.
The numerical core uses NumPy, SciPy and nmrglue. No Mnova licence or additional
model service is required. This independent project has no university or vendor endorsement.

## Working in this preview
- Import qualified Bruker 1D raw/processed spectra, numeric single-block 1D
  JCAMP-DX, CSV delay tables and checked ZIP wrappers. Preserve original bytes.
- Process complex FIDs, phase spectra, select affine baseline windows, reference
  ppm axes, detect signed peaks and edit integrals.
- Calculate internal-standard yield from explicitly supplied amounts, proton
  counts and stoichiometry. Acquisition suitability remains an assumption.
- Map spectra to explicit delay-table rows, integrate signed signals and fit T1
  or T2 with parameter standard uncertainty, residuals and diagnostic gates.
- Associate sample/atom/candidate assignments with evidence and proposed or
  confirmed status; mark derived work stale when its sources change.
- Share revision-controlled edits between the web workbench and MCP, reconcile
  uncertain requests, undo, reopen, and export immutable revision bundles.
  Bundles contain an actual reopenable `project.nmrproj`, JSON, CSV, SVG and hashes.

## Developer setup
Use Python 3.12 and [uv](https://docs.astral.sh/uv/).
```sh
uv sync --locked --group dev --python 3.12
uv run nmr-companion --project ./local/example.nmrproj create --name "NMR example"
uv run nmr-companion --project ./local/example.nmrproj web
```
Open the loopback URL printed by the command. The fragment contains a temporary
local session token; do not share that URL. The workbench runs only until stopped.
Create a synthetic demonstration from the empty workbench to try both workflows.
It is clearly labelled synthetic and is not experimental evidence.

For an MCP stdio frontend sharing the same project:
```sh
uv run nmr-companion --project ./local/example.nmrproj mcp
```
All edits require the observed revision and a request ID. Use `nmr_help` for
operation schemas; refresh conflicts and query `nmr_request` before retrying
uncertain edits. No agent has a separate hidden project.

The developer plugin manifest expects `nmr-companion` on the host's PATH.
Set `NMR_COMPANION_PROJECT` to the same absolute project path for GUI and MCP.
Without an explicit path, the CLI selects `~/NMR Companion/workspace.nmrproj`;
it does not create a project until instructed. Installed-host validation remains pending.

## Verify
```sh
uv run ruff check .
uv run pytest -q
uv build
```
Tests use synthetic public fixtures and a real local MCP subprocess. The Windows
cold-start test initializes scientific DLLs before the server reads requests.
GitHub CI targets Windows and Linux; configured CI is not a passing run.

## Scientific and delivery boundaries
No universal Bruker/JCAMP compatibility is claimed. Raw 2D, processed 2D import,
compressed/multiblock JCAMP, crosspeak editing, quantitative uncertainty for yield,
condition-comparison workflows and image/PDF evidence need further implementation
or qualification. Do not infer T2 echo-time meaning or delay lists from a filename.
A real benchtop DX/CSV pair remains unverified. Private manuals and data are not
included and the product does not obtain university portal data.

A single-exponential fit is a model. Residual screens do not prove model adequacy,
and covariance uncertainty excludes acquisition and preparation systematics.
Stale results remain visible for traceability and must not be reported as current.

This source preview requires developer setup. Bundled installation, upgrade and
removal, remote/cloud binding, named host/model workflows and the Terra max
benchmark have separate open acceptance gates.
See [acceptance](docs/ACCEPTANCE.md), [lifecycle](docs/LIFECYCLE.md),
[operation contract](docs/CONTRACT.md) and [third-party notices](THIRD_PARTY.md).
