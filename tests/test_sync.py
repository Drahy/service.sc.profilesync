import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from resources.lib.adapter import Adapter
from resources.lib.engine import Engine, decode, encode, valid_key
from resources.lib.kra import KraError, NAME
from resources.lib.local import read
from resources.lib.profile import apply_rows, export
from resources.lib.worker import Worker

DEVICE_A, DEVICE_B = "a" * 32, "b" * 32
KEY = "history|42|1|2"


def history(position=10, count=0, played="2026-10-20T12:00:00+00:00"):
    return {"position": position, "count": count, "played_at": played, "watched": count > 0}


def record(value, stamp=10, counter=1, origin=DEVICE_A):
    return {"value": value, "v": [stamp, counter, origin]}


def database(path, rows):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE storage(item_key TEXT PRIMARY KEY,item_value BLOB)")
    con.executemany("INSERT INTO storage VALUES(?,?)", [(key, json.dumps(value)) for key, value in rows.items()])
    con.commit()
    con.close()
    return path


def update(path, namespace, changes):
    con = sqlite3.connect(path)
    old = con.execute("SELECT item_value FROM storage WHERE item_key=?", (namespace,)).fetchone()
    value = json.loads(old[0]) if old else {}
    for key, item in changes.items():
        if item is None:
            value.pop(key, None)
        else:
            value[key] = item
    con.execute("INSERT OR REPLACE INTO storage VALUES(?,?)", (namespace, json.dumps(value)))
    con.commit()
    con.close()


class Backend:
    def __init__(self):
        self.files = {}
        self.offline = False
        self.on_download = None

    def list(self):
        if self.offline:
            raise KraError("offline")
        return [{"name": name, "ident": name} for name in self.files]

    def download(self, file):
        if self.on_download:
            callback, self.on_download = self.on_download, None
            callback()
        return self.files[file["ident"]]

    def upload(self, name, raw):
        assert NAME.fullmatch(name)
        self.files[name] = raw

    def prune(self, device):
        pass


def replica(tmp_path, device, backend, rows=None, preferences=None, playing=None):
    path = database(tmp_path / (device + ".db"), rows or {})
    prefs = preferences or {}

    def apply(addon, setting, value):
        prefs.setdefault(addon, {})[setting] = value
        return True

    adapter = Adapter(path, lambda: copy.deepcopy(prefs), apply)
    engine = Engine(device, now=lambda: 1792500000000)
    worker = Worker(engine, adapter, backend, tmp_path / (device + ".json"), playing)
    return worker, path, prefs


def test_payload_roundtrip_and_checksum():
    raw = encode(DEVICE_A, 1, {KEY: record(history())})
    assert decode(raw)["records"][KEY]["value"]["position"] == 10
    with pytest.raises(ValueError):
        decode(raw.replace(b'"position":10', b'"position":20'))


@pytest.mark.parametrize(
    "key",
    [
        "setting|plugin.video.stream-cinema|kraska.pass",
        "setting|plugin.video.stream-cinema|system.auth_token",
        "setting|kodi|services.webserverpassword",
        "setting|skin.amber|password",
        "file|../../outside",
        "bug_report_last_stream",
    ],
)
def test_secrets_and_paths_are_not_shared(key):
    assert not valid_key(key)
    with pytest.raises(ValueError):
        encode(DEVICE_A, 1, {key: record("secret")})


def test_export_excludes_debug_records_and_hardware():
    snapshot, _ = export(
        {"bug_report_last_stream": {"url": "private"}, "episode_cache": {"url": "private"}},
        {
            "plugin.video.stream-cinema": {"kraska.pass": "secret", "stream.max.bitrate": "50", "stream.lang1": "CZ"},
            "kodi": {"videoscreen.guipeakluminance": 100},
        },
    )
    assert snapshot == {"setting|plugin.video.stream-cinema|stream.lang1": "CZ"}


def test_seed_preserves_watched_list_only_entries():
    snapshot, _ = export({"all_watched": {"list": ["42/1/2", "99"]}})
    assert snapshot[KEY] == {"position": None, "count": None, "played_at": None, "watched": True}
    assert snapshot["history|99|-|-"]["watched"]


def test_completed_resume_removal_wins_over_an_old_client():
    a, b = Engine(DEVICE_A), Engine(DEVICE_B)
    a.merge({KEY: record(history(None, 1), stamp=20)})
    a.merge({KEY: record(history(100, 0), stamp=10, origin=DEVICE_B)})
    b.merge(a.records)
    assert b.records[KEY]["value"]["position"] is None
    assert b.records[KEY]["value"]["watched"]


def test_genuine_rewatch_keeps_its_newer_position():
    a = Engine(DEVICE_A)
    a.merge({KEY: record(history(None, 1), stamp=10)})
    a.merge({KEY: record(history(40, 1), stamp=20, origin=DEVICE_B)})
    assert a.records[KEY]["value"]["position"] == 40


