"""Professional native workbench over the shared transactional project service."""

from __future__ import annotations
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
import hashlib
from uuid import uuid4

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDockWidget,
    QFileDialog,
    QFrame,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableView,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QWidget,
)
from ..api import dispatch
from ..commands import OPERATIONS
from ..errors import NmrError
from ..service import Service
from .presentation import ScientificTable, display
from .plots import SpectrumView, GridView, StructureView, ReferenceView, FitView

COLLECTIONS = (
    ("spectra", "Spectra"),
    ("grids", "2D correlations"),
    ("tables", "Delay / data tables"),
    ("integrals", "Integrals"),
    ("peaklabels", "Signal labels"),
    ("analyses", "Analyses"),
    ("samples", "Samples & conditions"),
    ("structures", "Structure candidates"),
    ("assignments", "Assignments"),
    ("attachments", "Reference documents"),
    ("annotations", "Reference annotations"),
    ("crosspeaks", "Crosspeaks"),
)
TITLES = {
    "import": "Import data",
    "integrate": "Integrate region",
    "normalize": "Relative protons",
    "yield": "Yield / recovery",
    "peak_label": "Signal label",
    "peaks": "Detect peaks",
    "fit": "T1 / T2 relaxation",
    "process": "Process spectrum",
    "sample": "Sample & conditions",
    "structure": "Structure candidate",
    "assign": "Assignment",
    "crosspeak": "Crosspeak",
    "grid_metadata": "Declare 2D metadata",
    "attach": "Attach reference",
    "annotate": "Annotate reference",
    "compare": "Compare conditions",
    "dept": "DEPT / carbon",
    "undo": "Restore revision",
}
EDIT_OPERATIONS = {
    "integrals": ("integrate", "integral_id"),
    "peaklabels": ("peak_label", "peaklabel_id"),
    "samples": ("sample", "sample_id"),
    "structures": ("structure", "structure_id"),
    "assignments": ("assign", "assignment_id"),
    "crosspeaks": ("crosspeak", "crosspeak_id"),
    "annotations": ("annotate", "annotation_id"),
}


class WorkerSignals(QObject):
    finished = Signal(object, object)


class Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        try:
            result = self.operation()
            self.signals.finished.emit(result, None)
        except Exception as exc:
            self.signals.finished.emit(None, exc)


