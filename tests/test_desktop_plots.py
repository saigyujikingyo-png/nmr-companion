"""Native widget tests; offscreen Qt never controls a user's desktop window."""

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6 import QtCore, QtGui, QtTest, QtWidgets
import numpy as np
import pyqtgraph as pg
import pytest

from nmr_companion.models import Analysis, Grid, Integral, Spectrum
from nmr_companion.evidence_models import Annotation, Crosspeak, Structure


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(
        ["nmr-plots-tests", "-platform", "offscreen"]
    )
    yield app
    app.processEvents()


@pytest.fixture
def make_widget(qapp):
    widgets = []

    def make(cls):
        widget = cls()
        widget.resize(800, 540)
        widgets.append(widget)
        return widget

    yield make
    for widget in widgets:
        widget.close()
        widget.deleteLater()
    qapp.processEvents()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def test_native_empty_views_construct_without_project_or_service(make_widget, qapp):
    from nmr_companion.desktop.plots import (
        FitView,
        GridView,
        ReferenceView,
        SpectrumView,
        StructureView,
    )

    for cls in (SpectrumView, GridView, StructureView, ReferenceView, FitView):
        widget = make_widget(cls)
        widget.show()
        qapp.processEvents()
        assert isinstance(widget, QtWidgets.QWidget)
        assert not widget.grab().isNull()
    spectrum = make_widget(SpectrumView)
    assert spectrum.selected_region() is None


def spectrum(axis, signal, *, sid="trace", unit="ppm"):
    return Spectrum(
        id=sid,
        name=sid,
        axis=np.asarray(axis, dtype=float).tolist(),
        real=np.asarray(signal, dtype=float).tolist(),
        axis_unit=unit,
        domain="frequency" if unit == "ppm" else "time",
        nucleus="1H",
    )


def grid(*, regular=False, reverse_y=False):
    y = [100.0, 120.0]
    z = [[1.0, -2.0, 3.0], [4.0, -8.0, 6.0]]
    if reverse_y:
        y, z = y[::-1], z[::-1]
    return Grid(
        id="grid_1",
        name="Synthetic explicit axes",
        x=[6.0, 4.0, 2.0] if regular else [8.0, 3.0, 1.0],
        y=y,
        z=z,
        nuclei=["1H", "13C"],
    )


def plot_position(plot, x, y):
    return plot.mapFromScene(plot.getViewBox().mapViewToScene(QtCore.QPointF(x, y)))


def test_display_envelope_keeps_true_coordinates_both_signs_and_tail():
    from nmr_companion.desktop.plots import extrema_envelope

    x = np.linspace(-5, 5, 10007) ** 3
    y = np.zeros_like(x)
    spikes = {1: 7.0, 111: -9.0, 5100: 50.0, 10005: -60.0, 10006: 11.0}
    for index, value in spikes.items():
        y[index] = value
    before = y.copy()
    xx, yy = extrema_envelope(x, y, 128)
    assert len(xx) <= 128
    assert xx[0] == x[0] and xx[-1] == x[-1]
    for index, value in spikes.items():
        assert any(px == x[index] and py == value for px, py in zip(xx, yy, strict=True))
    assert np.array_equal(yy, y[np.searchsorted(x, xx)])
    assert np.array_equal(y, before)


@pytest.mark.parametrize("descending", [False, True])
def test_spectrum_extrema_survive_display_and_zoom_without_normalization(
    make_widget, qapp, descending
):
    from nmr_companion.desktop.plots import SpectrumView

    x = np.linspace(0, 10, 20001)
    y = np.zeros_like(x)
    y[7111], y[7112], y[-2] = 900.0, -450.0, -800.0
    if descending:
        x, y = x[::-1], y[::-1]
    first = spectrum(x, y)
    second = spectrum(x, y * 2, sid="second")
    before = [first.model_dump(), second.model_dump()]
    widget = make_widget(SpectrumView)
    widget.set_spectra([first, second])
    widget.show()
    qapp.processEvents()
    curves = [item for item in widget.plot.listDataItems() if item.name()]
    assert len(curves) == 2
    assert [np.max(curve.getData()[1]) for curve in curves] == [900, 1800]
    assert [np.min(curve.getData()[1]) for curve in curves] == [-800, -1600]
    assert widget.plot.getViewBox().state["xInverted"] is True
    widget.plot.setXRange(3.55, 3.56, padding=0)
    qapp.processEvents()
    xx, yy = curves[0].getData()
    assert 900 in yy and -450 in yy
    assert any(px == pytest.approx(3.5555) and py == 900 for px, py in zip(xx, yy, strict=True))
    assert widget.nearest_point(3.5555) == pytest.approx((3.5555, 900))
    assert widget.nearest_point(3.5555, "second") == pytest.approx((3.5555, 1800))
    widget.reset_view()
    assert [first.model_dump(), second.model_dump()] == before


