"""Tracks all open MenuDocuments for a session and manages submenu files.

A "workspace" is the set of menu JSON files opened from one backend during
an editing session. It provides the operations that touch more than one
file at a time: creating a new linked submenu, and safely deleting one
(checking whether other known menus still reference it before removing the
file itself).
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .backends import Backend, BackendError
from .model import MenuDocument, slugify


class Workspace:
    def __init__(self, backend: Backend):
        self.backend = backend
        # path -> MenuDocument, for every file opened in this session
        self.documents: Dict[str, MenuDocument] = {}

    def open(self, path: str) -> MenuDocument:
        if path in self.documents:
            return self.documents[path]
        doc = MenuDocument.load(self.backend, path)
        self.documents[path] = doc
        return doc

    def register(self, doc: MenuDocument) -> None:
        self.documents[doc.path] = doc

    def close(self, path: str) -> None:
        self.documents.pop(path, None)

    def new_submenu(
        self, parent_doc: MenuDocument, title: str, file_name: Optional[str] = None
    ) -> Tuple[MenuDocument, str]:
        """Create a new, empty submenu JSON file next to ``parent_doc``.

        Returns the new document and the (relative) file name that should be
        used for the ``file`` field of the linking item. Does *not* insert
        the linking item itself - callers do that via
        ``MenuDocument.add_item``.
        """

        if not file_name:
            file_name = slugify(title) + ".json"
        if not file_name.endswith(".json"):
            file_name += ".json"

        base_dir = self.backend.dirname(parent_doc.path)
        full_path = self.backend.join(base_dir, file_name)

        if self.backend.exists(full_path):
            raise FileExistsError(f'"{file_name}" already exists in this menu\'s folder')

        new_doc = MenuDocument.create_new(self.backend, full_path, title)
        new_doc.save(make_backup=False)
        self.register(new_doc)
        return new_doc, file_name

    def references_to(self, target_path: str) -> List[Tuple[MenuDocument, int]]:
        """Find (document, item_index) pairs referencing ``target_path``.

        Only considers documents already open in this workspace (best
        effort - a full repository-wide scan would require walking the
        remote directory tree, which callers may do separately via
        :meth:`scan_directory_for_references`).
        """

        results = []
        for doc in self.documents.values():
            for i, item in enumerate(doc.items):
                if item.get("type") == "menu":
                    if doc.resolve_submenu_path(item) == target_path:
                        results.append((doc, i))
        return results

    def scan_directory_for_references(self, directory: str, target_path: str) -> List[str]:
        """Best-effort scan of every *.json file in ``directory`` for a
        ``"file"`` reference resolving to ``target_path``. Returns a list of
        file paths that reference it, ignoring files that fail to parse.
        """

        import json

        hits = []
        try:
            names = self.backend.listdir(directory)
        except BackendError:
            return hits
        for name in names:
            if not name.endswith(".json"):
                continue
            path = self.backend.join(directory, name)
            if path == target_path:
                continue
            try:
                text = self.backend.read_text(path)
                data = json.loads(text)
            except Exception:
                continue
            for item in data.get("menu", []):
                if isinstance(item, dict) and item.get("type") == "menu":
                    file_name = (item.get("file") or "").strip()
                    if not file_name:
                        continue
                    resolved = self.backend.join(directory, file_name)
                    if resolved == target_path:
                        hits.append(path)
                        break
        return hits

    def delete_submenu_file(self, path: str) -> None:
        self.backend.remove(path)
        self.close(path)
