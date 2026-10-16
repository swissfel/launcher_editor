"""Where a configuration comes from, the "recent" list, and git checkouts.

No GUI dependency (tested in tests/test_sources.py). Three kinds of source:

- ``local``: a menu file on this machine.
- ``ssh``: a menu file on another host, opened over SFTP (host, user, path;
  never a password).
- ``git``: a menu file in a git repository that the editor clones into a
  local folder, edits there and publishes back with the Git menu.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from .backends import BackendError, LocalBackend

MAX_RECENT = 12


@dataclass
class Source:
    kind: str  # "local" | "ssh" | "git"
    path: str = ""  # local/ssh: absolute file path; git: root file relative to the checkout
    host: str = ""
    user: str = ""
    url: str = ""  # git remote URL
    branch: str = ""
    checkout: str = ""  # git: local folder the repository is cloned into
    extra: dict = field(default_factory=dict)

    def key(self) -> Tuple:
        """Identity for de-duplicating the recent list."""
        if self.kind == "git":
            return ("git", self.url, self.branch, self.checkout, self.path)
        if self.kind == "ssh":
            return ("ssh", self.host, self.user, self.path)
        return ("local", self.path)

    def label(self) -> str:
        if self.kind == "git":
            branch = f" [{self.branch}]" if self.branch else ""
            return f"{self.path} — git {self.url}{branch}"
        if self.kind == "ssh":
            who = f"{self.user}@" if self.user else ""
            return f"{os.path.basename(self.path)} — {who}{self.host}:{os.path.dirname(self.path)}"
        return f"{os.path.basename(self.path)} — {os.path.dirname(self.path)}"

    def local_file(self) -> Optional[str]:
        """The file to open on this machine (git: inside the checkout)."""
        if self.kind == "git":
            return os.path.join(self.checkout, self.path)
        if self.kind == "local":
            return self.path
        return None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v}

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class RecentList:
    """Most recently opened sources, newest first, stored as a JSON string."""

    def __init__(self, entries: Optional[List[Source]] = None, limit: int = MAX_RECENT):
        self.entries: List[Source] = list(entries or [])
        self.limit = limit

    def add(self, source: Source) -> None:
        self.entries = [e for e in self.entries if e.key() != source.key()]
        self.entries.insert(0, source)
        del self.entries[self.limit :]

    def remove(self, source: Source) -> None:
        self.entries = [e for e in self.entries if e.key() != source.key()]

    def clear(self) -> None:
        self.entries = []

    def git_urls(self) -> List[str]:
        seen: List[str] = []
        for e in self.entries:
            if e.kind == "git" and e.url not in seen:
                seen.append(e.url)
        return seen

    def last_for_url(self, url: str) -> Optional[Source]:
        for e in self.entries:
            if e.kind == "git" and e.url == url:
                return e
        return None

    def to_json(self) -> str:
        return json.dumps([e.to_dict() for e in self.entries])

    @classmethod
    def from_json(cls, text: Optional[str], limit: int = MAX_RECENT) -> "RecentList":
        try:
            raw = json.loads(text) if text else []
            entries = [Source.from_dict(d) for d in raw if isinstance(d, dict) and d.get("kind")]
        except (ValueError, TypeError):
            entries = []
        return cls(entries, limit)


# -- git checkouts --------------------------------------------------------
def repo_name(url: str) -> str:
    """Folder-friendly name of a repository URL (".../sf_bernina_launcher.git" -> "sf_bernina_launcher")."""
    tail = re.split(r"[/:]", url.rstrip("/"))[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tail) or "repository"


def default_checkout(url: str, base: Optional[str] = None) -> str:
    base = base or os.path.join(os.path.expanduser("~"), "launcher-editor")
    return os.path.join(base, repo_name(url))


class CheckoutError(Exception):
    """Cloning failed; the message is meant for the user."""


def clone_or_update(url: str, checkout: str, branch: str = "") -> str:
    """Make ``checkout`` a working copy of ``url`` that is as up to date as possible.

    First time: clone. Afterwards: ``pull --ff-only``. A failing update
    (no connection, local commits, ...) is not fatal: the existing copy is
    still usable, so the returned message just says so. Returns a short
    status message; raises CheckoutError if there is no usable copy.
    """
    backend = LocalBackend()
    checkout = os.path.abspath(os.path.expanduser(checkout))
    if os.path.isdir(os.path.join(checkout, ".git")):
        try:
            origin = backend.run_git(checkout, ["remote", "get-url", "origin"]).strip()
        except BackendError:
            origin = ""
        if origin and origin != url:
            raise CheckoutError(
                f"{checkout} is already a clone of a different repository:\n{origin}\n\n"
                "Choose another local folder."
            )
        if branch:
            try:
                current = backend.run_git(checkout, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
            except BackendError:
                current = ""
            if current != branch:
                try:
                    backend.run_git(checkout, ["checkout", "-q", branch])
                except BackendError as exc:
                    return f"Could not switch {checkout} to branch {branch}; it stays on {current}.\n\n{exc}"
        try:
            out = backend.run_git(checkout, ["pull", "--ff-only"], timeout=120)
            return out.strip().splitlines()[-1] if out.strip() else "Already up to date."
        except BackendError as exc:
            return (
                f"Could not update {checkout} (unpublished commits, local changes in the "
                f"way, or no connection). Opening it as it is.\n\n{exc}"
            )

    if os.path.exists(checkout) and os.listdir(checkout):
        raise CheckoutError(f"{checkout} exists and is not empty, so it can't be cloned into.")
    parent = os.path.dirname(checkout)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise CheckoutError(str(exc))
    args = ["clone", "-q"] + (["--branch", branch] if branch else []) + [url, checkout]
    try:
        backend.run_git(parent, args, timeout=300)
    except BackendError as exc:
        raise CheckoutError(
            f"Could not clone {url}:\n\n{exc}\n\n"
            "For SSH URLs (git@host:...) your SSH key must be available; "
            "for https URLs, credentials must be stored (the editor never asks for a password)."
        )
    return f"Cloned {url} into {checkout}."


def menu_files(checkout: str) -> List[str]:
    """Candidate root menu files (``*.json``) in the checkout, relative paths, top level first."""
    found: List[str] = []
    for dirpath, dirnames, filenames in os.walk(checkout):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        rel_dir = os.path.relpath(dirpath, checkout)
        depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1
        if depth > 2:
            dirnames[:] = []
            continue
        for name in sorted(filenames):
            if name.endswith(".json"):
                found.append(name if rel_dir == "." else os.path.join(rel_dir, name))
    return sorted(found, key=lambda p: (p.count(os.sep), p))