def test_spectrum_native_click_region_signal_and_time_axis(make_widget, qapp):
    from nmr_companion.desktop.plots import SpectrumView

    trace = spectrum([4, 3, 2, 1, 0], [0, 4, -2, 1, 0])
    before = trace.model_dump()
    widget = make_widget(SpectrumView)
    widget.set_spectra([trace])
    widget.show()
    qapp.processEvents()
    click = QtTest.QSignalSpy(widget.positionSelected)
    QtTest.QTest.mouseClick(
        widget.plot.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=plot_position(widget.plot, 2, -2),
    )
    qapp.processEvents()
    assert click.count() == 1 and click.at(0)[0] == 2.0
    regions = QtTest.QSignalSpy(widget.regionSelected)
    widget.set_region(3, 1)
    assert widget.selected_region() == (1.0, 3.0)
    assert regions.count() == 1 and regions.at(0) == [1.0, 3.0]
    widget.region.setRegion((1.5, 2.5))
    assert widget.selected_region() == (1.5, 2.5) and regions.count() >= 2
    assert trace.model_dump() == before
    time_trace = spectrum([0, 0.1, 0.2], [1, -2, 3], unit="s")
    with pytest.raises(ValueError, match="Seconds and ppm"):
        widget.set_spectra([trace, time_trace])
    widget.set_spectra([time_trace])
    assert widget.plot.getViewBox().state["xInverted"] is False
    assert widget.selected_region() is None
    with pytest.raises(ValueError):
        widget.set_region(-1, 0.1)


@pytest.mark.parametrize(
    "regular,reverse_y", [(False, False), (False, True), (True, False), (True, True)]
)
def test_grid_real_coordinates_nearest_values_signs_and_ppm_orientation(
    make_widget, qapp, regular, reverse_y
):
    from nmr_companion.desktop.plots import GridView

    matrix = grid(regular=regular, reverse_y=reverse_y)
    before = matrix.model_dump()
    widget = make_widget(GridView)
    widget.set_grid(matrix)
    widget.show()
    qapp.processEvents()
    vx = 4.0 if regular else 3.0
    assert widget.nearest_point(vx + 0.1, 119) == (vx, 120.0, -8.0)
    assert widget.nearest_point(999, 100) is None
    assert widget.plot.getViewBox().state["xInverted"] is True
    assert widget.plot.getViewBox().state["yInverted"] is True
    if regular:
        assert isinstance(widget.image_item, pg.ImageItem)
        assert np.array_equal(widget.image_item.image, [[3, -2, 1], [6, -8, 4]])
    else:
        assert isinstance(widget.image_item, pg.PColorMeshItem)
        assert np.array_equal(widget.image_item.x[0], [0.0, 2.0, 5.5, 10.5])
        assert np.array_equal(widget.image_item.y[:, 0], [90, 110, 130])
        assert np.array_equal(widget.image_item.z, [[3, -2, 1], [6, -8, 4]])
    image = widget.plot.viewport().grab().toImage()
    negative_pixel = image.pixelColor(plot_position(widget.plot, vx, 100))
    positive_pixel = image.pixelColor(plot_position(widget.plot, matrix.x[-1], 120))
    assert negative_pixel.red() > negative_pixel.blue()
    assert positive_pixel.blue() > positive_pixel.red()
    selected = QtTest.QSignalSpy(widget.pointSelected)
    QtTest.QTest.mouseClick(
        widget.plot.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=plot_position(widget.plot, vx, 120),
    )
    qapp.processEvents()
    assert selected.count() == 1 and selected.at(0) == [vx, 120.0]
    assert "-8" in widget.readout.text()
    assert matrix.model_dump() == before


