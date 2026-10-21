"""Exercise the real reviewed SC classes when the matching candidate is available."""

import ast
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def classes(tmp_path, monkeypatch):
    source = os.environ.get("SC_STORAGE_CANDIDATE")
    if not source:
        pytest.skip("Set SC_STORAGE_CANDIDATE to the matching patched SC common directory")
    properties = {}
    monkeypatch.setitem(
        sys.modules,
        "xbmcgui",
        SimpleNamespace(Window=lambda number: SimpleNamespace(getProperty=lambda key: properties.get(key, ""))),
    )
    bridge_path = Path(__file__).parents[1] / "resources/lib/sc_bridge.py"
    spec = importlib.util.spec_from_file_location("sc_integration_bridge", bridge_path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    env = {
        "os": os,
        "sqlite3": sqlite3,
        "loads": json.loads,
        "dumps": json.dumps,
        "translate_path": lambda path: path,
        "profile_sync": bridge,
        "checked": False,
        "_storage_cache": {},
        "ADDON": SimpleNamespace(getAddonInfo=lambda key: str(tmp_path)),
        "xbmcvfs": SimpleNamespace(exists=os.path.exists, mkdir=os.mkdir),
        "debug": lambda *args: None,
    }
    tree = ast.parse((Path(source) / "storage.py").read_text(encoding="utf-8"))
    chosen = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in ("Sqlite", "Storage")]
    exec(compile(ast.Module(body=chosen, type_ignores=[]), "reviewed-sc-storage.py", "exec"), env)
    tree = ast.parse((Path(source) / "lists.py").read_text(encoding="utf-8"))
    chosen = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "List"]
    exec(compile(ast.Module(body=chosen, type_ignores=[]), "reviewed-sc-lists.py", "exec"), env)
    return env["Storage"], env["List"], properties, tmp_path / "storage.db"


def remote(path, name, value):
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT OR REPLACE INTO storage VALUES(?,?)", (name, json.dumps(value)))


def test_existing_storage_object_reads_imported_resume(classes):
    Storage, _, properties, path = classes
    item = Storage("SCKODIItem-42")
    item["watched:1:2"] = 10
    remote(path, "SCKODIItem-42", {"watched:1:2": 30})
    properties["sc.profile.sync.SCKODIItem-42"] = "new"
    assert item.get("watched:1:2") == 30
    assert Storage("SCKODIItem-42")["watched:1:2"] == 30


def test_existing_watched_list_reads_remote_changes_and_does_not_resurrect_removals(classes):
    _, List, properties, path = classes
    watched = List("all_watched")
    watched.add("42/1/2")
    watched.add("42/1/3")
    remote(path, "all_watched", {"list": ["42/1/3", "42/1/4"]})
    properties["sc.profile.sync.all_watched"] = "new"
    assert watched.get() == ["42/1/3", "42/1/4"]
    watched.add("42/1/5")
    assert set(watched.get()) == {"42/1/3", "42/1/4", "42/1/5"}


def test_stale_storage_save_preserves_a_remote_field(classes):
    Storage, _, properties, path = classes
    item = Storage("SCKODIItem-42")
    item["watched:1:2"] = 10
    remote(path, "SCKODIItem-42", {"watched:1:2": 10, "watched:1:3": 80})
    item["watched:1:2"] = 20
    with sqlite3.connect(path) as connection:
        value = json.loads(
            connection.execute("SELECT item_value FROM storage WHERE item_key=?", ("SCKODIItem-42",)).fetchone()[0]
        )
    assert value == {"watched:1:2": 20, "watched:1:3": 80}


def test_repeated_readers_reuse_one_window_and_one_merge_snapshot(classes, monkeypatch):
    Storage, _, properties, _ = classes
    bridge = Storage.__init__.__globals__["profile_sync"]
    windows, snapshots = [], []
    real_copy = bridge.copy.deepcopy

    def window(number):
        windows.append(number)
        return SimpleNamespace(getProperty=lambda key: properties.get(key, ""))

    def snapshot(data):
        snapshots.append(data)
        return real_copy(data)

    monkeypatch.setattr(bridge, "Window", window)
    monkeypatch.setattr(bridge, "copy", SimpleNamespace(deepcopy=snapshot))
    item = Storage("SCKODIItem-42")
    item["series"] = {str(n): {"position": n} for n in range(100)}
    snapshots.clear()
    for _ in range(30):
        assert Storage("SCKODIItem-42").get("series")["42"]["position"] == 42
    assert windows == [10000]
    assert snapshots == []


def test_shared_snapshot_keeps_nested_local_edits_and_immediate_remote_refresh(classes):
    Storage, _, properties, path = classes
    item = Storage("SCKODIItem-42")
    item["series"] = {"1": {"position": 10}}
    reader = Storage("SCKODIItem-42")
    item.get("series")["1"]["position"] = 20
    remote(path, "SCKODIItem-42", {"series": {"1": {"position": 10}, "2": {"position": 30}}})
    properties["sc.profile.sync.SCKODIItem-42"] = "imported"
    assert reader.get("series") == {"1": {"position": 20}, "2": {"position": 30}}
    reader["last_ep"] = "1x2"
    assert Storage("SCKODIItem-42").get("series") == {"1": {"position": 20}, "2": {"position": 30}}
