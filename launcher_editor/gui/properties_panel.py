"""Right-hand dock: full property editor for the currently selected item."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from PyQt5 import QtCore, QtWidgets

from ..model import COMMON_OPTIONAL_FIELDS, MappingFile, validate_item

# Human-friendly labels for the fields we know about.
_FIELD_LABELS = {
    "text": "Text",
    "file": "Linked submenu file",
    "command": "Shell command",
    "panel": "Panel",
    "macros": "Macros",
    "param": "Extra parameters",
    "configuration": "Configuration file",
    "tip": "Tooltip",
    "help-link": "Help link (URL)",
    "style": "Style (QSS)",
    "theme": "Theme",
}


def _label_for(field_name: str) -> str:
    return _FIELD_LABELS.get(field_name, field_name.replace("-", " ").replace("_", " ").capitalize())


class PropertiesPanel(QtWidgets.QWidget):
    """Dynamic form for one item. Field order depends on the item's type."""

    fieldCommitted = QtCore.pyqtSignal(int, str, str)  # row, field, new value ("" clears it)
    openSubmenuRequested = QtCore.pyqtSignal(int)

    def __init__(self, mapping_provider: Callable[[], MappingFile], os_provider: Callable[[], str], parent=None):
        super().__init__(parent)
        self._mapping_provider = mapping_provider
        self._os_provider = os_provider
        self._row: Optional[int] = None
        self._item: Optional[Dict[str, Any]] = None
        self._editors: Dict[str, QtWidgets.QWidget] = {}

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        self.heading = QtWidgets.QLabel("No item selected")
        self.heading.setStyleSheet("font-weight: 600; font-size: 13px; padding-bottom: 4px;")
        outer.addWidget(self.heading)

        self.problem_label = QtWidgets.QLabel("")
        self.problem_label.setWordWrap(True)
        self.problem_label.setStyleSheet("color: #b3261e; font-size: 11px;")
        self.problem_label.setVisible(False)
        outer.addWidget(self.problem_label)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer.addWidget(scroll, 1)

        self.form_host = QtWidgets.QWidget()
        self.form = QtWidgets.QFormLayout(self.form_host)
        self.form.setRowWrapPolicy(QtWidgets.QFormLayout.WrapLongRows)
        self.form.setLabelAlignment(QtCore.Qt.AlignLeft)
        scroll.setWidget(self.form_host)

        self.setEnabled(False)

    # -- public API ---------------------------------------------------------
    def clear(self) -> None:
        self._row = None
        self._item = None
        self.heading.setText("No item selected")
        self.problem_label.setVisible(False)
        self._rebuild_form({})
        self.setEnabled(False)

    def set_item(self, row: int, item: Dict[str, Any]) -> None:
        self._row = row
        self._item = item
        self.setEnabled(True)
        type_name = item.get("type", "")
        self.heading.setText(f"{item.get('text') or '(untitled)'}  —  {type_name}")

        problems = validate_item(item)
        if problems:
            self.problem_label.setText("⚠ " + "; ".join(problems))
            self.problem_label.setVisible(True)
        else:
            self.problem_label.setVisible(False)

        self._rebuild_form(item)

    def refresh_heading(self) -> None:
        if self._item is not None:
            type_name = self._item.get("type", "")
            self.heading.setText(f"{self._item.get('text') or '(untitled)'}  —  {type_name}")

    # -- form construction ----------------------------------------------
    def _rebuild_form(self, item: Dict[str, Any]) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)
        self._editors.clear()

        type_name = item.get("type", "")
        if not type_name:
            return

        fields = self._fields_for(type_name, item)
        for field_name in fields:
            self._add_field_row(field_name, item.get(field_name, ""))

    def _fields_for(self, type_name: str, item: Dict[str, Any]) -> list:
        fields = []
        if type_name == "separator":
            return fields
        fields.append("text")
        if type_name == "menu":
            fields.append("file")
        else:
            mapping = self._mapping_provider()
            os_name = self._os_provider()
            mapped_fields = mapping.fields_for_type(os_name, type_name) if mapping else []
            if not mapped_fields and type_name == "cmd":
                mapped_fields = ["command"]
            # include any field already present on the item even if the
            # active mapping doesn't define it (e.g. mapping switched, or a
            # hand-authored file used an argument not in the loaded mapping)
            for key in item.keys():
                if key not in ("type",) + tuple(fields) + tuple(COMMON_OPTIONAL_FIELDS):
                    if key not in mapped_fields:
                        mapped_fields.append(key)
            fields.extend(mapped_fields)
        for opt in ("tip", "help-link"):
            fields.append(opt)
        return fields

    def _add_field_row(self, field_name: str, value: str) -> None:
        row_widget: QtWidgets.QWidget
        if field_name in ("command", "style"):
            editor = QtWidgets.QPlainTextEdit()
            editor.setPlainText(value or "")
            editor.setFixedHeight(56)
            editor.setTabChangesFocus(True)
            editor.textChanged.connect(lambda fn=field_name, ed=editor: self._commit_plain(fn, ed))
            row_widget = editor
        else:
            editor = QtWidgets.QLineEdit(value or "")
            editor.editingFinished.connect(
                lambda fn=field_name, ed=editor: self._commit(fn, ed.text())
            )
            row_widget = editor

        self._editors[field_name] = editor

        if field_name == "file":
            container = QtWidgets.QWidget()
            hbox = QtWidgets.QHBoxLayout(container)
            hbox.setContentsMargins(0, 0, 0, 0)
            hbox.addWidget(row_widget, 1)
            open_btn = QtWidgets.QPushButton("Open →")
            open_btn.setToolTip("Open (or create) the linked submenu file in a new tab")
            open_btn.clicked.connect(lambda: self.openSubmenuRequested.emit(self._row))
            hbox.addWidget(open_btn)
            self.form.addRow(_label_for(field_name), container)
        else:
            self.form.addRow(_label_for(field_name), row_widget)

    def _commit(self, field_name: str, value: str) -> None:
        if self._row is None:
            return
        self.fieldCommitted.emit(self._row, field_name, value)
        if field_name == "text" and self._item is not None:
            self._item["text"] = value
            self.refresh_heading()

    def _commit_plain(self, field_name: str, editor: QtWidgets.QPlainTextEdit) -> None:
        self._commit(field_name, editor.toPlainText())
