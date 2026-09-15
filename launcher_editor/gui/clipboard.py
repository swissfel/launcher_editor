"""Qt clipboard glue for copy/paste of menu items across menus and tabs."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from PyQt5 import QtCore, QtWidgets

from ..model import items_from_clipboard_text, items_to_clipboard_text

MIME_TYPE = "application/x-epics-launcher-items"


def copy_items(items: List[Dict[str, Any]]) -> None:
    text = items_to_clipboard_text(items)
    mime = QtCore.QMimeData()
    mime.setData(MIME_TYPE, text.encode("utf-8"))
    mime.setText(text)
    QtWidgets.QApplication.clipboard().setMimeData(mime)


def paste_items() -> Optional[List[Dict[str, Any]]]:
    mime = QtWidgets.QApplication.clipboard().mimeData()
    if mime is None:
        return None
    if mime.hasFormat(MIME_TYPE):
        text = bytes(mime.data(MIME_TYPE)).decode("utf-8")
    elif mime.hasText():
        text = mime.text()
    else:
        return None
    return items_from_clipboard_text(text)