class MainWindow(QMainWindow):
    projectChanged = Signal(int)
    operationFinished = Signal(str, bool)

    def __init__(self, service, project=None, parent=None, *, settings=None, auto_refresh=True):
        super().__init__(parent)
        self.service = service
        self.project = project if project is not None else service.read()
        self.settings = settings
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(2)
        self.busy = False
        self.pending_request = None
        self.last_request = ""
        self._poll_error = None
        self._worker = None
        self._poll_worker = None
        self._close_requested = False
        self._closed = False
        self._modal_depth = 0
        self.selected_id = None
        self.selected_collection = None
        self._position = None
        self._grid_position = None
        self._rectangle = None
        self._reference_context = None
        self._mutation_actions = []
        self.resize(1440, 920)
        self.setDockNestingEnabled(True)
        self._build_workspace()
        self._build_docks()
        self._build_actions()
        self._build_status()
        self.render_project()
        if settings:
            geometry = settings.value("native/geometry")
            layout = settings.value("native/layout")
            if geometry:
                self.restoreGeometry(geometry)
            if layout:
                self.restoreState(layout, 1)
        self.timer = QTimer(self)
        self.timer.setInterval(1800)
        self.timer.timeout.connect(self.poll_revision)
        if auto_refresh:
            self.timer.start()

    def _build_workspace(self):
        self.workspace = QTabWidget(self)
        self.workspace.setObjectName("ScientificWorkspace")
        self.spectrum_view = SpectrumView()
        self.grid_view = GridView()
        self.structure_view = StructureView()
        self.reference_view = ReferenceView()
        self.fit_view = FitView()
        self.workspace.addTab(self.spectrum_view, "Spectrum")
        self.workspace.addTab(self.grid_view, "2D correlation")
        self.workspace.addTab(self.structure_view, "Structure")
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_controls = QHBoxLayout()
        page_controls.addWidget(QLabel("Reference page"))
        self.reference_page = QSpinBox()
        self.reference_page.setRange(1, 1)
        page_controls.addWidget(self.reference_page)
        page_controls.addStretch()
        page_layout.addLayout(page_controls)
        page_layout.addWidget(self.reference_view, 1)
        self.workspace.addTab(page, "Reference")
        self.workspace.addTab(self.fit_view, "Fit / residuals")
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        guide = QFrame()
        guide.setObjectName("ContextGuide")
        guide_layout = QHBoxLayout(guide)
        guide_layout.setContentsMargins(6, 4, 6, 4)
        self.guide_text = QLabel()
        self.guide_text.setObjectName("ContextText")
        self.guide_text.setTextFormat(Qt.TextFormat.PlainText)
        self.guide_text.setWordWrap(True)
        self.guide_action = QPushButton()
        self.guide_action.setAccessibleName("Suggested next action")
        self._guide_operation = "import"
        self.guide_action.clicked.connect(self._run_guide_action)
        guide_layout.addWidget(self.guide_text, 1)
        guide_layout.addWidget(self.guide_action)
        layout.addWidget(guide)
        layout.addWidget(self.workspace, 1)
        self.setCentralWidget(container)
        self.spectrum_view.regionSelected.connect(self._region_changed)
        self.spectrum_view.positionSelected.connect(self._position_changed)
        self.grid_view.pointSelected.connect(self._grid_position_changed)
        self.reference_view.rectangleSelected.connect(self._rectangle_changed)
        self.structure_view.atomSelected.connect(self._atom_selected)
        self.reference_page.valueChanged.connect(self._reference_page_changed)

    def _dock(self, title, name, widget, area):
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    def _build_docks(self):
        browser = QWidget()
        box = QVBoxLayout(browser)
        box.setContentsMargins(4, 4, 4, 4)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filter project objects")
        self.search.setClearButtonEnabled(True)
        box.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Project object", "State"])
        self.tree.setColumnWidth(0, 225)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.tree.itemSelectionChanged.connect(self._overlay_selected)
        self.search.textChanged.connect(self._filter_tree)
        box.addWidget(self.tree)
        self.project_dock = self._dock(
            "Project explorer", "ProjectExplorer", browser, Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.properties = QTreeWidget()
        self.properties.setHeaderLabels(["Parameter / evidence", "Value"])
        self.properties.setAlternatingRowColors(True)
        self.properties.setColumnWidth(0, 155)
        property_container = QWidget()
        property_box = QVBoxLayout(property_container)
        property_box.setContentsMargins(4, 4, 4, 4)
        property_box.addWidget(self.properties)
        self.edit_button = QPushButton("Edit selected object…")
        self.edit_button.clicked.connect(self.edit_selected)
        property_box.addWidget(self.edit_button)
        self.property_dock = self._dock(
            "Properties & provenance",
            "Properties",
            property_container,
            Qt.DockWidgetArea.RightDockWidgetArea,
        )
        result_tabs = QTabWidget()
        self.result_table = QTableView()
        self.result_model = ScientificTable()
        self.result_table.setModel(self.result_model)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self.result_table.horizontalHeader().setStretchLastSection(False)
        self.result_model.modelReset.connect(self._size_result_columns)
        result_tabs.addTab(self.result_table, "Results / selected data")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(500)
        result_tabs.addTab(self.log, "Operation log")
        self.result_dock = self._dock(
            "Scientific results", "Results", result_tabs, Qt.DockWidgetArea.BottomDockWidgetArea
        )
        self.resizeDocks(
            [self.project_dock, self.property_dock], [280, 355], Qt.Orientation.Horizontal
        )
        self.resizeDocks([self.result_dock], [230], Qt.Orientation.Vertical)

    def _action(self, text, function, shortcut=None, *, mutation=False):
        action = QAction(text, self)
        action.triggered.connect(lambda checked=False: function())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if mutation:
            self._mutation_actions.append(action)
        return action

    def _command_action(self, operation):
        return self._action(
            TITLES[operation] + "…", lambda: self.command_dialog(operation), mutation=True
        )

    def _build_actions(self):
        file_menu = self.menuBar().addMenu("&File")
        self.new_action = self._action("&New project…", self.new_project, "Ctrl+N", mutation=True)
        self.open_action = self._action(
            "&Open project…", self.open_project, "Ctrl+O", mutation=True
        )
        self.import_action = self._command_action("import")
        self.import_action.setShortcut(QKeySequence("Ctrl+I"))
        self.export_action = self._action(
            "&Export revision…", self.export_revision, "Ctrl+E", mutation=True
        )
        for action in (self.new_action, self.open_action, self.import_action, self.export_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("Close", self.close, "Alt+F4"))
        edit = self.menuBar().addMenu("&Edit")
        self.edit_action = self._action(
            "Edit selected object…", self.edit_selected, "Ctrl+Return", mutation=True
        )
        edit.addAction(self.edit_action)
        self.remove_action = self._action(
            "Remove selected object…", self.remove_selected, mutation=True
        )
        edit.addAction(self.remove_action)
        edit.addAction(self._command_action("undo"))
        edit.addSeparator()
        edit.addAction(self._action("Reconcile request…", self.reconcile_request))
        analysis = self.menuBar().addMenu("&Analysis")
        for title, operations in (
            ("Organic", ("integrate", "normalize", "yield", "peak_label", "peaks", "dept")),
            ("Relaxation & comparison", ("fit", "compare")),
            (
                "Evidence",
                (
                    "sample",
                    "structure",
                    "assign",
                    "crosspeak",
                    "grid_metadata",
                    "attach",
                    "annotate",
                ),
            ),
        ):
            sub = analysis.addMenu(title)
            for operation in operations:
                sub.addAction(self._command_action(operation))
        analysis.addAction(self._command_action("process"))
        view = self.menuBar().addMenu("&View")
        self.refresh_action = self._action("Refresh saved project", self.refresh, "F5")
        view.addAction(self.refresh_action)
        view.addAction(self._action("Full spectrum range", self.spectrum_view.reset_view, "F"))
        for dock in (self.project_dock, self.property_dock, self.result_dock):
            view.addAction(dock.toggleViewAction())
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(
            self._action("Create synthetic demonstration…", self.demo, mutation=True)
        )
        help_menu.addAction(self._action("About NMR Companion", self.about))
        toolbar = QToolBar("Project and analysis", self)
        toolbar.setObjectName("MainToolbar")
        toolbar.setMovable(True)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.addToolBar(toolbar)
        for action in (
            self.open_action,
            self.import_action,
            self.export_action,
            self.refresh_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        for operation in ("integrate", "normalize", "fit", "peak_label", "assign"):
            toolbar.addAction(self._command_action(operation))
        toolbar.addSeparator()
        toolbar.addAction(self._action("Full range", self.spectrum_view.reset_view))

    def _build_status(self):
        self.path_label = QLabel(str(self.service.store.path))
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.revision_label = QLabel()
        self.operation_state = QLabel("Ready")
        self.operation_state.setObjectName("OperationStatus")
        self.operation_state.setAccessibleName("Operation status")
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(110)
        self.progress.setVisible(False)
        self.statusBar().addWidget(self.path_label, 1)
        self.statusBar().addPermanentWidget(self.progress)
        self.statusBar().addPermanentWidget(self.operation_state)
        self.statusBar().addPermanentWidget(self.revision_label)

    @contextmanager
    def _modal(self):
        self._modal_depth += 1
        try:
            yield
        finally:
            self._modal_depth -= 1

    def _operation_feedback(self, state, message):
        self.operation_state.setProperty("state", state)
        self.operation_state.setText(message)
        self.operation_state.style().unpolish(self.operation_state)
        self.operation_state.style().polish(self.operation_state)

    def _size_result_columns(self):
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
            if self.result_model.columnCount() <= 6
            else QHeaderView.ResizeMode.Interactive
        )
        if self.result_model.columnCount() > 6:
            header.setDefaultSectionSize(135)

    def _run_guide_action(self):
        if self._guide_operation == "edit_selected":
            self.edit_selected()
        else:
            self.command_dialog(self._guide_operation)

    def _update_guide(self, collection, obj):
        text = "Start with instrument spectra and, for relaxation, the matching delay table. Originals are preserved."
        operation, action = "import", "Import data…"
        if obj is not None:
            if collection == "spectra":
                if obj.domain == "time":
                    text = "Time-domain data. Review acquisition metadata, then Fourier transform to create a spectrum."
                    operation, action = "process", "Process spectrum…"
                else:
                    text = "Inspect the axis and signed signal. Select a region, then review its bounds before saving."
                    operation, action = "integrate", "Integrate region…"
            elif collection == "tables":
                text = "Review the original delay values and units. Map each trace to its measured delay before fitting."
                operation, action = "fit", "Map traces & fit…"
            elif collection == "grids":
                text = "Blue is positive and red is negative. Click a correlation, then record its coordinates and label."
                operation, action = "crosspeak", "Record crosspeak…"
            elif collection in ("attachments", "annotations"):
                text = "Reference document. Select a rectangle; record readings and uncertainty as approximate evidence."
                operation, action = (
                    ("edit_selected", "Edit annotation…")
                    if collection == "annotations"
                    else ("annotate", "Annotate reference…")
                )
            elif collection == "integrals":
                text = "Saved signed area. Review the region or use an explicit reference to calculate relative protons."
                operation, action = "normalize", "Relative protons…"
            elif collection == "analyses":
                text = "Review the result, uncertainty and residuals. Edit parameters to save a new analysis."
                operation, action = "edit_selected", "Review parameters…"
            elif collection in EDIT_OPERATIONS:
                text = "Review this interpretation and its supporting evidence. Edits keep the object's identity."
                operation, action = "edit_selected", "Edit selected…"
            if getattr(obj, "state", "") == "stale":
                text = (
                    "Needs review: supporting data changed. This saved result is historical. "
                    + text
                )
        elif collection and getattr(self.project, collection):
            text = "Select an object to inspect its values, provenance and saved state. Use Ctrl to overlay compatible spectra."
        self.guide_text.setText(text)
        self.guide_action.setText(action)
        self._guide_operation = operation

    def _append_log(self, text):
        self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {text}")

    def _set_busy(self, state):
        self.busy = state
        self.progress.setVisible(state)
        for action in self._mutation_actions:
            action.setEnabled(not state)
        self.guide_action.setEnabled(not state)
        self.edit_button.setEnabled(not state)
        self.tree.setEnabled(not state)
        self.reference_page.setEnabled(not state)

    def start_operation(self, title, function, on_success, *, request_id=None):
        if self.busy:
            return False
        self._set_busy(True)
        self.pending_request = request_id
        if request_id:
            self.last_request = request_id
        self._operation_feedback("busy", title + "…")
        self.statusBar().showMessage(title)
        self._append_log(title + (f" · request {request_id}" if request_id else ""))
        worker = Worker(function)
        self._worker = worker

        def finished(result, error):
            self._worker = None
            self._set_busy(False)
            if error is None:
                try:
                    on_success(result)
                except Exception as exc:
                    # A committed write remains committed if presentation fails.
                    error = NmrError(
                        "PRESENTATION_FAILED",
                        f"The operation finished but its view could not be updated: {exc}",
                    )
            if error is None:
                if not self.busy:
                    self._operation_feedback(
                        "ready",
                        f"Saved revision {self.project.revision}"
                        if request_id
                        else "Ready · " + title,
                    )
                self.operationFinished.emit(title, True)
            else:
                code = getattr(error, "code", "EXECUTION_FAILED")
                message = getattr(error, "message", str(error))
                detail = f"{code}: {message}"
                if request_id:
                    detail += f"\nRequest: {request_id}\nUse Edit > Reconcile request before retrying an uncertain operation."
                self._append_log(detail)
                self._operation_feedback(
                    "attention", "Needs attention · " + str(code).replace("_", " ").lower()
                )
                if code == "REVISION_CONFLICT":
                    self.revision_label.setText(
                        f"Revision {self.project.revision}  |  Refresh required"
                    )
                QMessageBox.warning(self, title, detail)
                self.operationFinished.emit(title, False)
            self.pending_request = None
            self.statusBar().clearMessage()
            if self._close_requested:
                self.close()

        worker.signals.finished.connect(finished, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)
        return True

    def render_project(self, preferred_id=None):
        preferred_id = preferred_id or self.selected_id
        self.spectrum_view.set_spectra([])
        self.grid_view.set_grid(None)
        self.structure_view.set_structure(None)
        self.fit_view.set_analysis(None)
        self.reference_view.clear()
        self._reference_context = None
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            selected = None
            first = None
            for collection, title in COLLECTIONS:
                items = getattr(self.project, collection)
                group = QTreeWidgetItem([f"{title} ({len(items)})", ""])
                group.setData(0, Qt.ItemDataRole.UserRole, (collection, None))
                self.tree.addTopLevelItem(group)
                for obj in items.values():
                    label = getattr(
                        obj, "name", getattr(obj, "label", getattr(obj, "atom", obj.id))
                    )
                    state = getattr(obj, "state", "")
                    item = QTreeWidgetItem([label, state])
                    item.setData(0, Qt.ItemDataRole.UserRole, (collection, obj.id))
                    item.setToolTip(0, f"{obj.id} · version {obj.version}")
                    if state == "stale":
                        item.setForeground(1, QColor("#956500"))
                    group.addChild(item)
                    first = first or item
                    if obj.id == preferred_id:
                        selected = item
                group.setExpanded(bool(items))
            if selected or first:
                self.tree.setCurrentItem(selected or first)
        finally:
            self.tree.blockSignals(False)
        self.setWindowTitle(f"{self.project.name} — NMR Companion")
        self.path_label.setText(str(self.service.store.path))
        self.revision_label.setText(f"Revision {self.project.revision}  |  Saved")
        self._filter_tree(self.search.text())
        self._selection_changed(self.tree.currentItem(), None)
        self.projectChanged.emit(self.project.revision)

    def _filter_tree(self, text):
        needle = text.casefold()
        for index in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(index)
            count = 0
            for row in range(group.childCount()):
                child = group.child(row)
                match = needle in child.text(0).casefold() or needle in child.toolTip(0).casefold()
                child.setHidden(not match)
                count += match
            group.setHidden(bool(needle) and count == 0)

    def _selection_changed(self, current, previous):
        if current is None:
            self.selected_id = self.selected_collection = None
            self.properties.clear()
            self.result_model.replace([], [])
            self._update_guide(None, None)
            return
        collection, identifier = current.data(0, Qt.ItemDataRole.UserRole)
        self.selected_collection, self.selected_id = collection, identifier
        self._position = self._grid_position = self._rectangle = None
        self._reference_context = None
        if identifier is None:
            self._collection_table(collection)
            self.properties.clear()
            self._update_guide(collection, None)
            return
        obj = getattr(self.project, collection)[identifier]
        self._update_guide(collection, obj)
        self._show_properties(obj)
        self._show_results(obj, collection)
        if collection == "spectra":
            self._overlay_selected()
            self.workspace.setCurrentIndex(0)
        elif collection == "grids":
            crosspeaks = [v for v in self.project.crosspeaks.values() if v.grid_id == identifier]
            self.grid_view.set_grid(obj, crosspeaks)
            self.workspace.setCurrentIndex(1)
        elif collection == "structures":
            self.structure_view.set_structure(obj)
            self.workspace.setCurrentIndex(2)
        elif collection == "attachments":
            self._show_reference(obj, 1)
        elif collection == "annotations":
            attachment = self.project.attachments.get(obj.attachment_id)
            if attachment:
                self._show_reference(attachment, obj.page)
        elif collection == "crosspeaks":
            grid = self.project.grids.get(obj.grid_id)
            if grid:
                self.grid_view.set_grid(
                    grid, [v for v in self.project.crosspeaks.values() if v.grid_id == grid.id]
                )
                self.workspace.setCurrentIndex(1)
        elif collection == "assignments" and obj.candidate_id:
            candidate = self.project.structures.get(obj.candidate_id)
            if candidate:
                self.structure_view.set_structure(candidate)
                self.workspace.setCurrentIndex(2)
        elif collection == "analyses" and obj.kind == "relaxation":
            self.fit_view.set_analysis(obj)
            self.workspace.setCurrentIndex(4)
        elif collection in ("integrals", "peaklabels"):
            spectrum = self.project.spectra.get(obj.spectrum_id)
            if spectrum:
                self.spectrum_view.set_spectra(
                    [spectrum],
                    [v for v in self.project.integrals.values() if v.spectrum_id == spectrum.id],
                    [v for v in self.project.peaklabels.values() if v.spectrum_id == spectrum.id],
                )
                if collection == "integrals":
                    self.spectrum_view.set_region(obj.lower, obj.upper)
                self.workspace.setCurrentIndex(0)

    def _overlay_selected(self):
        selected = []
        for item in self.tree.selectedItems():
            collection, identifier = item.data(0, Qt.ItemDataRole.UserRole)
            if collection == "spectra" and identifier:
                selected.append(self.project.spectra[identifier])
        if not selected:
            return
        # Different nuclei/domains never share one unlabelled numerical axis.
        first = next((s for s in selected if s.id == self.selected_id), selected[0])
        compatible = [first] + [
            s
            for s in selected
            if s.id != first.id
            and (s.domain, s.axis_unit, s.nucleus) == (first.domain, first.axis_unit, first.nucleus)
        ]
        if len(compatible) != len(selected):
            self.statusBar().showMessage(
                "Overlay contains only matching nucleus, domain and axis units.", 7000
            )
        ids = {s.id for s in compatible}
        self.spectrum_view.set_spectra(
            compatible,
            [v for v in self.project.integrals.values() if v.spectrum_id in ids],
            [v for v in self.project.peaklabels.values() if v.spectrum_id in ids],
        )

    def _show_properties(self, obj):
        self.properties.clear()
        body = obj.model_dump(mode="json")
        for key in ("axis", "real", "imag", "x", "y", "z"):
            value = body.get(key)
            if isinstance(value, list):
                body[key] = f"{len(value)} values; original numerical data retained"

        def add(parent, key, value):
            item = QTreeWidgetItem([str(key).replace("_", " "), ""])
            parent.addChild(item) if isinstance(
                parent, QTreeWidgetItem
            ) else parent.addTopLevelItem(item)
            if isinstance(value, dict):
                for name, child in value.items():
                    add(item, name, child)
            elif isinstance(value, list):
                item.setText(1, f"{len(value)} items")
                for index, child in enumerate(value[:32]):
                    add(item, index + 1, child)
                if len(value) > 32:
                    item.addChild(
                        QTreeWidgetItem(
                            ["Preview", "First 32 items; use results or export for all values"]
                        )
                    )
            else:
                item.setText(1, display(value))
                item.setToolTip(1, display(value))

        for key, value in body.items():
            add(self.properties, key, value)
        for source_id in getattr(obj, "source_ids", []):
            source = self.project.sources.get(source_id)
            if source:
                add(self.properties, "Original source", source.model_dump(mode="json"))
        self.properties.expandToDepth(0)

    def _collection_table(self, collection):
        rows = []
        for obj in getattr(self.project, collection).values():
            rows.append(
                [
                    getattr(obj, "name", getattr(obj, "label", getattr(obj, "atom", ""))),
                    getattr(obj, "state", ""),
                    obj.version,
                    obj.id,
                ]
            )
        self.result_model.replace(["Name / label", "State", "Version", "Stable ID"], rows)

    def _show_results(self, obj, collection):
        if collection == "tables":
            self.result_model.replace(
                obj.columns, [[row.get(k, "") for k in obj.columns] for row in obj.rows]
            )
        elif collection == "spectra":
            headers = [f"Axis / {obj.axis_unit}", "Signed real intensity"]
            rows = [[x, y] for x, y in zip(obj.axis, obj.real)]
            if obj.imag is not None:
                headers.append("Imaginary intensity")
                for row, value in zip(rows, obj.imag):
                    row.append(value)
            self.result_model.replace(headers, rows)
        elif collection == "analyses":
            result = obj.result
            if obj.kind == "relaxation":
                keys = ["time_s", "signals", "predicted", "residuals"]
                columns = [result.get(key, []) for key in keys]
                count = max((len(values) for values in columns), default=0)
                rows = [
                    [values[index] if index < len(values) else None for values in columns]
                    for index in range(count)
                ]
                self.result_model.replace(
                    ["Elapsed time / s", "Signed area", "Predicted", "Residual"], rows
                )
            else:
                vectors = next(
                    (
                        result[k]
                        for k in ("integrals", "rows", "peaks")
                        if isinstance(result.get(k), list)
                    ),
                    None,
                )
                if vectors:
                    headers = list(vectors[0])
                    self.result_model.replace(
                        headers, [[row.get(k) for k in headers] for row in vectors]
                    )
                else:
                    self.result_model.replace(
                        ["Result", "Value"], [[key, value] for key, value in result.items()]
                    )
        elif collection == "grids":
            self.result_model.replace(
                [f"y / {obj.nuclei[1]} ppm"] + [f"{x:.6g} ppm" for x in obj.x],
                [[y, *values] for y, values in zip(obj.y, obj.z)],
            )
        else:
            self.result_model.replace(
                ["Property", "Value"], [[k, v] for k, v in obj.model_dump(mode="json").items()]
            )

    def _region_changed(self, lower, upper):
        self.statusBar().showMessage(
            f"Selected region: {lower:.6g}–{upper:.6g}. Use Integrate or T1 / T2 to commit.", 7000
        )

    def _position_changed(self, position):
        self._position = position
        self.statusBar().showMessage(
            f"Signal position: {position:.7g}. Use Signal label to record an interpretation.", 7000
        )

    def _grid_position_changed(self, x, y):
        self._grid_position = (x, y)
        self.statusBar().showMessage(
            f"2D position: {x:.7g}, {y:.7g} ppm. Use Analysis > Evidence > Crosspeak to save.", 7000
        )

    def _rectangle_changed(self, x, y, width, height):
        self._rectangle = (x, y, width, height)
        self.statusBar().showMessage(
            "Reference region selected. Use Analysis > Evidence > Annotate reference to save.", 7000
        )

    def _atom_selected(self, atom_id):
        self.statusBar().showMessage(
            f"Selected atom {atom_id}; assignments require explicit observation evidence.", 7000
        )

    def _show_reference(self, attachment, page):
        self.reference_page.blockSignals(True)
        self.reference_page.setRange(1, attachment.pages)
        self.reference_page.setValue(page)
        self.reference_page.blockSignals(False)
        self.workspace.setCurrentIndex(3)
        self._reference_context = (attachment.id, page)
        self._load_reference(attachment, page)

    def _reference_page_changed(self, page):
        self._rectangle = None
        if self._reference_context:
            attachment = self.project.attachments.get(self._reference_context[0])
            if attachment:
                self._reference_context = (attachment.id, page)
                self._load_reference(attachment, page)

    def _load_reference(self, attachment, page):
        self.reference_view.clear()
        service = self.service
        annotations = [
            a
            for a in self.project.annotations.values()
            if a.attachment_id == attachment.id and a.page == page
        ]

        def render():
            from ..media import reference_png

            with service.store.connection() as db:
                row = db.execute(
                    "SELECT data FROM originals WHERE sha256=?", (attachment.source_id,)
                ).fetchone()
            if row is None or hashlib.sha256(row[0]).hexdigest() != attachment.source_id:
                raise NmrError("SOURCE_INTEGRITY", "Reference original is missing or changed.")
            return reference_png(row[0], attachment.media_type, page)

        def loaded(data):
            if (
                self._reference_context == (attachment.id, page)
                and self.reference_page.value() == page
            ):
                self.reference_view.set_page(data, annotations)

        self.start_operation("Render reference page", render, loaded)

    def _context_menu(self, point):
        if not self.selected_id:
            return
        menu = QMenu(self)
        menu.addAction(self.edit_action)
        menu.addAction(self.remove_action)
        menu.exec(self.tree.viewport().mapToGlobal(point))

    def command_dialog(self, operation, initial=None):
        if self.busy:
            return
        from .dialogs import get_command

        revision = self.project.revision
        defaults = dict(initial or {})
        obj = self.project.object(self.selected_id) if self.selected_id else None
        if operation in ("integrate", "peak_label", "peaks", "process"):
            if self.selected_collection == "spectra":
                defaults.setdefault("spectrum_id", self.selected_id)
            elif obj and hasattr(obj, "spectrum_id"):
                defaults.setdefault("spectrum_id", obj.spectrum_id)
        region = self.spectrum_view.selected_region()
        if region and operation in ("integrate", "fit"):
            defaults.setdefault("lower", float(region[0]))
            defaults.setdefault("upper", float(region[1]))
        if operation == "peak_label" and self._position is not None:
            defaults.setdefault("ppm", float(self._position))
        if operation == "fit" and self.selected_collection == "tables":
            defaults.setdefault("table_id", self.selected_id)
        if operation in ("crosspeak", "grid_metadata") and self.selected_collection == "grids":
            defaults.setdefault("grid_id", self.selected_id)
        if operation == "crosspeak" and self._grid_position:
            defaults.setdefault("x_ppm", self._grid_position[0])
            defaults.setdefault("y_ppm", self._grid_position[1])
        if operation == "annotate" and self._reference_context:
            defaults.setdefault("attachment_id", self._reference_context[0])
            defaults.setdefault("page", self.reference_page.value())
            if self._rectangle:
                defaults.update(dict(zip(("x", "y", "width", "height"), self._rectangle)))
        with self._modal():
            command = get_command(operation, self.project, parent=self, initial=defaults)
        if command is not None and not self.submit_command(command, revision):
            QMessageBox.information(
                self,
                "Command not submitted",
                "The current operation is still running. No new edit was submitted. Reopen the dialog after it finishes.",
            )

    def submit_command(self, command, revision=None):
        if self.busy:
            return False
        expected = self.project.revision if revision is None else revision
        request_id = "desktop_" + uuid4().hex
        service = self.service

        def apply():
            receipt = service.apply(expected, request_id, command)
            return receipt, service.read()

        def committed(result):
            receipt, self.project = result
            self._append_log(
                f"Committed revision {receipt.revision}; {receipt.operation}; request {receipt.request_id}"
            )
            for warning in receipt.warnings:
                self._append_log("Warning: " + warning)
            self.render_project(receipt.object_ids[0] if receipt.object_ids else None)

        return self.start_operation(
            TITLES.get(command["op"], command["op"]), apply, committed, request_id=request_id
        )

    def edit_selected(self):
        if not self.selected_id or self.busy:
            return
        obj = self.project.object(self.selected_id)
        if self.selected_collection in EDIT_OPERATIONS:
            operation, id_field = EDIT_OPERATIONS[self.selected_collection]
            initial = {
                k: v
                for k, v in obj.model_dump(mode="json").items()
                if k in OPERATIONS[operation].model_fields
            }
            initial[id_field] = obj.id
            self.command_dialog(operation, initial)
        elif self.selected_collection == "analyses":
            operation = obj.parameters.get("op")
            if operation in OPERATIONS:
                self.command_dialog(operation, dict(obj.parameters))
        elif self.selected_collection == "grids":
            self.command_dialog("grid_metadata")
        elif self.selected_collection == "spectra":
            self.command_dialog("process")
        else:
            QMessageBox.information(
                self,
                "Preserved source",
                "This object is preserved evidence. Add an explicit interpretation or import another source.",
            )

    def remove_selected(self):
        if not self.selected_id or self.busy:
            return
        identifier, revision = self.selected_id, self.project.revision
        obj = self.project.object(identifier)
        label = getattr(obj, "name", getattr(obj, "label", getattr(obj, "atom", identifier)))
        prompt = f"Remove {label} from revision {revision} in a new saved revision?\n\nEarlier revisions and original sources are retained."
        with self._modal():
            answer = QMessageBox.question(self, "Remove object", prompt)
        if answer == QMessageBox.StandardButton.Yes:
            if not self.submit_command({"op": "remove", "object_id": identifier}, revision):
                QMessageBox.information(
                    self,
                    "Removal not submitted",
                    "Another operation is still running. No removal was submitted.",
                )

    def refresh(self):
        service = self.service

        def loaded(project):
            self.project = project
            self.render_project()
            self._append_log(f"Read saved revision {project.revision}")

        self.start_operation("Refresh saved project", service.read, loaded)

    def poll_revision(self):
        if self._closed or self._modal_depth or self.busy or self._poll_worker is not None:
            return
        service = self.service

        def read_revision():
            with service.store.connection() as db:
                return db.execute("SELECT MAX(revision) FROM snapshots").fetchone()[0]

        worker = Worker(read_revision)
        self._poll_worker = worker

        def finished(revision, error):
            self._poll_worker = None
            if self._closed or self._modal_depth or service is not self.service:
                return
            if error is not None:
                message = getattr(error, "message", str(error))
                if message != self._poll_error:
                    self._append_log("Project availability check failed: " + message)
                self._poll_error = message
                self.revision_label.setText(
                    f"Revision {self.project.revision}  |  Refresh unavailable"
                )
            else:
                if self._poll_error is not None:
                    self._append_log("Project access restored; refreshing saved state.")
                    self._poll_error = None
                    if not self.busy:
                        self.refresh()
                elif not self.busy and revision != self.project.revision:
                    self._append_log("An external frontend saved a new revision; refreshing.")
                    self.refresh()

        worker.signals.finished.connect(finished, Qt.ConnectionType.QueuedConnection)
        self.pool.start(worker)

    def _open_path(self, path, create_name=None):
        if self.busy:
            return
        candidate = Service(path)

        def load():
            return candidate.create(create_name) if create_name is not None else candidate.read()

        def opened(project):
            self.service, self.project = candidate, project
            self.selected_id = None
            self.render_project()
            self._append_log(f"Opened {candidate.store.path}; revision {project.revision}")

        self.start_operation("Create project" if create_name else "Open project", load, opened)

    def open_project(self):
        with self._modal():
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Open NMR project",
                str(self.service.store.path.parent),
                "NMR project (*.nmrproj)",
            )
        if path:
            self._open_path(path)

    def new_project(self):
        with self._modal():
            path, _ = QFileDialog.getSaveFileName(
                self,
                "New NMR project",
                str(self.service.store.path.parent / "Untitled.nmrproj"),
                "NMR project (*.nmrproj)",
            )
        if not path:
            return
        if Path(path).exists():
            QMessageBox.warning(
                self,
                "Project exists",
                "Existing files are preserved. Select a new project filename.",
            )
            return
        with self._modal():
            name, accepted = QInputDialog.getText(
                self, "Project name", "Name", text=Path(path).stem
            )
        if accepted and name.strip():
            self._open_path(path, name.strip())

    def export_revision(self):
        if self.busy:
            return
        revision = self.project.revision
        with self._modal():
            path, _ = QFileDialog.getSaveFileName(
                self,
                f"Export revision {revision}",
                str(self.service.store.path.parent / f"nmr-project-r{revision}.zip"),
                "Project bundle (*.zip)",
                options=QFileDialog.Option.DontConfirmOverwrite,
            )
        if not path:
            return
        service = self.service

        def export():
            result = dispatch(
                service,
                "nmr_export",
                {"revision": revision, "destination": str(Path(path).absolute())},
            )
            if not result["ok"]:
                raise NmrError(result["error"]["code"], result["error"]["message"])
            return result["data"]

        def delivered(artifact):
            message = f"Revision {artifact['revision']}\n{artifact['local_path']}\n{artifact['size']:,} bytes\nSHA-256 {artifact['sha256']}"
            self._append_log("Delivered " + message.replace("\n", " · "))
            QMessageBox.information(self, "Verified project export", message)

        self.start_operation("Export named revision", export, delivered)

    def reconcile_request(self):
        with self._modal():
            request, accepted = QInputDialog.getText(
                self, "Reconcile saved operation", "Durable request ID", text=self.last_request
            )
        if accepted and request.strip():
            service = self.service

            def read():
                return service.store.request(request.strip()), service.read()

            def reconciled(result):
                receipt, self.project = result
                self.render_project()
                self._append_log(
                    f"Request {receipt.request_id} committed revision {receipt.revision}; not resubmitted."
                )
                QMessageBox.information(
                    self,
                    "Saved operation",
                    f"Committed revision {receipt.revision}: {receipt.operation}\nNo operation was replayed.",
                )

            self.start_operation("Reconcile request", read, reconciled)

    def demo(self):
        if self.project.spectra or self.project.tables:
            QMessageBox.information(
                self,
                "Empty project required",
                "Create a new empty project for synthetic demonstration data.",
            )
            return
        revision = self.project.revision
        with self._modal():
            answer = QMessageBox.question(
                self,
                "Synthetic demonstration",
                "Add clearly labelled synthetic spectra and delays to this empty project?",
            )
        if answer == QMessageBox.StandardButton.Yes:
            self.submit_command({"op": "demo"}, revision)

    def about(self):
        from .. import __version__

        QMessageBox.information(
            self,
            "About NMR Companion",
            f"NMR Companion {__version__}\nNative Windows scientific workbench · Qt Widgets\n\n"
            "The GUI and MCP share one versioned project and scientific core.\n"
            "Original data and signed relaxation signals are retained.\n"
            "Prerelease: instrument and chemical interpretation qualification remain separate.\n\n"
            "Open-source licenses and third-party notices are included with the installed runtime.",
        )

    def closeEvent(self, event):
        if self.busy:
            self._close_requested = True
            self.statusBar().showMessage(
                "Completing the current operation before closing; no automatic replay."
            )
            event.ignore()
            return
        self._closed = True
        self.timer.stop()
        self.pool.waitForDone(15000)
        if self.settings:
            self.settings.setValue("native/geometry", self.saveGeometry())
            self.settings.setValue("native/layout", self.saveState(1))
        event.accept()
