import copy
import importlib
import sys
from types import SimpleNamespace
from threading import Event

import pytest


def module(monkeypatch):
    monkeypatch.setitem(sys.modules, "xbmc", SimpleNamespace(Monitor=type("Monitor", (), {})))
    monkeypatch.delitem(sys.modules, "resources.lib.subtitles", raising=False)
    return importlib.import_module("resources.lib.subtitles")


def test_abort_drains_worker_callbacks_before_the_thread_disappears(monkeypatch):
    policy = module(monkeypatch)
    queued, destroyed, calls = [], [], []
    original = policy.SubtitleMonitor

    class AbortMonitor(original):
        def __init__(self, *args):
            super().__init__(*args)
            queued.append(lambda: self.onNotification("xbmc", "Player.OnAVStart", "{}"))

        def waitForAbort(self, _):
            return True  # Kodi's native path does not dispatch queued callbacks.

        def __del__(self):
            destroyed.append(not queued)

    def dispatch(_):
        while queued:
            queued.pop(0)()

    monkeypatch.setattr(policy, "SubtitleMonitor", AbortMonitor)
    monkeypatch.setattr(policy.xbmc, "sleep", dispatch, raising=False)
    service = policy.SubtitleService(lambda *args: calls.append(args), lambda: True)
    service.start()
    service.thread.join(timeout=2)
    assert not service.thread.is_alive()
    assert not queued and destroyed == [True]
    assert not calls


def controller(monkeypatch, audio="ces", enabled=True, streams=None):
    policy = module(monkeypatch)
    properties = {
        "currentaudiostream": {"index": 0, "language": audio},
        "subtitles": (
            streams
            if streams is not None
            else [{"index": 0, "language": "deu"}, {"index": 1, "language": "eng"}, {"index": 2, "language": "cze"}]
        ),
        "currentsubtitle": {"index": 0, "language": "deu"},
        "subtitleenabled": enabled,
    }
    actions = []

    def rpc(method, params=None):
        if method == "Player.GetActivePlayers":
            return [{"type": "video", "playerid": 1}]
        if method == "Player.GetProperties":
            return copy.deepcopy(properties)
        assert method == "Player.SetSubtitle"
        actions.append(params)
        properties["subtitleenabled"] = params["subtitle"] != "off"
        if type(params["subtitle"]) is int:
            properties["currentsubtitle"] = next(
                item for item in properties["subtitles"] if item["index"] == params["subtitle"]
            )

    return policy.SubtitleController(rpc), properties, actions


@pytest.mark.parametrize("audio", ["cs", "CZ", "ces", "cze", "cs-CZ", "Czech", "čeština"])
def test_czech_audio_hides_even_forced_subtitles(monkeypatch, audio):
    client, props, actions = controller(monkeypatch, audio)
    props["subtitles"][2]["isforced"] = True
    client.apply(reset=True)
    assert actions == [{"playerid": 1, "subtitle": "off"}]
    client.apply()
    assert len(actions) == 1


def test_audio_switch_and_manual_subtitle_disable(monkeypatch):
    client, props, actions = controller(monkeypatch)
    client.apply(reset=True)
    props["currentaudiostream"] = {"index": 1, "language": "eng"}
    client.apply()
    assert actions[-1] == {"playerid": 1, "subtitle": 2, "enable": True}
    props["subtitleenabled"] = False  # Explicit user choice during the same audio track.
    client.apply()
    assert len(actions) == 2
    props["currentaudiostream"] = {"index": 0, "language": "ces"}
    props["subtitleenabled"] = True
    client.apply()
    assert actions[-1]["subtitle"] == "off"


def test_english_fallback_and_foreign_only_tracks(monkeypatch):
    client, props, actions = controller(monkeypatch, "eng", streams=[{"index": 4, "language": "en-US"}])
    client.apply(reset=True)
    assert actions[-1]["subtitle"] == 4
    props["subtitles"] = [{"index": 5, "language": "fra"}]
    client.apply()
    assert actions[-1]["subtitle"] == "off"


def test_complete_czech_subtitles_are_preferred(monkeypatch):
    policy = module(monkeypatch)
    assert (
        policy.choose_subtitle(
            [
                {"index": 0, "language": "ces", "isforced": True},
                {"index": 1, "language": "eng", "isdefault": True},
                {"index": 2, "language": "cs"},
            ]
        )
        == 2
    )


def test_notifications_only_queue_work_and_stop_clears_pending_actions(monkeypatch):
    policy = module(monkeypatch)
    pending, restart, stopped = Event(), Event(), Event()
    monitor = policy.SubtitleMonitor(pending, restart, stopped)
    monitor.onNotification("xbmc", "Player.OnAVStart", "{}")
    assert pending.is_set() and restart.is_set() and not stopped.is_set()
    monitor.onNotification("xbmc", "Player.OnStop", "{}")
    assert stopped.is_set() and not pending.is_set() and not restart.is_set()
    monitor.onNotification("xbmc", "Player.OnPlay", "{}")
    assert not stopped.is_set() and pending.is_set()


def test_enabling_the_selected_track_does_not_reopen_its_decoder(monkeypatch):
    client, props, actions = controller(monkeypatch, "eng", enabled=False)
    props["currentsubtitle"] = {"index": 2, "language": "ces"}
    client.apply(reset=True)
    assert actions == [{"playerid": 1, "subtitle": "on"}]