def test_grid_markers_keep_manual_positions_instead_of_snapping_to_pixels(make_widget):
    from nmr_companion.desktop.plots import GridView

    peak = Crosspeak(
        id="crosspeak_1",
        grid_id="grid_1",
        x_ppm=3.2,
        y_ppm=115.0,
        intensity=-8.0,
        label="Manual H-C",
        state="stale",
        source_versions={"grid_1": 1},
    )
    widget = make_widget(GridView)
    widget.set_grid(grid(), [peak])
    x, y = widget.markers[0].getData()
    assert list(x) == [3.2] and list(y) == [115.0]
    assert widget.nearest_point(3.2, 115.0) == (3.0, 120.0, -8.0)


def test_visible_region_controls_initialize_inside_zoom_and_clear(make_widget, qapp):
    from nmr_companion.desktop.plots import INK, SpectrumView

    trace = spectrum([4, 3, 2, 1, 0], [0, 4, -2, 1, 0])
    before = trace.model_dump()
    widget = make_widget(SpectrumView)
    assert not widget.select_button.isEnabled()
    assert not widget.clear_button.isEnabled()
    widget.set_spectra([trace])
    widget.show()
    widget.plot.setXRange(1.0, 3.0, padding=0)
    qapp.processEvents()
    regions = QtTest.QSignalSpy(widget.regionSelected)
    QtTest.QTest.mouseClick(widget.select_button, QtCore.Qt.MouseButton.LeftButton)
    assert regions.count() == 1
    lower, upper = widget.selected_region()
    assert 1.0 <= lower < upper <= 3.0
    assert widget.region.isVisible() and widget.region.movable
    assert "Selected:" in widget.region_readout.text() and "ppm" in widget.region_readout.text()
    assert widget.clear_button.isEnabled()
    QtTest.QTest.mouseClick(widget.clear_button, QtCore.Qt.MouseButton.LeftButton)
    assert widget.selected_region() is None and not widget.region.isVisible()
    assert not widget.clear_button.isEnabled()
    assert regions.count() == 1
    assert QtGui.QColor(widget.legend.labelTextColor()) == QtGui.QColor(INK)
    assert trace.model_dump() == before
    widget.set_spectra([])
    assert not widget.select_button.isEnabled()


def test_isolated_negative_peak_is_drawn_red_to_true_zero_crossings(make_widget):
    from nmr_companion.desktop.plots import SpectrumView

    widget = make_widget(SpectrumView)
    widget.set_spectra([spectrum([0, 1, 2, 3, 4], [2, -2, 2, -1, -2])])
    negative = widget._series[0][-1]
    xx, yy = negative.getData()
    finite = np.isfinite(yy)
    assert np.array_equal(xx[finite], [0.5, 1, 1.5, 2 + 2 / 3, 3, 4])
    assert np.array_equal(yy[finite], [0, -2, 0, 0, -1, -2])
    assert np.isnan(yy).sum() == 1


def structure():
    return Structure(
        id="candidate_1",
        name="Manual stereochemical candidate",
        sample_id="sample_1",
        status="confirmed",
        state="stale",
        evidence_ids=["evidence_1"],
        source_versions={"evidence_1": 1},
        atoms=[
            {
                "id": name,
                "label": name,
                "element": "O" if name == "F" else "C",
                "x": x,
                "y": y,
                "stereo": "R (manual)" if name == "E" else "",
            }
            for name, x, y in [
                ("A", 0, 0),
                ("B", 1, 0),
                ("C", 2, 0),
                ("D", 0, 1),
                ("E", 1, 1),
                ("F", 2, 1),
            ]
        ],
        bonds=[
            {"a": a, "b": b, "order": order, "stereo": stereo}
            for a, b, order, stereo in [
                ("A", "B", 1, "none"),
                ("B", "C", 2, "none"),
                ("A", "D", 3, "none"),
                ("D", "E", 1.5, "none"),
                ("E", "F", 1, "wedge"),
                ("C", "F", 1, "hash"),
                ("E", "C", 1, "either"),
            ]
        ],
    )


