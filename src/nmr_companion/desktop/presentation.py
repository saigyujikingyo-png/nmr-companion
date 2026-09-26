"""Compact native presentation without changing scientific values."""

from __future__ import annotations
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


def display(value):
    if value is None:
        return "Unavailable"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, float):
        return format(value, ".10g")
    if isinstance(value, (list, tuple)):
        return "; ".join(display(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {display(v)}" for k, v in value.items())
    return str(value)


class ScientificTable(QAbstractTableModel):
    """Virtual table: full scientific rows, no per-cell widget allocation."""

    def __init__(self, headers=(), rows=(), parent=None):
        super().__init__(parent)
        self.headers = list(headers)
        self.rows = list(rows)

    def replace(self, headers, rows):
        self.beginResetModel()
        self.headers = list(headers)
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.headers)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        value = self.rows[index.row()][index.column()]
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            return display(value)
        if role == Qt.ItemDataRole.TextAlignmentRole and isinstance(value, (int, float)):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        if role == Qt.ItemDataRole.ForegroundRole and value == "stale":
            return QColor("#956500")
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        return self.headers[section] if orientation == Qt.Orientation.Horizontal else section + 1


STYLE = """
QMainWindow, QDialog { background: #eef0f3; color: #202832; }
QLabel { color: #202832; }
QFrame#ContextGuide { background: #edf3fa; border-left: 3px solid #326a9f; }
QLabel#ContextText { color: #25415f; padding: 3px 4px; }
QLabel#OperationStatus { color: #245d44; padding: 2px 7px; font-weight: 600; }
QLabel#OperationStatus[state="busy"] { color: #1d4c7c; }
QLabel#OperationStatus[state="attention"] { color: #87400d; }
QMenuBar, QMenu, QToolBar { background: #f4f5f7; color: #202832; }
QToolBar { border: 0; border-bottom: 1px solid #bec5cf; spacing: 3px; padding: 3px; }
QToolButton { padding: 4px 7px; border: 1px solid transparent; border-radius: 0; }
QToolButton:hover { background: #e1e7ef; border-color: #9cadc2; }
QToolButton:checked { background: #d5e1f0; border-color: #829ab8; }
QDockWidget::title { background: #dce1e7; padding: 5px; font-weight: 600; }
QTreeView, QTableView, QListView, QPlainTextEdit { background: white; alternate-background-color: #f5f7fa; border: 1px solid #c5ccd5; selection-background-color: #d4e2f3; selection-color: #172f4e; }
QHeaderView::section { background: #e9edf2; border: 0; border-right: 1px solid #c5ccd5; border-bottom: 1px solid #c5ccd5; padding: 5px; }
QTabWidget::pane { border: 1px solid #bcc6d3; background: white; }
QTabBar::tab { background: #e2e6ec; border: 1px solid #bcc6d3; padding: 5px 11px; }
QTabBar::tab:selected { background: white; border-bottom-color: white; color: #153d68; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: white; color: #202832; border: 1px solid #8797aa; padding: 4px; min-height: 22px; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus { border: 2px solid #326a9f; }
QPushButton { background: #e9edf3; border: 1px solid #aab6c5; padding: 5px 10px; border-radius: 0; }
QPushButton:hover { background: #dce5f0; }
QPushButton:pressed { background: #bed0e5; }
QPushButton:focus { border: 2px solid #326a9f; }
QPushButton:default { background: #245b8c; color: white; border-color: #1c456b; }
QPushButton:default:hover { background: #1b4a76; }
QMenu::item:selected { background: #d4e2f3; color: #172f4e; }
QPushButton:disabled { color: #8993a1; }
QGroupBox { border: 1px solid #bfc8d4; margin-top: 10px; padding: 8px 5px; }
QGroupBox::title { subcontrol-origin: margin; padding: 0 4px; }
QStatusBar { background: #e5e9ef; border-top: 1px solid #c0c8d2; }
"""
