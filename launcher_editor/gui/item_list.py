"""The draggable, inline-renameable list of items inside one menu file."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from ..model import item_label, validate_item
from . import icons

ROLE_ITEM = QtCore.Qt.UserRole + 1


class ItemListWidget(QtWidgets.QListWidget):
    """Shows one menu's items; supports drag-to-reorder and inline rename."""

    itemsReordered = QtCore.pyqtSignal(list)  # emits new order: List[Dict]
    itemRenamed = QtCore.pyqtSignal(int, str)  # row, new text
    currentRowChanged2 = QtCore.pyqtSignal(int)  # -1 if none

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self.setAlternatingRowColors(True)
        self.setUniformItemSizes(True)
        self.setIconSize(QtCore.QSize(20, 20))
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self._updating = False
        self.itemChanged.connect(self._on_item_changed)
        self.currentRowChanged.connect(self.currentRowChanged2.emit)

    # -- populating -------------------------------------------------------
    def refresh(self, items: List[Dict[str, Any]], keep_row: Optional[int] = None) -> None:
        self._updating = True
        self.clear()
        for item in items:
            self._append_widget_item(item)
        self._updating = False
        if keep_row is not None and 0 <= keep_row < self.count():
            self.setCurrentRow(keep_row)

    def _append_widget_item(self, item: Dict[str, Any]) -> QtWidgets.QListWidgetItem:
        w_item = QtWidgets.QListWidgetItem()
        self._style_widget_item(w_item, item)
        self.addItem(w_item)
        return w_item

    def _style_widget_item(self, w_item: QtWidgets.QListWidgetItem, item: Dict[str, Any]) -> None:
        w_item.setText(item_label(item))
        type_name = item.get("type", "")
        w_item.setIcon(icons.type_icon(type_name))
        w_item.setData(ROLE_ITEM, item)
        flags = QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsDragEnabled
        if type_name not in ("separator",):
            flags |= QtCore.Qt.ItemIsEditable
        w_item.setFlags(flags | QtCore.Qt.ItemIsDropEnabled)
        problems = validate_item(item)
        font = w_item.font()
        font.setItalic(bool(problems))
        w_item.setFont(font)
        w_item.setToolTip("\n".join(problems))
        w_item.setForeground(QtGui.QColor("#b3261e") if problems else self.palette().text().color())

    def update_row(self, row: int, item: Dict[str, Any]) -> None:
        """Refresh one row's label/icon in place.

        Unlike ``refresh`` this deletes nothing and doesn't touch the
        selection, so it is safe to call from inside a signal handler of the
        properties form or of the row being renamed.
        """
        w_item = self.item(row)
        if w_item is None:
            return
        self._updating = True
        try:
            self._style_widget_item(w_item, item)
        finally:
            self._updating = False

    def item_dict(self, row: int) -> Optional[Dict[str, Any]]:
        w_item = self.item(row)
        if w_item is None:
            return None
        return w_item.data(ROLE_ITEM)

    def all_item_dicts(self) -> List[Dict[str, Any]]:
        return [self.item(i).data(ROLE_ITEM) for i in range(self.count())]

    def selected_rows(self) -> List[int]:
        return sorted(idx.row() for idx in self.selectionModel().selectedRows())

    # -- inline rename ------------------------------------------------------
    def _on_item_changed(self, w_item: QtWidgets.QListWidgetItem) -> None:
        if self._updating:
            return
        row = self.row(w_item)
        new_text = w_item.text()
        self.itemRenamed.emit(row, new_text)

    def start_rename_current(self) -> None:
        w_item = self.currentItem()
        if w_item is not None and (w_item.flags() & QtCore.Qt.ItemIsEditable):
            self.editItem(w_item)

    # -- drag & drop reorder --------------------------------------------
    def dropEvent(self, event: QtCore.QEvent) -> None:  # type: ignore[override]
        super().dropEvent(event)
        self.itemsReordered.emit(self.all_item_dicts())
