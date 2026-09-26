# Legacy web spectrum workbench

This is the historical web interface record. Since 0.2.0-alpha.2, the delivered
Windows frontend is the [native Qt workbench](NATIVE_WORKBENCH.md). These browser
checks and the earlier Figma design do not qualify or define the native UI.

The workbench presents project data on the left, a spectrum and its computed
results in the centre, and the active analysis controls on the right. Organic,
relaxation, processing, assignment and advanced workflows share the same project
and selected spectrum. At narrower widths the inspector moves below the plot;
the workflow strip scrolls without widening the page.

## Spectrum interactions

| Control | Behaviour |
| --- | --- |
| Inspect / V | Read the axis coordinate under the pointer. Chemical shift decreases from left to right; elapsed time increases. |
| Zoom / Z | Drag across an interval to magnify it. Either drag direction works. |
| Pan / H | Drag the visible interval while retaining its width, bounded by the spectrum extent. |
| Back | Return to the preceding view; up to 24 view changes are retained per spectrum. |
| Full view / F | Show the entire spectrum and restore display gain to 1. |
| Gain minus / plus | Change displayed intensity scale only. |
| Visible range | Enter two distinct numeric bounds and apply a view. Bounds are ordered and clipped to the spectrum extent. |
| Integrate / I | In the organic workflow, drag to populate a new integral draft. Review the name and bounds, then choose Save integral. |
| Fit region / I | In relaxation, drag to populate the shared integration bounds. Review the explicit delay mapping and model, then choose Integrate & fit mapped traces. |
| Escape | Cancel an active gesture and return to Inspect. |

Keyboard shortcuts ignore text fields, numeric fields, selects and editable text.
The workflow tabs also support Left/Right and Home/End navigation. Numeric bounds
remain available when pointer gestures are unsuitable.

View changes do not create revisions or modify scientific arrays. Display sampling
retains minimum and maximum values, including narrow negative signals. All
integrals and fits use the full-resolution arrays in the numerical core.

## Drafts, saved results and shared edits

An integral brush populates a draft; it does not immediately change a saved region.
Use a saved region's Edit button to update that region's existing identity.
Integral drafts bind to a spectrum and object version. A source change clears the
visual draft. Relaxation bounds are a reusable recipe shared by the explicitly
mapped traces; selecting a different trace does not infer a new delay mapping.
Numeric edits to either set of bounds update its visual draft. Successful integral
or fit submission clears that draft.

Both forms use the same revision-checked commands as MCP. A stale revision fails
and refreshes the project; the frontend does not replay the rejected write.
Result cards retain their source versions, assumptions, uncertainty method and
current/stale status. Restoring a prior state creates a new revision.

## Design and assets

