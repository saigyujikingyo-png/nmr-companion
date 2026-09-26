"""Native, read-only scientific views. Signals describe selections, never mutations.

Qt owns these widgets on its application thread. Numeric cursor values always
come from captured original arrays; rendering never changes a project object.
"""

from __future__ import annotations

from html import escape
import math

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg

BLUE = "#194b7b"
RED = "#b53636"
INK = "#253342"
PALETTE = (BLUE, "#32665e", "#6d5482", "#765b32", "#485c72")


def _gui_thread():
    app = QtWidgets.QApplication.instance()
    if not isinstance(app, QtWidgets.QApplication):
        raise RuntimeError("Create QApplication on the UI thread before creating a view.")
    if QtCore.QThread.currentThread() != app.thread():
        raise RuntimeError("Native views must be updated on the QApplication thread.")


def _label(text=""):
    label = QtWidgets.QLabel(text)
    label.setTextFormat(QtCore.Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


def _layout(widget):
    layout = QtWidgets.QVBoxLayout(widget)
    layout.setContentsMargins(6, 6, 6, 6)
    layout.setSpacing(4)
    return layout


def _plot():
    plot = pg.PlotWidget(background="w")
    plot.setMenuEnabled(False)
    plot.showGrid(x=True, y=True, alpha=0.15)
    plot.getPlotItem().hideButtons()
    plot.getPlotItem().titleLabel.setAttr("color", INK)
    plot.getPlotItem().titleLabel.setAttr("size", "10pt")
    for side in ("left", "bottom"):
        axis = plot.getAxis(side)
        axis.setPen(INK)
        axis.setTextPen(INK)
        axis.setStyle(tickFont=QtGui.QFont("Segoe UI", 9))
        axis.setLabel(color=INK, **{"font-size": "10pt"})
        axis.enableAutoSIPrefix(False)
    return plot


def extrema_envelope(x, y, budget=4096):
    """Keep real coordinates of both extrema per block, including the tail.

    The envelope is for display only. Zooming chooses a new envelope from the
    original samples; no averaging, normalization or peak-position substitution.
    """
    if len(x) <= budget:
        return x, y
    bins = max(1, (budget - 2) // 2)
    edges = np.linspace(0, len(x), bins + 1, dtype=int)
    indices = [0, len(x) - 1]
    for start, stop in zip(edges[:-1], edges[1:], strict=True):
        block = y[start:stop]
        indices.extend((start + int(np.argmin(block)), start + int(np.argmax(block))))
    selected = np.unique(indices)
    return x[selected], y[selected]


def _negative_segments(x, y):
    """Color negative line segments, keeping isolated minima and exact crossings.

    Interpolated zero crossings only split an already displayed straight segment;
    cursor observations still read the complete original arrays.
    """
    changes = np.diff(np.r_[False, y < 0, False].astype(np.int8))
    starts, stops = np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)
    xx, yy = [], []
    for start, stop in zip(starts, stops, strict=True):
        if xx:
            xx.append(np.nan)
            yy.append(np.nan)
        if start:
            fraction = y[start - 1] / (y[start - 1] - y[start])
            xx.append(x[start - 1] + (x[start] - x[start - 1]) * fraction)
            yy.append(0.0)
        xx.extend(x[start:stop])
        yy.extend(y[start:stop])
        if stop < len(y):
            fraction = -y[stop - 1] / (y[stop] - y[stop - 1])
            xx.append(x[stop - 1] + (x[stop] - x[stop - 1]) * fraction)
            yy.append(0.0)
    return np.asarray(xx, dtype=float), np.asarray(yy, dtype=float)


def _edges(axis):
    middle = axis[:-1] + np.diff(axis) / 2
    return np.r_[axis[0] - (axis[1] - axis[0]) / 2, middle, axis[-1] + (axis[-1] - axis[-2]) / 2]


class SpectrumView(QtWidgets.QWidget):
    regionSelected = QtCore.Signal(float, float)
    positionSelected = QtCore.Signal(float)

    def __init__(self, parent=None):
        _gui_thread()
        super().__init__(parent)
        self.plot = _plot()
        self.plot.setLabel("left", "Signed intensity")
        self.readout = _label("No spectra selected.")
        self._series = []
        self._updating = False
        self._selected = False
        self.region = pg.LinearRegionItem(brush=(25, 75, 123, 28), pen=pg.mkPen(BLUE))
        self.region.setZValue(20)
        self.region.hide()
        self.region.sigRegionChangeFinished.connect(self._region_finished)
        self.plot.addItem(self.region, ignoreBounds=True)
        self.legend = self.plot.addLegend(offset=(8, 8), labelTextColor=INK, labelTextSize="10pt")
        self.plot.getViewBox().sigXRangeChanged.connect(self._refresh_curves)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        self.plot.scene().sigMouseMoved.connect(self._hovered)
        self.select_button = QtWidgets.QPushButton("Select region")
        self.select_button.setEnabled(False)
        self.select_button.clicked.connect(self._begin_region)
        self.clear_button = QtWidgets.QPushButton("Clear region")
        self.clear_button.setEnabled(False)
        self.clear_button.clicked.connect(self.clear_region)
        self.region_readout = _label("No region selected.")
        self.integral_table = QtWidgets.QTableView(self)
        self.integral_table.setAccessibleName("Saved integrals")
        self.integral_model = QtGui.QStandardItemModel(0, 7, self)
        self.integral_model.setHorizontalHeaderLabels(
            ["Integral", "Spectrum", "Lower / ppm", "Upper / ppm", "Signed area", "Unit", "State"]
        )
        self.integral_table.setModel(self.integral_model)
        self.integral_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.integral_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.integral_table.setAlternatingRowColors(True)
        self.integral_table.setWordWrap(False)
        self.integral_table.setTextElideMode(QtCore.Qt.TextElideMode.ElideRight)
        self.integral_table.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustIgnored
        )
        self.integral_table.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Fixed
        )
        self.integral_table.setMinimumWidth(0)
        header = self.integral_table.horizontalHeader()
        header.setMinimumSectionSize(40)
        for column in (0, 1):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Stretch)
        metrics = self.integral_table.fontMetrics()
        for column, sample in (
            (2, "-123.456789"),
            (3, "-123.456789"),
            (4, "-0.123456789"),
            (5, "intensity*ppm"),
            (6, "current"),
        ):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.ResizeMode.Fixed)
            caption = self.integral_model.headerData(column, QtCore.Qt.Orientation.Horizontal)
            header.resizeSection(
                column,
                max(metrics.horizontalAdvance(sample), metrics.horizontalAdvance(caption)) + 16,
            )
        self.integral_table.verticalHeader().hide()
        self.integral_table.verticalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Fixed
        )
        self.integral_table.verticalHeader().setDefaultSectionSize(max(24, metrics.height() + 8))
        self.integral_table.hide()
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.select_button)
        bar.addWidget(self.clear_button)
        bar.addWidget(self.region_readout, 1)
        layout = _layout(self)
        layout.addLayout(bar)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.integral_table)
        layout.addWidget(self.readout)

    def set_spectra(
        self, spectra: list, integrals: list | None = None, peaklabels: list | None = None
    ):
        _gui_thread()
        units = {s.axis_unit for s in spectra}
        if len(units) > 1:
            raise ValueError("Seconds and ppm cannot share one spectrum axis.")
        self.plot.clear()
        self.legend.clear()
        self.integral_model.removeRows(0, self.integral_model.rowCount())
        self.integral_table.hide()
        self._series = []
        self.clear_region()
        self.select_button.setEnabled(bool(spectra))
        self.plot.addItem(self.region, ignoreBounds=True)
        self.plot.disableAutoRange()
        for number, spectrum in enumerate(spectra):
            x, y = np.array(spectrum.axis, dtype=float), np.array(spectrum.real, dtype=float)
            if x[0] > x[-1]:
                x, y = x[::-1].copy(), y[::-1].copy()
            x.setflags(write=False)
            y.setflags(write=False)
            name = f"{spectrum.name} ({spectrum.nucleus or 'unknown nucleus'})"
            curve = pg.PlotDataItem(
                pen=pg.mkPen(PALETTE[number % len(PALETTE)], width=1.2),
                name=escape(name),
                dynamicRangeLimit=None,
            )
            negative = pg.PlotDataItem(
                pen=pg.mkPen(RED, width=1.4), connect="finite", dynamicRangeLimit=None
            )
            self.plot.addItem(curve)
            self.plot.addItem(negative)
            self._series.append(
                (spectrum.id, spectrum.version, spectrum.name, x, y, curve, negative)
            )
        unit = next(iter(units), "ppm")
        self._axis_unit = unit
        self.plot.setLabel("bottom", "Chemical shift" if unit == "ppm" else "Time", units=unit)
        self.plot.getViewBox().invertX(unit == "ppm")
        self.plot.getViewBox().invertY(False)
        if not self._series:
            self.readout.setText("No spectra selected.")
            return
        self.reset_view()
        versions = {s[0]: s[1] for s in self._series}
        names = {s[0]: s[2] for s in self._series}
        for integral in integrals or []:
            if integral.spectrum_id not in versions:
                continue
            band = pg.LinearRegionItem(
                (integral.lower, integral.upper),
                movable=False,
                brush=(100, 110, 120, 16),
                pen=pg.mkPen("#9ca6b0"),
            )
            band.setZValue(-5)
            self.plot.addItem(band, ignoreBounds=True)
            state = (
                "stale"
                if integral.spectrum_version != versions[integral.spectrum_id]
                else "current"
            )
            tooltip = (
                f"{integral.name}\nSpectrum: {names[integral.spectrum_id]} ({integral.spectrum_id})\n"
                f"Range: {integral.lower!r} to {integral.upper!r} ppm\n"
                f"Signed area: {integral.area!r} {integral.unit}\nState: {state}\nIntegral: {integral.id}"
            )
            band.setToolTip(tooltip)
            band.setAcceptHoverEvents(True)
            values = [
                integral.name,
                names[integral.spectrum_id],
                integral.lower,
                integral.upper,
                integral.area,
                integral.unit,
                state,
            ]
            cells = []
            for column, value in enumerate(values):
                item = QtGui.QStandardItem(
                    format(value, ".10g") if isinstance(value, float) else str(value)
                )
                item.setEditable(False)
                item.setData(value, QtCore.Qt.ItemDataRole.UserRole)
                item.setToolTip(tooltip)
                color = (
                    RED
                    if column == 4 and integral.area < 0
                    else "#875414"
                    if column == 6 and state == "stale"
                    else INK
                )
                item.setForeground(QtGui.QColor(color))
                if column in (2, 3, 4):
                    item.setTextAlignment(
                        QtCore.Qt.AlignmentFlag.AlignRight | QtCore.Qt.AlignmentFlag.AlignVCenter
                    )
                cells.append(item)
            self.integral_model.appendRow(cells)
        rows = self.integral_model.rowCount()
        if rows:
            self.integral_table.setFixedHeight(
                self.integral_table.horizontalHeader().sizeHint().height()
                + min(rows, 4) * self.integral_table.verticalHeader().defaultSectionSize()
                + 2 * self.integral_table.frameWidth()
            )
            self.integral_table.show()
        for peak in peaklabels or []:
            if peak.spectrum_id not in versions:
                continue
            marker = pg.ScatterPlotItem(
                [peak.ppm],
                [peak.intensity],
                symbol="+",
                pen=pg.mkPen(RED if peak.intensity < 0 else BLUE),
                size=10,
            )
            self.plot.addItem(marker, ignoreBounds=True)
            text = pg.TextItem(f"{peak.label} [{peak.state}]", color=INK, anchor=(0, 1))
            text.setPos(peak.ppm, peak.intensity)
            self.plot.addItem(text, ignoreBounds=True)
        self.readout.setText(
            "Drag to pan; wheel to zoom. Click reads original signed samples. Select region creates handles; use an analysis command to commit."
        )

    def _refresh_curves(self, *_):
        if self._updating or not self._series:
            return
        self._updating = True
        try:
            lower, upper = self.plot.getViewBox().viewRange()[0]
            budget = max(128, min(8192, self.plot.width() * 3))
            for _, _, _, x, y, curve, negative in self._series:
                start = max(0, int(np.searchsorted(x, lower)) - 1)
                stop = min(len(x), int(np.searchsorted(x, upper, side="right")) + 1)
                xx, yy = extrema_envelope(x[start:stop], y[start:stop], budget)
                curve.setData(xx, yy)
                negative.setData(*_negative_segments(xx, yy))
        finally:
            self._updating = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "plot"):
            self._refresh_curves()

    def reset_view(self):
        _gui_thread()
        if not self._series:
            return
        lower = min(float(s[3][0]) for s in self._series)
        upper = max(float(s[3][-1]) for s in self._series)
        minimum = min(0.0, min(float(np.min(s[4])) for s in self._series))
        maximum = max(0.0, max(float(np.max(s[4])) for s in self._series))
        if minimum == maximum:
            minimum, maximum = minimum - 1, maximum + 1
        self.plot.setXRange(lower, upper, padding=0.02)
        self.plot.setYRange(minimum, maximum, padding=0.12)
        self._refresh_curves()

    def _begin_region(self):
        _gui_thread()
        if not self._series:
            return
        lower, upper = self.plot.getViewBox().viewRange()[0]
        minimum = min(float(s[3][0]) for s in self._series)
        maximum = max(float(s[3][-1]) for s in self._series)
        lower, upper = max(lower, minimum), min(upper, maximum)
        if lower >= upper:
            self.reset_view()
            lower, upper = minimum, maximum
        margin = (upper - lower) / 4
        self.set_region(lower + margin, upper - margin)

    def clear_region(self):
        """Discard the display selection without emitting a scientific edit."""
        _gui_thread()
        self._selected = False
        self.region.hide()
        self.clear_button.setEnabled(False)
        self.region_readout.setText("No region selected.")

    def set_region(self, lower, upper):
        _gui_thread()
        if not self._series:
            raise ValueError("Select a spectrum before selecting a region.")
        lower, upper = sorted((float(lower), float(upper)))
        minimum = min(float(s[3][0]) for s in self._series)
        maximum = max(float(s[3][-1]) for s in self._series)
        if (
            not all(math.isfinite(v) for v in (lower, upper))
            or not minimum <= lower < upper <= maximum
        ):
            raise ValueError(
                "The region must be finite, nonempty and inside the displayed spectra."
            )
        self.region.blockSignals(True)
        try:
            self.region.setBounds((minimum, maximum))
            self.region.setRegion((lower, upper))
            self._selected = True
            self.region.show()
            self.clear_button.setEnabled(True)
        finally:
            self.region.blockSignals(False)
        self._region_finished()

    def selected_region(self) -> tuple | None:
        return tuple(sorted(float(v) for v in self.region.getRegion())) if self._selected else None

    def _region_finished(self):
        selected = self.selected_region()
        if selected is not None:
            self.region_readout.setText(
                f"Selected: {selected[0]:.7g} to {selected[1]:.7g} {self._axis_unit}"
            )
            self.regionSelected.emit(*selected)

    def nearest_point(self, position, spectrum_id=None):
        for sid, _, _, x, y, _, _ in self._series:
            if spectrum_id is not None and sid != spectrum_id:
                continue
            if not math.isfinite(position) or not x[0] <= position <= x[-1]:
                return None
            index = int(np.argmin(np.abs(x - position)))
            return float(x[index]), float(y[index])
        return None

    def _hovered(self, scene_position):
        if not self._series or not self.plot.getViewBox().sceneBoundingRect().contains(
            scene_position
        ):
            return
        point = self.plot.getViewBox().mapSceneToView(scene_position)
        readings = []
        for sid, _, name, _, _, _, _ in self._series:
            nearest = self.nearest_point(point.x(), sid)
            if nearest:
                readings.append(f"{name}: x={nearest[0]:.7g}, signed intensity={nearest[1]:.7g}")
        if readings:
            self.readout.setText("Nearest original samples | " + " | ".join(readings))

    def _clicked(self, event):
        if (
            event.button() != QtCore.Qt.MouseButton.LeftButton
            or not self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos())
        ):
            return
        self._hovered(event.scenePos())
        nearest = self.nearest_point(self.plot.getViewBox().mapSceneToView(event.scenePos()).x())
        if nearest:
            self.positionSelected.emit(nearest[0])


