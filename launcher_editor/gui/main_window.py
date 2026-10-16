"""Top-level application window: tabs, menus, toolbar, file I/O orchestration."""

from __future__ import annotations

import copy
import os
import shlex
from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from .. import gitflow, sources
from ..backends import Backend, BackendError, LocalBackend, RemoteConnectionInfo, SFTPBackend
from ..model import DEFAULT_MAPPING, MappingFile, MenuDocument, slugify
from ..sources import RecentList, Source
from ..workspace import Workspace
from . import icons
from .dialogs import (
    NewCustomTypeDialog,
    PasswordDialog,
    PublishDialog,
    RemoteConnectDialog,
    GitOpenDialog,
    confirm,
    show_about,
)
from .menu_editor import MenuEditorWidget

ORG_NAME = "PSI"
APP_NAME = "LauncherConfigEditor"

MAPPING_CANDIDATE_NAMES = ("launcher_mapping", "launcher_mapping_rhel7", "mapping.json")


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, read_only: bool = False, preview_command: str = "epics_launcher", publish_note: str = ""):
        super().__init__()
        self.setWindowTitle("Launcher Config Editor")
        self.resize(1250, 800)

        self.read_only = read_only
        self.preview_command = preview_command
        self.publish_note = publish_note
        self.root_path: Optional[str] = None
        self.preview_proc: Optional[QtCore.QProcess] = None
        # Coalesces the restarts from "Save All" into one.
        self._preview_restart = QtCore.QTimer(self)
        self._preview_restart.setSingleShot(True)
        self._preview_restart.setInterval(300)
        self._preview_restart.timeout.connect(self._launch_preview)

        self.backend: Optional[Backend] = None
        self.workspace: Optional[Workspace] = None
        self.mapping: MappingFile = MappingFile.default()
        self.os_name = "Linux"

        self.settings = QtCore.QSettings(ORG_NAME, APP_NAME)
        self.recent = RecentList.from_json(self.settings.value("recent_sources", ""))

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._on_current_tab_changed)
        self.setCentralWidget(self.tabs)

        self.status = self.statusBar()
        self.backend_label = QtWidgets.QLabel("No configuration open")
        self.status.addPermanentWidget(self.backend_label)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._restore_geometry()
        self._update_enabled_state()

    # -- window chrome ----------------------------------------------------
    def _build_actions(self) -> None:
        self.act_open_local = QtWidgets.QAction("Open &Local Configuration…", self)
        self.act_open_local.setShortcut(QtGui.QKeySequence.Open)
        self.act_open_local.triggered.connect(self.open_local_root)

        self.act_open_remote = QtWidgets.QAction("Open &Remote Configuration (SSH)…", self)
        self.act_open_remote.setShortcut("Ctrl+Shift+O")
        self.act_open_remote.triggered.connect(self.open_remote_root)

        self.act_open_git = QtWidgets.QAction("Open &Git Configuration…", self)
        self.act_open_git.setShortcut("Ctrl+Shift+G")
        self.act_open_git.setToolTip("Clone (or update) a repository and edit it locally (Ctrl+Shift+G)")
        self.act_open_git.triggered.connect(self.open_git_repository)

        self.act_clear_recent = QtWidgets.QAction("Clear List", self)
        self.act_clear_recent.triggered.connect(self._clear_recent)

        self.act_new_config = QtWidgets.QAction("&New Configuration…", self)
        self.act_new_config.setShortcut(QtGui.QKeySequence.New)
        self.act_new_config.triggered.connect(self.new_root_config)

        self.act_save = QtWidgets.QAction("&Save", self)
        self.act_save.setShortcut(QtGui.QKeySequence.Save)
        self.act_save.triggered.connect(self.save_current)

        self.act_save_all = QtWidgets.QAction("Save A&ll", self)
        self.act_save_all.setShortcut("Ctrl+Shift+S")
        self.act_save_all.triggered.connect(self.save_all)

        self.act_reload = QtWidgets.QAction("&Reload from Disk", self)
        self.act_reload.triggered.connect(self.reload_current)

        self.act_close_tab = QtWidgets.QAction("&Close Tab", self)
        self.act_close_tab.setShortcut(QtGui.QKeySequence.Close)
        self.act_close_tab.triggered.connect(lambda: self.close_tab(self.tabs.currentIndex()))

        self.act_quit = QtWidgets.QAction("&Quit", self)
        self.act_quit.setShortcut(QtGui.QKeySequence.Quit)
        self.act_quit.triggered.connect(self.close)

        self.act_cut = QtWidgets.QAction("Cu&t", self)
        self.act_cut.setShortcut(QtGui.QKeySequence.Cut)
        self.act_cut.triggered.connect(lambda: self._delegate("cut_selected"))

        self.act_copy = QtWidgets.QAction("&Copy", self)
        self.act_copy.setShortcut(QtGui.QKeySequence.Copy)
        self.act_copy.triggered.connect(lambda: self._delegate("copy_selected"))

        self.act_paste = QtWidgets.QAction("&Paste", self)
        self.act_paste.setShortcut(QtGui.QKeySequence.Paste)
        self.act_paste.triggered.connect(lambda: self._delegate("paste"))

        self.act_duplicate = QtWidgets.QAction("D&uplicate", self)
        self.act_duplicate.setShortcut("Ctrl+D")
        self.act_duplicate.triggered.connect(lambda: self._delegate("duplicate_selected"))

        self.act_delete = QtWidgets.QAction("&Delete", self)
        self.act_delete.setShortcut(QtGui.QKeySequence.Delete)
        self.act_delete.triggered.connect(lambda: self._delegate("delete_selected"))

        self.act_rename = QtWidgets.QAction("&Rename", self)
        self.act_rename.setShortcut("F2")
        self.act_rename.triggered.connect(self._rename_current)

        self.act_new_submenu = QtWidgets.QAction("New &Submenu…", self)
        self.act_new_submenu.setShortcut("Ctrl+Shift+N")
        self.act_new_submenu.triggered.connect(lambda: self._delegate("add_submenu"))

        self.act_move_up = QtWidgets.QAction("Move &Up", self)
        self.act_move_up.setShortcut("Ctrl+Up")
        self.act_move_up.triggered.connect(lambda: self._delegate("move_up"))

        self.act_move_down = QtWidgets.QAction("Move &Down", self)
        self.act_move_down.setShortcut("Ctrl+Down")
        self.act_move_down.triggered.connect(lambda: self._delegate("move_down"))

        self.act_menu_settings = QtWidgets.QAction("Menu &Settings…", self)
        self.act_menu_settings.triggered.connect(lambda: self._delegate("edit_menu_settings"))

        self.act_password = QtWidgets.QAction("Set/Clear &Password…", self)
        self.act_password.triggered.connect(self.set_password)

        self.act_add_custom_type = QtWidgets.QAction("Add Custom Command &Type…", self)
        self.act_add_custom_type.triggered.connect(self.add_custom_type)

        self.act_load_mapping = QtWidgets.QAction("&Load Mapping File…", self)
        self.act_load_mapping.triggered.connect(self.load_mapping_file)

        self.act_git_status = QtWidgets.QAction("Git &Status", self)
        self.act_git_status.triggered.connect(self.git_status)
        self.act_git_commit = QtWidgets.QAction("Git &Commit…", self)
        self.act_git_commit.triggered.connect(self.git_commit)
        self.act_git_push = QtWidgets.QAction("Git &Push…", self)
        self.act_git_push.triggered.connect(self.git_push)
        self.act_git_update = QtWidgets.QAction("&Update from Remote", self)
        self.act_git_update.triggered.connect(self.git_update)
        self.act_publish = QtWidgets.QAction("P&ublish…", self)
        self.act_publish.setShortcut("Ctrl+Shift+P")
        self.act_publish.setToolTip("Commit your saved changes and push them (Ctrl+Shift+P)")
        self.act_publish.triggered.connect(self.publish)

        self.act_preview = QtWidgets.QAction("&Preview", self)
        self.act_preview.setShortcut("F5")
        self.act_preview.setToolTip(
            "Open the root menu in the real launcher; it restarts each time you save (F5)"
        )
        self.act_preview.triggered.connect(self.start_preview)

        self.act_about = QtWidgets.QAction("&About", self)
        self.act_about.triggered.connect(lambda: show_about(self))

    def _build_menus(self) -> None:
        m_file = self.menuBar().addMenu("&File")
        m_file.addAction(self.act_open_git)
        m_file.addAction(self.act_open_local)
        m_file.addAction(self.act_open_remote)
        self.m_recent = m_file.addMenu("Open &Recent")
        self.m_recent.aboutToShow.connect(self._populate_recent)
        m_file.addAction(self.act_new_config)
        m_file.addSeparator()
        m_file.addAction(self.act_save)
        m_file.addAction(self.act_save_all)
        m_file.addAction(self.act_reload)
        m_file.addAction(self.act_preview)
        m_file.addSeparator()
        m_file.addAction(self.act_close_tab)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_edit = self.menuBar().addMenu("&Edit")
        m_edit.addAction(self.act_cut)
        m_edit.addAction(self.act_copy)
        m_edit.addAction(self.act_paste)
        m_edit.addAction(self.act_duplicate)
        m_edit.addAction(self.act_delete)
        m_edit.addAction(self.act_rename)
        m_edit.addSeparator()
        m_edit.addAction(self.act_move_up)
        m_edit.addAction(self.act_move_down)
        m_edit.addSeparator()
        m_edit.addAction(self.act_new_submenu)
        m_edit.addAction(self.act_menu_settings)

        m_tools = self.menuBar().addMenu("&Tools")
        m_tools.addAction(self.act_password)
        m_tools.addSeparator()
        m_tools.addAction(self.act_add_custom_type)
        m_tools.addAction(self.act_load_mapping)

        self.m_git = self.menuBar().addMenu("&Git")
        self.m_git.addAction(self.act_git_update)
        self.m_git.addAction(self.act_publish)
        self.m_git.addSeparator()
        self.m_git.addAction(self.act_git_status)
        self.m_git.addAction(self.act_git_commit)
        self.m_git.addAction(self.act_git_push)
        self.m_git.aboutToShow.connect(self._update_git_enabled)

        m_help = self.menuBar().addMenu("&Help")
        m_help.addAction(self.act_about)

    def _build_toolbar(self) -> None:
        tb = QtWidgets.QToolBar("Main")
        tb.setMovable(False)
        tb.setIconSize(QtCore.QSize(20, 20))
        self.addToolBar(tb)
        tb.addAction(self.act_open_git)
        tb.addAction(self.act_open_local)
        tb.addAction(self.act_open_remote)
        tb.addSeparator()
        self.act_save.setIcon(icons.action_icon("save"))
        tb.addAction(self.act_save)
        tb.addAction(self.act_save_all)
        tb.addSeparator()
        self.act_password.setIcon(icons.action_icon("lock"))
        tb.addAction(self.act_password)
        tb.addSeparator()
        tb.addAction(self.act_preview)
        tb.addAction(self.act_publish)

    def _restore_geometry(self) -> None:
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)

    # -- helpers ------------------------------------------------------------
    def current_editor(self) -> Optional[MenuEditorWidget]:
        return self.tabs.currentWidget()

    def _delegate(self, method_name: str) -> None:
        ed = self.current_editor()
        if ed is not None:
            getattr(ed, method_name)()

    def _on_current_tab_changed(self, _index: int) -> None:
        self._update_enabled_state()
        self._update_window_title()

    def _rename_current(self) -> None:
        ed = self.current_editor()
        if ed is not None:
            ed.list.start_rename_current()

    def _update_enabled_state(self) -> None:
        has_tab = self.current_editor() is not None
        for act in (
            self.act_save,
            self.act_save_all,
            self.act_reload,
            self.act_close_tab,
            self.act_cut,
            self.act_copy,
            self.act_paste,
            self.act_duplicate,
            self.act_delete,
            self.act_rename,
            self.act_new_submenu,
            self.act_move_up,
            self.act_move_down,
            self.act_menu_settings,
            self.act_password,
        ):
            act.setEnabled(has_tab)
        self.act_new_config.setEnabled(True)
        self.act_add_custom_type.setEnabled(self.workspace is not None)
        self.act_load_mapping.setEnabled(self.workspace is not None)
        self.act_preview.setEnabled(self.root_path is not None and isinstance(self.backend, LocalBackend))
        self.act_publish.setEnabled(has_tab)
        if self.read_only:
            for act in (
                self.act_save,
                self.act_save_all,
                self.act_new_config,
                self.act_cut,
                self.act_paste,
                self.act_duplicate,
                self.act_delete,
                self.act_rename,
                self.act_new_submenu,
                self.act_move_up,
                self.act_move_down,
                self.act_menu_settings,
                self.act_password,
                self.act_add_custom_type,
                self.act_publish,
            ):
                act.setEnabled(False)

    def _tab_label(self, doc: MenuDocument) -> str:
        base = self.backend.basename(doc.path) if self.backend else doc.path
        return base + (" ●" if doc.dirty else "")

    def _update_tab_title(self, editor: MenuEditorWidget) -> None:
        idx = self.tabs.indexOf(editor)
        if idx >= 0:
            self.tabs.setTabText(idx, self._tab_label(editor.doc))
        self._update_window_title()

    def _update_window_title(self) -> None:
        ed = self.current_editor()
        suffix = " [read-only]" if self.read_only else ""
        if ed is None or self.backend is None:
            self.setWindowTitle("Launcher Config Editor" + suffix)
            self.backend_label.setText("No configuration open")
        else:
            self.setWindowTitle(f"Launcher Config Editor — {ed.doc.path}{suffix}")
            self.backend_label.setText(f"Backend: {self.backend.label}")

    # -- opening configurations -------------------------------------------
    def open_local_root(self) -> None:
        last_dir = self.settings.value("last_local_dir", "")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Open Root Configuration", last_dir, "JSON files (*.json);;All files (*)"
        )
        if not path:
            return
        self.settings.setValue("last_local_dir", path)
        self._switch_backend_and_open(LocalBackend(), path, Source("local", path=os.path.abspath(path)))

    def open_remote_root(self) -> None:
        default_host = self.settings.value("last_remote_host", "")
        default_path = self.settings.value("last_remote_path", "")
        dlg = RemoteConnectDialog(self, default_host=default_host, default_path=default_path)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        values = dlg.values()
        try:
            backend = SFTPBackend(
                RemoteConnectionInfo(
                    host=values["host"],
                    username=values["username"],
                    password=values["password"],
                )
            )
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Connection Failed", str(exc))
            return

        path = values["path"]
        try:
            if backend.is_dir(path):
                chosen = self._pick_remote_file(backend, path)
                if not chosen:
                    backend.close()
                    return
                path = chosen
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Connection Failed", str(exc))
            backend.close()
            return

        self.settings.setValue("last_remote_host", values["host"])
        self.settings.setValue("last_remote_path", values["path"])
        self._switch_backend_and_open(
            backend, path, Source("ssh", host=values["host"], user=values["username"] or "", path=path)
        )

    def _pick_remote_file(self, backend: Backend, directory: str) -> Optional[str]:
        try:
            names = [n for n in backend.listdir(directory) if n.endswith(".json")]
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Open Remote", str(exc))
            return None
        if not names:
            QtWidgets.QMessageBox.information(self, "Open Remote", f"No .json files found in {directory}")
            return None
        name, ok = QtWidgets.QInputDialog.getItem(
            self, "Select Configuration File", f"Files in {directory}:", names, 0, False
        )
        if ok and name:
            return backend.join(directory, name)
        return None

    def _switch_backend_and_open(self, backend: Backend, path: str, source: Optional[Source] = None) -> bool:
        if self.workspace is not None and self.backend is not None:
            if not self._confirm_and_close_all_tabs():
                backend.close()
                return False
            self.backend.close()

        self._stop_preview()
        self.backend = backend
        self.root_path = path
        self.workspace = Workspace(backend)
        self._auto_load_mapping(backend, backend.dirname(path))
        self._open_path_in_tab(path)
        self._update_enabled_state()
        ed = self.current_editor()
        opened = ed is not None and ed.doc.path == path
        if opened:
            if source is None and isinstance(backend, LocalBackend):
                source = Source("local", path=os.path.abspath(path))
            if source is not None:
                self.recent.add(source)
                self._save_recent()
        return opened

    def _auto_load_mapping(self, backend: Backend, directory: str) -> None:
        for name in MAPPING_CANDIDATE_NAMES:
            candidate = backend.join(directory, name)
            if backend.exists(candidate):
                try:
                    self.mapping = MappingFile.load(backend, candidate)
                    self.status.showMessage(f"Loaded custom command types from {candidate}", 5000)
                    return
                except Exception:
                    continue
        self.mapping = MappingFile.default()

    def load_mapping_file(self) -> None:
        if self.backend is None:
            return
        if isinstance(self.backend, LocalBackend):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load Mapping File", "", "All files (*)")
            if not path:
                return
        else:
            directory = self.backend.dirname(self.current_editor().doc.path) if self.current_editor() else "/"
            name, ok = QtWidgets.QInputDialog.getText(self, "Load Mapping File", "Mapping file path:", text=directory)
            if not ok or not name.strip():
                return
            path = name.strip()
        try:
            self.mapping = MappingFile.load(self.backend, path)
        except (BackendError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self, "Load Mapping File", str(exc))
            return
        for i in range(self.tabs.count()):
            self.tabs.widget(i).refresh_add_menu()
        self.status.showMessage(f"Loaded mapping: {path}", 4000)

    def new_root_config(self) -> None:
        if self.workspace is None:
            directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Choose Folder for New Configuration")
            if not directory:
                return
            self.backend = LocalBackend()
            self.workspace = Workspace(self.backend)
            self.mapping = MappingFile.default()
        else:
            ed = self.current_editor()
            directory = self.backend.dirname(ed.doc.path) if ed else None
            if not directory:
                QtWidgets.QMessageBox.information(self, "New Configuration", "Open or select a tab first.")
                return

        title, ok = QtWidgets.QInputDialog.getText(self, "New Configuration", "Menu title:")
        if not ok or not title.strip():
            return
        default_name = slugify(title.strip()) + ".json"
        file_name, ok2 = QtWidgets.QInputDialog.getText(self, "New Configuration", "File name:", text=default_name)
        if not ok2 or not file_name.strip():
            return
        file_name = file_name.strip()
        if not file_name.endswith(".json"):
            file_name += ".json"
        path = self.backend.join(directory, file_name)
        if self.backend.exists(path):
            QtWidgets.QMessageBox.warning(self, "New Configuration", f'"{file_name}" already exists.')
            return
        doc = MenuDocument.create_new(self.backend, path, title.strip())
        try:
            doc.save(make_backup=False)
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "New Configuration", str(exc))
            return
        self.workspace.register(doc)
        self._open_path_in_tab(path)
        self._update_enabled_state()

    def _open_path_in_tab(self, path: str) -> None:
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, MenuEditorWidget) and w.doc.path == path:
                self.tabs.setCurrentIndex(i)
                return
        try:
            doc = self.workspace.open(path)
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Open Failed", str(exc))
            return

        editor = MenuEditorWidget(self.workspace, doc, lambda: self.mapping, lambda: self.os_name)
        editor.titleChanged.connect(lambda ed=editor: self._update_tab_title(ed))
        editor.statusMessage.connect(lambda msg, ms: self.status.showMessage(msg, ms))
        editor.requestOpenPath.connect(self._open_path_in_tab)
        idx = self.tabs.addTab(editor, self._tab_label(doc))
        self.tabs.setCurrentIndex(idx)
        self._update_window_title()

    # -- saving -------------------------------------------------------------
    def save_current(self) -> None:
        ed = self.current_editor()
        if ed is None:
            return
        self._save_editor(ed)

    def _save_editor(self, ed: MenuEditorWidget) -> bool:
        if self.read_only:
            QtWidgets.QMessageBox.information(self, "Save", "This configuration is open read-only.")
            return False
        problems = ed.doc.validate()
        if problems:
            preview = "\n".join(problems[:6]) + ("\n…" if len(problems) > 6 else "")
            if not confirm(self, "Save", f"This menu has validation warnings:\n\n{preview}\n\nSave anyway?"):
                return False
        try:
            ed.doc.save()
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Save Failed", str(exc))
            return False
        self._update_tab_title(ed)
        self.status.showMessage(f"Saved {ed.doc.path}", 4000)
        if self._preview_running():
            self._preview_restart.start()
        return True

    def save_all(self) -> None:
        saved = 0
        for i in range(self.tabs.count()):
            ed = self.tabs.widget(i)
            if ed.is_dirty:
                if self._save_editor(ed):
                    saved += 1
        self.status.showMessage(f"Saved {saved} file(s)", 4000)

    def reload_current(self) -> None:
        ed = self.current_editor()
        if ed is None:
            return
        if ed.is_dirty and not confirm(self, "Reload", "Discard unsaved changes and reload from disk?"):
            return
        try:
            fresh = MenuDocument.load(self.backend, ed.doc.path)
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Reload Failed", str(exc))
            return
        ed.doc.data = fresh.data
        ed.doc.dirty = False
        ed.refresh()
        self._update_tab_title(ed)

    # -- closing --------------------------------------------------------
    def close_tab(self, index: int) -> None:
        ed = self.tabs.widget(index)
        if ed is None:
            return
        if ed.is_dirty and not self.read_only:
            ret = QtWidgets.QMessageBox.question(
                self,
                "Unsaved Changes",
                f'Save changes to "{self.backend.basename(ed.doc.path)}" before closing?',
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            )
            if ret == QtWidgets.QMessageBox.Cancel:
                return
            if ret == QtWidgets.QMessageBox.Save and not self._save_editor(ed):
                return
        if self.workspace is not None:
            self.workspace.close(ed.doc.path)
        self.tabs.removeTab(index)
        self._update_enabled_state()
        self._update_window_title()

    def _confirm_and_close_all_tabs(self) -> bool:
        dirty = [self.tabs.widget(i) for i in range(self.tabs.count()) if self.tabs.widget(i).is_dirty]
        if dirty and not self.read_only:
            ret = QtWidgets.QMessageBox.question(
                self,
                "Unsaved Changes",
                f"{len(dirty)} file(s) have unsaved changes. Save them before switching configuration?",
                QtWidgets.QMessageBox.Save | QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel,
            )
            if ret == QtWidgets.QMessageBox.Cancel:
                return False
            if ret == QtWidgets.QMessageBox.Save:
                for ed in dirty:
                    if not self._save_editor(ed):
                        return False
        self.tabs.clear()
        return True

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        # Commit a field that is still being edited, so the unsaved-changes
        # check below sees it.
        focused = QtWidgets.QApplication.focusWidget()
        if focused is not None:
            focused.clearFocus()
        editors = [self.tabs.widget(i) for i in range(self.tabs.count())]
        if not self._confirm_and_close_all_tabs():
            event.ignore()
            return
        for ed in editors:
            ed.properties.shutdown()
        self._stop_preview()
        if self.backend is not None:
            self.backend.close()
        self.settings.setValue("geometry", self.saveGeometry())
        event.accept()

    # -- password -----------------------------------------------------
    def set_password(self) -> None:
        ed = self.current_editor()
        if ed is None:
            return
        dlg = PasswordDialog(self, ed.doc.has_password())
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        pw = dlg.result_password()
        if pw is None:
            return
        ed.doc.set_password(pw if pw else None)
        ed.titleChanged.emit()
        self.status.showMessage("Password updated — remember to Save", 4000)

    # -- custom command types (mapping) -----------------------------------
    def add_custom_type(self) -> None:
        if self.workspace is None:
            return
        dlg = NewCustomTypeDialog(self)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        name, command, arg_flags = dlg.values()
        if not name or not command:
            QtWidgets.QMessageBox.warning(self, "New Custom Command Type", "Please provide a type name and command template.")
            return

        if self.mapping.path is None:
            ed = self.current_editor()
            if ed is None:
                QtWidgets.QMessageBox.warning(self, "New Custom Command Type", "Open a configuration first.")
                return
            directory = self.backend.dirname(ed.doc.path)
            fname, ok = QtWidgets.QInputDialog.getText(
                self, "Create Mapping File", "This site has no mapping file yet. File name:", text="launcher_mapping"
            )
            if not ok or not fname.strip():
                return
            path = self.backend.join(directory, fname.strip())
            self.mapping = MappingFile(self.backend, path, copy.deepcopy(DEFAULT_MAPPING))

        self.mapping.add_or_update_type(name, command, arg_flags or None)
        try:
            self.mapping.save()
        except BackendError as exc:
            QtWidgets.QMessageBox.critical(self, "Save Mapping Failed", str(exc))
            return
        for i in range(self.tabs.count()):
            self.tabs.widget(i).refresh_add_menu()
        self.status.showMessage(f'Added custom type "{name}" to {self.mapping.path}', 5000)

    # -- git integration (optional convenience) ---------------------------
    def _git_directory(self) -> Optional[str]:
        ed = self.current_editor()
        if ed is None or self.backend is None:
            return None
        return gitflow.repo_root(self.backend, self.backend.dirname(ed.doc.path))

    def _update_git_enabled(self) -> None:
        enabled = self._git_directory() is not None
        for act in (self.act_git_status, self.act_git_commit, self.act_git_push, self.act_git_update, self.act_publish):
            act.setEnabled(enabled)
        if self.read_only:
            for act in (self.act_git_commit, self.act_git_push, self.act_git_update, self.act_publish):
                act.setEnabled(False)

    def git_status(self) -> None:
        directory = self._git_directory()
        if not directory:
            return
        try:
            out = self.backend.run_git(directory, ["status", "--short"])
        except BackendError as exc:
            QtWidgets.QMessageBox.warning(self, "Git Status", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Git Status", out.strip() or "Working tree is clean.")

    def git_commit(self) -> None:
        directory = self._git_directory()
        if not directory:
            return
        message, ok = QtWidgets.QInputDialog.getMultiLineText(
            self, "Git Commit", "Commit message:", "Update launcher configuration"
        )
        if not ok or not message.strip():
            return
        try:
            self.backend.run_git(directory, ["add", "-A"])
            out = self.backend.run_git(directory, ["commit", "-m", message.strip()])
        except BackendError as exc:
            QtWidgets.QMessageBox.warning(self, "Git Commit", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Git Commit", out.strip() or "Committed.")

    def git_push(self) -> None:
        directory = self._git_directory()
        if not directory:
            return
        if not confirm(
            self,
            "Git Push",
            "Push committed changes to the shared remote repository now?\n\nThis affects everyone using this configuration.",
        ):
            return
        try:
            out = self.backend.run_git(directory, ["push"])
        except BackendError as exc:
            QtWidgets.QMessageBox.warning(self, "Git Push", str(exc))
            return
        QtWidgets.QMessageBox.information(self, "Git Push", out.strip() or "Pushed.")

    # -- update / publish -------------------------------------------------
    def _save_all_first(self, title: str) -> bool:
        dirty = [self.tabs.widget(i) for i in range(self.tabs.count()) if self.tabs.widget(i).is_dirty]
        if not dirty:
            return True
        if not confirm(self, title, f"{len(dirty)} file(s) have unsaved changes. Save them first?"):
            return False
        return all(self._save_editor(ed) for ed in dirty)

    def _reload_all_from_disk(self) -> None:
        """Re-read every open tab after git changed the files underneath."""
        for i in range(self.tabs.count()):
            ed = self.tabs.widget(i)
            try:
                fresh = MenuDocument.load(self.backend, ed.doc.path)
            except BackendError:
                continue  # file removed upstream; the tab keeps its last state
            ed.doc.data = fresh.data
            ed.doc.dirty = False
            ed.refresh()
            self._update_tab_title(ed)
        if self.root_path:
            self._auto_load_mapping(self.backend, self.backend.dirname(self.root_path))

    def _run_busy(self, func, *args):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            return func(*args)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def git_update(self) -> None:
        root = self._git_directory()
        if not root or not self._save_all_first("Update from Remote"):
            return
        try:
            out = self._run_busy(gitflow.update, self.backend, root)
        except (gitflow.PublishError, BackendError) as exc:
            QtWidgets.QMessageBox.warning(self, "Update from Remote", str(exc))
            return
        self._reload_all_from_disk()
        if self._preview_running():
            self._preview_restart.start()
        self.status.showMessage(out.splitlines()[-1] if out else "Updated", 5000)

    def publish(self) -> None:
        root = self._git_directory()
        if not root:
            QtWidgets.QMessageBox.information(
                self, "Publish", "The open configuration is not inside a git repository, so there is nothing to publish to."
            )
            return
        if not self._save_all_first("Publish"):
            return
        try:
            pending = gitflow.prepare(self.backend, root)
        except (gitflow.PublishError, BackendError) as exc:
            QtWidgets.QMessageBox.warning(self, "Publish", str(exc))
            return
        if pending.nothing_to_publish:
            gitflow.unstage(self.backend, root)
            QtWidgets.QMessageBox.information(self, "Publish", "Nothing to publish: everything is already pushed.")
            return
        dlg = PublishDialog(
            self, root, gitflow.changed_files(pending.status), pending.diff, pending.ahead, self.publish_note
        )
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            gitflow.unstage(self.backend, root)
            return
        try:
            summary = self._run_busy(gitflow.publish, self.backend, root, dlg.message())
        except (gitflow.PublishError, BackendError) as exc:
            QtWidgets.QMessageBox.critical(self, "Publish Failed", str(exc))
            return
        self._reload_all_from_disk()  # the rebase may have brought in others' changes
        if self._preview_running():
            self._preview_restart.start()
        QtWidgets.QMessageBox.information(
            self, "Published", summary + (f"\n\n{self.publish_note}" if self.publish_note else "")
        )

    # -- preview ------------------------------------------------------------
    def _preview_running(self) -> bool:
        return self.preview_proc is not None and self.preview_proc.state() != QtCore.QProcess.NotRunning

    def _stop_preview(self) -> None:
        self._preview_restart.stop()
        proc, self.preview_proc = self.preview_proc, None
        if proc is not None and proc.state() != QtCore.QProcess.NotRunning:
            proc.terminate()
            if not proc.waitForFinished(1500):
                proc.kill()
                proc.waitForFinished(1000)

    def start_preview(self) -> None:
        if not self.root_path or not isinstance(self.backend, LocalBackend):
            return
        dirty = [self.tabs.widget(i) for i in range(self.tabs.count()) if self.tabs.widget(i).is_dirty]
        if dirty and not self.read_only and confirm(
            self, "Preview", "The preview shows the saved files. Save your changes first?"
        ):
            for ed in dirty:
                if not self._save_editor(ed):
                    return
        self._launch_preview()

    def _launch_preview(self) -> None:
        self._stop_preview()
        try:
            cmd = shlex.split(self.preview_command) + [self.root_path]
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Preview", f"Invalid preview command: {exc}")
            return
        proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(QtCore.QProcess.ForwardedChannels)
        proc.errorOccurred.connect(lambda err, c=cmd[0]: self._on_preview_error(err, c))
        proc.start(cmd[0], cmd[1:])
        self.preview_proc = proc
        self.status.showMessage("Preview started; it restarts each time you save", 5000)

    def _on_preview_error(self, error: QtCore.QProcess.ProcessError, program: str) -> None:
        if error == QtCore.QProcess.FailedToStart:
            QtWidgets.QMessageBox.warning(self, "Preview", f'Could not start "{program}". Is it installed and on PATH?')

    # -- recent configurations ----------------------------------------------
    def _save_recent(self) -> None:
        self.settings.setValue("recent_sources", self.recent.to_json())

    def _clear_recent(self) -> None:
        self.recent.clear()
        self._save_recent()

    def _populate_recent(self) -> None:
        self.m_recent.clear()
        if not self.recent.entries:
            empty = self.m_recent.addAction("(nothing opened yet)")
            empty.setEnabled(False)
        icons_by_kind = {"local": "Local", "ssh": "SSH", "git": "Git"}
        for i, src in enumerate(self.recent.entries):
            act = self.m_recent.addAction(f"&{i + 1:X}  [{icons_by_kind.get(src.kind, src.kind)}]  {src.label()}")
            act.triggered.connect(lambda checked=False, s=src: self.open_recent(s))
        self.m_recent.addSeparator()
        self.m_recent.addAction(self.act_clear_recent)
        self.act_clear_recent.setEnabled(bool(self.recent.entries))

    def open_recent(self, src: Source) -> None:
        if src.kind == "git":
            self.open_git(src.url, src.branch, src.checkout, src.path)
        elif src.kind == "ssh":
            self._open_recent_ssh(src)
        else:
            if not os.path.exists(src.path):
                if confirm(self, "Open Recent", f"{src.path} no longer exists. Remove it from the list?"):
                    self.recent.remove(src)
                    self._save_recent()
                return
            self._switch_backend_and_open(LocalBackend(), src.path, src)

    def _open_recent_ssh(self, src: Source) -> None:
        try:
            backend = self._run_busy(
                SFTPBackend, RemoteConnectionInfo(host=src.host, username=src.user or None)
            )
        except BackendError:
            # Key/agent login didn't work: ask, prefilled.
            dlg = RemoteConnectDialog(self, default_host=src.host, default_path=src.path, default_user=src.user)
            if dlg.exec_() != QtWidgets.QDialog.Accepted:
                return
            values = dlg.values()
            try:
                backend = SFTPBackend(
                    RemoteConnectionInfo(host=values["host"], username=values["username"], password=values["password"])
                )
            except BackendError as exc:
                QtWidgets.QMessageBox.critical(self, "Connection Failed", str(exc))
                return
            src = Source("ssh", host=values["host"], user=values["username"] or "", path=values["path"])
        self._switch_backend_and_open(backend, src.path, src)

    # -- git repositories ---------------------------------------------------
    def open_git_repository(self) -> None:
        dlg = GitOpenDialog(self, self.recent.git_urls(), sources.default_checkout)
        if dlg.exec_() != QtWidgets.QDialog.Accepted:
            return
        url, branch, checkout = dlg.values()
        self.open_git(url, branch, checkout)

    def open_git(self, url: str, branch: str, checkout: str, root: Optional[str] = None) -> bool:
        """Clone or update ``url`` into ``checkout`` and open its root menu file."""
        checkout = os.path.abspath(os.path.expanduser(checkout))
        try:
            message = self._run_busy(sources.clone_or_update, url, checkout, branch)
        except sources.CheckoutError as exc:
            QtWidgets.QMessageBox.critical(self, "Open Git Repository", str(exc))
            return False
        if message.startswith("Could not"):
            QtWidgets.QMessageBox.warning(self, "Open Git Repository", message)
        else:
            self.status.showMessage(message, 6000)

        if not root or not os.path.isfile(os.path.join(checkout, root)):
            previous = self.recent.last_for_url(url)
            if previous and previous.checkout == checkout and os.path.isfile(os.path.join(checkout, previous.path)):
                root = previous.path
            else:
                root = self._pick_root_file(checkout)
                if not root:
                    return False
        path = os.path.join(checkout, root)
        return self._switch_backend_and_open(
            LocalBackend(), path, Source("git", url=url, branch=branch, checkout=checkout, path=root)
        )

    def _pick_root_file(self, checkout: str) -> Optional[str]:
        files = sources.menu_files(checkout)
        if not files:
            QtWidgets.QMessageBox.information(self, "Open Git Repository", f"No .json menu files found in {checkout}.")
            return None
        # Beamline launchers conventionally start at S_<Name>.json.
        preferred = next((i for i, f in enumerate(files) if os.path.basename(f).startswith("S_")), 0)
        name, ok = QtWidgets.QInputDialog.getItem(
            self, "Choose the Root Menu", f"Menu files in {checkout}:", files, preferred, False
        )
        return name if ok and name else None
