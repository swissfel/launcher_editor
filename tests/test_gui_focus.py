"""Regression: leaving an edited field must not delete it mid-focusOut.

Qt delivers editingFinished from inside QLineEdit::focusOutEvent. The editor
used to rebuild the item list and the properties form from that signal, which
deleted the field while Qt was still in its focusOutEvent (SIGSEGV in
QWidget::focusPolicy). The test sends that exact focus-out event; on the old
code the field is already deleted when focus_out() returns (on a real
display that is a use-after-free and crashes; offscreen it may not).
"""

import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtCore = pytest.importorskip("PyQt5.QtCore")
QtGui = pytest.importorskip("PyQt5.QtGui")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")
from PyQt5 import sip  # noqa: E402

from launcher_editor.backends import LocalBackend  # noqa: E402
from launcher_editor.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def window(app, tmp_path):
    menu = {
        "menu-title": {"text": "Test"},
        "menu": [
            {"type": "cmd", "text": "first", "command": "true"},
            {"type": "cmd", "text": "second", "command": "true"},
        ],
    }
    path = tmp_path / "menu.json"
    path.write_text(json.dumps(menu))
    w = MainWindow()
    w._switch_backend_and_open(LocalBackend(), str(path))
    yield w
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.dirty = False
    w.close()


def focus_out(widget, reason=QtCore.Qt.ActiveWindowFocusReason):
    QtWidgets.QApplication.sendEvent(widget, QtGui.QFocusEvent(QtCore.QEvent.FocusOut, reason))


@pytest.mark.parametrize("field", ["text", "tip"])
def test_leaving_edited_field_keeps_editor_alive(app, window, field):
    ed = window.current_editor()
    ed.list.setCurrentRow(0)
    app.processEvents()
    line = ed.properties._editors[field]
    line.setText("changed")
    focus_out(line)  # crashed here before the fix
    assert not sip.isdeleted(line), "field deleted inside its own focusOutEvent"
    app.processEvents()
    assert ed.doc.items[0][field] == "changed"
    assert ed.doc.dirty
    if field == "text":
        assert ed.list.item(0).text() == "changed"


def test_rename_in_list_then_edit_field(app, window):
    ed = window.current_editor()
    ed.list.setCurrentRow(1)
    app.processEvents()
    ed.list.item(1).setText("renamed")  # inline rename path
    app.processEvents()
    assert ed.doc.items[1]["text"] == "renamed"
    line = ed.properties._editors["text"]
    assert line.text() == "renamed"
    line.setText("renamed again")
    focus_out(line)
    assert not sip.isdeleted(line)
    app.processEvents()
    assert ed.list.item(1).text() == "renamed again"
