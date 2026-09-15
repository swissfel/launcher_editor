"""One tab: the editor for a single menu JSON file."""

from __future__ import annotations

from typing import Callable, Optional

from PyQt5 import QtCore, QtWidgets

from ..backends import BackendError
from ..model import BUILTIN_STRUCTURAL_TYPES, MenuDocument, default_item_for_type
from ..workspace import Workspace
from . import clipboard, icons
from .dialogs import DeleteSubmenuDialog, MenuSettingsDialog, NewSubmenuDialog, confirm
from .item_list import ItemListWidget
from .properties_panel import PropertiesPanel

_TYPE_DISPLAY_NAMES = {
    "separator": "Separator",
    "title": "Title / section header",
    "menu": "Link to existing submenu file",
    "cmd": "Custom shell command",
    "caqtdm": "caQtDM screen",
    "caqtdm-no-attach": "caQtDM screen (no attach)",
    "medm": "MEDM screen",
    "pep": "PEP panel",
}


def _display_name(type_name: str) -> str:
    return _TYPE_DISPLAY_NAMES.get(type_name, type_name)


class MenuEditorWidget(QtWidgets.QWidget):
    titleChanged = QtCore.pyqtSignal()
    statusMessage = QtCore.pyqtSignal(str, int)
    requestOpenPath = QtCore.pyqtSignal(str)

    def __init__(
        self,
        workspace: Workspace,
        doc: MenuDocument,
        mapping_provider: Callable,
        os_provider: Callable[[], str],
        parent=None,
    ):
        super().__init__(parent)
        self.workspace = workspace
        self.doc = doc
        self._mapping_provider = mapping_provider
        self._os_provider = os_provider

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.toolbar = QtWidgets.QToolBar()
        self.toolbar.setIconSize(QtCore.QSize(18, 18))
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        outer.addWidget(self.toolbar)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        outer.addWidget(splitter, 1)

        self.list = ItemListWidget()
        splitter.addWidget(self.list)

        self.properties = PropertiesPanel(self._mapping_provider, self._os_provider)
        splitter.addWidget(self.properties)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 320])

        self._build_toolbar()

        self.list.currentRowChanged2.connect(self._on_selection_changed)
        self.list.itemRenamed.connect(self._on_item_renamed)
        self.list.itemsReordered.connect(self._on_items_reordered)
        self.properties.fieldCommitted.connect(self._on_field_committed)
        self.properties.openSubmenuRequested.connect(self._on_open_submenu_requested)

        self.refresh()

    # -- toolbar ------------------------------------------------------------
    def _build_toolbar(self) -> None:
        self.add_button = QtWidgets.QToolButton()
        self.add_button.setText("Add ▾")
        self.add_button.setIcon(icons.action_icon("add"))
        self.add_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.add_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.add_menu = QtWidgets.QMenu(self.add_button)
        self.add_button.setMenu(self.add_menu)
        self.toolbar.addWidget(self.add_button)
        self.refresh_add_menu()

        submenu_action = self.toolbar.addAction(icons.action_icon("submenu"), "New Submenu…")
        submenu_action.triggered.connect(self.add_submenu)

        self.toolbar.addSeparator()
        self.toolbar.addAction(icons.action_icon("cut"), "Cut", self.cut_selected)
        self.toolbar.addAction(icons.action_icon("copy"), "Copy", self.copy_selected)
        self.toolbar.addAction(icons.action_icon("paste"), "Paste", self.paste)
        self.toolbar.addAction(icons.action_icon("duplicate"), "Duplicate", self.duplicate_selected)
        self.toolbar.addAction(icons.action_icon("delete"), "Delete", self.delete_selected)
        self.toolbar.addSeparator()
        self.toolbar.addAction(icons.action_icon("up"), "Move Up", self.move_up)
        self.toolbar.addAction(icons.action_icon("down"), "Move Down", self.move_down)
        self.toolbar.addSeparator()
        self.toolbar.addAction("Menu Settings…", self.edit_menu_settings)

    def refresh_add_menu(self) -> None:
        self.add_menu.clear()
        for type_name in BUILTIN_STRUCTURAL_TYPES:
            if type_name == "menu":
                continue  # covered by the dedicated "New Submenu" action
            action = self.add_menu.addAction(icons.type_icon(type_name), _display_name(type_name))
            action.triggered.connect(lambda checked=False, t=type_name: self.add_item_template(t))
        self.add_menu.addSeparator()
        mapping = self._mapping_provider()
        os_name = self._os_provider()
        for type_name in mapping.types_for_os(os_name):
            action = self.add_menu.addAction(icons.type_icon(type_name), _display_name(type_name))
            action.triggered.connect(lambda checked=False, t=type_name: self.add_item_template(t))

    # -- helpers --------------------------------------------------------
    def refresh(self, select_row: Optional[int] = None) -> None:
        row = select_row if select_row is not None else self.list.currentRow()
        self.list.refresh(self.doc.items, keep_row=row if row is not None and row >= 0 else None)
        if row is None or row < 0 or row >= len(self.doc.items):
            self.properties.clear()

    def _current_row(self) -> int:
        return self.list.currentRow()

    def _insertion_index(self) -> Optional[int]:
        row = self._current_row()
        return row + 1 if row >= 0 else None

    def mark_saved(self) -> None:
        self.titleChanged.emit()

    @property
    def is_dirty(self) -> bool:
        return self.doc.dirty

    # -- selection / editing --------------------------------------------
    def _on_selection_changed(self, row: int) -> None:
        if 0 <= row < len(self.doc.items):
            self.properties.set_item(row, self.doc.items[row])
        else:
            self.properties.clear()

    def _on_item_renamed(self, row: int, new_text: str) -> None:
        if 0 <= row < len(self.doc.items):
            self.doc.set_item_text(row, new_text)
            self.list.refresh(self.doc.items, keep_row=row)
            if self._current_row() == row:
                self.properties.set_item(row, self.doc.items[row])
            self.titleChanged.emit()

    def _on_field_committed(self, row: int, field: str, value: str) -> None:
        if not (0 <= row < len(self.doc.items)):
            return
        self.doc.update_item(row, **{field: value})
        if field == "text":
            self.list.refresh(self.doc.items, keep_row=row)
        self.titleChanged.emit()

    def _on_items_reordered(self, new_order) -> None:
        self.doc.data["menu"] = new_order
        self.doc.mark_dirty()
        self.titleChanged.emit()

    # -- toolbar actions --------------------------------------------------
    def add_item_template(self, type_name: str) -> None:
        mapping = self._mapping_provider()
        item = default_item_for_type(type_name, mapping, self._os_provider())
        idx = self.doc.add_item(item, index=self._insertion_index())
        self.refresh(select_row=idx)
        self.titleChanged.emit()
        if type_name != "separator":
            QtCore.QTimer.singleShot(0, self.list.start_rename_current)
        self.statusMessage.emit(f"Added {_display_name(type_name)}", 3000)

    def add_submenu(self) -> None:
        existing = [n for n in self.workspace.backend.listdir(self.workspace.backend.dirname(self.doc.path))] \
            if self.workspace.backend.exists(self.workspace.backend.dirname(self.doc.path)) else []
        dlg = NewSubmenuDialog(self, existing_names=existing)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        title, file_name = dlg.values()
        try:
            new_doc, file_name = self.workspace.new_submenu(self.doc, title, file_name)
        except (FileExistsError, BackendError) as exc:
            QtWidgets.QMessageBox.warning(self, "New Submenu", str(exc))
            return

        item = {"type": "menu", "text": title, "file": file_name}
        idx = self.doc.add_item(item, index=self._insertion_index())
        self.refresh(select_row=idx)
        self.titleChanged.emit()
        self.statusMessage.emit(f'Created submenu "{file_name}"', 4000)

        if confirm(self, "New Submenu", f'Open "{title}" now to start adding entries?'):
            self.requestOpenPath.emit(new_doc.path)

    def duplicate_selected(self) -> None:
        rows = self.list.selected_rows()
        if not rows:
            return
        offset = 0
        last_new = None
        for row in rows:
            last_new = self.doc.duplicate_item(row + offset)
            offset += 1
        self.refresh(select_row=last_new)
        self.titleChanged.emit()

    def delete_selected(self) -> None:
        rows = self.list.selected_rows()
        if not rows:
            return
        for row in sorted(rows, reverse=True):
            item = self.doc.items[row]
            if item.get("type") == "menu" and item.get("file"):
                if not self._confirm_and_delete_submenu(row, item):
                    continue
            else:
                self.doc.remove_item(row)
        self.refresh(select_row=min(rows[0], len(self.doc.items) - 1))
        self.titleChanged.emit()

    def _confirm_and_delete_submenu(self, row: int, item: dict) -> bool:
        target_path = self.doc.resolve_submenu_path(item)
        base_dir = self.workspace.backend.dirname(self.doc.path)
        others = self.workspace.scan_directory_for_references(base_dir, target_path)
        others = [p for p in others if p != self.doc.path]
        dlg = DeleteSubmenuDialog(self, item.get("text", ""), target_path, others)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return False
        self.doc.remove_item(row)
        if dlg.delete_file():
            try:
                self.workspace.delete_submenu_file(target_path)
                self.statusMessage.emit(f"Deleted file {target_path}", 4000)
            except BackendError as exc:
                QtWidgets.QMessageBox.warning(self, "Delete Submenu", str(exc))
        return True

    def cut_selected(self) -> None:
        rows = self.list.selected_rows()
        if not rows:
            return
        items = [self.doc.items[r] for r in rows]
        clipboard.copy_items(items)
        for row in sorted(rows, reverse=True):
            self.doc.remove_item(row)
        self.refresh(select_row=min(rows[0], len(self.doc.items) - 1) if self.doc.items else None)
        self.titleChanged.emit()
        self.statusMessage.emit(f"Cut {len(rows)} item(s)", 3000)

    def copy_selected(self) -> None:
        rows = self.list.selected_rows()
        if not rows:
            return
        items = [self.doc.items[r] for r in rows]
        clipboard.copy_items(items)
        self.statusMessage.emit(f"Copied {len(rows)} item(s)", 3000)

    def paste(self) -> None:
        items = clipboard.paste_items()
        if not items:
            self.statusMessage.emit("Clipboard has no launcher item(s) to paste", 3000)
            return
        index = self._insertion_index()
        first = None
        for offset, item in enumerate(items):
            idx = self.doc.add_item(item, index=(index + offset) if index is not None else None)
            if first is None:
                first = idx
        self.refresh(select_row=first)
        self.titleChanged.emit()
        self.statusMessage.emit(f"Pasted {len(items)} item(s)", 3000)

    def move_up(self) -> None:
        row = self._current_row()
        if row > 0:
            self.doc.move_item(row, row - 1)
            self.refresh(select_row=row - 1)
            self.titleChanged.emit()

    def move_down(self) -> None:
        row = self._current_row()
        if 0 <= row < len(self.doc.items) - 1:
            self.doc.move_item(row, row + 1)
            self.refresh(select_row=row + 1)
            self.titleChanged.emit()

    def edit_menu_settings(self) -> None:
        dlg = MenuSettingsDialog(self, self.doc)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            dlg.apply()
            self.titleChanged.emit()

    def _on_open_submenu_requested(self, row: int) -> None:
        if not (0 <= row < len(self.doc.items)):
            return
        item = self.doc.items[row]
        file_name = (item.get("file") or "").strip()
        if not file_name:
            QtWidgets.QMessageBox.information(
                self, "Open Submenu", "Set a file name for this submenu first."
            )
            return
        target_path = self.doc.resolve_submenu_path(item)
        if not self.workspace.backend.exists(target_path):
            if confirm(self, "Open Submenu", f'"{file_name}" does not exist yet. Create it?'):
                new_doc = MenuDocument.create_new(self.workspace.backend, target_path, item.get("text", "New submenu"))
                new_doc.save(make_backup=False)
                self.workspace.register(new_doc)
            else:
                return
        self.requestOpenPath.emit(target_path)
