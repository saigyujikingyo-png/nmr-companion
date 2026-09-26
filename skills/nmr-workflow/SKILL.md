---
name: nmr-workflow
description: Work with a shared local NMR project using qualified imports, explicit scientific inputs, organic integration and relaxation analysis.
---

# NMR Companion workflow
Prerelease. Consult docs/ACCEPTANCE.md for the current instrument, host and model evidence.
Use the configured NMR Companion tools; do not add a second paid reasoning service.

1. Call nmr_project for current project identity and revision. Create an empty
   project only when requested or implied by the analysis task.
2. Use nmr_help to discover the needed operation schema. Import only user-authorized
   local data. Preserve originals; never obtain university portal data implicitly.
3. Inspect imported objects and processing stage. FFT only raw time-domain complex
   data, not processed spectra. Use explicit phase and baseline choices.
4. Integrate selected regions with signed values. Internal-standard yield needs
   one acquired spectrum, separated quantitative regions, explicit proton counts,
   standard/limiting amounts in mol and stoichiometry. Report acquisition assumptions.
5. For T1/T2, map every spectrum to an explicit delay-table row. Require time units;
   T2 echo intervals need a supplied conversion multiplier. Preserve signs, trace
   scale, replicates and order. Do not invent delays, normalize traces separately
   or silently exclude observations.
6. Read fitted parameter uncertainty, residuals, warnings and model limitations.
   Null means unavailable, never zero. Uncertainty is a standard uncertainty, not
   automatically a confidence interval. Keep preliminary acquisitions labelled.
7. Cite existing evidence when proposing or confirming assignments. Treat stale
   analyses and assignments as historical until deliberately recomputed/reviewed.
8. For each edit, supply expected_revision and a unique request_id. On conflict
   refresh and reconsider. On uncertain completion call nmr_request; never blindly
   resubmit scientific work. An identical request replays its original receipt.
9. Export a named revision. Report its hash and actual delivery method separately.
   The ZIP includes a reopenable project and immutable source copies.

Unsupported format encodings, raw 2D and private-course-specific claims
are not silently approximated. Do not imply vendor/university endorsement or
claim compatibility merely because the tool is listed.


## Organic evidence and conditions
Use sample to record own/reference/synthetic/unknown provenance, material stages,
transformations, solvent, temperature in K, additives and reference conventions.
Relative proton normalization never rescales the numerical spectra; never use it
to independently normalize relaxation traces. Yield can include explicitly
identified recovered material and supplied standard uncertainties; the total
retains shared-standard covariance and missing uncertainty stays unavailable.

Processed COSY/HSQC imports require explicit nuclei and ppm axes. Bruker processing
numbers may be selected explicitly to avoid decoding unrelated profiles; all
originals remain preserved and skipped profiles are not qualified. Read metadata
before using grid_metadata to make any explicit user-supplied declaration.

Draw and revise structure candidates with stable atoms, bonds, manual stereo
labels and alternatives. Link assignments to actual observations; no automatic CIP
or structure elucidation is implied. DEPT polarity conventions require a declared
reference. Missing DEPT signal alone does not establish a quaternary carbon.
Competing matches remain ambiguous.

PDF/image pages and rectangles remain reference annotations, never numerical
spectra or quantitative integrals. External IR, HRMS and rotation records retain
their category and source role. Comparison requires explicit samples and signal
correspondence; propagated uncertainty requires an independence declaration.

## Delivery and runtime
The Windows bundle supplies its own runtime and stable launcher. GUI and MCP must
use the same absolute project. Supported plugin installation, tool discovery, real
model invocation and file delivery are separate checks. Other/cloud hosts need
their own qualification. Close workbench explicitly; closing only the browser tab
does not stop the local server.

Export a named revision with editable state, originals, CSV/JSON and SVG/PNG figures.
Check artifact hash and actual delivery. Long nmr_read tables may be truncated
explicitly; full results are in the archive. Reference previews have a 32-page
export limit with a coverage manifest; every original remains included.

## Delivering local exports

For a local host, call `nmr_export` with the accepted revision and an explicit
absolute `destination` for a new `.zip` file in an existing output directory.
Return its successful `local_path` as a clickable local file link, with its
revision and hash. Existing files are never overwritten. A default resource URI
or a browser download request alone does not establish a saved-file delivery.
If completion is uncertain, inspect the destination and compare bytes/hash before
retrying. Preserve any existing file; do not remove it merely to reuse its name.
The ZIP contains the editable database, original inputs, CSV and SVG/PNG figures.
