"""Recent list, source labels and git checkouts (against a throwaway bare repo)."""

import os
import subprocess

import pytest

from launcher_editor import sources
from launcher_editor.sources import RecentList, Source


def git(cwd, *args):
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def remote(tmp_path):
    remote = tmp_path / "configs.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "master", str(remote)], check=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", "-q", str(remote), str(seed)], check=True, capture_output=True)
    git(seed, "config", "user.name", "T")
    git(seed, "config", "user.email", "t@x")
    (seed / "S_Test.json").write_text("{}\n")
    (seed / "sub").mkdir()
    (seed / "sub" / "S_Sub.json").write_text("{}\n")
    (seed / "launcher_mapping").write_text("{}\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "seed")
    git(seed, "push", "-q", "origin", "master")
    git(seed, "checkout", "-qb", "dev")
    (seed / "S_Dev.json").write_text("{}\n")
    git(seed, "add", "-A")
    git(seed, "commit", "-qm", "dev only")
    git(seed, "push", "-q", "origin", "dev")
    git(seed, "checkout", "-q", "master")
    return remote, seed


def test_recent_dedupes_orders_and_limits():
    r = RecentList(limit=3)
    a = Source("local", path="/a/menu.json")
    b = Source("ssh", host="h", user="u", path="/b/menu.json")
    c = Source("git", url="git@x:y.git", checkout="/c", path="S.json")
    for s in (a, b, c, a):
        r.add(s)
    assert [e.kind for e in r.entries] == ["local", "git", "ssh"]
    r.add(Source("local", path="/d.json"))
    assert len(r.entries) == 3 and r.entries[0].path == "/d.json"


def test_recent_json_roundtrip_and_garbage():
    r = RecentList()
    r.add(Source("git", url="git@x:y.git", branch="dev", checkout="/c", path="S.json"))
    r.add(Source("ssh", host="h", path="/p/m.json"))
    back = RecentList.from_json(r.to_json())
    assert [e.key() for e in back.entries] == [e.key() for e in r.entries]
    assert RecentList.from_json("not json").entries == []
    assert RecentList.from_json('[{"no": "kind"}, 3]').entries == []
    assert RecentList.from_json(None).entries == []


def test_recent_never_stores_passwords():
    s = Source.from_dict({"kind": "ssh", "host": "h", "path": "/m.json", "password": "secret"})
    assert "password" not in s.to_dict()


def test_git_urls_and_last_for_url():
    r = RecentList()
    r.add(Source("git", url="u1", checkout="/a", path="A.json"))
    r.add(Source("git", url="u2", checkout="/b", path="B.json"))
    r.add(Source("git", url="u1", checkout="/a", path="C.json"))
    assert r.git_urls() == ["u1", "u2"]
    assert r.last_for_url("u1").path == "C.json"


@pytest.mark.parametrize(
    "url,name",
    [
        ("git@gitea.psi.ch:autodeploy_config/sf_bernina_launcher.git", "sf_bernina_launcher"),
        ("https://github.com/org/repo/", "repo"),
        ("/tmp/x/configs.git", "configs"),
    ],
)
def test_repo_name(url, name):
    assert sources.repo_name(url) == name


def test_clone_then_update(remote, tmp_path):
    remote, seed = remote
    checkout = tmp_path / "work" / "configs"
    msg = sources.clone_or_update(str(remote), str(checkout))
    assert "Cloned" in msg and (checkout / "S_Test.json").exists()
    assert sources.menu_files(str(checkout)) == ["S_Test.json", os.path.join("sub", "S_Sub.json")]

    (seed / "S_Test.json").write_text('{"x": 1}\n')
    git(seed, "commit", "-qam", "upstream change")
    git(seed, "push", "-q", "origin", "master")
    sources.clone_or_update(str(remote), str(checkout))
    assert (checkout / "S_Test.json").read_text() == '{"x": 1}\n'


def test_clone_branch(remote, tmp_path):
    remote, _ = remote
    checkout = tmp_path / "dev"
    sources.clone_or_update(str(remote), str(checkout), branch="dev")
    assert (checkout / "S_Dev.json").exists()


def test_update_failure_keeps_copy_usable(remote, tmp_path):
    remote, seed = remote
    checkout = tmp_path / "configs"
    sources.clone_or_update(str(remote), str(checkout))
    git(checkout, "config", "user.name", "T")
    git(checkout, "config", "user.email", "t@x")
    (checkout / "S_Test.json").write_text('{"local": 1}\n')
    git(checkout, "commit", "-qam", "local, unpublished")
    (seed / "S_Test.json").write_text('{"remote": 1}\n')
    git(seed, "commit", "-qam", "remote")
    git(seed, "push", "-q", "origin", "master")
    msg = sources.clone_or_update(str(remote), str(checkout))
    assert "Opening it as it is" in msg
    assert (checkout / "S_Test.json").read_text() == '{"local": 1}\n'


def test_refuses_foreign_checkout_and_nonempty_folder(remote, tmp_path):
    remote, _ = remote
    checkout = tmp_path / "configs"
    sources.clone_or_update(str(remote), str(checkout))
    with pytest.raises(sources.CheckoutError, match="different repository"):
        sources.clone_or_update(str(tmp_path / "other.git"), str(checkout))
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "file").write_text("x")
    with pytest.raises(sources.CheckoutError, match="not empty"):
        sources.clone_or_update(str(remote), str(busy))


def test_clone_failure_message(tmp_path):
    with pytest.raises(sources.CheckoutError, match="Could not clone"):
        sources.clone_or_update(str(tmp_path / "missing.git"), str(tmp_path / "x"))
