"""Model Kodi's independently cached Addon handles, including private local edits."""

import copy
import importlib
import json
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET


def runtime(monkeypatch, tmp_path):
    values = {
        "plugin.video.stream-cinema": {"stream.lang1": "CZ", "kraska.token": "old-token"},
        "service.upnext": {"autoPlaySeasonTime": "30"},
    }
    for name, settings in values.items():
        root = ET.Element("settings")
        for key in settings:
            ET.SubElement(root, "setting", {"id": key})
        directory = tmp_path / name / "resources"
        directory.mkdir(parents=True)
        (directory / "settings.xml").write_bytes(ET.tostring(root))

    class Addon:
        def __init__(self, addon):
            self.addon = addon
            self.snapshot = copy.deepcopy(values[addon])

        def getSetting(self, key):
            return self.snapshot.get(key, "")

        def getAddonInfo(self, key):
            assert key == "path"
            return str(tmp_path / self.addon)

        def setSetting(self, key, value):
            self.snapshot[key] = value
            values[self.addon] = copy.deepcopy(self.snapshot)

    monkeypatch.setitem(sys.modules, "xbmcaddon", SimpleNamespace(Addon=Addon))
    monkeypatch.setitem(
        sys.modules,
        "xbmc",
        SimpleNamespace(Monitor=type("Monitor", (), {}), executeJSONRPC=lambda raw: json.dumps({"error": {}})),
    )
    monkeypatch.setitem(sys.modules, "xbmcgui", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "xbmcvfs", SimpleNamespace())
    monkeypatch.delitem(sys.modules, "resources.lib.runtime", raising=False)
    module = importlib.import_module("resources.lib.runtime")
    result = module.Runtime.__new__(module.Runtime)
    result.sc = Addon("plugin.video.stream-cinema")
    result.upnext = Addon("service.upnext")
    result.skin_settings = tmp_path / "missing-skin-settings.xml"
    result.window = SimpleNamespace(clearProperty=lambda key: None)
    result.setting_ids = {}
    return result, values


def test_preferences_notice_other_scripts_changes(monkeypatch, tmp_path):
    client, values = runtime(monkeypatch, tmp_path)
    assert client.preferences()["service.upnext"]["autoPlaySeasonTime"] == "30"
    values["service.upnext"]["autoPlaySeasonTime"] = "31"
    values["plugin.video.stream-cinema"]["stream.lang1"] = "EN"
    latest = client.preferences()
    assert latest["service.upnext"]["autoPlaySeasonTime"] == "31"
    assert latest["plugin.video.stream-cinema"]["stream.lang1"] == "EN"


def test_import_preserves_new_private_account_settings(monkeypatch, tmp_path):
    client, values = runtime(monkeypatch, tmp_path)
    values["plugin.video.stream-cinema"]["kraska.token"] = "new-token"
    assert client.apply_preference("plugin.video.stream-cinema", "stream.lang1", "EN")
    assert values["plugin.video.stream-cinema"]["kraska.token"] == "new-token"
    assert client.get_sc_setting("kraska.token") == "new-token"
    client.set_sc_setting("kraska.token", "refreshed-token")
    assert values["plugin.video.stream-cinema"]["stream.lang1"] == "EN"


def test_future_setting_is_retained_without_writing_an_unsupported_version(monkeypatch, tmp_path):
    client, values = runtime(monkeypatch, tmp_path)
    assert "autoPlayCreditsTime" not in client.preferences()["service.upnext"]
    assert not client.apply_preference("service.upnext", "autoPlayCreditsTime", "0")
    assert "autoPlayCreditsTime" not in values["service.upnext"]


def test_monitor_callbacks_queue_work_without_running_the_worker(monkeypatch, tmp_path):
    runtime(monkeypatch, tmp_path)
    monitor = sys.modules["resources.lib.runtime"].ProfileMonitor()
    monitor.onNotification("xbmc", "Player.OnPlay", "{}")
    assert not monitor.pending.is_set()
    for method in ("Player.OnStop", "System.OnWake"):
        monitor.onNotification("xbmc", method, "{}")
        assert monitor.pending.is_set()
        monitor.pending.clear()
    for callback in (monitor.onScreensaverDeactivated, monitor.onDPMSDeactivated):
        callback()
        assert monitor.pending.is_set()
        monitor.pending.clear()
    monitor.onSettingsChanged()
    assert monitor.settings_changed.is_set() and monitor.pending.is_set()
