# NMR Companion
A local, editable NMR workbench with one project shared by people and AI tools.
**0.2.0-alpha.1 is a prerelease.** Scientific instrument and host qualification remain separately documented.

Organic and relaxation analysis are both in the first development batch.
The numerical core uses NumPy, SciPy and nmrglue. No Mnova licence or additional
model service is required. This independent project has no university or vendor endorsement.

## Windows installation
Download the x64 bundle from the [versioned GitHub Release](https://github.com/saigyujikingyo-png/nmr-companion/releases/tag/v0.2.0-alpha.1) and follow [installation and recovery](docs/INSTALLATION.md). The bundle includes its locked Python/scientific runtime; ordinary use needs no source checkout. Use Close workbench to stop the local server. Closing a browser tab alone does not stop it.

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
  New sample/condition records, editable structure candidates, stable atoms and
  assignments retain own/reference provenance, transformations and alternatives.
  Local hosts can pass an explicit new `.zip` destination to `nmr_export` and
  receive a verified local file link without replacing existing files.
  Bundles contain an actual reopenable `project.nmrproj`, JSON, scientific CSV tables, annotated SVG/PNG figures and hashes.

The three-pane workbench includes drag zoom, pan, signed spectrum display,
and region selection for both organic integration and relaxation fits.
See the [interaction guide and editable Figma design](docs/WORKBENCH_UI.md).

Processed COSY/HSQC import and crosspeak editing, signed DEPT-135 matching,
reference PDF/image annotations, relative proton normalization, recovered-material
yield and supplied uncertainty propagation are included. Condition comparison
requires explicit samples and corresponding observations. Raw 2D processing remains
unsupported. See [processed formats](docs/PROCESSED_2D_FORMATS.md).

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
it does not create a project until instructed. Host-specific validation is recorded
in the versioned release evidence.

## Verify
```sh
uv run ruff check .
uv run pytest -q
node --check src/nmr_companion/static/app.js
node --check src/nmr_companion/static/batch.js
node --test tests/frontend/*.test.cjs
uv build
```
Frontend checks require Node 22 or newer; Node is not a workbench runtime dependency.
Tests use synthetic public fixtures and a real local MCP subprocess. The Windows
cold-start test initializes scientific DLLs before the server reads requests.
GitHub CI targets Windows and Linux; configured CI is not a passing run.

## Scientific and delivery boundaries
No universal Bruker/JCAMP compatibility is claimed. Raw 2D and compressed/multiblock
JCAMP remain unsupported. Structural and stereochemical interpretation requires
qualified human review; the product does not automatically elucidate molecules. Do not infer T2 echo-time meaning or delay lists from a filename.
A real benchtop DX/CSV pair remains unverified. Private manuals and data are not
included and the product does not obtain university portal data.

A single-exponential fit is a model. Residual screens do not prove model adequacy,
and covariance uncertainty excludes acquisition and preparation systematics.
Stale results remain visible for traceability and must not be reported as current.

The source workflow requires developer setup; the Windows bundle is independent.
Schema 1 reads remain unchanged; a successful first new edit publishes a validated
schema 1 backup beside the project before committing schema 2. Software rollback
does not undo scientific history. Clean-device acceptance, remote/cloud binding,
named host/model workflows and the Terra max benchmark have separate gates.
See [acceptance](docs/ACCEPTANCE.md), [lifecycle](docs/LIFECYCLE.md),
[operation contract](docs/CONTRACT.md) and [third-party notices](THIRD_PARTY.md).