def test_explicit_unwatched_state_and_delete_are_retained():
    rows = {"SCKODIItem-42": {"play_count:1:2": 1, "watched:1:2": 99}, "all_watched": {"list": ["42/1/2", "99"]}}
    result = apply_rows(rows, {KEY: record(history(None, 0), 20)})
    assert result["all_watched"]["list"] == ["99"]
    assert "watched:1:2" not in result["SCKODIItem-42"]
    result = apply_rows(rows, {KEY: record(None, 20)})
    assert "play_count:1:2" not in result["SCKODIItem-42"]


def test_clock_after_remote_future_timestamp_is_causally_newer():
    engine = Engine(DEVICE_B, now=lambda: 1)
    engine.capture({KEY: history(10)})
    incoming = record(history(20), stamp=500, counter=50)
    engine.merge({KEY: incoming})
    engine.capture({KEY: history(30)})
    assert tuple(engine.records[KEY]["v"]) > tuple(incoming["v"])


def test_concurrent_merge_order_is_deterministic():
    x, y = Engine(DEVICE_A), Engine(DEVICE_B)
    first = {KEY: record(history(20), stamp=10, origin=DEVICE_A)}
    second = {KEY: record(history(30), stamp=10, origin=DEVICE_B)}
    x.merge(first)
    x.merge(second)
    y.merge(second)
    y.merge(first)
    assert x.records == y.records


def test_last_seen_union_order_and_explicit_remove():
    engine = Engine(DEVICE_A, now=lambda: 100)
    engine.capture({"list|lasts|1": {"rank": 0}, "list|lasts|2": {"rank": 1}})
    engine.merge({"list|lasts|3": record(True, stamp=20, origin=DEVICE_B)})
    changed = apply_rows({}, engine.records)
    assert changed["lasts"]["list"] == ["3", "1", "2"]
    engine.capture({"list|lasts|2": {"rank": 0}})
    assert engine.records["list|lasts|1"]["value"] is None
    assert engine.records["list|lasts|2"]["v"][0] == 100


def test_rank_shift_does_not_rewrite_other_visit_times():
    engine = Engine(DEVICE_A, now=lambda: 100)
    engine.capture({"list|lasts|1": {"rank": 0}, "list|lasts|2": {"rank": 1}})
    old = copy.deepcopy(engine.records["list|lasts|1"])
    engine.capture({"list|lasts|3": {"rank": 0}, "list|lasts|1": {"rank": 1}, "list|lasts|2": {"rank": 2}})
    assert engine.records["list|lasts|1"] == old


def test_absent_addon_does_not_delete_its_shared_preferences():
    engine = Engine(DEVICE_A)
    key = "setting|service.upnext|simpleMode"
    engine.capture({key: "0"})
    engine.capture({})
    assert engine.records[key]["value"] == "0"


def test_delayed_native_preference_import_does_not_echo_as_a_local_edit():
    engine = Engine(DEVICE_A, now=lambda: 100)
    key = "setting|service.upnext|simpleMode"
    engine.capture({key: "1"})
    incoming = record("0", stamp=200, origin=DEVICE_B)
    engine.merge({key: incoming})
    engine.dirty = False
    engine.capture({key: "0"})
    assert engine.records[key] == incoming
    assert not engine.dirty


def test_adapter_does_not_overwrite_a_local_edit_after_capture(tmp_path):
    backend = Backend()
    worker, path, _ = replica(tmp_path, DEVICE_A, backend, {"SCKODIItem-42": {"watched:1:2": 10}})
    expected, _ = worker.adapter.snapshot()
    update(path, "SCKODIItem-42", {"watched:1:2": 90})
    worker.adapter.apply({KEY: record(history(20), 50)}, expected)
    assert worker.adapter.snapshot()[0][KEY]["position"] == 90


def test_two_devices_converge_without_echo_uploads(tmp_path):
    backend = Backend()
    a, path_a, _ = replica(
        tmp_path,
        DEVICE_A,
        backend,
        {"SCKODIItem-42": {"watched:1:2": 50, "last_played:1:2": "2026-10-20T12:00:00+00:00"}},
    )
    b, path_b, _ = replica(tmp_path, DEVICE_B, backend)
    a.sync()
    b.sync()
    a.sync()
    assert b.adapter.snapshot()[0][KEY]["position"] == 50
    generation = b.engine.generation
    b.sync()
    assert b.engine.generation == generation
    update(path_b, "SCKODIItem-42", {"watched:1:2": None, "play_count:1:2": 1})
    b.sync()
    a.sync()
    b.sync()
    assert a.adapter.snapshot()[0][KEY]["position"] is None
    assert a.adapter.snapshot()[0][KEY]["watched"]


def test_new_device_restores_existing_cloud_preferences_instead_of_its_defaults(tmp_path):
    backend = Backend()
    a, _, _ = replica(tmp_path, DEVICE_A, backend, preferences={"service.upnext": {"autoPlaySeasonTime": "35"}})
    a.sync()
    b, _, preferences = replica(
        tmp_path, DEVICE_B, backend, preferences={"service.upnext": {"autoPlaySeasonTime": "30"}}
    )
    b.sync()
    assert preferences["service.upnext"]["autoPlaySeasonTime"] == "35"
    a.sync()
    assert a.adapter.snapshot()[0]["setting|service.upnext|autoPlaySeasonTime"] == "35"


