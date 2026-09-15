"""Core data model for editing epics_launcher menu configuration files.

This module is intentionally free of any GUI toolkit dependency so it can be
unit tested in isolation and reused by any front-end. It mirrors the JSON
format read by ``epics_launcher.launcher_model`` (see the upstream project at
https://gitea.psi.ch/augustin_s/epics_launcher) closely enough that anything
written here loads back into the original launcher unchanged.

Top level menu document keys (all optional except ``menu``):

    menu-title:   {"text": ..., "style": ..., "theme": ...}
    file-choice:  [{"text": ..., "file": ...}, ...]
    menu:         [ <item>, ... ]
    password:     "<md5 hex digest>"
    flags:        {...}                 (root menu only, opaque passthrough)

Item ``type`` is either one of the built-in structural types (``separator``,
``title``, ``menu``) or a custom type defined in a *mapping* file (``cmd``,
``caqtdm``, ``medm``, ``pep``, or any site-specific type).
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from .backends import Backend, BackendError

BUILTIN_STRUCTURAL_TYPES = ("separator", "title", "menu")

# Preferred key order used when serializing, purely cosmetic (JSON key order
# is not semantically meaningful to the parser, but a stable, readable order
# keeps diffs small across repeated saves).
_DOC_KEY_ORDER = ["menu-title", "file-choice", "menu", "password", "flags"]
_ITEM_KEY_ORDER = [
    "type",
    "text",
    "file",
    "command",
    "panel",
    "macros",
    "param",
    "configuration",
    "arg1",
    "arg2",
    "tip",
    "help-link",
    "style",
    "theme",
]
_TITLE_KEY_ORDER = ["text", "style", "theme"]

# Fields every item may optionally carry, regardless of type.
COMMON_OPTIONAL_FIELDS = ("tip", "help-link", "style", "theme")

# Bundled fallback mapping, mirroring epics_launcher's own default mapping
# file, used when no site mapping file is loaded yet so the "new entry"
# gallery is never empty.
DEFAULT_MAPPING: Dict[str, Any] = {
    "Linux": {
        "theme_base": "../themes/",
        "cmd": {"command": "{command}"},
        "caqtdm": {
            "command": "caqtdm {param} \"{macros}\" {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "medm": {
            "command": "medm -x {param} {macros} {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "pep": {
            "command": "bash -c \"pep {param} {panel}\"",
            "arg_flags": {"panel": "-f"},
        },
    },
    "Windows": {
        "theme_base": "../themes/",
        "cmd": {"command": "{command}"},
        "caqtdm": {
            "command": "caqtdm {param} {macros} {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "medm": {
            "command": "medm -x {param} {macros} {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "pep": {
            "command": "cmd /c \"pep {param} {panel}\"",
            "arg_flags": {"panel": "-f"},
        },
    },
    "OS_X": {
        "theme_base": "../themes/",
        "cmd": {"command": "{command}"},
        "caqtdm": {
            "command": "caqtdm {param} {macros} {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "medm": {
            "command": "medm -x {param} {macros} {panel}",
            "arg_flags": {"macros": "-macro"},
        },
        "pep": {
            "command": "bash -c \"pep {param} {panel}\"",
            "arg_flags": {"panel": "-f"},
        },
    },
}


def hash_password(password: str) -> str:
    """MD5 hash a password exactly the way epics_launcher-protect does."""
    m = hashlib.md5()
    m.update(password.encode())
    return m.hexdigest()


def _reorder(d: Dict[str, Any], key_order: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key in key_order:
        if key in d:
            out[key] = d[key]
    for key, value in d.items():
        if key not in out:
            out[key] = value
    return out


def slugify(text: str) -> str:
    """Turn a menu title into a reasonable JSON file base name."""
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = text.strip("_")
    return text or "menu"


# ---------------------------------------------------------------------------
# Mapping (custom type definitions)
# ---------------------------------------------------------------------------


class MappingFile:
    """Wraps a launcher mapping file (per-OS custom type definitions)."""

    def __init__(self, backend: Optional[Backend], path: Optional[str], data: Dict[str, Any]):
        self.backend = backend
        self.path = path
        self.data = data
        self.dirty = False

    @classmethod
    def load(cls, backend: Backend, path: str) -> "MappingFile":
        text = backend.read_text(path)
        data = json.loads(text)
        return cls(backend, path, data)

    @classmethod
    def default(cls) -> "MappingFile":
        return cls(None, None, copy.deepcopy(DEFAULT_MAPPING))

    def operating_systems(self) -> List[str]:
        return [k for k in self.data.keys()]

    def types_for_os(self, os_name: str) -> Dict[str, Any]:
        section = self.data.get(os_name, {})
        return {k: v for k, v in section.items() if k != "theme_base"}

    def fields_for_type(self, os_name: str, type_name: str) -> List[str]:
        cfg = self.data.get(os_name, {}).get(type_name)
        if not cfg:
            return []
        command = cfg.get("command", "")
        # preserve first-occurrence order, de-duplicated
        seen: List[str] = []
        for m in re.finditer(r"{(\w+)}", command):
            name = m.group(1)
            if name not in seen and name != "configuration":
                seen.append(name)
        return seen

    def add_or_update_type(
        self,
        type_name: str,
        command: str,
        arg_flags: Optional[Dict[str, str]] = None,
        os_names: Optional[List[str]] = None,
    ) -> None:
        os_names = os_names or self.operating_systems() or ["Linux", "Windows", "OS_X"]
        for os_name in os_names:
            section = self.data.setdefault(os_name, {})
            entry: Dict[str, Any] = {"command": command}
            if arg_flags:
                entry["arg_flags"] = arg_flags
            section[type_name] = entry
        self.dirty = True

    def remove_type(self, type_name: str) -> None:
        for section in self.data.values():
            if isinstance(section, dict):
                section.pop(type_name, None)
        self.dirty = True

    def to_text(self) -> str:
        return json.dumps(self.data, indent=4, ensure_ascii=False) + "\n"

    def save(self, make_backup: bool = True) -> None:
        if self.backend is None or self.path is None:
            raise BackendError("Mapping file has no associated path/backend")
        text = self.to_text()
        if make_backup and self.backend.exists(self.path):
            try:
                original = self.backend.read_text(self.path)
                self.backend.write_text(self.path + ".bak", original)
            except BackendError:
                pass
        self.backend.write_text(self.path, text)
        self.dirty = False


# ---------------------------------------------------------------------------
# Menu item helpers
# ---------------------------------------------------------------------------


def default_item_for_type(
    type_name: str, mapping: Optional[MappingFile] = None, os_name: str = "Linux"
) -> Dict[str, Any]:
    """Build a starter item dict for a freshly inserted template."""

    if type_name == "separator":
        return {"type": "separator"}
    if type_name == "title":
        return {"type": "title", "text": "New Title"}
    if type_name == "menu":
        return {"type": "menu", "text": "New submenu", "file": ""}

    item: Dict[str, Any] = {"type": type_name, "text": f"New {type_name}"}
    if mapping is not None:
        for field_name in mapping.fields_for_type(os_name, type_name):
            item[field_name] = ""
    elif type_name == "cmd":
        item["command"] = ""
    return item


def item_label(item: Dict[str, Any]) -> str:
    t = item.get("type", "")
    if t == "separator":
        return "──────── separator ────────"
    return item.get("text") or f"(untitled {t})"


def clean_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Drop empty optional fields and apply a stable, readable key order."""

    cleaned = {}
    for key, value in item.items():
        if key in COMMON_OPTIONAL_FIELDS and (value is None or value == ""):
            continue
        if value is None:
            continue
        cleaned[key] = value
    return _reorder(cleaned, _ITEM_KEY_ORDER)


