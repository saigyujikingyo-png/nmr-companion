"""Native, revision-neutral editors for the public scientific commands.

The caller owns QApplication, project refresh and execution. These dialogs only
read the supplied project and return validated commands on explicit acceptance.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
import re
from uuid import uuid4

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..commands import COMMAND, OPERATIONS


TITLES = {
    "import": "Import numerical data",
    "demo": "Create synthetic demonstration",
    "integrate": "Integral region",
    "process": "Process spectrum",
    "peaks": "Detect signed peak candidates",
    "yield": "Internal-standard yield",
    "fit": "Relaxation fit",
    "assign": "Evidence assignment",
    "remove": "Remove derived object",
    "undo": "Restore project revision",
    "sample": "Sample and conditions",
    "structure": "Structure candidate",
    "crosspeak": "Crosspeak observation",
    "grid_metadata": "Confirm 2D axes",
    "peak_label": "Signal label",
    "normalize": "Relative proton integration",
    "attach": "Attach reference evidence",
    "annotate": "Reference page annotation",
    "compare": "Compare sample conditions",
    "dept": "DEPT-135 / carbon evidence",
}
ACTIONS = {
    "import": "Import data",
    "demo": "Create demonstration",
    "integrate": "Save integral",
    "process": "Apply processing",
    "peaks": "Find peak candidates",
    "yield": "Calculate yield",
    "fit": "Fit mapped traces",
    "assign": "Save assignment",
    "remove": "Remove object",
    "undo": "Restore revision",
    "sample": "Save sample",
    "structure": "Save candidate",
    "crosspeak": "Save crosspeak",
    "grid_metadata": "Confirm axes",
    "peak_label": "Save label",
    "normalize": "Calculate relative protons",
    "attach": "Attach reference",
    "annotate": "Save annotation",
    "compare": "Compare conditions",
    "dept": "Match DEPT evidence",
}

EDIT_IDS = {
    "integrate": "integral_id",
    "sample": "sample_id",
    "structure": "structure_id",
    "crosspeak": "crosspeak_id",
    "peak_label": "peaklabel_id",
    "annotate": "annotation_id",
    "assign": "assignment_id",
}
EVIDENCE_COLLECTIONS = (
    "spectra",
    "grids",
    "tables",
    "integrals",
    "analyses",
    "assignments",
    "samples",
    "structures",
    "crosspeaks",
    "peaklabels",
    "attachments",
    "annotations",
)
REMOVABLE = (
    "integrals",
    "analyses",
    "assignments",
    "structures",
    "crosspeaks",
    "peaklabels",
    "annotations",
)


class NumberEdit(QLineEdit):
    """Scientific notation, with an actual unavailable value rather than zero."""

    def __init__(self, label, value=None, *, optional=False, integer=False):
        super().__init__("" if value is None else str(value))
        self.label, self.optional, self.integer = label, optional, integer
        self.setAccessibleName(label)
        self.setPlaceholderText("Not supplied" if optional else "Required")
        self.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.setMinimumWidth(90)

    def value(self):
        raw = self.text().strip()
        if not raw:
            if self.optional:
                return None
            raise ValueError(f"{self.label}: enter a value.")
        if self.integer:
            if not re.fullmatch(r"[+-]?\d+", raw):
                raise ValueError(f"{self.label}: enter a whole number.")
            return int(raw)
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError(
                f"{self.label}: enter a finite number (for example 0.2 or 2e-4)."
            ) from exc
        if not math.isfinite(value):
            raise ValueError(f"{self.label}: NaN and infinity are not supported.")
        return value


class ChoiceBox(QComboBox):
    def __init__(self, label, options=(), value=None, *, optional=False):
        super().__init__()
        self.label, self.optional = label, optional
        self.setAccessibleName(label)
        self.setMinimumContentsLength(18)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.set_options(options, value)

    def set_options(self, options, value=None):
        self.blockSignals(True)
        self.clear()
        self.addItem("None / not supplied" if self.optional else "Select…", None)
        self.available = {key for key, _ in options}
        for key, title in options:
            self.addItem(title, key)
        if value is not None and value not in self.available:
            self.addItem(f"Unavailable: {value}", value)
        self.setCurrentIndex(max(0, self.findData(value)))
        self.blockSignals(False)

    def value(self):
        value = self.currentData()
        if value is None:
            if self.optional:
                return None
            raise ValueError(f"{self.label}: make an explicit selection.")
        if value not in self.available:
            raise ValueError(
                f"{self.label}: {value} is no longer available; select a current object."
            )
        return value


class ObjectList(QListWidget):
    def __init__(self, label, options, selected=()):
        super().__init__()
        self.label = label
        self.setAccessibleName(label)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMinimumHeight(140)
        self.set_options(options, selected)

    def selected_ids(self):
        return [
            self.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.count())
            if self.item(i).checkState() == Qt.CheckState.Checked
        ]

    def set_options(self, options, selected=()):
        selected = list(selected)
        self.blockSignals(True)
        self.clear()
        names = dict(options)
        self.available = set(names)
        order = list(dict.fromkeys([*selected, *names]))
        for key in order:
            item = QListWidgetItem(names.get(key, f"Unavailable: {key}"), self)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked
            )
        self.blockSignals(False)

    def value(self):
        selected = self.selected_ids()
        missing = set(selected) - self.available
        if missing:
            raise ValueError(
                f"{self.label}: remove unavailable selections: {', '.join(sorted(missing))}."
            )
        return selected


@dataclass
class Column:
    key: str
    label: str
    kind: str = "text"
    default: object = ""
    options: object = ()


class RowTable(QWidget):
    """Editable native rows; sorting never changes scientific pairing."""

    changed = Signal()

    def __init__(self, columns, rows=(), *, title="Rows", add_label="Add row", defaults=None):
        super().__init__()
        self.columns, self.defaults = columns, defaults
        self.table = QTableWidget(0, len(columns), self)
        self.table.setAccessibleName(title)
        self.table.setHorizontalHeaderLabels([c.label for c in columns])
        self.table.setSortingEnabled(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setDefaultSectionSize(31)
        self.table.setMinimumHeight(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.add_button, self.remove_button = (
            QPushButton(add_label),
            QPushButton("Remove selected rows"),
        )
        for button in (self.add_button, self.remove_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.add_button.clicked.connect(lambda: self.add_row())
        self.remove_button.clicked.connect(self.remove_selected)
        for row in rows:
            self.add_row(row)

    def cell(self, row, key):
        return self.table.cellWidget(
            row, next(i for i, c in enumerate(self.columns) if c.key == key)
        )

    def add_row(self, values=None):
        values = dict(values if values is not None else self.defaults() if self.defaults else {})
        row = self.table.rowCount()
        self.table.insertRow(row)
        for index, col in enumerate(self.columns):
            value = values.get(col.key, col.default)
            if col.kind in ("number", "optional_number", "integer"):
                widget = NumberEdit(
                    col.label,
                    value,
                    optional=col.kind == "optional_number",
                    integer=col.kind == "integer",
                )
                widget.textChanged.connect(lambda *_: self.changed.emit())
            elif col.kind == "choice":
                options = col.options() if callable(col.options) else col.options
                widget = ChoiceBox(col.label, options, value)
                widget.currentIndexChanged.connect(lambda *_: self.changed.emit())
            elif col.kind == "check":
                widget = QCheckBox()
                widget.setAccessibleName(col.label)
                widget.setChecked(bool(value))
                widget.toggled.connect(lambda *_: self.changed.emit())
            else:
                widget = QLineEdit("" if value is None else str(value))
                widget.setAccessibleName(col.label)
                if col.kind == "display":
                    widget.setReadOnly(True)
                else:
                    widget.textChanged.connect(lambda *_: self.changed.emit())
            widget.setObjectName(col.key)
            self.table.setCellWidget(row, index, widget)
            self.table.setColumnWidth(index, 190 if col.kind == "choice" else 125)
        self.changed.emit()

    def remove_selected(self):
        rows = {i.row() for i in self.table.selectionModel().selectedRows()}
        if not rows and self.table.currentRow() >= 0:
            rows.add(self.table.currentRow())
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
        self.changed.emit()

    def value(self):
        rows = []
        for row in range(self.table.rowCount()):
            data = {}
            for col in self.columns:
                if col.kind == "display":
                    continue
                widget = self.cell(row, col.key)
                try:
                    data[col.key] = (
                        widget.value()
                        if isinstance(widget, (NumberEdit, ChoiceBox))
                        else widget.isChecked()
                        if isinstance(widget, QCheckBox)
                        else widget.text()
                    )
                except ValueError as exc:
                    raise ValueError(f"Row {row + 1}: {exc}") from exc
            rows.append(data)
        return rows


class CommandDialog(QDialog):
    def __init__(self, operation: str, project, parent=None, initial: dict | None = None):
        super().__init__(parent)
        if operation not in OPERATIONS:
            raise ValueError(f"Unknown scientific operation: {operation}")
        self.operation, self.project = operation, project
        self.initial = deepcopy(initial or {})
        if isinstance(self.initial.get("parameters"), dict):
            self.initial = {**self.initial["parameters"], **self.initial}
        self.identity_field = EDIT_IDS.get(operation)
        if (
            self.identity_field
            and self.initial.get("id")
            and self.identity_field not in self.initial
        ):
            self.initial[self.identity_field] = self.initial["id"]
        self.fields, self._getters = {}, {}
        self._accepted_command = None
        self._error_widget = None
        self.setWindowTitle(TITLES[operation])
        self.resize(820 if operation in ("fit", "structure", "sample") else 660, 610)
        layout = QVBoxLayout(self)
        identity = self.initial.get(self.identity_field) if self.identity_field else None
        if identity:
            label = QLabel(f"Edit existing object: {identity}")
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label)
        self.tabs = QTabWidget(self)
        layout.addWidget(self.tabs, 1)
        self._page("Details")
        getattr(self, f"_build_{operation}")()
        self.error_label = QLabel()
        self.error_label.setObjectName("validation_error")
        self.error_label.setAccessibleName("Command validation error")
        self.error_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.error_label.setTextFormat(Qt.TextFormat.PlainText)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #a12622;")
        self.error_label.hide()
        layout.addWidget(self.error_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(ACTIONS[operation])
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _page(self, title):
        body = QWidget()
        self.form = QFormLayout(body)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.form.setVerticalSpacing(8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        self.tabs.addTab(scroll, title)

    def _note(self, text):
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        self.form.addRow(label)
        return label

    def _register(self, key, label, widget, getter=None):
        widget.setObjectName(key)
        widget.setAccessibleName(label)
        self.fields[key] = widget
        if getter:
            self._getters[key] = getter
        self.form.addRow(label, widget)
        return widget

    def _text(self, key, label, default="", *, multiline=False, optional=False, nullable=False):
        value = self.initial.get(key, default)
        widget = QPlainTextEdit() if multiline else QLineEdit()
        if multiline:
            widget.setPlainText("" if value is None else str(value))
            widget.setMaximumHeight(100)
        else:
            widget.setText("" if value is None else str(value))

        def read():
            value = widget.toPlainText() if multiline else widget.text()
            if not value.strip():
                if nullable:
                    return None
                if not optional:
                    raise ValueError(f"{label}: enter a value.")
            return value

        return self._register(key, label, widget, read)

    def _number(self, key, label, default=None, *, optional=False, integer=False):
        widget = NumberEdit(
            label, self.initial.get(key, default), optional=optional, integer=integer
        )
        return self._register(key, label, widget, widget.value)

    def _choice(self, key, label, options, default=None, *, optional=False):
        widget = ChoiceBox(label, options, self.initial.get(key, default), optional=optional)
        return self._register(key, label, widget, widget.value)

    def _enum(self, key, label, values, default=None, *, optional=False):
        return self._choice(key, label, [(v, str(v)) for v in values], default, optional=optional)

    def _choices(self, collections, predicate=None):
        options = []
        if isinstance(collections, str):
            collections = (collections,)
        for collection in collections:
            for oid, obj in getattr(self.project, collection, {}).items():
                if predicate and not predicate(obj):
                    continue
                name = getattr(obj, "name", getattr(obj, "label", oid))
                state = " [stale]" if getattr(obj, "state", "current") == "stale" else ""
                options.append((oid, f"{name} · {oid}{state}"))
        return options

    def _object(self, key, label, collections, *, optional=False, predicate=None):
        return self._choice(key, label, self._choices(collections, predicate), optional=optional)

    def _objects(self, key, label, collections, *, predicate=None):
        widget = ObjectList(label, self._choices(collections, predicate), self.initial.get(key, []))
        return self._register(key, label, widget, widget.value)

    def _check(self, key, label, default=False):
        widget = QCheckBox(label)
        widget.setChecked(bool(self.initial.get(key, default)))
        self._register(key, "", widget, widget.isChecked)
        widget.setAccessibleName(label)
        return widget

    def _table(self, key, title, columns, rows=None, *, add_label="Add row", defaults=None):
        widget = RowTable(
            columns,
            self.initial.get(key, []) if rows is None else rows,
            title=title,
            add_label=add_label,
            defaults=defaults,
        )
        widget.setObjectName(key)
        self.fields[key], self._getters[key] = widget, widget.value
        caption = QLabel(title)
        caption.setBuddy(widget.table)
        self.form.addRow(caption)
        self.form.addRow(widget)
        return widget

    def _spectrum(self, key="spectrum_id", label="Spectrum", *, nucleus=None, all_domains=False):
        return self._object(
            key,
            label,
            "spectra",
            predicate=lambda s: (
                (all_domains or s.domain == "frequency")
                and (nucleus is None or s.nucleus == nucleus)
            ),
        )

    def _bounds(self):
        self._number("lower", "Lower bound (ppm)")
        self._number("upper", "Upper bound (ppm)")

    def _path(self, *, reference=False):
        field = self._text(
            "path", "Original file or directory" if not reference else "Original reference file"
        )
        buttons = QHBoxLayout()
        browse = QPushButton("Choose file…")
        browse.setAutoDefault(False)

        def choose_file():
            filters = (
                "References (*.pdf *.png *.jpg *.jpeg *.webp)"
                if reference
                else "NMR data (*.dx *.jdx *.csv *.zip *.json);;All files (*)"
            )
            path, _ = QFileDialog.getOpenFileName(
                self, "Select original input", field.text(), filters
            )
            if path:
                field.setText(path)

        browse.clicked.connect(choose_file)
        buttons.addWidget(browse)
        if not reference:
            directory = QPushButton("Choose directory…")
            directory.setAutoDefault(False)

            def choose_directory():
                path = QFileDialog.getExistingDirectory(
                    self, "Select original input directory", field.text()
                )
                if path:
                    field.setText(path)

            directory.clicked.connect(choose_directory)
            buttons.addWidget(directory)
        buttons.addStretch()
        self.form.addRow(buttons)

    def _build_import(self):
        self._path()
        numbers = self.initial.get("bruker_processing_numbers")
        self.initial["bruker_processing_numbers"] = (
            ", ".join(map(str, numbers)) if numbers is not None else ""
        )
        field = self._text("bruker_processing_numbers", "Bruker processing numbers", optional=True)

        def read_numbers():
            raw = field.text().strip()
            if not raw:
                return None
            pieces = [p.strip() for p in raw.split(",")]
            if any(not re.fullmatch(r"\d+", p) for p in pieces):
                raise ValueError("Processing numbers: use comma-separated positive integers.")
            values = [int(p) for p in pieces]
            if len(set(values)) != len(values) or any(not 1 <= v <= 999999 for v in values):
                raise ValueError("Processing numbers must be unique integers from 1 to 999999.")
            return values

        self._getters["bruker_processing_numbers"] = read_numbers
        self._note(
            "Blank means strict decoding of all supported datasets. An explicit list selects processed datasets across every experiment. All originals remain preserved; unselected profiles are not qualified. Raw data validation still applies."
        )

    def _build_demo(self):
        self._note(
            "Create the built-in synthetic spectra and delay table for software exploration. These data are labelled synthetic and are not acquired measurements."
        )

    def _build_integrate(self):
        self._spectrum()
        self._text("name", "Region name", "Integral")
        self._bounds()
        self._note(
            "Signed integration uses the full-resolution numerical spectrum, with interpolated boundaries."
        )

    def _build_peaks(self):
        self._spectrum()
        self._number("prominence", "Minimum prominence (intensity units)")
        self._note(
            "Both positive and negative local extrema are retained. Peak candidates are observations, not automatic assignments."
        )

    def _build_peak_label(self):
        self._spectrum()
        self._number("ppm", "Position (ppm)")
        self._text("label", "Signal label")
        self._text("multiplicity", "Multiplicity interpretation (optional)", nullable=True)
        self._number("protons", "Proton-count interpretation (optional)", optional=True)
        self._note(
            "Manual position; intensity is interpolated from the original array. Multiplicity and proton count are supplied interpretations."
        )

    def _build_process(self):
        self._spectrum(all_domains=True)
        self._enum("method", "Processing method", ["fft", "phase", "baseline", "reference"])
        self._note(
            "Only the selected method executes. FFT requires qualified complex time data; phase requires a complex frequency spectrum. Original bytes remain preserved."
        )
        self._page("FFT")
        self._enum("zero_fill_factor", "Zero-fill factor", [1, 2, 4], 2)
        self._number("line_broadening_hz", "Exponential line broadening (Hz)", 0.3)
        self._page("Phase / reference")
        for key, label in (
            ("ph0_deg", "Zero-order phase (degrees)"),
            ("ph1_deg", "First-order phase (degrees)"),
            ("pivot_ppm", "Phase pivot (ppm)"),
            ("reference_shift_ppm", "Reference shift (ppm)"),
        ):
            self._number(key, label, 0.0)
        self._page("Baseline windows")
        table = self._table(
            "regions",
            "Baseline windows (ppm)",
            [
                Column("lower", "Lower ppm", "number", None),
                Column("upper", "Upper ppm", "number", None),
            ],
            rows=[{"lower": r[0], "upper": r[1]} for r in self.initial.get("regions", [])],
        )
        self._getters["regions"] = lambda: [[r["lower"], r["upper"]] for r in table.value()]
        self._note(
            "An affine baseline uses only the explicitly selected windows. Choose signal-free regions and review the result."
        )

    def _build_yield(self):
        self._text("name", "Analysis name", "Internal-standard yield")
        self._object("product_integral_id", "Product integral", "integrals")
        self._object("standard_integral_id", "Internal-standard integral", "integrals")
        for key, label in (
            ("product_protons", "Product proton count"),
            ("standard_protons", "Standard proton count"),
            ("standard_mol", "Standard amount (mol)"),
            ("limiting_mol", "Initial limiting-reactant amount (mol)"),
        ):
            self._number(key, label)
        self._number("stoichiometric_factor", "Product / reactant stoichiometric factor", 1.0)
        self._object(
            "recovered_integral_id",
            "Recovered starting-material integral",
            "integrals",
            optional=True,
        )
        self._number("recovered_protons", "Recovered-material proton count", optional=True)
        self._note(
            "Select separated regions from one acquired spectrum. Standard amount and reactant amount are independent explicit inputs; equimolarity is not assumed."
        )
        self._page("Standard uncertainties")
        self._note(
            "Blank means unavailable, not zero. Enter standard uncertainties, not confidence limits or solver tolerances. Supplied area/amount uncertainties are treated as independent; shared-standard covariance is retained for material balance."
        )
        for key, label in (
            ("u_product_area", "u(product area), intensity·ppm"),
            ("u_standard_area", "u(standard area), intensity·ppm"),
            ("u_recovered_area", "u(recovered area), intensity·ppm"),
            ("u_standard_mol", "u(standard amount), mol"),
            ("u_limiting_mol", "u(limiting-reactant amount), mol"),
        ):
            self._number(key, label, optional=True)

    def _build_normalize(self):
        self._text("name", "Analysis name", "Relative proton integration")
        self._object("reference_integral_id", "Reference integral", "integrals")
        self._number("reference_protons", "Reference proton count")
        self._objects("integral_ids", "Integrals to report", "integrals")
        self._note(
            "All selected integrals must belong to the same 1H spectrum. The reference area must be positive. Signed areas are retained; this operation never rescales relaxation traces."
        )

    def _build_fit(self):
        self._text("name", "Analysis name", "Relaxation analysis")
        self._enum("model", "Model", ["T1", "T2"])
        table_choice = self._object("table_id", "Original delay table", "tables")
        self._choice("delay_column", "Delay column", [])
        self._choice("sigma_column", "Integral standard-uncertainty column", [], optional=True)
        self._enum("time_unit", "Original delay unit", ["s", "ms", "us"])
        self._enum("time_basis", "Meaning of the delay", ["elapsed", "echo_interval"])
        self._number("delay_multiplier", "Echo interval → evolution-time multiplier", optional=True)
        self._enum(
            "purpose", "Declared acquisition purpose", ["analysis", "quick_check"], "analysis"
        )
        self._bounds()
        self._note(
            "T1: A − B exp(−kt); T2: C + A exp(−kt). Signals stay signed. Use comparable acquisition scales and one physical region. Purpose is user-declared; an analysis label does not qualify acquisition quality."
        )
        self._page("Trace-to-delay mapping")
        self._note(
            "Add one row for each trace and explicitly enter its CSV data-row number (1 = first data row, excluding the header). Input order and repeated delay values are preserved. Mark exclusions on their original rows. Changing the table clears data-row selections; no pairing or time units are guessed."
        )
        traces, indices = self.initial.get("spectrum_ids", []), self.initial.get("row_indices", [])
        excluded = self.initial.get("excluded_indices", [])
        rows = [
            {
                "spectrum_id": traces[i] if i < len(traces) else None,
                "row_number": indices[i] + 1 if i < len(indices) else None,
                "excluded": i in excluded,
            }
            for i in range(max(len(traces), len(indices)))
        ]
        mapping = self._table(
            "mapping",
            "Explicit trace mapping",
            [
                Column(
                    "spectrum_id",
                    "Trace",
                    "choice",
                    None,
                    lambda: self._choices("spectra", lambda s: s.domain == "frequency"),
                ),
                Column("row_number", "CSV data row (1-based)", "integer", None),
                Column("delay", "Original delay", "display"),
                Column("sigma", "Original area uncertainty", "display"),
                Column("excluded", "Exclude", "check", False),
            ],
            rows=rows,
            add_label="Add trace mapping",
        )
        del self._getters["mapping"]
        self._fit_initializing = True
        self._fit_table_changed()
        self._fit_initializing = False
        table_choice.currentIndexChanged.connect(self._fit_table_changed)
        self.fields["delay_column"].currentIndexChanged.connect(self._fit_preview)
        self.fields["sigma_column"].currentIndexChanged.connect(self._fit_preview)
        mapping.changed.connect(self._fit_preview)
        self._fit_preview()

    def _fit_table_changed(self, *_):
        table = getattr(self.project, "tables", {}).get(self.fields["table_id"].currentData())
        options = [(c, c) for c in table.columns] if table else []
        for key in ("delay_column", "sigma_column"):
            value = self.initial.get(key) if self._fit_initializing else None
            self.fields[key].set_options(options, value)
        if not self._fit_initializing:
            mapping = self.fields["mapping"]
            for row in range(mapping.table.rowCount()):
                mapping.cell(row, "row_number").clear()
        self._fit_preview()

    def _fit_preview(self, *_):
        mapping = self.fields["mapping"]
        table = getattr(self.project, "tables", {}).get(self.fields["table_id"].currentData())
        for row in range(mapping.table.rowCount()):
            raw = mapping.cell(row, "row_number").text().strip()
            index = int(raw) - 1 if re.fullmatch(r"\d+", raw) else -1
            data = table.rows[index] if table and 0 <= index < len(table.rows) else {}
            for preview, column in (("delay", "delay_column"), ("sigma", "sigma_column")):
                mapping.cell(row, preview).setText(
                    str(data.get(self.fields[column].currentData(), ""))
                )

    def _read_mapping(self):
        rows = self.fields["mapping"].value()
        table = getattr(self.project, "tables", {}).get(self.fields["table_id"].value())
        traces, indices, excluded = [], [], []
        for position, row in enumerate(rows):
            index = row["row_number"] - 1
            if not table or not 0 <= index < len(table.rows):
                raise ValueError(
                    f"Mapping row {position + 1}: CSV data-row number is outside the selected table."
                )
            traces.append(row["spectrum_id"])
            indices.append(index)
            if row["excluded"]:
                excluded.append(position)
        if len(set(traces)) != len(traces) or len(set(indices)) != len(indices):
            raise ValueError(
                "Map each trace and CSV row only once. Replicate delays require distinct source rows."
            )
        if len(rows) - len(excluded) < 4:
            raise ValueError(
                "Select at least four included trace mappings for a three-parameter fit."
            )
        return {"spectrum_ids": traces, "row_indices": indices, "excluded_indices": excluded}

    def _build_sample(self):
        self._text("name", "Sample name")
        self._enum("role", "Source role", ["own", "reference", "synthetic", "unknown"])
        self._text("stage", "Material / reaction stage", optional=True)
        self._objects(
            "object_ids", "Associated spectra, grids and tables", ("spectra", "grids", "tables")
        )
        self._page("Transformation and provenance")
        self._objects("parent_ids", "Parent samples", "samples")
        self._text(
            "transformation", "Transformation from parent samples", multiline=True, optional=True
        )
        self._text("reference", "Frequency / source reference", multiline=True, optional=True)
        self._text("notes", "Notes", multiline=True, optional=True)
        self._page("Conditions")
        conditions = self.initial.get("conditions", {})
        self.initial.update(
            {"solvent": conditions.get("solvent"), "temperature_k": conditions.get("temperature_k")}
        )
        self._text("solvent", "Solvent (optional)", nullable=True)
        self._number("temperature_k", "Temperature (K, optional)", optional=True)
        additives = self._table(
            "additives",
            "Named additives",
            [
                Column("name", "Additive name"),
                Column("concentration_mol_l", "Concentration (mol/L)", "optional_number", None),
                Column("notes", "Notes"),
            ],
            rows=conditions.get("additives", []),
            add_label="Add additive",
        )
        solvent, temperature = self._getters.pop("solvent"), self._getters.pop("temperature_k")
        self._getters.pop("additives")
        self._getters["conditions"] = lambda: {
            "solvent": solvent(),
            "temperature_k": temperature(),
            "additives": additives.value(),
        }
        self._note(
            "Blank temperature or concentration remains unknown. No solvent or laboratory condition is inferred from the selected spectra."
        )

    def _build_structure(self):
        self._text("name", "Candidate name")
        self._object("sample_id", "Sample / transformation stage", "samples")
        self._text("alternative_group", "Alternative-candidate group", optional=True)
        self._enum("status", "Review status", ["proposed", "confirmed"], "proposed")
        self._text(
            "description",
            "Interpretation and stereochemical context",
            multiline=True,
            optional=True,
        )
        self._note(
            "A drawing and R/S or wedge/hash labels are manual interpretations. The software does not assign CIP or automatically prove a structure. Confirmed candidates require explicit evidence."
        )
        self._page("Atoms")
        atoms = self._table(
            "atoms",
            "Stable atoms and drawing coordinates",
            [
                Column("id", "Stable atom ID"),
                Column("label", "Atom label"),
                Column("element", "Element", default="C"),
                Column("x", "Drawing x", "number", 0.0),
                Column("y", "Drawing y", "number", 0.0),
                Column("stereo", "Stereo context"),
            ],
            add_label="Add atom",
            defaults=lambda: {
                "id": f"atom_{uuid4().hex[:12]}",
                "label": "",
                "element": "C",
                "x": 0.0,
                "y": 0.0,
                "stereo": "",
            },
        )
        self._note(
            "Atom IDs link assignments and bond endpoints. Moving or relabelling an atom should retain its ID; deleting or replacing an identity can make linked interpretations stale."
        )
        self._page("Bonds")
        bonds = self._table(
            "bonds",
            "Bond endpoints, order and stereo display",
            [
                Column("a", "First atom", "choice", None, self._atom_options),
                Column("b", "Second atom", "choice", None, self._atom_options),
                Column(
                    "order",
                    "Bond order",
                    "choice",
                    1.0,
                    [
                        (1.0, "Single (1)"),
                        (2.0, "Double (2)"),
                        (3.0, "Triple (3)"),
                        (1.5, "Aromatic (1.5)"),
                    ],
                ),
                Column(
                    "stereo",
                    "Stereo display",
                    "choice",
                    "none",
                    [(v, v) for v in ("none", "wedge", "hash", "either")],
                ),
            ],
            add_label="Add bond",
        )

        def update_endpoints():
            options = self._atom_options()
            for row in range(bonds.table.rowCount()):
                for key in ("a", "b"):
                    field = bonds.cell(row, key)
                    field.set_options(options, field.currentData())

        atoms.changed.connect(update_endpoints)
        self._page("Evidence")
        self._objects(
            "evidence_ids",
            "Supporting observations",
            EVIDENCE_COLLECTIONS,
            predicate=lambda o: o.id != self.initial.get("structure_id"),
        )

    def _atom_options(self):
        atoms = self.fields["atoms"]
        options = []
        for row in range(atoms.table.rowCount()):
            oid = atoms.cell(row, "id").text()
            label = atoms.cell(row, "label").text()
            if oid:
                options.append((oid, f"{label or oid} · {oid}"))
        return options

    def _build_crosspeak(self):
        self._object("grid_id", "Processed 2D grid", "grids")
        self._number("x_ppm", "x / column position (ppm)")
        self._number("y_ppm", "y / row position (ppm)")
        self._text("label", "Correlation label")
        self._note(
            "The saved intensity is the nearest original grid point, retaining its sign. Confirm experiment and axis nuclei before assigning a correlation."
        )

    def _build_grid_metadata(self):
        self._object("grid_id", "Processed 2D grid", "grids")
        self._enum("experiment", "Explicit experiment identity", ["COSY", "HSQC"])
        nuclei = self.initial.get("nuclei", [None, None])
        self.initial["x_nucleus"], self.initial["y_nucleus"] = nuclei
        self._enum("x_nucleus", "x / column nucleus", ["1H", "13C", "15N"])
        self._enum("y_nucleus", "y / row nucleus", ["1H", "13C", "15N"])
        x, y = self._getters.pop("x_nucleus"), self._getters.pop("y_nucleus")
        self._getters["nuclei"] = lambda: [x(), y()]
        self._text("reference", "Basis for axis / experiment confirmation")
        self._note(
            "COSY requires 1H/1H. HSQC accepts 1H with 13C or 15N in either explicit orientation. Original parameters remain preserved; this declaration does not transpose data."
        )

    def _build_attach(self):
        self._path(reference=True)
        self._text("name", "Display name (optional)", nullable=True)
        self._object("sample_id", "Associated sample", "samples")
        self._enum("source_role", "Document provenance", ["own", "reference"])
        self._enum(
            "category",
            "Evidence category",
            ["nmr_reference", "IR", "HRMS", "optical_rotation", "other"],
        )
        self._text("notes", "Source notes", multiline=True, optional=True)
        self._note(
            "The original PDF/PNG/JPEG/WebP is preserved as supplied. A document is reference evidence, not a numerical spectrum or a newly measured result."
        )

    def _build_annotate(self):
        attachment = self._object("attachment_id", "Reference attachment", "attachments")
        self._number("page", "Page (1-based)", 1, integer=True)
        for key, label in (
            ("x", "Left x (page fraction)"),
            ("y", "Top y (page fraction)"),
            ("width", "Width (page fraction)"),
            ("height", "Height (page fraction)"),
        ):
            self._number(key, label)
        self._text("label", "Annotation label")
        self._text("observation", "Manual observation", multiline=True, optional=True)
        self._number("approximate_ppm", "Approximate image reading (ppm)", optional=True)
        self._number("reading_uncertainty_ppm", "Reading standard uncertainty (ppm)", optional=True)
        note = self._note("")

        def page_note(*_):
            obj = getattr(self.project, "attachments", {}).get(attachment.currentData())
            count = f"Selected document: {obj.pages} page(s). " if obj else ""
            note.setText(
                count
                + "Coordinates run from 0 to 1 with a top-left origin. Image readings are approximate observations; no numeric spectrum or quantitative integral is generated."
            )

        attachment.currentIndexChanged.connect(page_note)
        page_note()

    def _build_assign(self):
        sample = self._object("sample_id", "Explicit sample (optional)", "samples", optional=True)
        candidate = self._object(
            "candidate_id", "Saved candidate (optional)", "structures", optional=True
        )
        self._text("sample", "Sample description")
        self._text("candidate", "Candidate interpretation")
        self._text("atom", "Atom / signal label")
        self._enum("status", "Review status", ["proposed", "confirmed"], "proposed")
        self._text("observation", "Evidence interpretation", multiline=True)
        self._page("Atoms and observations")
        atoms = ObjectList("Saved candidate atoms", [], self.initial.get("atom_ids", []))
        self._register("atom_ids", "Saved candidate atoms", atoms, atoms.value)
        self._objects(
            "evidence_ids",
            "Supporting observations",
            EVIDENCE_COLLECTIONS,
            predicate=lambda o: o.id != self.initial.get("assignment_id"),
        )
        self._note(
            "Choose saved atom identities from the selected candidate. Proposed/confirmed is a human review state, not automatic chemical proof. Supporting evidence is required."
        )

        def candidate_changed(*_):
            obj = getattr(self.project, "structures", {}).get(candidate.currentData())
            options = (
                [(a.id, f"{a.label} ({a.element}) · {a.id}") for a in obj.atoms] if obj else []
            )
            atoms.set_options(options, atoms.selected_ids())
            if obj and not self.fields["candidate"].text():
                self.fields["candidate"].setText(obj.name)

        def sample_changed(*_):
            obj = getattr(self.project, "samples", {}).get(sample.currentData())
            if obj and not self.fields["sample"].text():
                self.fields["sample"].setText(obj.name)

        candidate.currentIndexChanged.connect(candidate_changed)
        sample.currentIndexChanged.connect(sample_changed)
        candidate_changed()
        sample_changed()

    def _build_compare(self):
        self._text("name", "Comparison name")
        metric = self._enum("metric", "Quantity to compare", ["T_s", "chemical_shift_ppm"])
        self._choice("left_id", "Left observation / fit", [])
        self._choice("right_id", "Right observation / fit", [])
        for side in ("left", "right"):
            sample = self._object(f"{side}_sample_id", f"{side.title()} sample", "samples")
            note = self._note("")

            def update_context(*_, field=sample, label=note, prefix=side.title()):
                obj = getattr(self.project, "samples", {}).get(field.currentData())
                if obj is None:
                    label.setText(f"{prefix} conditions: select a sample.")
                    return
                c = obj.conditions
                additives = (
                    "; ".join(
                        f"{a.name}: {a.concentration_mol_l if a.concentration_mol_l is not None else 'unknown'} mol/L"
                        for a in c.additives
                    )
                    or "unspecified"
                )
                label.setText(
                    f"{prefix}: {obj.role}; solvent {c.solvent or 'unspecified'}; temperature {c.temperature_k if c.temperature_k is not None else 'unknown'} K; additives {additives}; reference {obj.reference or 'unspecified'}"
                )

            sample.currentIndexChanged.connect(update_context)
            update_context()
        self._text("signal_label", "Corresponding signal label")
        self._text("correspondence", "Evidence for signal / sample correspondence")
        self._check(
            "independent_uncertainties", "Input standard uncertainties are independently justified"
        )
        self._note(
            "Reports right minus left; a time ratio is right / left. Missing uncertainty stays unavailable. Sample and signal correspondence must be supplied explicitly; matching peak order is insufficient."
        )

        def metric_changed(*_):
            if metric.currentData() == "T_s":
                options = self._choices("analyses", lambda a: a.kind == "relaxation")
            elif metric.currentData() == "chemical_shift_ppm":
                options = self._choices("peaklabels")
            else:
                options = []
            for key in ("left_id", "right_id"):
                field = self.fields[key]
                field.set_options(options, field.currentData())

        metric.currentIndexChanged.connect(metric_changed)
        metric_changed()

    def _build_dept(self):
        self._text("name", "Analysis name", "DEPT-135 / carbon evidence")
        self._spectrum("carbon_spectrum_id", "13C reference spectrum", nucleus="13C")
        self._spectrum("dept_spectrum_id", "DEPT-135 spectrum", nucleus="13C")
        self._number("carbon_prominence", "13C prominence (intensity units)")
        self._number("dept_prominence", "DEPT prominence (intensity units)")
        self._number("tolerance_ppm", "Matching tolerance (ppm)")
        self._enum(
            "reference_convention",
            "Verified DEPT phase convention",
            ["positive_ch_ch3", "negative_ch_ch3"],
        )
        self._text("reference", "Basis for phase / frequency reference")
        self._note(
            "Signed matches remain proposed evidence. A match must be unique in both directions. An absent DEPT signal does not by itself prove a quaternary carbon."
        )

    def _build_remove(self):
        self._object("object_id", "Derived object to remove", REMOVABLE)
        self._note(
            "Remove this editable object from the next revision. Dependent interpretations become stale. Preserved originals and earlier revisions remain available."
        )

    def _build_undo(self):
        self._number("target_revision", "Retained revision to restore", integer=True)
        self._note(
            f"Current revision: {getattr(self.project, 'revision', 0)}. Restore creates a new revision; it does not erase history or replay scientific operations."
        )

    def command(self) -> dict:
        command = {"op": self.operation}
        self._error_widget = None
        for key, read in self._getters.items():
            try:
                command[key] = read()
            except ValueError:
                self._error_widget = self.fields.get(key)
                raise
        if self.identity_field:
            command[self.identity_field] = self.initial.get(self.identity_field)
        if self.operation == "fit":
            try:
                command.update(self._read_mapping())
            except ValueError:
                self._error_widget = self.fields["mapping"]
                raise
        try:
            command = COMMAND.validate_python(command).model_dump(mode="json")
        except ValidationError as exc:
            errors = []
            location = exc.errors(include_input=False)[0]["loc"]
            for index, key in enumerate(location):
                if key in self.fields:
                    widget = self.fields[key]
                    if isinstance(widget, RowTable) and index + 2 < len(location):
                        row, column = location[index + 1 : index + 3]
                        if isinstance(row, int) and column in {c.key for c in widget.columns}:
                            widget = widget.cell(row, column)
                    self._error_widget = widget
                    break
            for issue in exc.errors(include_input=False)[:5]:
                location = ".".join(map(str, issue["loc"]))
                errors.append(f"{location}: {issue['msg']}")
            raise ValueError("\n".join(errors)) from exc
        self._validate_context(command)
        return command

    def accept(self):
        try:
            self._accepted_command = self.command()
        except ValueError as exc:
            self.error_label.setText(f"Please correct the following:\n{exc}")
            self.error_label.show()
            widget = self._error_widget or self.error_label
            if isinstance(widget, RowTable):
                widget = widget.table
            ancestor = widget.parentWidget()
            while ancestor is not None:
                if isinstance(ancestor, QScrollArea):
                    self.tabs.setCurrentWidget(ancestor)
                    ancestor.ensureWidgetVisible(widget)
                    break
                ancestor = ancestor.parentWidget()
            widget.setFocus(Qt.FocusReason.OtherFocusReason)
            if isinstance(widget, QLineEdit):
                widget.selectAll()
            return
        self.error_label.hide()
        super().accept()

    def _object_by_id(self, oid):
        for name in EVIDENCE_COLLECTIONS:
            if oid in getattr(self.project, name, {}):
                return getattr(self.project, name)[oid]
        return None

    @staticmethod
    def _ordered(lower, upper, label="Region"):
        if lower >= upper:
            raise ValueError(f"{label}: lower bound must be smaller than upper bound.")

    @staticmethod
    def _within(values, axis, label):
        if any(not min(axis) <= value <= max(axis) for value in values):
            raise ValueError(f"{label}: coordinates must lie within the selected data axis.")

    @staticmethod
    def _grid_semantics(experiment, nuclei):
        valid = (experiment == "COSY" and nuclei == ["1H", "1H"]) or (
            experiment == "HSQC"
            and nuclei in (["1H", "13C"], ["13C", "1H"], ["1H", "15N"], ["15N", "1H"])
        )
        if not valid:
            raise ValueError(
                "Confirm compatible COSY/HSQC experiment and x/y nuclei; do not infer or swap axes."
            )

    def _validate_context(self, c):
        op = self.operation
        if op in ("integrate", "fit"):
            self._ordered(c["lower"], c["upper"])
            ids = c["spectrum_ids"] if op == "fit" else [c["spectrum_id"]]
            for oid in ids:
                self._within(
                    [c["lower"], c["upper"]], self.project.spectra[oid].axis, "Integral region"
                )
        if op == "fit":
            if c["time_basis"] == "echo_interval" and c["delay_multiplier"] is None:
                raise ValueError(
                    "Echo-interval time requires an explicit positive evolution-time multiplier."
                )
            table = self.project.tables[c["table_id"]]
            for pos, index in enumerate(c["row_indices"]):
                for key in ("delay_column", "sigma_column"):
                    if c[key] is None:
                        continue
                    try:
                        number = float(table.rows[index][c[key]])
                    except (KeyError, ValueError, TypeError) as exc:
                        raise ValueError(
                            f"Mapping row {pos + 1}: {c[key]} must contain a finite numeric value."
                        ) from exc
                    if (
                        not math.isfinite(number)
                        or number < 0
                        or (key == "sigma_column" and number == 0)
                    ):
                        raise ValueError(
                            f"Mapping row {pos + 1}: delay must be nonnegative and supplied area uncertainty positive and finite."
                        )
        if op == "process":
            spectrum = self.project.spectra[c["spectrum_id"]]
            method = c["method"]
            if method == "fft" and (spectrum.domain != "time" or spectrum.imag is None):
                raise ValueError(
                    "FFT requires qualified complex time-domain data; processed data cannot be transformed again."
                )
            if method != "fft" and spectrum.domain != "frequency":
                raise ValueError(
                    "Phase, baseline and reference operations require a frequency-domain spectrum."
                )
            if method == "phase" and spectrum.imag is None:
                raise ValueError(
                    "Phase correction requires retained complex data; quadrature cannot be invented."
                )
            if method == "baseline":
                for lower, upper in c["regions"]:
                    self._ordered(lower, upper, "Baseline window")
                    self._within([lower, upper], spectrum.axis, "Baseline window")
                if not c["regions"]:
                    raise ValueError("Choose explicit signal-free baseline windows.")
        if op == "yield":
            if bool(c["recovered_integral_id"]) != (c["recovered_protons"] is not None):
                raise ValueError("Recovered material requires both its integral and proton count.")
            ids = [c["product_integral_id"], c["standard_integral_id"]]
            if c["recovered_integral_id"]:
                ids.append(c["recovered_integral_id"])
            integrals = [self.project.integrals[i] for i in ids]
            if len({i.spectrum_id for i in integrals}) != 1:
                raise ValueError("Yield regions must belong to one acquired spectrum.")
            for i, integral in enumerate(integrals):
                if integral.area <= 0:
                    raise ValueError(
                        "Yield requires positive quantitative integral areas; review phase and region selection."
                    )
                for other in integrals[:i]:
                    if max(integral.lower, other.lower) < min(integral.upper, other.upper):
                        raise ValueError(
                            "Selected quantitative regions overlap; choose separated signals."
                        )
        if op == "normalize":
            ref = self.project.integrals[c["reference_integral_id"]]
            if ref.area <= 0 or self.project.spectra[ref.spectrum_id].nucleus != "1H":
                raise ValueError("Proton normalization requires a positive 1H reference integral.")
            if any(
                self.project.integrals[i].spectrum_id != ref.spectrum_id for i in c["integral_ids"]
            ):
                raise ValueError("Relative proton integrals must belong to the same 1H spectrum.")
        if op == "sample":
            if c["parent_ids"] and not c["transformation"].strip():
                raise ValueError("Describe the transformation from parent samples.")
            pending, seen = list(c["parent_ids"]), set()
            while pending:
                oid = pending.pop()
                if oid == c["sample_id"]:
                    raise ValueError("Sample transformations cannot form a cycle.")
                if oid not in seen:
                    seen.add(oid)
                    pending.extend(self.project.samples[oid].parent_ids)
        if op == "structure":
            ids = [a["id"] for a in c["atoms"]]
            if len(set(ids)) != len(ids):
                raise ValueError("Atom IDs must be unique within the candidate.")
            pairs = set()
            for bond in c["bonds"]:
                pair = tuple(sorted((bond["a"], bond["b"])))
                if bond["a"] not in ids or bond["b"] not in ids or pair in pairs:
                    raise ValueError(
                        "Bonds must join existing distinct atoms without duplicate pairs."
                    )
                pairs.add(pair)
            if c["status"] == "confirmed" and not c["evidence_ids"]:
                raise ValueError("Confirmed candidates require supporting observations.")
        if op in ("assign", "structure"):
            for oid in c["evidence_ids"]:
                if getattr(self._object_by_id(oid), "state", "current") == "stale":
                    raise ValueError(
                        "Refresh stale supporting evidence before using it in a saved interpretation."
                    )
        if op == "assign":
            candidate = self.project.structures.get(c["candidate_id"])
            if candidate and candidate.sample_id != c["sample_id"]:
                raise ValueError("Assignment and candidate must refer to the same explicit sample.")
            if c["atom_ids"] and not candidate:
                raise ValueError("Saved atom identities require a selected candidate structure.")
        if op == "grid_metadata":
            self._grid_semantics(c["experiment"], c["nuclei"])
        if op == "crosspeak":
            grid = self.project.grids[c["grid_id"]]
            self._grid_semantics(grid.metadata.get("experiment"), grid.nuclei)
            self._within([c["x_ppm"]], grid.x, "Crosspeak x")
            self._within([c["y_ppm"]], grid.y, "Crosspeak y")
        if op == "peak_label":
            self._within([c["ppm"]], self.project.spectra[c["spectrum_id"]].axis, "Signal label")
        if op == "annotate":
            if c["x"] + c["width"] > 1 + 1e-12 or c["y"] + c["height"] > 1 + 1e-12:
                raise ValueError("The annotation rectangle must remain inside its page.")
            if c["page"] > self.project.attachments[c["attachment_id"]].pages:
                raise ValueError("The selected reference page does not exist.")
            if c["reading_uncertainty_ppm"] is not None and c["approximate_ppm"] is None:
                raise ValueError("Reading uncertainty requires an approximate image reading.")
        if op == "compare" and c["left_id"] == c["right_id"]:
            raise ValueError("Choose two distinct observations for comparison.")
        if op == "undo" and not 0 <= c["target_revision"] <= getattr(self.project, "revision", 0):
            raise ValueError("Choose a retained revision between zero and the current revision.")


def get_command(operation, project, parent=None, initial=None) -> dict | None:
    """Run one modal editor; cancellation never emits a command."""
    dialog = CommandDialog(operation, project, parent, initial)
    try:
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.command()
        return None
    finally:
        # A parented modal remains a Qt child after closing unless explicitly released.
        # Defer destruction so Qt can finish delivering the acceptance/cancel signal.
        dialog.deleteLater()
