"""Opening from git and from the recent list, through the main window."""

import os
import subprocess

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from launcher_editor.gui import main_window as mw  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def remote(tmp_path):
    remote = tmp_path / "configs.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
    git(seed, "config", "user.name", "T")
    git(seed, "config", "user.email", "t@x")
    (seed / "a_other.json").write_text('{"menu": []}\n')
    (seed / "S_Test.json").write_text('{"menu-title": {"text": "T"}, "menu": [{"type": "cmd", "text": "x", "command": "true"}]}\n')
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "seed")
    git(seed, "push", "-q", "origin", "master")
    return remote


@pytest.fixture
def no_dialogs(monkeypatch):
    calls = []
    monkeypatch.setattr(mw, "confirm", lambda *a: True)
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name, staticmethod(lambda *a, n=name, **k: calls.append((n, a[2]))))
    return calls


def close(w):
    for i in range(w.tabs.count()):
        w.tabs.widget(i).doc.dirty = False
    w.close()


def test_open_git_clones_picks_root_and_records(app, remote, tmp_path, monkeypatch, no_dialogs):
    picked = []

    def get_item(parent, title, label, items, current, editable):
        picked.append((list(items), current))
        return items[current], True

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(get_item))
    w = mw.MainWindow()
    checkout = tmp_path / "work" / "configs"
    assert w.open_git(str(remote), "", str(checkout))
    assert picked == [(["S_Test.json", "a_other.json"], 0)]  # S_* preselected
    assert w.current_editor().doc.path == str(checkout / "S_Test.json")
    entry = w.recent.entries[0]
    assert (entry.kind, entry.url, entry.checkout, entry.path) == ("git", str(remote), str(checkout), "S_Test.json")
    assert w._git_directory() == str(checkout)
    close(w)


def test_recent_survives_restart_and_reopens_without_questions(app, remote, tmp_path, monkeypatch, no_dialogs):
    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(lambda *a: ("S_Test.json", True)))
    checkout = tmp_path / "configs"
    w = mw.MainWindow()
    w.open_git(str(remote), "", str(checkout))
    close(w)

    def must_not_ask(*a):
        raise AssertionError("asked for the root file again")

    monkeypatch.setattr(QtWidgets.QInputDialog, "getItem", staticmethod(must_not_ask))
    w2 = mw.MainWindow()  # fresh window, same (isolated) settings
    assert w2.recent.entries and w2.recent.entries[0].kind == "git"
    w2._populate_recent()
    labels = [a.text() for a in w2.m_recent.actions() if a.text()]
    assert any("[Git]" in t and "S_Test.json" in t for t in labels)
    w2.open_recent(w2.recent.entries[0])
    assert w2.current_editor().doc.path == str(checkout / "S_Test.json")
    close(w2)


def test_local_open_recorded_and_missing_file_removed(app, tmp_path, no_dialogs):
    f = tmp_path / "menu.json"
    f.write_text('{"menu": []}\n')
    w = mw.MainWindow()
    w._switch_backend_and_open(mw.LocalBackend(), str(f))
    assert w.recent.entries[0].key() == ("local", str(f))
    f.unlink()
    w.open_recent(w.recent.entries[0])
    assert all(e.key() != ("local", str(f)) for e in w.recent.entries)
    close(w)


def test_git_clone_error_is_reported(app, tmp_path, no_dialogs):
    w = mw.MainWindow()
    assert not w.open_git(str(tmp_path / "missing.git"), "", str(tmp_path / "x"))
    assert no_dialogs and no_dialogs[-1][0] == "critical" and "Could not clone" in no_dialogs[-1][1]
    assert not w.recent.entries
    close(w)
