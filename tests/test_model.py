import json
import os

import pytest

from launcher_editor.backends import LocalBackend
from launcher_editor.model import (
    MappingFile,
    MenuDocument,
    clean_item,
    default_item_for_type,
    hash_password,
    item_label,
    items_from_clipboard_text,
    items_to_clipboard_text,
    slugify,
    validate_item,
)
from launcher_editor.workspace import Workspace


SAMPLE_MENU = {
    "menu-title": {"text": "Bernina beamline components", "style": "color: #000000"},
    "menu": [
        {"type": "cmd", "text": "Aramis overview panel", "command": "/sf/bernina/bin/aramis-home"},
        {"type": "title", "text": "Front end"},
        {
            "type": "caqtdm",
            "text": "SARFE10-OAPU044",
            "panel": "OAPU_JJXRay.ui",
            "macros": "P=SARFE10-OAPU044",
        },
        {"type": "separator"},
        {"type": "menu", "text": "Motion control", "file": "S_motion.json"},
    ],
}

SAMPLE_MAPPING = {
    "Linux": {
        "theme_base": "../themes/",
        "cmd": {"command": "bash -c \"{command}\""},
        "caqtdm": {
            "command": "bash -c 'caqtdm -noMsg {param} {macros} {panel}'",
            "arg_flags": {"macros": "-macro"},
        },
    }
}


@pytest.fixture
def backend():
    return LocalBackend()


@pytest.fixture
def sample_path(tmp_path):
    path = tmp_path / "bernina_beamline.json"
    path.write_text(json.dumps(SAMPLE_MENU), encoding="utf-8")
    return str(path)


@pytest.fixture
def mapping_path(tmp_path):
    path = tmp_path / "launcher_mapping"
    path.write_text(json.dumps(SAMPLE_MAPPING), encoding="utf-8")
    return str(path)