def validate_item(item: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable problems with an item, if any."""

    problems = []
    t = item.get("type", "")
    if not t:
        problems.append("Item has no type")
        return problems
    if t == "title" and not item.get("text"):
        problems.append('"title" items require text')
    if t == "menu":
        if not item.get("text"):
            problems.append('Submenu items require text')
        if not item.get("file"):
            problems.append('Submenu items require a linked file')
    if t == "cmd" and not item.get("command"):
        problems.append('Command items require a "command"')
    return problems


# ---------------------------------------------------------------------------
# Menu document
# ---------------------------------------------------------------------------


class MenuDocument:
    """A single menu JSON file, loaded, edited and saved through a backend."""

    def __init__(self, backend: Backend, path: str, data: Optional[Dict[str, Any]] = None):
        self.backend = backend
        self.path = path
        self.data: Dict[str, Any] = data if data is not None else {"menu-title": {}, "menu": []}
        self.dirty = False
        self._loaded_text: Optional[str] = None

    # -- loading / creating ------------------------------------------------
    @classmethod
    def load(cls, backend: Backend, path: str) -> "MenuDocument":
        text = backend.read_text(path)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise BackendError(f"{path}: invalid JSON ({exc})") from exc
        doc = cls(backend, path, data)
        doc._loaded_text = text
        return doc

    @classmethod
    def create_new(cls, backend: Backend, path: str, title: str) -> "MenuDocument":
        data = {"menu-title": {"text": title}, "menu": []}
        doc = cls(backend, path, data)
        doc.dirty = True
        return doc

    # -- basic accessors -----------------------------------------------
    @property
    def items(self) -> List[Dict[str, Any]]:
        return self.data.setdefault("menu", [])

    @property
    def title_text(self) -> str:
        return self.data.get("menu-title", {}).get("text", "")

    def set_title(
        self, text: str, style: Optional[str] = None, theme: Optional[str] = None
    ) -> None:
        title = {"text": text}
        if style:
            title["style"] = style
        if theme:
            title["theme"] = theme
        self.data["menu-title"] = _reorder(title, _TITLE_KEY_ORDER)
        self.mark_dirty()

    @property
    def file_choices(self) -> List[Dict[str, Any]]:
        return self.data.setdefault("file-choice", [])

    def set_file_choices(self, choices: List[Dict[str, Any]]) -> None:
        if choices:
            self.data["file-choice"] = choices
        else:
            self.data.pop("file-choice", None)
        self.mark_dirty()

    def has_password(self) -> bool:
        return bool(self.data.get("password"))

    def set_password(self, password: Optional[str]) -> None:
        if password:
            self.data["password"] = hash_password(password)
        else:
            self.data.pop("password", None)
        self.mark_dirty()

    # -- item CRUD --------------------------------------------------------
    def add_item(self, item: Dict[str, Any], index: Optional[int] = None) -> int:
        items = self.items
        if index is None:
            index = len(items)
        index = max(0, min(index, len(items)))
        items.insert(index, clean_item(item))
        self.mark_dirty()
        return index

    def remove_item(self, index: int) -> Dict[str, Any]:
        items = self.items
        removed = items.pop(index)
        self.mark_dirty()
        return removed

    def move_item(self, from_index: int, to_index: int) -> None:
        items = self.items
        if from_index == to_index:
            return
        item = items.pop(from_index)
        if to_index > from_index:
            to_index -= 1
        items.insert(to_index, item)
        self.mark_dirty()

    def duplicate_item(self, index: int) -> int:
        items = self.items
        new_item = copy.deepcopy(items[index])
        items.insert(index + 1, new_item)
        self.mark_dirty()
        return index + 1

    def update_item(self, index: int, **fields: Any) -> None:
        # Mutates the item dict in place (clear+update rather than replacing
        # the list entry) so that any external references to this exact
        # dict object - e.g. cached by a list widget row or a properties
        # panel - keep seeing live data instead of a stale copy.
        item = self.items[index]
        for key, value in fields.items():
            if value is None or value == "":
                item.pop(key, None)
            else:
                item[key] = value
        cleaned = clean_item(item)
        item.clear()
        item.update(cleaned)
        self.mark_dirty()

    def set_item_text(self, index: int, text: str) -> None:
        self.update_item(index, text=text)

    # -- dirty tracking / persistence --------------------------------------
    def mark_dirty(self) -> None:
        self.dirty = True

    def to_text(self) -> str:
        data = dict(self.data)
        data["menu"] = [clean_item(i) for i in self.items]
        ordered = _reorder(data, _DOC_KEY_ORDER)
        return json.dumps(ordered, indent=2, ensure_ascii=False) + "\n"

    def save(self, make_backup: bool = True) -> None:
        text = self.to_text()
        if make_backup and self.backend.exists(self.path):
            try:
                original = self.backend.read_text(self.path)
                if original != text:
                    self.backend.write_text(self.path + ".bak", original)
            except BackendError:
                pass
        self.backend.write_text(self.path, text)
        self._loaded_text = text
        self.dirty = False

    def resolve_submenu_path(self, item: Dict[str, Any]) -> str:
        file_name = (item.get("file") or "").strip()
        base_dir = self.backend.dirname(self.path)
        return self.backend.join(base_dir, file_name)

    def validate(self) -> List[str]:
        problems = []
        for i, item in enumerate(self.items):
            for msg in validate_item(item):
                problems.append(f"Item {i + 1} ({item_label(item)}): {msg}")
        return problems


# ---------------------------------------------------------------------------
# Clipboard payload (de)serialization - used by the GUI clipboard glue, kept
# here so the format itself is unit-testable without a Qt event loop.
# ---------------------------------------------------------------------------

CLIPBOARD_MAGIC = "epics-launcher-editor-items"


def items_to_clipboard_text(items: List[Dict[str, Any]]) -> str:
    payload = {"magic": CLIPBOARD_MAGIC, "items": [clean_item(i) for i in items]}
    return json.dumps(payload, indent=2, ensure_ascii=False)


def items_from_clipboard_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse items previously produced by :func:`items_to_clipboard_text`.

    Also accepts a bare JSON list of items, or a single item object, so that
    hand-copied JSON snippets can be pasted too. Returns ``None`` if ``text``
    isn't recognizable as launcher item(s).
    """

    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if isinstance(data, dict) and data.get("magic") == CLIPBOARD_MAGIC:
        items = data.get("items", [])
    elif isinstance(data, dict) and "type" in data:
        items = [data]
    elif isinstance(data, list):
        items = [d for d in data if isinstance(d, dict)]
    else:
        return None

    if not items:
        return None
    return [clean_item(copy.deepcopy(i)) for i in items]
