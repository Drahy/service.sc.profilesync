"""Kodi adapter: preferences are allowlisted, and active playback is never controlled."""

import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from .adapter import Adapter
from .engine import Engine
from .kra import Kra
from .local import identity, read, write
from .policy import SC_SETTINGS, NEXT_SETTINGS, KODI_SETTINGS, shared_setting
from .worker import Worker


def rpc(method, params=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if "error" in reply:
        raise ValueError("Kodi request unavailable: " + method)
    return reply.get("result")


class Runtime:
    def __init__(self):
        self.addon = xbmcaddon.Addon("service.sc.profilesync")
        self.directory = Path(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")))
        self.directory.mkdir(parents=True, exist_ok=True)
        sc = xbmcaddon.Addon("plugin.video.stream-cinema")
        self.window = xbmcgui.Window(10000)
        self.monitor = xbmc.Monitor()
        self.setting_ids = {}
        self.database = Path(xbmcvfs.translatePath(sc.getAddonInfo("profile"))) / "storage.db"
        self.skin_settings = Path(xbmcvfs.translatePath("special://profile/addon_data/skin.amber/settings.xml"))

    def preferences(self):
        # Kodi reloads only the first registered Addon handle after another script
        # saves settings. New handles read the current file and preserve local edits.
        sc = xbmcaddon.Addon("plugin.video.stream-cinema")
        upnext = xbmcaddon.Addon("service.upnext")
        result = {
            "plugin.video.stream-cinema": {k: sc.getSetting(k) for k in SC_SETTINGS if k in self.supported(sc)},
            "service.upnext": {k: upnext.getSetting(k) for k in NEXT_SETTINGS if k in self.supported(upnext)},
            "kodi": {},
            "skin.amber": {},
        }
        for key in KODI_SETTINGS:
            try:
                result["kodi"][key] = rpc("Settings.GetSettingValue", {"setting": key})["value"]
            except ValueError:
                pass
        if self.skin_settings.exists():
            for node in ET.parse(self.skin_settings).getroot().findall("setting"):
                key = node.get("id", "")
                value = node.text or ""
                if not shared_setting("skin.amber", key):
                    continue
                if node.get("type") == "bool":
                    if xbmc.getSkinDir() == "skin.amber":
                        value = bool(xbmc.getCondVisibility("Skin.HasSetting(" + key + ")"))
                    else:
                        value = value.lower() == "true"
                elif xbmc.getSkinDir() == "skin.amber":
                    value = xbmc.getInfoLabel("Skin.String(" + key + ")")
                if type(value) is bool or (
                    isinstance(value, str)
                    and len(value) <= 128
                    and not any(c in value for c in ['"', ",", ")", "\\", "://", "/"])
                ):
                    result["skin.amber"][key] = value
        return result

    def supported(self, addon):
        path = Path(addon.getAddonInfo("path")) / "resources/settings.xml"
        key = str(path)
        if key not in self.setting_ids:
            self.setting_ids[key] = {node.get("id") for node in ET.parse(path).getroot().iter("setting")}
        return self.setting_ids[key]

    def apply_preference(self, addon, key, value):
        if not shared_setting(addon, key):
            return False
        if addon == "kodi":
            return rpc("Settings.SetSettingValue", {"setting": key, "value": value}) is True
        if addon == "skin.amber":
            if xbmc.getSkinDir() != "skin.amber":
                return False
            if type(value) is bool:
                xbmc.executebuiltin(("Skin.SetBool(" if value else "Skin.Reset(") + key + ")")
                return True
            if (
                isinstance(value, str)
                and len(value) <= 128
                and not any(c in value for c in ['"', ",", ")", "\\", "://", "/"])
            ):
                xbmc.executebuiltin("Skin.SetString(" + key + "," + value + ")")
                return True
            return False
        target = xbmcaddon.Addon(addon)
        if key not in self.supported(target):
            return False
        target.setSetting(key, str(value))
        if addon == "plugin.video.stream-cinema":
            self.window.clearProperty("SC:stream_filter_prefs")
        return target.getSetting(key) == str(value)

    @staticmethod
    def get_sc_setting(key):
        return xbmcaddon.Addon("plugin.video.stream-cinema").getSetting(key)

    @staticmethod
    def set_sc_setting(key, value):
        xbmcaddon.Addon("plugin.video.stream-cinema").setSetting(key, value)

    def invalidate(self, namespaces):
        token = str(time.time_ns())
        for namespace in namespaces:
            self.window.setProperty("sc.profile.sync." + namespace, token)

    def status(self, value):
        write(self.directory / "status.json", value)

    def run(self):
        if self.monitor.waitForAbort(12):
            return
        device = identity(self.directory)
        try:
            saved = read(self.directory / "state.json")
        except (ValueError, OSError):
            path = self.directory / "state.json"
            path.rename(path.with_name("state.corrupt-" + str(int(time.time())) + ".json"))
            saved = None
        engine = Engine(device, saved)
        adapter = Adapter(self.database, self.preferences, self.apply_preference, self.invalidate)
        worker = Worker(
            engine,
            adapter,
            Kra(self.get_sc_setting, self.set_sc_setting),
            self.directory / "state.json",
            playing=lambda: bool(xbmc.Player().isPlaying()),
            status=self.status,
        )
        last_network = 0
        backoff = 20
        while not self.monitor.abortRequested():
            try:
                if self.database.exists() and self.addon.getSetting("enabled") != "false":
                    worker.capture()
                    requested = self.window.getProperty("sc.profile.sync.request")
                    if requested or time.monotonic() - last_network >= backoff:
                        self.window.clearProperty("sc.profile.sync.request")
                        last_network = time.monotonic()
                        worker.sync()
                        backoff = 20
            except Exception as error:
                # Exception messages may contain private URLs; report only the class.
                self.status(
                    {
                        "ok": False,
                        "error": type(error).__name__,
                        "retry_seconds": min(backoff * 2, 180),
                        "pending_upload": engine.dirty,
                    }
                )
                xbmc.log("[service.sc.profilesync] Sync deferred: " + type(error).__name__, xbmc.LOGWARNING)
                backoff = min(backoff * 2, 180)
                last_network = time.monotonic()
                worker.save()
            if self.monitor.waitForAbort(2):
                break