def test_load_round_trip(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    assert doc.title_text == "Bernina beamline components"
    assert len(doc.items) == 5
    assert doc.items[1]["type"] == "title"

    doc.save(make_backup=False)
    reloaded = MenuDocument.load(backend, sample_path)
    assert reloaded.data["menu"] == doc.data["menu"]
    assert reloaded.title_text == doc.title_text


def test_save_creates_backup_of_original_content(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    # First save reformats (compact -> pretty JSON), so a backup of the
    # pristine original is expected even though no field values changed.
    doc.save(make_backup=True)
    assert os.path.exists(sample_path + ".bak")
    backup = json.loads(open(sample_path + ".bak").read())
    assert backup == SAMPLE_MENU

    # A second, truly no-op save should not clobber that backup with the
    # already-reformatted content.
    doc.save(make_backup=True)
    backup_after = json.loads(open(sample_path + ".bak").read())
    assert backup_after == SAMPLE_MENU


def test_add_remove_move_duplicate_item(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    start_len = len(doc.items)

    idx = doc.add_item({"type": "title", "text": "New Section"}, index=0)
    assert idx == 0
    assert doc.items[0]["text"] == "New Section"
    assert len(doc.items) == start_len + 1

    doc.move_item(0, 2)
    assert doc.items[1]["text"] == "New Section"

    dup_idx = doc.duplicate_item(1)
    assert dup_idx == 2
    assert doc.items[2]["text"] == "New Section"
    assert doc.items[1] is not doc.items[2]

    removed = doc.remove_item(2)
    assert removed["text"] == "New Section"
    assert len(doc.items) == start_len + 1
    assert doc.dirty is True


def test_update_item_strips_empty_optionals(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    doc.update_item(2, tip="hover text", **{"help-link": ""})
    assert doc.items[2]["tip"] == "hover text"
    assert "help-link" not in doc.items[2]


def test_rename_item_text_only(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    before = dict(doc.items[2])
    doc.set_item_text(2, "Renamed label")
    after = doc.items[2]
    assert after["text"] == "Renamed label"
    # everything else about the item is untouched
    for key in ("panel", "macros", "type"):
        assert after[key] == before[key]


def test_clean_item_orders_keys_and_drops_empties():
    item = {
        "style": "",
        "text": "Hi",
        "type": "cmd",
        "command": "ls",
        "tip": "",
        "help-link": None,
    }
    cleaned = clean_item(item)
    assert list(cleaned.keys()) == ["type", "text", "command"]


def test_password_hash_matches_protect_py():
    # protect.py: hashlib.md5(password.encode()).hexdigest()
    assert hash_password("secret") == "5ebe2294ecd0e0f08eab7690d2a6ee69"


def test_set_and_clear_password(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    assert not doc.has_password()
    doc.set_password("secret")
    assert doc.has_password()
    assert doc.data["password"] == hash_password("secret")
    doc.set_password(None)
    assert not doc.has_password()
    assert "password" not in doc.data


def test_validate_flags_missing_required_fields():
    problems = validate_item({"type": "menu", "text": "Sub"})
    assert any("file" in p for p in problems)
    problems = validate_item({"type": "title"})
    assert any("text" in p for p in problems)
    assert validate_item({"type": "separator"}) == []


def test_item_label():
    assert item_label({"type": "title", "text": "Hi"}) == "Hi"
    assert "separator" in item_label({"type": "separator"})
    assert item_label({"type": "cmd"}).startswith("(untitled")


def test_slugify():
    assert slugify("Timing & Event System") == "timing_event_system"
    assert slugify("  Motion Control  ") == "motion_control"
    assert slugify("!!!") == "menu"


def test_mapping_fields_for_type(backend, mapping_path):
    mapping = MappingFile.load(backend, mapping_path)
    fields = mapping.fields_for_type("Linux", "caqtdm")
    assert fields == ["param", "macros", "panel"]
    assert mapping.fields_for_type("Linux", "cmd") == ["command"]
    assert mapping.fields_for_type("Linux", "nonexistent") == []


def test_mapping_add_and_remove_type(backend, mapping_path):
    mapping = MappingFile.load(backend, mapping_path)
    mapping.add_or_update_type(
        "my-tool", "my-awesome-program {arg1} {arg2}", {"arg1": "--option"}
    )
    assert "my-tool" in mapping.types_for_os("Linux")
    mapping.save(make_backup=False)

    reloaded = MappingFile.load(backend, mapping_path)
    assert reloaded.data["Linux"]["my-tool"]["command"] == "my-awesome-program {arg1} {arg2}"

    reloaded.remove_type("my-tool")
    assert "my-tool" not in reloaded.types_for_os("Linux")


def test_default_item_for_type_uses_mapping_fields(backend, mapping_path):
    mapping = MappingFile.load(backend, mapping_path)
    item = default_item_for_type("caqtdm", mapping, "Linux")
    assert item["type"] == "caqtdm"
    assert set(["param", "macros", "panel"]).issubset(item.keys())


def test_default_item_for_builtin_types():
    assert default_item_for_type("separator") == {"type": "separator"}
    title = default_item_for_type("title")
    assert title["type"] == "title" and title["text"]
    submenu = default_item_for_type("menu")
    assert submenu["type"] == "menu" and "file" in submenu


def test_clipboard_round_trip():
    items = [
        {"type": "title", "text": "Section"},
        {"type": "cmd", "text": "Run", "command": "ls"},
    ]
    text = items_to_clipboard_text(items)
    restored = items_from_clipboard_text(text)
    assert restored == items


def test_clipboard_accepts_bare_json_list_or_item():
    items = [{"type": "separator"}]
    assert items_from_clipboard_text(json.dumps(items)) == items
    single = {"type": "title", "text": "X"}
    assert items_from_clipboard_text(json.dumps(single)) == [single]


def test_clipboard_rejects_garbage():
    assert items_from_clipboard_text("not json") is None
    assert items_from_clipboard_text("") is None
    assert items_from_clipboard_text("42") is None


def test_workspace_new_submenu_and_link(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    ws = Workspace(backend)
    ws.register(doc)

    new_doc, file_name = ws.new_submenu(doc, "Vacuum System")
    assert file_name == "vacuum_system.json"
    assert new_doc.title_text == "Vacuum System"
    assert backend.exists(new_doc.path)

    idx = doc.add_item({"type": "menu", "text": "Vacuum System", "file": file_name})
    assert doc.items[idx]["file"] == file_name

    refs = ws.references_to(new_doc.path)
    assert (doc, idx) in refs


def test_workspace_new_submenu_rejects_existing_file(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    ws = Workspace(backend)
    ws.register(doc)
    ws.new_submenu(doc, "Vacuum System")
    with pytest.raises(FileExistsError):
        ws.new_submenu(doc, "Vacuum System")


def test_workspace_scan_directory_for_references(backend, tmp_path):
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"
    target = tmp_path / "target.json"
    a.write_text(json.dumps({"menu": [{"type": "menu", "text": "T", "file": "target.json"}]}))
    b.write_text(json.dumps({"menu": [{"type": "cmd", "text": "x", "command": "ls"}]}))
    target.write_text(json.dumps({"menu": []}))

    ws = Workspace(backend)
    hits = ws.scan_directory_for_references(str(tmp_path), str(target))
    assert hits == [str(a)]


def test_workspace_delete_submenu_file(backend, sample_path):
    doc = MenuDocument.load(backend, sample_path)
    ws = Workspace(backend)
    ws.register(doc)
    new_doc, _ = ws.new_submenu(doc, "Temp")
    assert backend.exists(new_doc.path)
    ws.delete_submenu_file(new_doc.path)
    assert not backend.exists(new_doc.path)
    assert new_doc.path not in ws.documents