The [editable Figma design](https://www.figma.com/design/i45KoXbN8h7Bc6uX82vAFX?node-id=2-195)
is a synthetic desktop design reference, built from Simple Design System button,
input and tab instances, product colour variables and editable spectrum vectors.
It establishes the visual hierarchy; the running workbench supplies the complete
forms and scientific evidence tables.

The interaction reference is Mnova's
[practical analysis example](https://www.mestrelabcn.com/Manual_HTML_Mnova_15/practical_example.htm),
particularly region selection, separate analysis controls and reusable settings.
The independent NMR project and open numerical core remain the implementation.
The source includes an original interface and a local Inter font under OFL 1.1;
see [third-party notices](../THIRD_PARTY.md). There are no runtime CDN requests.

## Verified increment — 2026-09-25

- Windows CPython 3.12: 92 Python tests passed, including a real MCP subprocess,
  HTTP shared-state edits, offline asset responses, MIME/CSP and the Host boundary.
- Node: five geometry tests passed for axis direction, bounds, pan limits,
  signed extrema and interpolation across a view narrower than sample spacing.
- Ruff, JavaScript syntax and source/wheel build passed. The built wheel contains
  the view module, Inter WOFF2 font and its full licence.
- Actual in-app browser: drag zoom, pan, Back, Full view, numeric view bounds and
  organic brush/save were exercised. A 1.7–2.3 ppm brush saved the expected
  synthetic area of 0.338395 intensity·ppm in revision 8 of a review copy.
- Actual relaxation controls: loaded eight saved trace/delay mappings, displayed
  a negative trace and selected 3.7–4.3 ppm. The brush left revision 8 unchanged;
  explicit submission created revision 9 with T1 = 0.5 s. Numeric-bound changes
  and a second fit verified draft clearing in revision 10. Restoring the initial
  review state created revision 11 with the original two current analyses.
- Keyboard mode switching, input-field shortcut isolation and workflow-tab
  navigation were exercised. Desktop 1440×960, mobile 390×844 and the normal
  812-pixel in-app viewport were inspected. No page-level horizontal overflow
  or browser console errors/warnings were observed; the temporary viewport
  override was reset.
- The Figma frame was visually checked, including the final field and trace
  labels; all text uses Inter. Figma is design evidence, separate from browser
  execution and scientific acceptance.

This increment does not complete the whole first batch. Processed 2D/correlation
editing, graphical structure assignment, image/PDF evidence, condition comparison,
experimental qualification and installed-host delivery remain tracked in
[acceptance](ACCEPTANCE.md). The existing alpha release is a separate source
checkpoint; these UI changes do not update that published release automatically.

## First-batch evidence workflows — 2026-09-26 implementation

The batch extension adds labelled controls that submit the same revision-checked
commands as MCP. The original 1D view, signed T1/T2 fit, undo and export controls
remain available. At viewport widths of 1120 pixels or less, workflow tabs wrap
into visible rows and retain their tab roles and keyboard navigation.

| Workflow | Editable controls and shared result |
| --- | --- |
| Samples & conditions | Own, reference, synthetic or unknown role; owned spectra/grids/tables; material stage; parent samples and transformation; solvent, temperature in K, named additives and optional concentrations in mol L-1; source reference and notes. |
| Structure candidates | Atom creation from labelled x/y fields or canvas, selection and movement; stable atom labels/IDs; element, coordinates and stereochemical context; editable bond endpoints, single/double/triple/aromatic order and wedge/hash/either display; candidate alternatives, evidence and explicit review state. |
| 2D correlations | Processed-grid selection, explicit COSY/HSQC and x/y nucleus confirmation (including 15N), reference provenance, signed heatmap, nearest original-point readout, new crosspeak drafts and existing crosspeak edits. |
| Reference evidence | Preserve an authorized PDF/PNG/JPEG/WebP original, declare sample/role/category, preview a selected page, draw or numerically edit a rectangle, record an observation and optional approximate ppm reading with separate reading uncertainty. |
| Organic analysis | Manually positioned signal labels, multiplicity/proton interpretations, same-spectrum relative proton integration, recovered starting material and supplied yield-input standard uncertainties. |
| Processing | Explicit DEPT-135 / 13C matching prominence, ppm tolerance, phase/sign convention and reference; proposed evidence appears in a table. |
| Assignments | Link sample, saved candidate, stable atoms and numerical/image observations. A saved atom, crosspeak, signal label or page annotation can open a new assignment draft. Observation and evidence review precede saving. |
| Compare conditions | Explicit left/right sample and signal/fit correspondence, recorded conditions/reference conventions, right-minus-left difference, right/left ratio where defined, and independently justified uncertainty propagation. |

Drawings and annotations are drafts until their Save button is used. Source
objects and loaded editor objects are checked by identity and version; a refresh
that changes them clears the associated draft. An assignment draft also clears
when its saved object changes. Selecting another project clears the batch drafts.
The core remains authoritative for scientific validation, stale propagation and
revision conflicts. A rejected edit is not replayed automatically.

The 2D view has x decreasing from left to right and y increasing from top to
bottom. Original columns remain x and rows remain y even when either stored axis
is reversed. Rendering bins retain positive maxima and negative minima separately;
when both occupy a bin, separate pixel halves show each sign. The labelled display
cutoff and square-root colour scale change presentation only. Crosspeak intensity
comes from the nearest original grid point; all numerical analysis continues to
use the original full-resolution arrays.

Structure coordinates and stereochemical labels are reviewer-editable context.
The workbench does not perform automatic CIP assignment or confirm a structure
from a drawing. Existing candidates can be duplicated as proposed alternatives.
Assignments link saved atom identities; drawing changes must be saved before
linking the changed drawing to a new assignment.

Reference previews use authenticated requests followed by local Blob URLs; tokens
are never placed in preview URLs. Page coordinates are normalized from zero to
one, with a top-left origin and one-based page numbers. Approximate image readings
remain distinguishable from numerical spectra. The preserved original has a
separate download action. Download initiation is not proof of receipt or reopening.

The import form includes an optional Bruker processing-number list. Blank means
strict full-package decoding; an explicit comma-separated list selects processed
datasets to decode while preserving every original. Invalid, zero, negative or
duplicate numbers fail locally. The UI never selects a processing number or skips
a processing directory automatically.

Close workbench sends the authenticated `/api/quit` request and disables further
edits after the server acknowledges it. Saved project revisions remain in the
project database. Process exit, restart and installed-host behavior require their
separate lifecycle evidence.

### Focused frontend evidence

- `node --check src/nmr_companion/static/app.js`: passed.
- `node --check src/nmr_companion/static/batch.js`: passed.
- `node --test tests/frontend/*.test.cjs`: 12 passed (7 batch geometry/input checks
  and 5 existing 1D geometry checks) on Node 24.21.0.
- Batch checks cover axis orientation, reversed row/column storage, nearest
  original-point inspection, simultaneous positive/negative display extrema,
  bounded rectangle geometry, stable atom hit selection and explicit processing
  selection. They do not establish browser or scientific acceptance.

Live browser, package, installed-host, real instrument and artifact-reopening
acceptance are recorded separately by the product coordinator. This frontend
implementation record does not mark the joint 26-use-case batch complete.
