"""Application entry point: ``launcher-editor`` console script."""

from __future__ import annotations

import argparse
import os
import sys

from PyQt5 import QtWidgets

from ..backends import LocalBackend
from .main_window import MainWindow


def _load_stylesheet() -> str:
    style_path = os.path.join(os.path.dirname(__file__), "style.qss")
    try:
        with open(style_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="launcher-editor",
        description="GUI editor for epics_launcher menu configuration files.",
    )
    parser.add_argument(
        "configuration",
        nargs="?",
        help="Root menu JSON file to open immediately (local path).",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Open for viewing only: saving, publishing and editing are disabled.",
    )
    parser.add_argument(
        "--preview-command",
        default="epics_launcher",
        metavar="CMD",
        help='Command for Preview; the root menu file is appended (default: "epics_launcher").',
    )
    parser.add_argument(
        "--publish-note",
        default="",
        metavar="TEXT",
        help="Extra text shown in the Publish dialog and after publishing "
        "(e.g. what happens once the change is pushed).",
    )
    args = parser.parse_args(argv)

    app = QtWidgets.QApplication(sys.argv[:1])
    app.setApplicationName("Launcher Config Editor")
    app.setStyleSheet(_load_stylesheet())

    window = MainWindow(
        read_only=args.read_only,
        preview_command=args.preview_command,
        publish_note=args.publish_note,
    )
    window.show()

    if args.configuration:
        path = os.path.abspath(args.configuration)
        window._switch_backend_and_open(LocalBackend(), path)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
