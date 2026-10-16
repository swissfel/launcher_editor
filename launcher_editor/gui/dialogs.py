"""Modal dialogs used by the editor."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from ..model import slugify
from .. import __version__


class NewSubmenuDialog(QtWidgets.QDialog):
    """Prompt for a new submenu's title and backing file name."""

    def __init__(self, parent=None, existing_names: Optional[List[str]] = None):
        super().__init__(parent)
        self.setWindowTitle("New Submenu")
        self.setMinimumWidth(420)
        self._existing = set(existing_names or [])

        form = QtWidgets.QFormLayout(self)

        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("e.g. Vacuum System")
        form.addRow("Submenu title:", self.title_edit)

        self.file_edit = QtWidgets.QLineEdit()
        form.addRow("File name:", self.file_edit)

        self.hint = QtWidgets.QLabel("")
        self.hint.setStyleSheet("color: #b3261e; font-size: 11px;")
        self.hint.setVisible(False)
        form.addRow("", self.hint)

        self._file_edited_manually = False
        self.file_edit.textEdited.connect(lambda: setattr(self, "_file_edited_manually", True))
        self.title_edit.textChanged.connect(self._sync_file_name)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._buttons = buttons
        self.title_edit.setFocus()

    def _sync_file_name(self, text: str) -> None:
        if not self._file_edited_manually:
            self.file_edit.setText(slugify(text) + ".json" if text.strip() else "")

    def _on_accept(self) -> None:
        if not self.title_edit.text().strip():
            self.hint.setText("Please enter a title.")
            self.hint.setVisible(True)
            return
        if not self.file_edit.text().strip():
            self.hint.setText("Please enter a file name.")
            self.hint.setVisible(True)
            return
        file_name = self.file_edit.text().strip()
        if not file_name.endswith(".json"):
            file_name += ".json"
        if file_name in self._existing:
            self.hint.setText(f'"{file_name}" already exists in this folder.')
            self.hint.setVisible(True)
            return
        self.accept()

    def values(self) -> Tuple[str, str]:
        file_name = self.file_edit.text().strip()
        if not file_name.endswith(".json"):
            file_name += ".json"
        return self.title_edit.text().strip(), file_name


class DeleteSubmenuDialog(QtWidgets.QDialog):
    """Confirm removing a submenu link, optionally deleting the file too."""

    def __init__(
        self,
        parent,
        submenu_title: str,
        file_path: str,
        other_references: List[str],
    ):
        super().__init__(parent)
        self.setWindowTitle("Delete Submenu")
        layout = QtWidgets.QVBoxLayout(self)

        msg = f'Remove the link to submenu "{submenu_title}"\n({file_path})?'
        layout.addWidget(QtWidgets.QLabel(msg))

        self.delete_file_checkbox = QtWidgets.QCheckBox("Also delete the underlying JSON file")
        layout.addWidget(self.delete_file_checkbox)

        if other_references:
            warn = QtWidgets.QLabel(
                "⚠ This file is still referenced from:\n"
                + "\n".join(f"  • {r}" for r in other_references)
                + "\n\nDeleting it will break those menus too."
            )
            warn.setStyleSheet("color: #b3261e;")
            layout.addWidget(warn)
        else:
            self.delete_file_checkbox.setChecked(False)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def delete_file(self) -> bool:
        return self.delete_file_checkbox.isChecked()


