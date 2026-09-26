# Native Windows workbench

The primary frontend is a Qt Widgets Windows application. Open `NMR Companion.exe`
from the installed product directory. It needs no browser, WebView, network
listener or development project. The same saved `.nmrproj` is shared with MCP.

## Workspace

The left project explorer lists spectra, delay tables, integrals, analyses, samples,
structures, assignments, references and crosspeaks. Select an object to inspect its
original values, provenance, version and current/stale state. The right properties
dock and bottom numerical table can be resized, moved or hidden with the View menu.
A short guidance strip explains the selected evidence and its next action. Clear
text accompanies running, saved and needs-attention feedback; color never carries
the state alone. Keyboard focus, readable plot labels and compact 10-point text
keep the workspace navigable. An operation log records revision and request
receipts. Window layout persists in
a product-specific user INI file.

The central tabs show spectra, signed COSY/HSQC grids, editable candidate drawings,
reference pages, and stored fit predictions/residuals. Select compatible spectra
with Ctrl to overlay their original signed intensities. Chemical shift decreases
left to right; time increases. Mouse navigation changes only the view. Display
sampling preserves extrema, while calculations always use the original arrays.
Use Full range or F to reset the spectrum view. Move the region handles or enter
explicit numeric bounds in the analysis dialog.

## Scientific work

File > Import opens a native chooser for spectra, tables or qualified archives.
Explicit Bruker processing numbers are optional; no skipped profile is silently
qualified. File > Open and File > New use standard project dialogs. Existing files
are never replaced by New.

Analysis > Organic provides integration, relative protons, yield/recovery, signal
labels, signed peak detection and DEPT/carbon comparison. Analysis > Relaxation &
comparison provides explicit trace-to-delay mapping and condition comparison.
The mapping table requires every trace and CSV row, declared time units, model and
shared integration bounds. Optional uncertainty stays blank when unavailable;
no time meaning or trace normalization is inferred.

Analysis > Evidence provides sample conditions, candidate atoms/bonds and manual
stereochemical labels, evidence-linked assignments, 2D crosspeaks and PDF/image
annotations. References remain source documents; rectangular readings never
become numerical spectra. Structure and assignment status is an explicit human
interpretation, not automated molecular elucidation.

Double-check the selected object's stable identity before Edit selected object.
Editing a saved region or interpretation retains its identity and invalidates its
dependents. Rerunning an analysis creates a new analysis result. Restoring a saved
revision creates a new revision rather than deleting history.

## Shared edits, closing and delivery

Each submitted edit captures the observed revision and a durable request ID.
A conflicting edit fails without automatic replay. The GUI checks for external
MCP revisions and refreshes saved state; stale evidence remains visible. If a
write's outcome is uncertain, use Edit > Reconcile request before retrying.
Project switching and competing GUI writes are disabled during active operations.
Closing waits for the current operation to finish, then exits the window process.

File > Export revision captures the selected revision before showing a native
save dialog. Choose a new ZIP filename. The completed receipt shows path, bytes
and SHA-256; an existing file is preserved. The archive contains a reopenable
project, originals, JSON/CSV and scientific SVG/PNG figures.

| Shortcut | Action |
| --- | --- |
| Ctrl+N / Ctrl+O | New / open project |
| Ctrl+I / Ctrl+E | Import / export revision |
| Ctrl+Enter | Edit selected object |
| F5 / F | Refresh saved project / full spectrum range |
| Alt+F4 | Close the native window after active work finishes |

## Verification boundary

Automated Qt tests use isolated offscreen windows and synthetic data. Native
widget rendering, original coordinates/signs, command forms, conflicts, external
stale propagation, export readback and deferred close have separate checks.
Physical Windows interaction, actual instrument data and each agent host require
their own evidence. Prior [web interface checks](WORKBENCH_UI.md) are historical
and do not qualify this native frontend.
