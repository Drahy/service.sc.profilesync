"""Kodi adapter: preferences are allowlisted, and active playback is never controlled."""

import json
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import xbmc
import xbmcaddon
import xbmcvfs

from .adapter import Adapter
from .engine import Engine
from .kra import Kra
from .local import identity, read, write
from .lifecycle import ProfileMonitor, SyncStopped
from .policy import SC_SETTINGS, NEXT_SETTINGS, KODI_SETTINGS, PROFILE_SETTINGS, shared_setting
from .worker import Worker
from .schedule import Schedule
from .subtitles import SubtitleService


def rpc(method, params=None):
    request = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    if "error" in reply:
        raise ValueError("Kodi request unavailable: " + method)
    return reply.get("result")


class Runtime:
    def __init__(self, monitor=None):
        self.monitor = monitor or ProfileMonitor()
        self.monitor.check_running()
        self.addon = xbmcaddon.Addon("service.sc.profilesync")
        self.directory = Path(xbmcvfs.translatePath(self.addon.getAddonInfo("profile")))
        self.directory.mkdir(parents=True, exist_ok=True)
        sc = xbmcaddon.Addon("plugin.video.stream-cinema")
        self.window = self.monitor.window
        self.setting_ids = {}
        self.database = Path(xbmcvfs.translatePath(sc.getAddonInfo("profile"))) / "storage.db"
        self.skin_settings = Path(xbmcvfs.translatePath("special://profile/addon_data/skin.amber/settings.xml"))
        self.core_settings = Path(xbmcvfs.translatePath("special://profile/guisettings.xml"))

    def call_rpc(self, method, params=None):
        self.monitor.check_running()
        return rpc(method, params)

    def preferences(self):
        self.monitor.check_running()
        # Kodi reloads only the first registered Addon handle after another script
        # saves settings. New handles read the current file and preserve local edits.
        sc = xbmcaddon.Addon("plugin.video.stream-cinema")
        upnext = xbmcaddon.Addon("service.upnext")
        profile = xbmcaddon.Addon("service.sc.profilesync")
        result = {
            "plugin.video.stream-cinema": {k: sc.getSetting(k) for k in SC_SETTINGS if k in self.supported(sc)},
            "service.upnext": {k: upnext.getSetting(k) for k in NEXT_SETTINGS if k in self.supported(upnext)},
            "service.sc.profilesync": {
                k: profile.getSetting(k) for k in PROFILE_SETTINGS if k in self.supported(profile)
            },
            "kodi": {},
            "skin.amber": {},
        }
        for key in KODI_SETTINGS:
            try:
                result["kodi"][key] = self.call_rpc("Settings.GetSettingValue", {"setting": key})["value"]
            except ValueError:
                pass
        if self.skin_settings.exists():
            for node in ET.parse(self.skin_settings).getroot().findall("setting"):
                self.monitor.check_running()
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
        self.monitor.check_running()
        if not shared_setting(addon, key):
            return False
        if addon == "kodi":
            try:
                self.call_rpc("Settings.GetSettingValue", {"setting": key})
                if (
                    key
                    in (
                        "locale.language",
                        "lookandfeel.skin",
                        "lookandfeel.soundskin",
                        "subtitles.tv",
                        "subtitles.movie",
                    )
                    and value
                ):
                    resource = self.call_rpc("Addons.GetAddonDetails", {"addonid": value, "properties": ["enabled"]})
                    if not resource["addon"]["enabled"]:
                        return False
                return self.call_rpc("Settings.SetSettingValue", {"setting": key, "value": value}) is True
            except ValueError:
                return False
        if addon == "skin.amber":
            if xbmc.getSkinDir() != "skin.amber":
                return False
            if type(value) is bool:
                xbmc.executebuiltin(("Skin.SetBool(" if value else "Skin.Reset(") + key + ")", True)
                return True
            if (
                isinstance(value, str)
                and len(value) <= 128
                and not any(c in value for c in ['"', ",", ")", "\\", "://", "/"])
            ):
                xbmc.executebuiltin("Skin.SetString(" + key + "," + value + ")", True)
                return True
            return False
        target = xbmcaddon.Addon(addon)
        if key not in self.supported(target):
            return False
        target.setSetting(key, str(value))
        if addon == "plugin.video.stream-cinema":
            self.window.clearProperty("SC:stream_filter_prefs")
        if addon == "service.sc.profilesync":
            self.monitor.settings_changed.set()
        return target.getSetting(key) == str(value)

    def persist_preferences(self, preferences):
        self.monitor.check_running()
        # Kodi 21's JSON-RPC setter does not save guisettings.xml. This idempotent
        # private skin flag invokes Kodi's native Save without changing the UI.
        xbmc.executebuiltin("Skin.SetBool(scprofilesync.internal.settingssaved,false)", True)
        saved = ET.parse(self.core_settings).getroot()
        for key, value in preferences.get("kodi", {}).items():
            node = saved.find("setting[@id='" + key + "']")
            if node is None or not saved_value_matches(node.text or "", value):
                raise OSError("Kodi preference was not saved: " + key)

    @staticmethod
    def get_sc_setting(key):
        return xbmcaddon.Addon("plugin.video.stream-cinema").getSetting(key)

    @staticmethod
    def set_sc_setting(key, value):
        xbmcaddon.Addon("plugin.video.stream-cinema").setSetting(key, value)

    def invalidate(self, namespaces):
        self.monitor.check_running()
        token = str(time.time_ns())
        for namespace in namespaces:
            self.window.setProperty("sc.profile.sync." + namespace, token)

    def status(self, value):
        write(self.directory / "status.json", value)

    def run(self):
        try:
            self._run()
        except SyncStopped:
            pass
        finally:
            xbmc.log("[service.sc.profilesync] Worker stopped", xbmc.LOGINFO)

    def _run(self):
        if self.monitor.wait_for_stop(12):
            return
        device = identity(self.directory)
        try:
            saved = read(self.directory / "state.json")
        except (ValueError, OSError):
            path = self.directory / "state.json"
            path.rename(path.with_name("state.corrupt-" + str(int(time.time())) + ".json"))
            saved = None
        engine = Engine(device, saved)
        adapter = Adapter(
            self.database, self.preferences, self.apply_preference, self.invalidate, self.persist_preferences
        )
        worker = Worker(
            engine,
            adapter,
            Kra(self.get_sc_setting, self.set_sc_setting, self.monitor.check_running, self.monitor.wait_for_stop),
            self.directory / "state.json",
            playing=lambda: bool(xbmc.Player().isPlaying()),
            status=self.status,
            check_running=self.monitor.check_running,
        )
        schedule = Schedule()
        subtitles = SubtitleService(
            self.call_rpc,
            lambda: xbmcaddon.Addon("service.sc.profilesync").getSetting("hide_subtitles_for_czech_audio") != "false",
        )
        try:
            subtitles.start()
            self.monitor.settings_changed.set()
            while not self.monitor.stopping():
                self._cycle(schedule, worker, engine)
                # No database/settings polling here: Schedule owns capture cadence.
                if self.monitor.wait_for_stop(1):
                    break
        finally:
            subtitles.close()

    def _cycle(self, schedule, worker, engine):
        try:
            self.monitor.check_running()
            if self.monitor.settings_changed.is_set():
                self.monitor.settings_changed.clear()
                schedule.configure(
                    self.addon.getSetting("local_interval"), self.addon.getSetting("remote_interval")
                )
            if self.monitor.pending.is_set():
                self.monitor.pending.clear()
                # Allow the playback addon to finish persisting its Stop callback.
                schedule.request(delay=2)
            if self.window.getProperty("sc.profile.sync.request"):
                self.window.clearProperty("sc.profile.sync.request")
                schedule.request()
            capture, network = schedule.take()
            if self.database.exists() and self.addon.getSetting("enabled") != "false":
                if network:
                    worker.sync()
                    schedule.success()
                elif capture:
                    worker.capture()
        except SyncStopped:
            raise
        except Exception as error:
            # Exception messages may contain private URLs; report only the class.
            self.status(
                {
                    "ok": False,
                    "error": type(error).__name__,
                    "retry_seconds": schedule.failure(),
                    "pending_upload": engine.dirty,
                }
            )
            xbmc.log("[service.sc.profilesync] Sync deferred: " + type(error).__name__, xbmc.LOGWARNING)
            worker.save()


def saved_value_matches(text, value):
    if type(value) is bool:
        return text.lower() == str(value).lower()
    if isinstance(value, list):
        return text == ",".join(str(part) for part in value)
    if type(value) in (int, float):
        try:
            return float(text) == value
        except ValueError:
            return False
    return text == value
