"""Model Kodi's independently cached Addon handles, including private local edits."""

import copy
import importlib
import json
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import pytest


def runtime(monkeypatch, tmp_path):
    values = {
        "plugin.video.stream-cinema": {"stream.lang1": "CZ", "kraska.token": "old-token"},
        "service.upnext": {"autoPlaySeasonTime": "30"},
        "service.sc.profilesync": {
            "local_interval": "15",
            "remote_interval": "60",
            "hide_subtitles_for_czech_audio": "true",
        },
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
        SimpleNamespace(
            Monitor=type("Monitor", (), {}),
            Player=type("Player", (), {}),
            executeJSONRPC=lambda raw: json.dumps({"error": {}}),
        ),
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
    result.monitor = SimpleNamespace(settings_changed=SimpleNamespace(set=lambda: None))
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


def test_native_interface_sound_reads_and_imports_do_not_touch_hardware(monkeypatch, tmp_path):
    client, _ = runtime(monkeypatch, tmp_path)
    settings = {"audiooutput.guisoundmode": 1, "audiooutput.guisoundvolume": 100}

    def rpc(method, params):
        key = params["setting"]
        if key not in settings:
            raise ValueError("Unsupported test setting")
        if method == "Settings.GetSettingValue":
            return {"value": settings[key]}
        assert method == "Settings.SetSettingValue"
        settings[key] = params["value"]
        return True

    monkeypatch.setattr(sys.modules["resources.lib.runtime"], "rpc", rpc)
    assert client.preferences()["kodi"] == settings
    assert client.apply_preference("kodi", "audiooutput.guisoundmode", 0)
    assert settings["audiooutput.guisoundmode"] == 0
    assert not client.apply_preference("kodi", "audiooutput.passthrough", True)


def test_core_preferences_are_saved_and_verified_before_returning(monkeypatch, tmp_path):
    client, _ = runtime(monkeypatch, tmp_path)
    client.core_settings = tmp_path / "guisettings.xml"
    client.core_settings.write_text('<settings><setting id="audiooutput.guisoundmode">1</setting></settings>')

    def builtin(command, wait):
        assert command == "Skin.SetBool(scprofilesync.internal.settingssaved,false)" and wait
        client.core_settings.write_text('<settings><setting id="audiooutput.guisoundmode">0</setting></settings>')

    monkeypatch.setattr(sys.modules["xbmc"], "executebuiltin", builtin, raising=False)
    client.persist_preferences({"kodi": {"audiooutput.guisoundmode": 0}})
    # Kodi can reject a disk write; it must not be acknowledged as durable.
    with pytest.raises(OSError):
        client.persist_preferences({"kodi": {"audiooutput.guisoundmode": 1}})


@pytest.mark.parametrize(
    "text,value", [("true", True), ("1,2", [1, 2]), ("Czech,English", ["Czech", "English"]), ("42.000000", 42)]
)
def test_saved_native_types(monkeypatch, tmp_path, text, value):
    runtime(monkeypatch, tmp_path)
    assert sys.modules["resources.lib.runtime"].saved_value_matches(text, value)


def test_missing_native_settings_and_resources_are_not_written(monkeypatch, tmp_path):
    client, _ = runtime(monkeypatch, tmp_path)
    calls = []

    def rpc(method, params):
        calls.append(method)
        if params.get("setting") == "subtitles.blur":
            raise ValueError("Unavailable")
        if method == "Settings.GetSettingValue":
            return {"value": ""}
        raise ValueError("Resource is not installed")

    monkeypatch.setattr(sys.modules["resources.lib.runtime"], "rpc", rpc)
    assert not client.apply_preference("kodi", "subtitles.blur", 1)
    assert not client.apply_preference("kodi", "lookandfeel.soundskin", "resource.uisounds.missing")
    assert "Settings.SetSettingValue" not in calls


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