def test_structure_manual_graph_orders_stereo_context_and_native_atom_selection(make_widget, qapp):
    from nmr_companion.desktop.plots import StructureView

    candidate = structure()
    before = candidate.model_dump()
    widget = make_widget(StructureView)
    widget.set_structure(candidate)
    widget.show()
    qapp.processEvents()
    assert set(widget.atom_items) == {"A", "B", "C", "D", "E", "F"}
    assert "confirmed" in widget.context.text() and "stale" in widget.context.text()
    assert "R (manual)" in widget.atom_items["E"].text()
    grouped = {}
    for item in widget.bond_items:
        grouped.setdefault(tuple(item.data(0)), []).append(item)
    assert {pair: len(items) for pair, items in grouped.items()} == {
        ("A", "B"): 1,
        ("B", "C"): 2,
        ("A", "D"): 3,
        ("D", "E"): 2,
        ("E", "F"): 1,
        ("C", "F"): 8,
        ("E", "C"): 1,
    }
    assert grouped["D", "E"][1].pen().style() == QtCore.Qt.PenStyle.DashLine
    polygon = grouped["E", "F"][0].polygon()
    centers = {key: item.sceneBoundingRect().center() for key, item in widget.atom_items.items()}
    assert polygon[0] == centers["E"]
    assert (polygon[1] + polygon[2]) / 2 == centers["F"]
    hashes = [item.line().length() for item in grouped["C", "F"]]
    assert hashes == sorted(hashes) and hashes[-1] > hashes[0]
    atom_click = QtTest.QSignalSpy(widget.atomSelected)
    QtTest.QTest.mouseClick(
        widget.view.viewport(),
        QtCore.Qt.MouseButton.LeftButton,
        pos=widget.view.mapFromScene(centers["E"]),
    )
    qapp.processEvents()
    assert atom_click.count() == 1 and atom_click.at(0) == ["E"]
    assert candidate.model_dump() == before
    widget.set_structure(None)
    assert not widget.view.scene().items() and not widget.atom_items


def png_page():
    image = QtGui.QImage(400, 200, QtGui.QImage.Format.Format_ARGB32)
    image.fill(QtGui.QColor("white"))
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def test_reference_rectangles_use_page_coordinates_after_zoom_and_clear(make_widget, qapp):
    from nmr_companion.desktop.plots import ReferenceView

    annotation = Annotation(
        id="annotation_1",
        attachment_id="attachment_1",
        page=2,
        x=0.1,
        y=0.2,
        width=0.3,
        height=0.25,
        label="Manual reference",
        state="stale",
        source_versions={"attachment_1": 1},
    )
    before = annotation.model_dump()
    widget = make_widget(ReferenceView)
    widget.set_page(png_page(), [annotation])
    widget.show()
    qapp.processEvents()
    rectangle = widget.annotation_items[0].rect()
    assert rectangle == QtCore.QRectF(40, 40, 120, 50)
    assert widget.annotation_items[0].pen().style() == QtCore.Qt.PenStyle.DashLine
    assert widget.view.transform().m11() == widget.view.transform().m22()
    selected = QtTest.QSignalSpy(widget.rectangleSelected)
    QtTest.QTest.mouseClick(widget.select_button, QtCore.Qt.MouseButton.LeftButton)
    for factor in (1.0, 1.3):
        widget.view.scale(factor, factor)
        widget.view.centerOn(200, 100)
        qapp.processEvents()
        start = widget.view.mapFromScene(QtCore.QPointF(100, 50))
        stop = widget.view.mapFromScene(QtCore.QPointF(220, 110))
        QtTest.QTest.mousePress(widget.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=start)
        QtTest.QTest.mouseMove(widget.view.viewport(), stop)
        QtTest.QTest.mouseRelease(
            widget.view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=stop
        )
        qapp.processEvents()
        assert selected.at(selected.count() - 1) == pytest.approx([0.25, 0.25, 0.3, 0.3], abs=0.005)
    assert selected.count() == 2
    assert "Selected page rectangle:" in widget.note.text() and "save" in widget.note.text()
    assert annotation.model_dump() == before
    with pytest.raises(ValueError, match="PNG"):
        widget.set_page(b"not an image")
    assert widget.page_item is not None
    widget.clear()
    assert widget.page_item is None and not widget.annotation_items
    assert not widget.view.scene().items() and widget.view.page_rect.isEmpty()
    assert not widget.select_button.isChecked() and not widget.select_button.isEnabled()
    assert "No reference page" in widget.note.text()
    widget.set_page(png_page())
    assert widget.select_button.isEnabled() and not widget.select_button.isChecked()


