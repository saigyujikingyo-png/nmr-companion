"""Native Qt entrypoints; no browser or local HTTP service is started."""

from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time


def application():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont, QFontDatabase
    from .presentation import STYLE

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("NMR Companion")
    app.setOrganizationName("Chembridge")
    # The Windows offscreen plugin does not enumerate installed system fonts.
    # Load the existing OS font in this process only; never copy it into a bundle.
    if os.name == "nt" and not QFontDatabase.families():
        font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        for name in ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf"):
            font = font_root / name
            if font.is_file():
                QFontDatabase.addApplicationFont(str(font))
    family = "Segoe UI" if "Segoe UI" in QFontDatabase.families() else app.font().family()
    app.setFont(QFont(family, 10))
    app.setStyleSheet(STYLE)
    return app


def run(service):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QProgressDialog
    from .main_window import MainWindow

    app = application()
    opening = QProgressDialog("Opening project and scientific views…", "", 0, 0)
    opening.setWindowTitle("NMR Companion")
    opening.setCancelButton(None)
    opening.setMinimumDuration(0)
    opening.show()
    app.processEvents()
    settings = QSettings(
        QSettings.Format.IniFormat, QSettings.Scope.UserScope, "Chembridge", "NMR Companion"
    )
    first_launch = not settings.contains("native/geometry")
    try:
        window = MainWindow(service, settings=settings)
    finally:
        opening.close()
        opening.deleteLater()
    if first_launch:
        window.showMaximized()
    else:
        window.show()
    return app.exec()


def check(output=None):
    """Isolated render/synchronization probe, not a physical UI-acceptance claim."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QBuffer, QIODevice
    from .main_window import MainWindow
    from ..service import Service

    started = time.perf_counter()
    app = application()
    with tempfile.TemporaryDirectory(prefix="nmr-native-check-") as root:
        service = Service(Path(root) / "native.nmrproj")
        service.create("Synthetic native workbench validation")
        service.apply(0, "native_check_demo", {"op": "demo"})
        window = MainWindow(service, auto_refresh=False)
        window.resize(1440, 920)
        window.show()
        app.processEvents()
        assert window.project.revision == 1
        assert window.tree.topLevelItemCount() >= 8
        assert window.workspace.count() >= 5
        from PySide6.QtGui import QFontMetrics

        metrics = QFontMetrics(app.font())
        assert all(metrics.inFont(c) for c in "Spectrum 0123456789"), (
            "Native interface font is unavailable"
        )
        pixmap = window.grab()
        assert not pixmap.isNull() and pixmap.width() >= 1000
        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        assert pixmap.save(buffer, "PNG")
        data = bytes(buffer.data())
        if output:
            path = Path(output)
            with path.open("xb") as handle:
                handle.write(data)
        window.close()
        app.processEvents()
        result = {
            "ok": True,
            "frontend": "native Qt Widgets",
            "browser": False,
            "http_listener": False,
            "scope": "isolated synthetic Qt widget/render probe",
            "revision": 1,
            "spectra": 9,
            "width": pixmap.width(),
            "height": pixmap.height(),
            "png_bytes": len(data),
            "png_sha256": hashlib.sha256(data).hexdigest(),
            "seconds": round(time.perf_counter() - started, 4),
        }
        return json.dumps(result)
