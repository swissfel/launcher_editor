"""Git steps behind the editor's "Publish…" command.

No GUI dependency, so the whole flow is unit tested against throwaway
repositories (see tests/test_gitflow.py). Every git call goes through
``Backend.run_git``, so it works the same for local and SSH-backed files.

Publishing means: stage everything in the repository (the menu files you
edited, new submenu files, the mapping file), commit it with your message,
rebase onto whatever others pushed in the meantime, and push. If the rebase
hits a conflict it is aborted again, so the working copy is never left
half-rebased; your commit stays local and the error says what to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .backends import Backend, BackendError

# Editor backups (written next to each file on save) never belong in a commit.
EXCLUDE_PATTERNS = ("*.bak",)


class PublishError(Exception):
    """A publish step failed; the message is meant to be shown to the user."""


@dataclass
class PendingChanges:
    root: str
    status: str  # `git status --short` of the staged changes
    diff: str  # full staged diff, for review
    ahead: int  # local commits not pushed yet (before committing these changes)

    @property
    def has_changes(self) -> bool:
        return bool(self.status.strip())

    @property
    def nothing_to_publish(self) -> bool:
        return not self.has_changes and self.ahead == 0


def repo_root(backend: Backend, directory: str) -> Optional[str]:
    """Top level of the git repository containing ``directory``, or None."""
    try:
        return backend.run_git(directory, ["rev-parse", "--show-toplevel"]).strip() or None
    except BackendError:
        return None


def ensure_excluded(backend: Backend, root: str, patterns=EXCLUDE_PATTERNS) -> None:
    """Add ``patterns`` to the repository's local .git/info/exclude.

    Local-only (never committed), so the shared repository's .gitignore is
    left alone.
    """
    path = backend.run_git(root, ["rev-parse", "--git-path", "info/exclude"]).strip()
    if not path.startswith("/"):
        path = backend.join(root, path)
    existing = backend.read_text(path) if backend.exists(path) else ""
    lines = existing.splitlines()
    missing = [p for p in patterns if p not in lines]
    if missing:
        text = existing + ("" if not existing or existing.endswith("\n") else "\n")
        backend.write_text(path, text + "\n".join(missing) + "\n")


def _ahead(backend: Backend, root: str) -> int:
    try:
        return int(backend.run_git(root, ["rev-list", "--count", "@{u}..HEAD"]).strip() or 0)
    except (BackendError, ValueError):
        return 0


def _rebase_in_progress(backend: Backend, root: str) -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        path = backend.run_git(root, ["rev-parse", "--git-path", name]).strip()
        if not path.startswith("/"):
            path = backend.join(root, path)
        if backend.exists(path):
            return True
    return False


def prepare(backend: Backend, root: str) -> PendingChanges:
    """Stage all changes and return them for review (``unstage`` undoes this)."""
    if _rebase_in_progress(backend, root):
        raise PublishError(
            f"{root} is in the middle of an unfinished git rebase.\n\n"
            "Finish it (git rebase --continue) or abort it (git rebase --abort) first."
        )
    ensure_excluded(backend, root)
    backend.run_git(root, ["add", "-A"])
    status = backend.run_git(root, ["diff", "--cached", "--name-status"])
    diff = backend.run_git(root, ["diff", "--cached"])
    return PendingChanges(root=root, status=status, diff=diff, ahead=_ahead(backend, root))


def unstage(backend: Backend, root: str) -> None:
    try:
        backend.run_git(root, ["reset", "-q"])
    except BackendError:
        pass


def _upstream(backend: Backend, root: str) -> str:
    try:
        return backend.run_git(root, ["rev-parse", "--abbrev-ref", "@{u}"]).strip()
    except BackendError:
        raise PublishError(
            "This branch has no upstream branch to publish to.\n\n"
            "Set one once with: git push -u origin <branch>"
        )


def publish(backend: Backend, root: str, message: str) -> str:
    """Commit staged changes (if any), rebase onto the upstream, push.

    Returns a short summary for the user. Raises PublishError on failure.
    """
    upstream = _upstream(backend, root)
    staged = backend.run_git(root, ["diff", "--cached", "--name-only"]).strip()
    if staged:
        if not message.strip():
            raise PublishError("Please enter a short description of the change.")
        try:
            backend.run_git(root, ["commit", "-q", "-m", message.strip()])
        except BackendError as exc:
            raise PublishError(f"Commit failed:\n\n{exc}")

    try:
        backend.run_git(root, ["pull", "--rebase", "-q"], timeout=120)
    except BackendError as exc:
        if _rebase_in_progress(backend, root):
            try:
                backend.run_git(root, ["rebase", "--abort"])
            except BackendError:
                pass
            raise PublishError(
                "Someone else changed the same part of these files in the meantime, "
                "so your change could not be combined automatically.\n\n"
                "Nothing was published. Your change is saved as a local commit in\n"
                f"{root}\n\n"
                "Resolve it there with git (git pull --rebase, fix the conflict, "
                "git rebase --continue), or ask someone familiar with git.\n\n"
                f"Details:\n{exc}"
            )
        raise PublishError(f"Could not get the latest version from {upstream}:\n\n{exc}")

    try:
        backend.run_git(root, ["push", "-q"], timeout=120)
    except BackendError as exc:
        raise PublishError(
            f"Push to {upstream} failed. Your change is committed locally and can be "
            f"published again later.\n\nDetails:\n{exc}"
        )

    head = backend.run_git(root, ["log", "-1", "--format=%h %s"]).strip()
    return f"Published to {upstream}:\n{head}"


def update(backend: Backend, root: str) -> str:
    """Fast-forward to the upstream branch (no merge commits, no rebase)."""
    try:
        out = backend.run_git(root, ["pull", "--ff-only"], timeout=120)
    except BackendError as exc:
        raise PublishError(
            "Could not update from the remote repository (local commits or changes "
            f"in the way, or no connection).\n\nDetails:\n{exc}"
        )
    return out.strip() or "Already up to date."


def changed_files(status: str) -> List[str]:
    return [line.split("\t")[-1] for line in status.splitlines() if line.strip()]
