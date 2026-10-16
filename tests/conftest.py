import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_qt_settings(tmp_path_factory):
    """Keep GUI tests away from the real ~/.config/PSI settings (recent list, geometry)."""
    try:
        from PyQt5 import QtCore
    except ImportError:
        yield
        return
    path = str(tmp_path_factory.mktemp("qsettings"))
    for fmt in (QtCore.QSettings.NativeFormat, QtCore.QSettings.IniFormat):
        QtCore.QSettings.setPath(fmt, QtCore.QSettings.UserScope, path)
    yield