class GridView(QtWidgets.QWidget):
    pointSelected = QtCore.Signal(float, float)

    def __init__(self, parent=None):
        _gui_thread()
        super().__init__(parent)
        self.plot = _plot()
        self.plot.getViewBox().invertX(True)
        self.plot.getViewBox().invertY(True)
        self.readout = _label("No processed 2D grid selected.")
        self.legend = _label("Signed intensity: negative red, zero white, positive blue.")
        self.image_item = None
        self._original = None
        self._bounds = None
        self.markers = []
        self.color_map = pg.ColorMap([0.0, 0.5, 1.0], [RED, "#ffffff", BLUE])
        self.plot.scene().sigMouseMoved.connect(self._hovered)
        self.plot.scene().sigMouseClicked.connect(self._clicked)
        layout = _layout(self)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.legend)
        layout.addWidget(self.readout)

    def set_grid(self, grid, crosspeaks: list | None = None):
        _gui_thread()
        self.plot.clear()
        self.image_item = None
        self._original = None
        self._bounds = None
        self.markers = []
        if grid is None:
            self.plot.setTitle("")
            self.plot.setLabel("bottom", "x", units="ppm")
            self.plot.setLabel("left", "y", units="ppm")
            self.legend.setText("Signed intensity: negative red, zero white, positive blue.")
            self.readout.setText("No processed 2D grid selected.")
            return
        x, y, z = (np.array(values, dtype=float) for values in (grid.x, grid.y, grid.z))
        for array in (x, y, z):
            array.setflags(write=False)
        self._original = x, y, z
        xx, yy, zz = x, y, z
        if x[0] > x[-1]:
            xx, zz = x[::-1], zz[:, ::-1]
        if y[0] > y[-1]:
            yy, zz = y[::-1], zz[::-1, :]
        xe, ye = _edges(xx), _edges(yy)
        self._bounds = (float(xe[0]), float(xe[-1]), float(ye[0]), float(ye[-1]))
        limit = float(np.max(np.abs(z))) or 1.0
        regular = all(
            np.allclose(np.diff(axis), axis[1] - axis[0], rtol=1e-12, atol=0) for axis in (xx, yy)
        )
        if regular:
            self.image_item = pg.ImageItem(axisOrder="row-major")
            self.image_item.setLookupTable(self.color_map.getLookupTable(nPts=257))
            self.image_item.setImage(
                np.ascontiguousarray(zz),
                autoLevels=False,
                levels=(-limit, limit),
                autoDownsample=False,
            )
            self.image_item.setRect(QtCore.QRectF(xe[0], ye[0], xe[-1] - xe[0], ye[-1] - ye[0]))
        else:
            mx, my = np.meshgrid(xe, ye)
            self.image_item = pg.PColorMeshItem(
                mx, my, zz, colorMap=self.color_map, levels=(-limit, limit), enableAutoLevels=False
            )
        self.plot.addItem(self.image_item)
        self.plot.setLabel("bottom", f"x / {grid.nuclei[0] or 'unknown nucleus'}", units="ppm")
        self.plot.setLabel("left", f"y / {grid.nuclei[1] or 'unknown nucleus'}", units="ppm")
        self.plot.setTitle(escape(grid.name))
        for peak in crosspeaks or []:
            if peak.grid_id != grid.id:
                continue
            marker = pg.ScatterPlotItem(
                [peak.x_ppm], [peak.y_ppm], symbol="+", size=12, pen=pg.mkPen(INK, width=1.5)
            )
            self.plot.addItem(marker, ignoreBounds=True)
            self.markers.append(marker)
            label = pg.TextItem(f"{peak.label} [{peak.state}]", color=INK, anchor=(0, 1))
            label.setPos(peak.x_ppm, peak.y_ppm)
            self.plot.addItem(label, ignoreBounds=True)
        self.legend.setText(
            f"Signed intensity: red {-limit:.6g} | white 0 | blue {limit:.6g}. Linear display colors; original numeric values retained."
        )
        self.readout.setText(
            "x = columns, y = rows. Drag to pan; wheel to zoom. Click reads the nearest original grid point."
        )
        self.reset_view()

    def reset_view(self):
        _gui_thread()
        if self._bounds:
            x0, x1, y0, y1 = self._bounds
            self.plot.setRange(xRange=(x0, x1), yRange=(y0, y1), padding=0.02)

    def nearest_point(self, x, y):
        if self._original is None or not all(math.isfinite(v) for v in (x, y)):
            return None
        x0, x1, y0, y1 = self._bounds
        if not x0 <= x <= x1 or not y0 <= y <= y1:
            return None
        original_x, original_y, values = self._original
        column = int(np.argmin(np.abs(original_x - x)))
        row = int(np.argmin(np.abs(original_y - y)))
        return float(original_x[column]), float(original_y[row]), float(values[row, column])

    def _hovered(self, position):
        if not self.plot.getViewBox().sceneBoundingRect().contains(position):
            return
        point = self.plot.getViewBox().mapSceneToView(position)
        nearest = self.nearest_point(point.x(), point.y())
        if nearest:
            self.readout.setText(
                f"Nearest original point: x={nearest[0]:.7g} ppm, y={nearest[1]:.7g} ppm, signed intensity={nearest[2]:.7g}"
            )

    def _clicked(self, event):
        if (
            event.button() != QtCore.Qt.MouseButton.LeftButton
            or not self.plot.getViewBox().sceneBoundingRect().contains(event.scenePos())
        ):
            return
        self._hovered(event.scenePos())
        point = self.plot.getViewBox().mapSceneToView(event.scenePos())
        nearest = self.nearest_point(point.x(), point.y())
        if nearest:
            self.pointSelected.emit(nearest[0], nearest[1])