def fit_analysis(*, identified=True):
    return Analysis(
        id="fit_1",
        name="Stored T1 signed fit",
        kind="relaxation",
        state="stale",
        source_versions={"trace_1": 1},
        parameters={},
        result={
            "model": "T1",
            "status": "warning" if identified else "unidentifiable",
            "time_s": [2.0, 0.1, 1.0],
            "signals": [3.5, -5.0, 0.5],
            "predicted": [3.0, -4.0, 1.0] if identified else [],
            "residuals": [0.5, -1.0, -0.5] if identified else [],
            "parameters": {},
            "T_s": 1.0 if identified else None,
            "u_T_s": None,
            "uncertainty_method": "unavailable",
            "warnings": ["Synthetic diagnostic warning"],
            "diagnostics": {},
            "purpose": "quick_check",
        },
    )


def test_fit_uses_stored_signed_pairs_residuals_and_unavailable_state(make_widget, qapp):
    from nmr_companion.desktop.plots import FitView, INK

    analysis = fit_analysis()
    before = analysis.model_dump()
    widget = make_widget(FitView)
    widget.set_analysis(analysis)
    widget.show()
    qapp.processEvents()
    assert np.array_equal(widget.observed.getData()[0], [2.0, 0.1, 1.0])
    assert np.array_equal(widget.observed.getData()[1], [3.5, -5.0, 0.5])
    assert np.array_equal(widget.predicted.getData()[0], [0.1, 1.0, 2.0])
    assert np.array_equal(widget.predicted.getData()[1], [-4.0, 1.0, 3.0])
    assert np.array_equal(widget.residuals.getData()[0], [2.0, 0.1, 1.0])
    assert np.array_equal(widget.residuals.getData()[1], [0.5, -1.0, -0.5])
    assert not widget.signal_plot.getViewBox().state["xInverted"]
    assert "stale" in widget.context.text() and "quick_check" in widget.context.text()
    assert "u(T)=unavailable" in widget.context.text()
    assert "Synthetic diagnostic warning" in widget.warnings.text()
    assert QtGui.QColor(widget.legend.labelTextColor()) == QtGui.QColor(INK)
    assert analysis.model_dump() == before
    widget.set_analysis(fit_analysis(identified=False))
    assert widget.predicted is None and widget.residuals is None
    assert "T=unavailable" in widget.context.text()
    widget.set_analysis(None)
    assert widget.observed is None and widget.predicted is None and widget.residuals is None
    assert not widget.signal_plot.listDataItems() and not widget.residual_plot.listDataItems()


def test_widget_updates_reject_worker_thread_before_changing_scene(make_widget):
    from concurrent.futures import ThreadPoolExecutor
    from nmr_companion.desktop.plots import GridView

    widget = make_widget(GridView)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with pytest.raises(RuntimeError, match="QApplication thread"):
            worker.submit(widget.set_grid, grid()).result(timeout=5)
    assert widget.image_item is None


def test_structure_unusual_supplied_stereo_order_is_not_silently_lost(make_widget):
    from nmr_companion.desktop.plots import StructureView

    values = structure().model_dump()
    values["bonds"] = [{"a": "A", "b": "B", "order": 2, "stereo": "wedge"}]
    candidate = Structure.model_validate(values)
    widget = make_widget(StructureView)
    widget.set_structure(candidate)
    labels = [
        item.text()
        for item in widget.bond_items
        if isinstance(item, QtWidgets.QGraphicsSimpleTextItem)
    ]
    assert labels == ["order 2"]
    assert any(isinstance(item, QtWidgets.QGraphicsPolygonItem) for item in widget.bond_items)
    assert all("supplied order 2" in item.toolTip() for item in widget.bond_items)


def test_plot_titles_axes_legends_and_empty_grid_are_readable(make_widget):
    from nmr_companion.desktop.plots import INK, GridView, FitView, SpectrumView

    grid_view = make_widget(GridView)
    grid_view.set_grid(grid())
    fit_view = make_widget(FitView)
    fit_view.set_analysis(fit_analysis())
    spectrum_view = make_widget(SpectrumView)
    spectrum_view.set_spectra([spectrum([0, 1, 2], [1, -2, 3])])
    for plot in (grid_view.plot, fit_view.signal_plot, fit_view.residual_plot, spectrum_view.plot):
        assert plot.getPlotItem().titleLabel.opts["color"] == INK
        for side in ("bottom", "left"):
            assert plot.getAxis(side).labelStyle["color"] == INK
    grid_view.set_grid(None)
    assert grid_view._original is None and grid_view.image_item is None
    assert grid_view.plot.getPlotItem().titleLabel.text == ""
    assert grid_view.plot.getAxis("bottom").labelText == "x"
    assert "negative red" in grid_view.legend.text()


