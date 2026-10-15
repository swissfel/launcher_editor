"""Publish flow against throwaway git repositories (a bare "server" + clones)."""

import subprocess

import pytest

from launcher_editor import gitflow
from launcher_editor.backends import LocalBackend


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


def clone(remote, path):
    subprocess.run(["git", "clone", "-q", str(remote), str(path)], check=True)
    git(path, "config", "user.name", "Test User")
    git(path, "config", "user.email", "test@example.org")
    return path


@pytest.fixture
def repos(tmp_path):
    """A bare remote with one commit, and two independent clones ("alice", "bob")."""
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(remote)], check=True)
    seed = clone(remote, tmp_path / "seed")
    (seed / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "b",\n    "c"\n  ]\n}\n')
    (seed / "other.json").write_text("{}\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-q", "-m", "initial")
    git(seed, "push", "-q", "origin", "master")
    return remote, clone(remote, tmp_path / "alice"), clone(remote, tmp_path / "bob")


def remote_log(remote):
    return git(remote, "log", "--format=%s", "master").split("\n")


def test_repo_root_from_subdirectory(repos):
    _, alice, _ = repos
    (alice / "sub").mkdir()
    assert gitflow.repo_root(LocalBackend(), str(alice / "sub")) == str(alice)


def test_repo_root_outside_git(tmp_path):
    assert gitflow.repo_root(LocalBackend(), str(tmp_path)) is None


def test_publish_commits_and_pushes_but_never_bak(repos):
    remote, alice, _ = repos
    be = LocalBackend()
    (alice / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "B",\n    "c"\n  ]\n}\n')
    (alice / "menu.json.bak").write_text("old\n")
    (alice / "new_submenu.json").write_text("{}\n")

    pending = gitflow.prepare(be, str(alice))
    assert pending.has_changes
    assert sorted(gitflow.changed_files(pending.status)) == ["menu.json", "new_submenu.json"]
    assert '+    "B",' in pending.diff

    summary = gitflow.publish(be, str(alice), "Rename b")
    assert "Rename b" in summary
    assert remote_log(remote)[0] == "Rename b"
    tracked = git(remote, "ls-tree", "--name-only", "master").split()
    assert "menu.json.bak" not in tracked and "new_submenu.json" in tracked
    assert "*.bak" in (alice / ".git" / "info" / "exclude").read_text()


def test_nothing_to_publish(repos):
    _, alice, _ = repos
    pending = gitflow.prepare(LocalBackend(), str(alice))
    assert pending.nothing_to_publish


def test_unstage_after_cancel(repos):
    _, alice, _ = repos
    be = LocalBackend()
    (alice / "other.json").write_text('{"x": 1}\n')
    gitflow.prepare(be, str(alice))
    gitflow.unstage(be, str(alice))
    assert git(alice, "diff", "--cached", "--name-only").strip() == ""
    assert git(alice, "status", "--short").strip() == "M other.json"


def test_publish_rebases_onto_unrelated_remote_change(repos):
    remote, alice, bob = repos
    be = LocalBackend()
    (bob / "other.json").write_text('{"bob": 1}\n')
    gitflow.prepare(be, str(bob))
    gitflow.publish(be, str(bob), "Bob's change")

    (alice / "menu.json").write_text('{\n  "menu": [\n    "A",\n    "b",\n    "c"\n  ]\n}\n')
    gitflow.prepare(be, str(alice))
    gitflow.publish(be, str(alice), "Alice's change")

    assert remote_log(remote)[:3] == ["Alice's change", "Bob's change", "initial"]
    # linear history, no merge commits
    assert git(remote, "rev-list", "--merges", "master").strip() == ""


def test_conflict_is_aborted_and_kept_local(repos):
    remote, alice, bob = repos
    be = LocalBackend()
    (bob / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "BOB",\n    "c"\n  ]\n}\n')
    gitflow.prepare(be, str(bob))
    gitflow.publish(be, str(bob), "Bob's change")

    (alice / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "ALICE",\n    "c"\n  ]\n}\n')
    gitflow.prepare(be, str(alice))
    with pytest.raises(gitflow.PublishError, match="Nothing was published"):
        gitflow.publish(be, str(alice), "Alice's change")

    assert remote_log(remote)[0] == "Bob's change"
    assert not gitflow._rebase_in_progress(be, str(alice))  # not left half-rebased
    assert git(alice, "log", "-1", "--format=%s").strip() == "Alice's change"


def test_prepare_refuses_during_unfinished_rebase(repos):
    _, alice, bob = repos
    be = LocalBackend()
    (bob / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "BOB",\n    "c"\n  ]\n}\n')
    gitflow.prepare(be, str(bob))
    gitflow.publish(be, str(bob), "Bob's change")
    (alice / "menu.json").write_text('{\n  "menu": [\n    "a",\n    "ALICE",\n    "c"\n  ]\n}\n')
    git(alice, "commit", "-qam", "Alice's change")
    subprocess.run(["git", "-C", str(alice), "pull", "-q", "--rebase"], capture_output=True)
    with pytest.raises(gitflow.PublishError, match="unfinished git rebase"):
        gitflow.prepare(be, str(alice))


def test_update_fast_forwards(repos):
    _, alice, bob = repos
    be = LocalBackend()
    (bob / "other.json").write_text('{"bob": 1}\n')
    gitflow.prepare(be, str(bob))
    gitflow.publish(be, str(bob), "Bob's change")
    gitflow.update(be, str(alice))
    assert git(alice, "log", "-1", "--format=%s").strip() == "Bob's change"