class _GraphicsCanvas(QtWidgets.QGraphicsView):
    """Native scene navigation shared by structure and reference views."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setBackgroundBrush(QtGui.QColor("#edf0f3"))
        self.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing | QtGui.QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._fit_on_resize = True

    def reset_view(self):
        self._fit_on_resize = True
        self.resetTransform()
        if not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_on_resize and not self.sceneRect().isEmpty():
            self.fitInView(self.sceneRect(), QtCore.Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, event):
        if not event.angleDelta().y():
            event.ignore()
            return
        factor = 1.2 if event.angleDelta().y() > 0 else 1 / 1.2
        if 0.01 <= self.transform().m11() * factor <= 200:
            self._fit_on_resize = False
            self.scale(factor, factor)
        event.accept()


class _AtomItem(QtWidgets.QGraphicsSimpleTextItem):
    def __init__(self, atom, selected):
        text = f"{atom.label} [{atom.element}]" + (f"  {atom.stereo}" if atom.stereo else "")
        super().__init__(text)
        self._selected = selected
        self._id = atom.id
        self.setData(0, atom.id)
        self.setBrush(QtGui.QColor(INK))
        font = QtGui.QFont("Segoe UI", 11)
        self.setFont(font)
        self.setZValue(10)
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"Atom {atom.id}; manual coordinates ({atom.x:g}, {atom.y:g}); stereo label {atom.stereo or 'unspecified'}"
        )
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        background = QtWidgets.QGraphicsRectItem(self.boundingRect().adjusted(-3, -2, 3, 2), self)
        background.setPen(QtGui.QPen(QtCore.Qt.PenStyle.NoPen))
        background.setBrush(QtGui.QColor("white"))
        background.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemStacksBehindParent)
        background.setAcceptedMouseButtons(QtCore.Qt.MouseButton.NoButton)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            event.accept()
            self._selected.emit(self._id)
        else:
            super().mousePressEvent(event)


class StructureView(QtWidgets.QWidget):
    atomSelected = QtCore.Signal(str)

    def __init__(self, parent=None):
        _gui_thread()
        super().__init__(parent)
        self.context = _label("No manual structure selected.")
        self.view = _GraphicsCanvas(self)
        self.atom_items = {}
        self.bond_items = []
        layout = _layout(self)
        layout.addWidget(self.context)
        layout.addWidget(self.view, 1)
        self.note = _label(
            "Manual atom/bond graph. Wedges and stereochemical labels are supplied interpretations, not inferred chemistry."
        )
        layout.addWidget(self.note)

    def set_structure(self, structure):
        _gui_thread()
        scene = self.view.scene()
        scene.clear()
        self.atom_items = {}
        self.bond_items = []
        if structure is None:
            self.context.setText("No manual structure selected.")
            self.view.setSceneRect(QtCore.QRectF())
            return
        self.context.setText(
            f"{structure.name} | {structure.status} | {structure.state} | sample {structure.sample_id}"
        )
        xs = [atom.x for atom in structure.atoms]
        ys = [atom.y for atom in structure.atoms]
        scale = 500 / max(max(xs) - min(xs), max(ys) - min(ys), 1)
        points = {
            atom.id: QtCore.QPointF((atom.x - min(xs)) * scale, (atom.y - min(ys)) * scale)
            for atom in structure.atoms
        }
        for bond in structure.bonds:
            a, b = points[bond.a], points[bond.b]
            dx, dy = b.x() - a.x(), b.y() - a.y()
            length = math.hypot(dx, dy) or 1.0
            normal = QtCore.QPointF(-dy / length, dx / length)
            pen = pg.mkPen(INK, width=1.8)
            items = []
            if bond.stereo == "wedge":
                polygon = QtGui.QPolygonF([a, b + normal * 8, b - normal * 8])
                items.append(scene.addPolygon(polygon, pen, QtGui.QBrush(QtGui.QColor(INK))))
            elif bond.stereo == "hash":
                for fraction in np.linspace(0.12, 0.95, 8):
                    center = a + (b - a) * float(fraction)
                    half = normal * (8 * float(fraction))
                    items.append(scene.addLine(QtCore.QLineF(center - half, center + half), pen))
            elif bond.stereo == "either":
                path = QtGui.QPainterPath(a)
                for index in range(1, 13):
                    point = a + (b - a) * (index / 13) + normal * (3 if index % 2 else -3)
                    path.lineTo(point)
                path.lineTo(b)
                items.append(scene.addPath(path, pen))
            else:
                offsets = (
                    [0, 5]
                    if bond.order == 1.5
                    else [
                        (index - (int(bond.order) - 1) / 2) * 5 for index in range(int(bond.order))
                    ]
                )
                for index, offset in enumerate(offsets):
                    line_pen = pg.mkPen(
                        INK,
                        width=1.8,
                        style=QtCore.Qt.PenStyle.DashLine
                        if bond.order == 1.5 and index == 1
                        else QtCore.Qt.PenStyle.SolidLine,
                    )
                    shift = normal * offset
                    items.append(scene.addLine(QtCore.QLineF(a + shift, b + shift), line_pen))
            if bond.stereo != "none" and bond.order != 1:
                # An unusual supplied order/stereo combination is shown literally,
                # not silently downgraded or interpreted as different chemistry.
                order_text = scene.addSimpleText(f"order {bond.order:g}")
                order_text.setBrush(QtGui.QColor(INK))
                order_text.setPos((a + b) / 2 + normal * 12)
                items.append(order_text)
            for item in items:
                item.setToolTip(
                    f"{bond.a} to {bond.b}; supplied order {bond.order:g}; stereo {bond.stereo}"
                )
                item.setData(0, (bond.a, bond.b))
                item.setData(1, bond.order)
                item.setData(2, bond.stereo)
                item.setZValue(0)
            self.bond_items.extend(items)
        for atom in structure.atoms:
            item = _AtomItem(atom, self.atomSelected)
            item.setPos(points[atom.id] - item.boundingRect().center())
            scene.addItem(item)
            self.atom_items[atom.id] = item
        self.view.setSceneRect(scene.itemsBoundingRect().adjusted(-25, -25, 25, 25))
        self.view.reset_view()


class _PageCanvas(_GraphicsCanvas):
    rectangleSelected = QtCore.Signal(float, float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.page_rect = QtCore.QRectF()
        self.selection_mode = False
        self._start = None
        self._selection_item = None

    def set_selection_mode(self, enabled):
        self.selection_mode = enabled
        self._start = None
        self.setDragMode(
            QtWidgets.QGraphicsView.DragMode.NoDrag
            if enabled
            else QtWidgets.QGraphicsView.DragMode.ScrollHandDrag
        )
        self.viewport().setCursor(
            QtCore.Qt.CursorShape.CrossCursor if enabled else QtCore.Qt.CursorShape.OpenHandCursor
        )

    def _rectangle(self, position):
        return (
            QtCore.QRectF(self._start, self.mapToScene(position))
            .normalized()
            .intersected(self.page_rect)
        )

    def mousePressEvent(self, event):
        point = self.mapToScene(event.position().toPoint())
        if (
            self.selection_mode
            and event.button() == QtCore.Qt.MouseButton.LeftButton
            and self.page_rect.contains(point)
        ):
            self._start = point
            if self._selection_item is not None:
                self.scene().removeItem(self._selection_item)
            self._selection_item = self.scene().addRect(
                QtCore.QRectF(point, point), pg.mkPen(BLUE, width=1.5), pg.mkBrush(25, 75, 123, 25)
            )
            self._selection_item.setZValue(20)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._start is not None:
            self._selection_item.setRect(self._rectangle(event.position().toPoint()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._start is not None and event.button() == QtCore.Qt.MouseButton.LeftButton:
            rectangle = self._rectangle(event.position().toPoint())
            self._selection_item.setRect(rectangle)
            self._start = None
            event.accept()
            if rectangle.width() > 0 and rectangle.height() > 0:
                self.rectangleSelected.emit(
                    rectangle.x() / self.page_rect.width(),
                    rectangle.y() / self.page_rect.height(),
                    rectangle.width() / self.page_rect.width(),
                    rectangle.height() / self.page_rect.height(),
                )
            return
        super().mouseReleaseEvent(event)


class ReferenceView(QtWidgets.QWidget):
    rectangleSelected = QtCore.Signal(float, float, float, float)

    def __init__(self, parent=None):
        _gui_thread()
        super().__init__(parent)
        self.view = _PageCanvas(self)
        self.view.rectangleSelected.connect(self._rectangle_selected)
        self.select_button = QtWidgets.QToolButton()
        self.select_button.setText("Select rectangle")
        self.select_button.setCheckable(True)
        self.select_button.setEnabled(False)
        self.select_button.toggled.connect(self.view.set_selection_mode)
        fit_button = QtWidgets.QPushButton("Fit page")
        fit_button.clicked.connect(self.view.reset_view)
        bar = QtWidgets.QHBoxLayout()
        bar.addWidget(self.select_button)
        bar.addWidget(fit_button)
        bar.addStretch(1)
        layout = _layout(self)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
        self.note = _label(
            "No reference page selected. Page annotations are normalized image coordinates, not numerical spectra."
        )
        layout.addWidget(self.note)
        self.annotation_items = []
        self.page_item = None

    def _rectangle_selected(self, x, y, width, height):
        self.note.setText(
            f"Selected page rectangle: x={x:.4f}, y={y:.4f}, width={width:.4f}, height={height:.4f}. "
            "Normalized image coordinates; use Annotate reference to save."
        )
        self.rectangleSelected.emit(x, y, width, height)

    def clear(self):
        """Clear a previous page immediately while a new selection is loading."""
        _gui_thread()
        self.select_button.setChecked(False)
        self.select_button.setEnabled(False)
        self.view._start = None
        self.view._selection_item = None
        self.view.scene().clear()
        self.view.page_rect = QtCore.QRectF()
        self.view.setSceneRect(QtCore.QRectF())
        self.view.reset_view()
        self.annotation_items = []
        self.page_item = None
        self.note.setText(
            "No reference page selected. Page annotations are normalized image coordinates, not numerical spectra."
        )

    def set_page(self, png_bytes: bytes, annotations: list | None = None):
        """Show one rendered page; callers filter annotations to that attachment/page."""
        _gui_thread()
        if not isinstance(png_bytes, bytes) or len(png_bytes) > 32 * 1024 * 1024:
            raise ValueError("Supply a bounded rendered PNG page.")
        image = QtGui.QImage.fromData(png_bytes, "PNG")
        if image.isNull() or image.width() * image.height() > 16000000:
            raise ValueError("The PNG page is invalid or exceeds 16 million pixels.")
        image.setDevicePixelRatio(1)
        self.clear()
        self.select_button.setEnabled(True)
        scene = self.view.scene()
        self.page_item = scene.addPixmap(QtGui.QPixmap.fromImage(image))
        width, height = image.width(), image.height()
        self.view.page_rect = QtCore.QRectF(0, 0, width, height)
        self.view.setSceneRect(self.view.page_rect)
        for annotation in annotations or []:
            rectangle = QtCore.QRectF(
                annotation.x * width,
                annotation.y * height,
                annotation.width * width,
                annotation.height * height,
            )
            pen = pg.mkPen(
                RED,
                width=1.5,
                style=QtCore.Qt.PenStyle.DashLine
                if annotation.state == "stale"
                else QtCore.Qt.PenStyle.SolidLine,
            )
            item = scene.addRect(rectangle, pen)
            item.setData(0, annotation.id)
            self.annotation_items.append(item)
            text = scene.addSimpleText(f"{annotation.label} [{annotation.state}]")
            text.setBrush(QtGui.QColor(RED))
            text.setPos(rectangle.x(), max(0, rectangle.y() - text.boundingRect().height()))
        self.view.reset_view()
        self.note.setText(
            "Reference page only. Drag to pan; wheel to zoom. Enable Select rectangle to mark normalized page coordinates. Approximate image readings never become numerical spectra."
        )


class FitView(QtWidgets.QWidget):
    def __init__(self, parent=None):
        _gui_thread()
        super().__init__(parent)
        self.context = _label("No relaxation analysis selected.")
        self.signal_plot = _plot()
        self.residual_plot = _plot()
        self.signal_plot.setLabel("left", "Signed integrated signal")
        self.residual_plot.setLabel("left", "Residual (observed - predicted)")
        for plot in (self.signal_plot, self.residual_plot):
            plot.setLabel("bottom", "Elapsed time", units="s")
            plot.getViewBox().invertX(False)
        self.residual_plot.setXLink(self.signal_plot)
        self.legend = self.signal_plot.addLegend(
            offset=(8, 8), labelTextColor=INK, labelTextSize="10pt"
        )
        self.warnings = _label("")
        self.observed = self.predicted = self.residuals = None
        layout = _layout(self)
        layout.addWidget(self.context)
        layout.addWidget(self.signal_plot, 3)
        layout.addWidget(self.residual_plot, 2)
        layout.addWidget(self.warnings)

    def set_analysis(self, analysis):
        _gui_thread()
        if analysis is not None and analysis.kind != "relaxation":
            raise ValueError("FitView needs a relaxation analysis.")
        self.signal_plot.clear()
        self.residual_plot.clear()
        self.legend.clear()
        self.signal_plot.setTitle("")
        self.residual_plot.setTitle("")
        self.observed = self.predicted = self.residuals = None
        if analysis is None:
            self.context.setText("No relaxation analysis selected.")
            self.warnings.setText("")
            return
        result = analysis.result
        time = np.array(result["time_s"], dtype=float)
        signal = np.array(result["signals"], dtype=float)
        brushes = [pg.mkBrush(RED if value < 0 else BLUE) for value in signal]
        self.observed = pg.PlotDataItem(
            time,
            signal,
            pen=None,
            symbol="o",
            symbolSize=7,
            symbolBrush=brushes,
            name="Observed signed signal",
            dynamicRangeLimit=None,
        )
        self.signal_plot.addItem(self.observed)
        if result["predicted"]:
            order = np.argsort(time, kind="stable")
            self.predicted = pg.PlotDataItem(
                time[order],
                np.array(result["predicted"])[order],
                pen=pg.mkPen(BLUE, width=1.5),
                name="Predicted at observed times",
                dynamicRangeLimit=None,
            )
            self.signal_plot.addItem(self.predicted)
            residual = np.array(result["residuals"], dtype=float)
            self.residuals = pg.PlotDataItem(
                time,
                residual,
                pen=None,
                symbol="o",
                symbolSize=6,
                symbolBrush=[pg.mkBrush(RED if value < 0 else BLUE) for value in residual],
                dynamicRangeLimit=None,
            )
            self.residual_plot.addItem(self.residuals)
            self.residual_plot.setTitle("Signed residuals")
        else:
            self.residual_plot.setTitle("Residuals unavailable: no identified prediction")
        for plot in (self.signal_plot, self.residual_plot):
            plot.addItem(pg.InfiniteLine(0, angle=0, pen=pg.mkPen("#aeb8c2")), ignoreBounds=True)
            plot.enableAutoRange()
        estimate = "unavailable" if result["T_s"] is None else f"{result['T_s']:.7g} s"
        uncertainty = "unavailable" if result["u_T_s"] is None else f"{result['u_T_s']:.5g} s"
        self.context.setText(
            f"{analysis.name} | {analysis.state} | {result['model']} | {result['status']} | {result['purpose']} | T={estimate}; u(T)={uncertainty}"
        )
        warnings = result["warnings"]
        self.warnings.setText(
            "Stored fit results; no refitting in the view. "
            + (
                " | ".join(warnings)
                if warnings
                else "Uncertainty is conditional on the declared model and input data."
            )
        )
