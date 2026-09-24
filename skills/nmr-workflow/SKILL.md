---
name: nmr-workflow
description: Work with a shared local NMR project using qualified imports, explicit scientific inputs, organic integration and relaxation analysis.
---

# NMR Companion workflow
Developer alpha. Installed-host and full manual acceptance remain separate.
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

Unsupported format encodings, raw/processed 2D and private-course-specific claims
are not silently approximated. Do not imply vendor/university endorsement or
claim compatibility merely because the tool is listed.
