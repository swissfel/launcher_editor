"""Small, self-contained icon set drawn with QPainter.

No external image assets are bundled - every icon is generated at runtime so
the package stays dependency-free and MIT/GPL-icon-license-free. Icons are
cached per (type, size).
"""

from __future__ import annotations

import hashlib
from typing import Dict, Tuple

from PyQt5 import QtCore, QtGui

_CACHE: Dict[Tuple[str, int], QtGui.QIcon] = {}

# Fixed, recognizable colors for well-known types; anything else gets a
# deterministic color derived from its name so custom mapping types are
# still visually distinct and stable across sessions.
_FIXED_COLORS = {
    "separator": "#9aa5b1",
    "title": "#5b6b79",
    "menu": "#7c5cbf",
    "cmd": "#2f8f4e",
    "caqtdm": "#1f6fb2",
    "caqtdm-no-attach": "#1f6fb2",
    "medm": "#c46b1f",
    "pep": "#b23b6b",
}

_GLYPHS = {
    "separator": "―",
    "title": "T",
    "menu": "▸",
    "cmd": "$",
}


def _color_for_type(type_name: str) -> QtGui.QColor:
    if type_name in _FIXED_COLORS:
        return QtGui.QColor(_FIXED_COLORS[type_name])
    digest = hashlib.md5(type_name.encode()).hexdigest()
    hue = int(digest[:2], 16) / 255.0
    color = QtGui.QColor.fromHsvF(hue, 0.55, 0.80)
    return color


def _glyph_for_type(type_name: str) -> str:
    if type_name in _GLYPHS:
        return _GLYPHS[type_name]
    letters = "".join(c for c in type_name if c.isalnum())[:2].upper()
    return letters or "?"


def type_icon(type_name: str, size: int = 20) -> QtGui.QIcon:
    key = (type_name, size)
    if key in _CACHE:
        return _CACHE[key]

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)

    color = _color_for_type(type_name)
    painter.setBrush(QtGui.QBrush(color))
    painter.setPen(QtCore.Qt.NoPen)

    if type_name == "separator":
        painter.setBrush(QtCore.Qt.NoBrush)
        pen = QtGui.QPen(color)
        pen.setWidth(max(2, size // 8))
        painter.setPen(pen)
        y = size // 2
        painter.drawLine(size // 6, y, size - size // 6, y)
    else:
        rect = QtCore.QRectF(1, 1, size - 2, size - 2)
        if type_name == "menu":
            painter.drawRoundedRect(rect, size * 0.25, size * 0.25)
        else:
            painter.drawEllipse(rect)

        glyph = _glyph_for_type(type_name)
        painter.setPen(QtGui.QColor("#ffffff"))
        font = painter.font()
        font.setBold(True)
        font.setPixelSize(int(size * (0.55 if len(glyph) == 1 else 0.38)))
        painter.setFont(font)
        painter.drawText(rect, QtCore.Qt.AlignCenter, glyph)

    painter.end()
    icon = QtGui.QIcon(pixmap)
    _CACHE[key] = icon
    return icon


def action_icon(kind: str, size: int = 18) -> QtGui.QIcon:
    """Simple symbolic icons for toolbar/menu actions (not item types)."""

    key = (f"action:{kind}", size)
    if key in _CACHE:
        return _CACHE[key]

    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor("#334155"))
    pen.setWidthF(size * 0.11)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)

    m = size * 0.2
    if kind == "add":
        painter.drawLine(QtCore.QPointF(size / 2, m), QtCore.QPointF(size / 2, size - m))
        painter.drawLine(QtCore.QPointF(m, size / 2), QtCore.QPointF(size - m, size / 2))
    elif kind == "delete":
        painter.drawLine(QtCore.QPointF(m, m), QtCore.QPointF(size - m, size - m))
        painter.drawLine(QtCore.QPointF(size - m, m), QtCore.QPointF(m, size - m))
    elif kind == "duplicate":
        painter.drawRoundedRect(QtCore.QRectF(m, m * 1.4, size - 2 * m, size - 2 * m), 2, 2)
        painter.drawRoundedRect(QtCore.QRectF(m * 1.6, m * 0.4, size - 2 * m, size - 2 * m), 2, 2)
    elif kind == "cut":
        painter.drawEllipse(QtCore.QRectF(m, size - 2 * m, m, m))
        painter.drawEllipse(QtCore.QRectF(size - 2 * m, size - 2 * m, m, m))
        painter.drawLine(QtCore.QPointF(m + m / 2, size - 1.5 * m), QtCore.QPointF(size - m, m))
        painter.drawLine(
            QtCore.QPointF(size - m - m / 2, size - 1.5 * m), QtCore.QPointF(m, m)
        )
    elif kind == "copy":
        painter.drawRoundedRect(QtCore.QRectF(m, m * 1.5, size - 2.2 * m, size - 2.2 * m), 2, 2)
        painter.drawRoundedRect(QtCore.QRectF(m * 1.8, m * 0.5, size - 2.2 * m, size - 2.2 * m), 2, 2)
    elif kind == "paste":
        painter.drawRoundedRect(QtCore.QRectF(m * 0.8, m * 1.2, size - 1.6 * m, size - 1.8 * m), 2, 2)
        painter.drawRoundedRect(QtCore.QRectF(m * 1.6, m * 0.4, size - 3.2 * m, m * 1.0), 1, 1)
    elif kind == "save":
        painter.drawRoundedRect(QtCore.QRectF(m * 0.8, m * 0.8, size - 1.6 * m, size - 1.6 * m), 2, 2)
        painter.drawRect(QtCore.QRectF(m * 1.6, m * 0.8, size - 3.2 * m, m * 1.2))
    elif kind == "lock":
        painter.drawRoundedRect(QtCore.QRectF(m, size / 2, size - 2 * m, size / 2 - m * 0.6), 2, 2)
        painter.drawArc(QtCore.QRectF(m * 1.3, m * 0.6, size - 2.6 * m, size * 0.6), 0, 180 * 16)
    elif kind == "up":
        painter.drawLine(QtCore.QPointF(size / 2, size - m), QtCore.QPointF(size / 2, m))
        painter.drawLine(QtCore.QPointF(m, size / 2), QtCore.QPointF(size / 2, m))
        painter.drawLine(QtCore.QPointF(size - m, size / 2), QtCore.QPointF(size / 2, m))
    elif kind == "down":
        painter.drawLine(QtCore.QPointF(size / 2, m), QtCore.QPointF(size / 2, size - m))
        painter.drawLine(QtCore.QPointF(m, size / 2), QtCore.QPointF(size / 2, size - m))
        painter.drawLine(QtCore.QPointF(size - m, size / 2), QtCore.QPointF(size / 2, size - m))
    elif kind == "submenu":
        painter.drawRoundedRect(QtCore.QRectF(m * 0.6, m * 0.9, size - 1.2 * m, size - 1.8 * m), 2, 2)
        painter.drawLine(QtCore.QPointF(size * 0.42, size * 0.42), QtCore.QPointF(size * 0.65, size * 0.55))
        painter.drawLine(QtCore.QPointF(size * 0.42, size * 0.68), QtCore.QPointF(size * 0.65, size * 0.55))
    else:
        painter.drawEllipse(QtCore.QRectF(m, m, size - 2 * m, size - 2 * m))

    painter.end()
    icon = QtGui.QIcon(pixmap)
    _CACHE[key] = icon
    return icon