def test_new_device_restores_legacy_zero_clock_cloud_preferences(tmp_path):
    backend = Backend()
    key = "setting|service.upnext|autoPlaySeasonTime"
    name = "kodi-profile-v1-" + DEVICE_A + "-000000000001.json"
    backend.files[name] = encode(DEVICE_A, 1, {key: record("35", stamp=0, counter=0)})
    b, _, preferences = replica(
        tmp_path, DEVICE_B, backend, preferences={"service.upnext": {"autoPlaySeasonTime": "30"}}
    )
    b.sync()
    assert preferences["service.upnext"]["autoPlaySeasonTime"] == "35"


def test_explicit_local_preference_change_before_first_connection_is_preserved(tmp_path):
    backend = Backend()
    a, _, _ = replica(tmp_path, DEVICE_A, backend, preferences={"service.upnext": {"autoPlaySeasonTime": "35"}})
    a.sync()
    b, _, preferences = replica(
        tmp_path, DEVICE_B, backend, preferences={"service.upnext": {"autoPlaySeasonTime": "30"}}
    )
    b.capture()
    preferences["service.upnext"]["autoPlaySeasonTime"] = "40"
    b.sync()
    assert preferences["service.upnext"]["autoPlaySeasonTime"] == "40"


def test_offline_edits_survive_a_restart(tmp_path):
    backend = Backend()
    worker, path, prefs = replica(tmp_path, DEVICE_A, backend, {"SCKODIItem-42": {"watched:1:2": 25}})
    backend.offline = True
    with pytest.raises(KraError):
        worker.sync()
    saved = read(worker.checkpoint)
    assert saved["dirty"]
    restored = Worker(Engine(DEVICE_A, saved), worker.adapter, backend, worker.checkpoint)
    backend.offline = False
    restored.sync()
    assert not restored.engine.dirty and backend.files


def test_active_playback_defers_import_but_keeps_pending_state(tmp_path):
    backend = Backend()
    a, _, _ = replica(tmp_path, DEVICE_A, backend, {"SCKODIItem-42": {"watched:1:2": 55}})
    active = [True]
    b, _, _ = replica(tmp_path, DEVICE_B, backend, playing=lambda: active[0])
    a.sync()
    b.sync()
    assert KEY not in b.adapter.snapshot()[0]
    active[0] = False
    b.sync()
    assert b.adapter.snapshot()[0][KEY]["position"] == 55


def test_local_edit_during_cloud_download_wins_without_being_erased(tmp_path):
    backend = Backend()
    a, _, _ = replica(tmp_path, DEVICE_A, backend, {"SCKODIItem-42": {"watched:1:2": 15}})
    b, path_b, _ = replica(tmp_path, DEVICE_B, backend, {"SCKODIItem-42": {"watched:1:2": 5}})
    b.capture()
    a.sync()
    backend.on_download = lambda: update(path_b, "SCKODIItem-42", {"watched:1:2": 80})
    b.sync()
    assert b.adapter.snapshot()[0][KEY]["position"] == 80


@pytest.fixture
def bridge(monkeypatch):
    properties = {}
    monkeypatch.setitem(
        sys.modules,
        "xbmcgui",
        SimpleNamespace(Window=lambda number: SimpleNamespace(getProperty=lambda key: properties.get(key, ""))),
    )
    path = Path(__file__).parents[1] / "resources/lib/sc_bridge.py"
    spec = importlib.util.spec_from_file_location("tested_sc_bridge", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, properties


def test_bridge_keeps_remote_deletion_when_local_adds_another_item(bridge):
    module, _ = bridge
    assert module.three_way(["1", "2"], ["3", "1", "2"], ["1"]) == ["3", "1"]


def test_bridge_merges_different_episode_flags(bridge):
    module, _ = bridge
    assert module.three_way(
        {"season": {"1": True}}, {"season": {"1": True, "2": True}}, {"season": {"1": True, "3": True}}
    ) == {"season": {"1": True, "2": True, "3": True}}


def test_bridge_atomic_save_keeps_remote_progress_of_another_episode(tmp_path, bridge):
    module, _ = bridge
    path = database(tmp_path / "bridge.db", {"SCKODIItem-42": {"watched:1:2": 10, "watched:1:3": 70}})
    obj = SimpleNamespace(
        _name="SCKODIItem-42",
        _data={"watched:1:2": 20},
        _profile_sync_base={"watched:1:2": 10},
        _db=SimpleNamespace(_path=str(path)),
        _sql_get="SELECT item_value FROM storage WHERE item_key=?",
        _sql_set="INSERT OR REPLACE INTO storage VALUES(?,?)",
    )
    assert module.save(obj, {})
    assert obj._data == {"watched:1:2": 20, "watched:1:3": 70}