def test_overlapping_integral_captions_use_bounded_table_not_plot_canvas(make_widget, qapp):
    from nmr_companion.desktop.app import application
    from nmr_companion.desktop.plots import SpectrumView

    # Use the delivered native font/style: the Windows offscreen plugin otherwise
    # has no system font, so its placeholder glyph widths cannot qualify layout.
    assert application() is qapp
    trace = spectrum([9, 8, 7, 6, 5], [0, 2, -3, 1, 0])
    trace.version = 2
    integrals = [
        Integral(
            id=f"integral_{i}",
            spectrum_id=trace.id,
            spectrum_version=1 if i % 2 else 2,
            name=(f"Overlapping reference {i} " + "long-description " * 12)[:200],
            lower=6.1234567890123 + i / 100,
            upper=8.9876543210987,
            area=(-1 if i % 2 else 1) * 0.123456789012345 * (i + 1),
        )
        for i in range(6)
    ]
    before = [trace.model_dump(), [value.model_dump() for value in integrals]]
    widget = make_widget(SpectrumView)
    widget.resize(760, 540)
    widget.set_spectra([trace], integrals)
    widget.show()
    qapp.processEvents()
    captions = [item for item in widget.plot.items() if isinstance(item, pg.TextItem)]
    assert captions == [], "Saved integral captions must not overlap data or legend space"
    bands = [
        item
        for item in widget.plot.items()
        if isinstance(item, pg.LinearRegionItem) and item is not widget.region
    ]
    assert len(bands) == 6 and all(not band.movable for band in bands)
    table = widget.integral_table
    model = table.model()
    assert table.isVisible() and model.rowCount() == 6
    assert model.columnCount() == 7
    assert table.geometry().top() > widget.plot.geometry().bottom()
    assert (
        table.height()
        <= table.horizontalHeader().height()
        + 4 * table.verticalHeader().defaultSectionSize()
        + 2 * table.frameWidth()
    )
    assert table.verticalScrollBar().maximum() > 0
    assert table.horizontalScrollBar().maximum() == 0
    assert widget.width() == 760 and widget.minimumSizeHint().width() <= 760
    assert table.wordWrap() is False
    assert table.editTriggers() == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
    for row, integral in enumerate(integrals):
        raw = [
            model.index(row, column).data(QtCore.Qt.ItemDataRole.UserRole) for column in range(7)
        ]
        assert raw == [
            integral.name,
            trace.name,
            integral.lower,
            integral.upper,
            integral.area,
            "intensity*ppm",
            "stale" if row % 2 else "current",
        ]
        tooltip = model.index(row, 0).data(QtCore.Qt.ItemDataRole.ToolTipRole)
        assert integral.name in tooltip and repr(integral.area) in tooltip
        assert repr(integral.lower) in tooltip and integral.spectrum_id in tooltip
        assert any(tooltip == band.toolTip() for band in bands)
        assert model.index(row, 4).data() == format(integral.area, ".10g")
    assert model.headerData(2, QtCore.Qt.Orientation.Horizontal) == "Lower / ppm"
    assert model.headerData(3, QtCore.Qt.Orientation.Horizontal) == "Upper / ppm"
    assert model.headerData(4, QtCore.Qt.Orientation.Horizontal) == "Signed area"
    assert len(widget.legend.items) == 1
    assert widget.nearest_point(7) == (7.0, -3.0)
    widget.set_region(6.5, 7.5)
    assert widget.selected_region() == (6.5, 7.5)
    assert [trace.model_dump(), [value.model_dump() for value in integrals]] == before
    widget.set_spectra([spectrum([2, 1, 0], [0, 1, 0], sid="other")], integrals)
    assert table.isHidden() and model.rowCount() == 0
    widget.set_spectra([trace], integrals[:1])
    assert model.rowCount() == 1 and not table.isHidden()
    widget.set_spectra([])
    assert table.isHidden() and model.rowCount() == 0
