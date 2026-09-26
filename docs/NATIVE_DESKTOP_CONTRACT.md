# Native Windows workbench contract

The user requires professional desktop software rather than a web frontend. The primary Windows frontend is a real Qt Widgets application (PySide6 Essentials), without a browser, WebView, HTTP listener, HTML or JavaScript. The existing optional web command remains a legacy developer route and is not the delivered desktop interface.

## Product behavior and layout

Use a compact Windows workbench: menu bar and flat toolbars, a project tree on the left, a large central spectrum/2D/reference/structure workspace, dockable property and result tables, a revision/status bar, and standard native file dialogs. Use restrained neutral backgrounds, dark blue selected traces, red negative features, compact typography and precise units. Avoid rounded marketing cards, hero text, oversized navigation and decorative whitespace. Normal scientific work must not require JSON or a browser. Readability is equally required: clear 10-point interface text, dark plot labels, restrained semantic colors accompanied by text, visible keyboard focus, concise context guidance and explicit busy/saved/needs-review feedback. Professional density must not hide controls or the next action.

The same Service and SQLite project remain authoritative. Native edits use expected revisions, durable unique request IDs and existing command validation; reload/reconcile after errors, never automatically replay uncertain writes. Explicit commits preserve originals and invalidate dependent evidence. The GUI reacts to external MCP revision changes. Closing a native window stops its own process; no scientific replay or new background owner is introduced.

A worker thread executes bounded Service calls while Qt's UI thread owns all widgets. Pending mutation state prevents competing GUI writes and project switching. Results/errors return on queued signals; busy close is deferred safely. File export uses the existing validated non-overwrite local-delivery API. Every numeric calculation uses original arrays, not display samples.

## Independent contributor seams

Coordinator owns desktop/__init__.py, desktop/app.py, desktop/main_window.py, application style/controller, CLI, dependencies, contracts and integration tests.

### Native dialogs (dialogs.py; tests/test_desktop_dialogs.py)

`CommandDialog(operation: str, project, parent=None, initial: dict | None=None)` is a QDialog. `command() -> dict` returns a command accepted by COMMAND.validate_python, or raises a useful ValueError before accepting. `get_command(operation, project, parent=None, initial=None) -> dict | None` runs the modal dialog and returns a valid command only on explicit acceptance. No Service calls, project mutations, QApplication creation or dependency edits in this module.

All joint-batch operations have native controls. Use object combos/multiselects retaining stable IDs, optional numeric controls with blank meaning unavailable, native path choosers, editable table rows for lists/atoms/bonds/conditions, and a dedicated fit mapping table preserving explicit trace-to-delay row mapping. Ordinary operations cannot require JSON. Preserve initial values when editing. Notes identify units, approximate image readings, signed relaxation and manual chemical interpretations. Fit mapping, optional uncertainty, enum choices and invalid values must be verified against independent expected commands.

### Native visualizations (plots.py; tests/test_desktop_plots.py)

Use PySide6 Widgets and pyqtgraph 0.14. No Service calls or project edits. Use read-only Pydantic objects from the current models.

- `SpectrumView(QWidget)`: `set_spectra(spectra: list, integrals: list | None=None, peaklabels: list | None=None)`, `set_region(lower, upper)`, `selected_region() -> tuple | None`, `reset_view()`. Signals `regionSelected(float,float)` and `positionSelected(float)`; left click can inspect, region selection is an explicit movable LinearRegionItem, mouse pan/zoom, ppm reversed and seconds forward. Multiple traces retain signs and scale. Nonlinear rescaling is display-only if supplied; no automatic normalization. Display decimation must preserve extrema.
- `GridView(QWidget)`: `set_grid(grid, crosspeaks: list | None=None)`, `reset_view()`. Signal `pointSelected(float,float)`. Correct x-column/y-row mapping, reversed ppm axes, nonuniform coordinate support, diverging signed colors, nearest-original-point cursor readout. Markers represent actual crosspeak positions.
- `StructureView(QWidget)`: `set_structure(structure)`. Signal `atomSelected(str)`. Draw stable atoms and bond order/wedge/hash, show proposed/confirmed and stale context; this display is not automatic chemistry inference.
- `ReferenceView(QWidget)`: `set_page(png_bytes: bytes, annotations: list | None=None)`. Signal `rectangleSelected(float,float,float,float)` with normalized page coordinates. Keep aspect ratio, zoom/scroll, draw saved rectangles; no image-to-spectrum conversion.
- `FitView(QWidget)`: `set_analysis(analysis)` shows fit/predicted signed signals and residuals from the existing result.

Controller can fall back to tables for an empty selection. Constructors accept `parent=None`. Initial empty state must render without sample data. GUI tests are isolated in a test QApplication and offscreen platform where needed; they do not operate unrelated user windows.

## Packaging and acceptance

Windows delivery needs a double-click .exe entrypoint, private pinned Python/Qt runtime, required upstream Qt/PySide/shiboken/pyqtgraph licenses and source notices, verified relocation and no development checkout. Bundled libraries stay dynamically replaceable under applicable open-source license terms. Installation, upgrade, rollback, project reopening, actual Codex project-variable forwarding, native widget/render tests and user-device interaction remain separate evidence. Existing web screenshots do not qualify the new native frontend.