class PasswordDialog(QtWidgets.QDialog):
    """Set or clear the MD5-hashed password guarding a menu."""

    def __init__(self, parent, currently_protected: bool):
        super().__init__(parent)
        self.setWindowTitle("Menu Password")
        self.setMinimumWidth(400)
        layout = QtWidgets.QVBoxLayout(self)

        note = QtWidgets.QLabel(
            "This stores an MD5 hash in the JSON file, matching "
            "epics_launcher-protect. It deters casual use, not a security "
            "control."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(note)

        form = QtWidgets.QFormLayout()
        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow("New password:", self.password_edit)
        layout.addLayout(form)

        self.clear_checkbox = QtWidgets.QCheckBox("Remove password protection")
        self.clear_checkbox.setChecked(False)
        self.clear_checkbox.setEnabled(currently_protected)
        self.clear_checkbox.toggled.connect(
            lambda checked: self.password_edit.setEnabled(not checked)
        )
        layout.addWidget(self.clear_checkbox)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.password_edit.setFocus()

    def result_password(self) -> Optional[str]:
        """None means "no change requested"; "" means clear it."""
        if self.clear_checkbox.isChecked():
            return ""
        text = self.password_edit.text()
        return text or None


class MenuSettingsDialog(QtWidgets.QDialog):
    """Edit menu-title, file-choice entries, and password state."""

    def __init__(self, parent, doc):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Menu Settings")
        self.resize(480, 380)
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.title_edit = QtWidgets.QLineEdit(doc.title_text)
        form.addRow("Menu title:", self.title_edit)
        self.style_edit = QtWidgets.QLineEdit(doc.data.get("menu-title", {}).get("style", ""))
        form.addRow("Title style (QSS):", self.style_edit)
        self.theme_edit = QtWidgets.QLineEdit(doc.data.get("menu-title", {}).get("theme", ""))
        form.addRow("Title theme:", self.theme_edit)
        layout.addLayout(form)

        layout.addWidget(QtWidgets.QLabel("View switcher (file-choice):"))
        self.choice_table = QtWidgets.QTableWidget(0, 2)
        self.choice_table.setHorizontalHeaderLabels(["Text", "File"])
        self.choice_table.horizontalHeader().setStretchLastSection(True)
        for choice in doc.file_choices:
            self._add_choice_row(choice.get("text", ""), choice.get("file", ""))
        layout.addWidget(self.choice_table)

        row_buttons = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add view")
        add_btn.clicked.connect(lambda: self._add_choice_row("", ""))
        remove_btn = QtWidgets.QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_selected_choice)
        row_buttons.addWidget(add_btn)
        row_buttons.addWidget(remove_btn)
        row_buttons.addStretch(1)
        layout.addLayout(row_buttons)

        pw_status = "protected" if doc.has_password() else "not protected"
        layout.addWidget(QtWidgets.QLabel(f"Password: {pw_status} (use Tools → Set Password to change)"))

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _add_choice_row(self, text: str, file: str) -> None:
        row = self.choice_table.rowCount()
        self.choice_table.insertRow(row)
        self.choice_table.setItem(row, 0, QtWidgets.QTableWidgetItem(text))
        self.choice_table.setItem(row, 1, QtWidgets.QTableWidgetItem(file))

    def _remove_selected_choice(self) -> None:
        rows = sorted({idx.row() for idx in self.choice_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.choice_table.removeRow(row)

    def apply(self) -> None:
        self.doc.set_title(
            self.title_edit.text().strip(),
            style=self.style_edit.text().strip() or None,
            theme=self.theme_edit.text().strip() or None,
        )
        choices = []
        for row in range(self.choice_table.rowCount()):
            text_item = self.choice_table.item(row, 0)
            file_item = self.choice_table.item(row, 1)
            text = text_item.text().strip() if text_item else ""
            file_name = file_item.text().strip() if file_item else ""
            if text and file_name:
                choices.append({"text": text, "file": file_name})
        self.doc.set_file_choices(choices)


class RemoteConnectDialog(QtWidgets.QDialog):
    """Collect SSH/SFTP connection details for remote editing."""

    def __init__(self, parent=None, default_host: str = "", default_path: str = "", default_user: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Open Remote Configuration (SSH)")
        self.setMinimumWidth(460)
        form = QtWidgets.QFormLayout(self)

        self.host_edit = QtWidgets.QLineEdit(default_host)
        form.addRow("Host:", self.host_edit)

        self.user_edit = QtWidgets.QLineEdit(default_user or "")
        self.user_edit.setPlaceholderText("(default: current user / SSH config)")
        form.addRow("Username:", self.user_edit)

        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.password_edit.setPlaceholderText("(leave blank to use SSH keys/agent)")
        form.addRow("Password:", self.password_edit)

        self.path_edit = QtWidgets.QLineEdit(default_path)
        form.addRow("Root config file or folder:", self.path_edit)

        note = QtWidgets.QLabel(
            "Uses your local SSH keys / agent by default, same as running "
            "'ssh <host>' from a terminal."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 11px;")
        form.addRow(note)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> Dict[str, str]:
        return {
            "host": self.host_edit.text().strip(),
            "username": self.user_edit.text().strip() or None,
            "password": self.password_edit.text() or None,
            "path": self.path_edit.text().strip(),
        }


class GitOpenDialog(QtWidgets.QDialog):
    """Repository URL, optional branch, and the local folder to clone into."""

    def __init__(self, parent, known_urls: List[str], default_checkout, initial_url: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Open Git Repository")
        self.setMinimumWidth(560)
        self._default_checkout = default_checkout
        self._folder_edited = False
        form = QtWidgets.QFormLayout(self)

        self.url_combo = QtWidgets.QComboBox()
        self.url_combo.setEditable(True)
        self.url_combo.addItems(known_urls)
        self.url_combo.setCurrentText(initial_url or (known_urls[0] if known_urls else ""))
        self.url_combo.lineEdit().setPlaceholderText("git@host:group/repo.git  or  https://host/group/repo.git")
        form.addRow("Repository URL:", self.url_combo)

        self.branch_edit = QtWidgets.QLineEdit()
        self.branch_edit.setPlaceholderText("(default branch)")
        form.addRow("Branch:", self.branch_edit)

        folder_row = QtWidgets.QHBoxLayout()
        self.folder_edit = QtWidgets.QLineEdit()
        self.folder_edit.textEdited.connect(self._mark_folder_edited)
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder_edit, 1)
        folder_row.addWidget(browse)
        form.addRow("Local folder:", folder_row)

        note = QtWidgets.QLabel(
            "The repository is cloned into the local folder the first time and "
            "updated (fast-forward) each time you open it. You edit the local copy; "
            "Git → Publish… pushes your changes back. SSH URLs use your SSH key; "
            "https URLs need stored credentials (the editor never asks for a password)."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #6b7280; font-size: 11px;")
        form.addRow(note)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        buttons.addButton("Open", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self.url_combo.currentTextChanged.connect(self._url_changed)
        self._url_changed(self.url_combo.currentText())

    def _mark_folder_edited(self, _text: str) -> None:
        self._folder_edited = True

    def _url_changed(self, url: str) -> None:
        if not self._folder_edited:
            self.folder_edit.setText(self._default_checkout(url.strip()) if url.strip() else "")

    def _browse(self) -> None:
        start = self.folder_edit.text() or ""
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Local Folder for the Clone", start)
        if directory:
            self.folder_edit.setText(directory)
            self._folder_edited = True

    def _accept(self) -> None:
        if not self.url_combo.currentText().strip() or not self.folder_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "Open Git Repository", "Please enter a repository URL and a local folder.")
            return
        self.accept()

    def values(self) -> Tuple[str, str, str]:
        return (
            self.url_combo.currentText().strip(),
            self.branch_edit.text().strip(),
            self.folder_edit.text().strip(),
        )


class NewCustomTypeDialog(QtWidgets.QDialog):
    """Define a brand-new, reusable custom command type in the mapping file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Custom Command Type")
        self.resize(480, 320)
        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("e.g. my-tool")
        form.addRow("Type name:", self.name_edit)

        self.command_edit = QtWidgets.QLineEdit()
        self.command_edit.setPlaceholderText("my-awesome-program {arg1} {arg2}")
        form.addRow("Command template:", self.command_edit)

        self.flags_edit = QtWidgets.QLineEdit()
        self.flags_edit.setPlaceholderText("arg1=--option, arg2=--macro  (optional)")
        form.addRow("Argument flags:", self.flags_edit)
        layout.addLayout(form)

        help_label = QtWidgets.QLabel(
            "Every {argname} in the command template becomes an editable "
            "field on items of this type. Argument flags prefix the "
            "argument's value on the command line, e.g. arg1=--option "
            "produces '--option <value>'."
        )
        help_label.setWordWrap(True)
        help_label.setStyleSheet("color: #6b7280; font-size: 11px;")
        layout.addWidget(help_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> Tuple[str, str, Dict[str, str]]:
        name = self.name_edit.text().strip()
        command = self.command_edit.text().strip()
        arg_flags = {}
        raw = self.flags_edit.text().strip()
        if raw:
            for pair in raw.split(","):
                if "=" in pair:
                    key, val = pair.split("=", 1)
                    arg_flags[key.strip()] = val.strip()
        return name, command, arg_flags


class PublishDialog(QtWidgets.QDialog):
    """Review staged changes and enter the commit message before publishing."""

    def __init__(self, parent, root: str, files: List[str], diff: str, ahead: int, note: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Publish Changes")
        self.resize(820, 620)
        layout = QtWidgets.QVBoxLayout(self)

        if files:
            head = f"<b>{len(files)} changed file(s)</b> in {root}:<br>" + "<br>".join(files)
        else:
            head = f"No new changes in {root}."
        if ahead:
            head += f"<br><br>{ahead} earlier local commit(s) will be published as well."
        label = QtWidgets.QLabel(head)
        label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        label.setWordWrap(True)
        layout.addWidget(label)

        self.diff_view = QtWidgets.QPlainTextEdit(diff)
        self.diff_view.setReadOnly(True)
        self.diff_view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.diff_view.setFont(QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont))
        layout.addWidget(self.diff_view, 1)

        form = QtWidgets.QFormLayout()
        self.message_edit = QtWidgets.QLineEdit()
        self.message_edit.setPlaceholderText("e.g. Add chiller panel to Components")
        self.message_edit.setEnabled(bool(files))
        form.addRow("What did you change?", self.message_edit)
        layout.addLayout(form)

        if note:
            note_label = QtWidgets.QLabel(note)
            note_label.setWordWrap(True)
            layout.addWidget(note_label)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
        self.publish_button = buttons.addButton("Publish", QtWidgets.QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._needs_message = bool(files)

    def _accept(self) -> None:
        if self._needs_message and not self.message().strip():
            QtWidgets.QMessageBox.warning(self, "Publish", "Please describe the change in a few words.")
            return
        self.accept()

    def message(self) -> str:
        return self.message_edit.text()


def confirm(parent, title: str, text: str) -> bool:
    result = QtWidgets.QMessageBox.question(
        parent, title, text, QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
    )
    return result == QtWidgets.QMessageBox.Yes


def show_about(parent) -> None:
    QtWidgets.QMessageBox.about(
        parent,
        "About Launcher Editor",
        f"<h3>Launcher Config Editor</h3>"
        f"<p>Version {__version__}</p>"
        "<p>A GUI editor for <b>epics_launcher</b> menu configuration files "
        "(<a href='https://gitea.psi.ch/augustin_s/epics_launcher'>"
        "gitea.psi.ch/augustin_s/epics_launcher</a>). Files it writes are "
        "plain JSON and load unchanged in the original launcher.</p>",
    )
