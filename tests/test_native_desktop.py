"""Native-controller tests use only an isolated offscreen QApplication."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hashlib
import sys
from threading import Event
import time
import zipfile

import pytest
from PySide6.QtCore import Qt, QCoreApplication, QEvent
from PySide6.QtWidgets import QFileDialog, QMessageBox
from nmr_companion.desktop.app import application
from nmr_companion.desktop.main_window import MainWindow
from nmr_companion.service import Service


@pytest.fixture(scope="module")
def app():
    return application()


@pytest.fixture
def service(tmp_path):
    service = Service(tmp_path / "native.nmrproj")
    service.create("Synthetic native controller")
    service.apply(0, "demo", {"op": "demo"})
    return service


@pytest.fixture
def window(app, service):
    result = MainWindow(service, auto_refresh=False)
    result.show()
    app.processEvents()
    yield result
    result.close()
    result.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def wait(app, predicate, seconds=12):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert predicate(), "Native worker did not reach the expected state"


def select(window, identifier):
    for i in range(window.tree.topLevelItemCount()):
        group = window.tree.topLevelItem(i)
        for j in range(group.childCount()):
            item = group.child(j)
            if item.data(0, Qt.ItemDataRole.UserRole)[1] == identifier:
                window.tree.setCurrentItem(item)
                return item
    raise AssertionError(identifier)


def edit(service, request, command):
    return service.apply(service.read().revision, request, command).object_ids[0]


def test_desktop_cli_routes_to_native_without_web(tmp_path, monkeypatch):
    from nmr_companion import cli
    import nmr_companion.desktop.app as native
    import nmr_companion.web as web

    seen = []
    monkeypatch.setattr(native, "run", lambda service: seen.append(service.read()) or 0)
    monkeypatch.setattr(web, "run", lambda *args: pytest.fail("desktop launched an HTTP frontend"))
    monkeypatch.setattr(
        sys, "argv", ["nmr-companion", "--project", str(tmp_path / "new.nmrproj"), "desktop"]
    )
    cli.main()
    assert len(seen) == 1 and seen[0].revision == 0


def test_original_signed_trace_and_project_groups(window):
    negative = next(s for s in window.project.spectra.values() if min(s.real) < -0.1)
    select(window, negative.id)
    assert window.tree.topLevelItemCount() == 12
    assert window.workspace.count() == 5
    assert window.result_model.rowCount() == len(negative.real)
    assert [row[1] for row in window.result_model.rows] == negative.real
    assert min(row[1] for row in window.result_model.rows) < 0


def test_external_edit_refreshes_stale_dependents_without_losing_selection(window, service, app):
    sid = next(iter(service.read().spectra))
    peak = edit(service, "peak", {"op": "peak_label", "spectrum_id": sid, "ppm": 2, "label": "H-a"})
    sample = edit(
        service,
        "sample",
        {"op": "sample", "name": "Synthetic A", "role": "synthetic", "object_ids": [sid]},
    )
    candidate = edit(
        service,
        "candidate",
        {
            "op": "structure",
            "sample_id": sample,
            "name": "Candidate A",
            "atoms": [{"id": "C1", "label": "C1", "element": "C", "x": 0.3, "y": 0.5}],
            "evidence_ids": [peak],
        },
    )
    assignment = edit(
        service,
        "assignment",
        {
            "op": "assign",
            "sample_id": sample,
            "candidate_id": candidate,
            "atom_ids": ["C1"],
            "sample": "Synthetic A",
            "atom": "C1",
            "candidate": "Candidate A",
            "observation": "Synthetic correlation",
            "evidence_ids": [peak],
        },
    )
    window.refresh()
    wait(app, lambda: not window.busy and window.project.revision == 5)
    select(window, candidate)
    edit(
        service,
        "external_peak_edit",
        {"op": "peak_label", "peaklabel_id": peak, "spectrum_id": sid, "ppm": 2.01, "label": "H-a"},
    )
    window.poll_revision()
    wait(app, lambda: not window.busy and window.project.revision == 6)
    assert window.selected_id == candidate
    assert window.project.structures[candidate].state == "stale"
    assert window.project.assignments[assignment].state == "stale"
    assert window.tree.currentItem().text(1) == "stale"
    assert "external frontend" in window.log.toPlainText()


def test_revision_conflict_never_retries_or_commits(window, service, app, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    sid = next(iter(service.read().spectra))
    edit(service, "external", {"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3})
    assert window.submit_command(
        {"op": "peak_label", "spectrum_id": sid, "ppm": 2, "label": "must not commit"}
    )
    request = window.last_request
    wait(app, lambda: not window.busy)
    assert service.read().revision == 2 and not service.read().peaklabels
    with service.store.connection() as db:
        assert db.execute("SELECT count(*) FROM requests WHERE id=?", (request,)).fetchone()[0] == 0
    assert any("REVISION_CONFLICT" in warning and request in warning for warning in warnings)


def test_busy_close_waits_for_one_commit(window, service, app, monkeypatch):
    started, release = Event(), Event()
    original = service.apply

    def blocked(*args, **kwargs):
        started.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(service, "apply", blocked)
    sid = next(iter(window.project.spectra))
    assert window.submit_command(
        {"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3}
    )
    try:
        wait(app, started.is_set)
        request = window.last_request
        window.close()
        assert window.isVisible() and window.busy
        assert not window.open_action.isEnabled()
    finally:
        release.set()
    wait(app, lambda: not window.busy and not window.isVisible())
    assert service.read().revision == 2
    assert service.store.request(request).revision == 2
    with service.store.connection() as db:
        assert db.execute("SELECT count(*) FROM requests WHERE id=?", (request,)).fetchone()[0] == 1
    assert not window.timer.isActive()


def test_export_captures_revision_before_native_file_dialog(
    window, service, app, monkeypatch, tmp_path
):
    destination = tmp_path / "delivered-r1.zip"
    messages = []

    def choose(*args, **kwargs):
        sid = next(iter(service.read().spectra))
        edit(
            service,
            "external_during_dialog",
            {"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3},
        )
        return str(destination), "Project bundle (*.zip)"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", choose)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    window.export_revision()
    wait(app, lambda: not window.busy)
    assert service.read().revision == 2
    with zipfile.ZipFile(destination) as archive:
        project_name = next(n for n in archive.namelist() if n.endswith(".nmrproj"))
        reopen = tmp_path / "reopened.nmrproj"
        reopen.write_bytes(archive.read(project_name))
    assert Service(reopen).read().revision == 1
    assert any(hashlib.sha256(destination.read_bytes()).hexdigest() in m for m in messages)


def test_export_collision_preserves_file_and_does_not_create_artifact(
    window, service, app, monkeypatch, tmp_path
):
    destination = tmp_path / "existing.zip"
    destination.write_bytes(b"user-owned original")
    warnings = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(destination), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    window.export_revision()
    wait(app, lambda: not window.busy)
    assert destination.read_bytes() == b"user-owned original"
    assert any("FILE_EXISTS" in warning for warning in warnings)
    with service.store.connection() as db:
        assert db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 0


def test_presentation_failure_reports_saved_request_without_replaying(
    window, service, app, monkeypatch
):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    def broken(*args, **kwargs):
        raise ValueError("simulated display failure")

    monkeypatch.setattr(window, "render_project", broken)
    sid = next(iter(service.read().spectra))
    window.submit_command({"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3})
    request = window.last_request
    wait(app, lambda: not window.busy)
    assert service.read().revision == service.store.request(request).revision == 2
    assert len(service.read().integrals) == 1
    assert any("PRESENTATION_FAILED" in m and request in m for m in warnings)


def test_multiselection_cursor_and_command_follow_active_nucleus(window, monkeypatch):
    import nmr_companion.desktop.dialogs as dialogs

    proton = next(iter(window.project.spectra.values()))
    carbon = proton.model_copy(
        deep=True, update={"id": "carbon_fixture", "name": "Synthetic carbon", "nucleus": "13C"}
    )
    window.project.spectra[carbon.id] = carbon
    window.render_project(proton.id)
    proton_item = window.tree.currentItem()
    carbon_item = select(window, carbon.id)
    proton_item.setSelected(True)
    carbon_item.setSelected(True)
    window._overlay_selected()
    assert window.spectrum_view._series[0][0] == carbon.id
    assert all(series[0] != proton.id for series in window.spectrum_view._series)
    window._position_changed(2.0)
    captured = []
    monkeypatch.setattr(
        dialogs, "get_command", lambda *a, **k: captured.append(k["initial"]) or None
    )
    window.command_dialog("peak_label")
    assert captured[0]["spectrum_id"] == carbon.id and captured[0]["ppm"] == 2.0


def test_remove_confirmation_captures_target_and_revision(window, service, monkeypatch):
    sid = next(iter(service.read().spectra))
    original = edit(
        service,
        "remove_one",
        {
            "op": "integrate",
            "spectrum_id": sid,
            "name": "Original target",
            "lower": 1.7,
            "upper": 2.3,
        },
    )
    other = edit(
        service,
        "remove_two",
        {
            "op": "integrate",
            "spectrum_id": sid,
            "name": "Another region",
            "lower": 6.7,
            "upper": 7.3,
        },
    )
    window.project = service.read()
    window.render_project(original)
    captured = []

    def confirm(*args):
        assert "Original target" in args[2] and "revision 3" in args[2]
        service.apply(3, "outside_remove", {"op": "remove", "object_id": original})
        window.project = service.read()
        window.render_project(other)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    monkeypatch.setattr(
        window,
        "submit_command",
        lambda command, revision=None: captured.append((command, revision)) or True,
    )
    window.remove_selected()
    assert captured == [({"op": "remove", "object_id": original}, 3)]
    assert other in service.read().integrals


def test_reference_page_change_discards_previous_rectangle(window, monkeypatch):
    window._rectangle = (0.1, 0.2, 0.3, 0.4)
    monkeypatch.setattr(window, "_load_reference", lambda *args: None)
    window._reference_page_changed(2)
    assert window._rectangle is None


def test_unidentifiable_fit_table_keeps_observations(window):
    from nmr_companion.models import Analysis

    analysis = Analysis(
        id="unidentified_fit",
        kind="relaxation",
        name="Unidentified synthetic fit",
        source_versions={},
        parameters={},
        result={
            "time_s": [0.1, 0.2, 0.3, 0.4],
            "signals": [-1.0, -0.5, 0.5, 1.0],
            "predicted": [],
            "residuals": [],
            "model": "T1",
            "status": "unidentifiable",
            "parameters": {},
            "T_s": None,
            "u_T_s": None,
            "uncertainty_method": "unavailable_unidentifiable",
            "warnings": ["Synthetic unavailable prediction fixture"],
            "diagnostics": {},
        },
    )
    window._show_results(analysis, "analyses")
    assert window.result_model.rows == [
        [0.1, -1.0, None, None],
        [0.2, -0.5, None, None],
        [0.3, 0.5, None, None],
        [0.4, 1.0, None, None],
    ]


def test_modal_command_defers_poll_and_is_not_silently_dropped(window, service, app, monkeypatch):
    import nmr_companion.desktop.dialogs as dialogs

    sid = next(iter(service.read().spectra))

    def form(*args, **kwargs):
        assert window._modal_depth == 1
        window.poll_revision()
        app.processEvents()
        assert window._poll_worker is None and not window.busy
        return {"op": "integrate", "spectrum_id": sid, "lower": 1.7, "upper": 2.3}

    monkeypatch.setattr(dialogs, "get_command", form)
    window.command_dialog("integrate")
    wait(app, lambda: not window.busy)
    assert window._modal_depth == 0
    assert service.read().revision == 2 and len(service.read().integrals) == 1
    assert service.store.request(window.last_request).revision == 2


@pytest.mark.parametrize("saved_geometry", [False, True])
def test_native_entrypoint_opens_and_closes_its_own_event_loop(
    service, app, monkeypatch, tmp_path, saved_geometry
):
    import PySide6.QtCore as qt_core
    from PySide6.QtCore import QTimer, QSettings

    class IsolatedSettings(QSettings):
        def __init__(self, *args):
            super().__init__(str(tmp_path / "native.ini"), QSettings.Format.IniFormat)
            if saved_geometry:
                self.setValue("native/geometry", b"existing")

    monkeypatch.setattr(qt_core, "QSettings", IsolatedSettings)
    import nmr_companion.desktop.app as native_app
    import nmr_companion.desktop.main_window as controller

    observed = []

    class BoundedWindow(MainWindow):
        def __init__(self, *args, **kwargs):
            kwargs["settings"] = None
            kwargs["auto_refresh"] = False
            super().__init__(*args, **kwargs)
            observed.append(self)
            QTimer.singleShot(100, self.close)

    monkeypatch.setattr(controller, "MainWindow", BoundedWindow)
    started = time.monotonic()
    assert native_app.run(service) == 0
    assert time.monotonic() - started >= 0.08
    assert len(observed) == 1 and observed[0]._closed
    assert observed[0].isMaximized() is not saved_geometry
    observed[0].deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert service.read().revision == 1
