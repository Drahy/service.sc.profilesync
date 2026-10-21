"""Kodi announces Quit before aborting individual service interpreters."""

import importlib
import sys
from types import SimpleNamespace

import pytest

from resources.lib.cancellation import SyncStopped
from resources.lib.kra import Kra, KraError


def monitor(monkeypatch):
    properties = {"Amber.ShuttingDown": "stale"}

    class NativeMonitor:
        def abortRequested(self):
            return False

        def waitForAbort(self, seconds):
            # Native abort remains false while earlier services are shutting down.
            self.onNotification("xbmc", "System.OnQuit", "{}")
            return False

    window = SimpleNamespace(
        clearProperty=lambda key: properties.pop(key, None),
        setProperty=lambda key, value: properties.__setitem__(key, value),
    )
    monkeypatch.setitem(sys.modules, "xbmc", SimpleNamespace(Monitor=NativeMonitor, log=lambda *args: None, LOGINFO=1))
    monkeypatch.setitem(sys.modules, "xbmcgui", SimpleNamespace(Window=lambda _: window))
    monkeypatch.delitem(sys.modules, "resources.lib.lifecycle", raising=False)
    module = importlib.import_module("resources.lib.lifecycle")
    return module.ProfileMonitor(), properties


def test_quit_interrupts_startup_before_native_service_abort(monkeypatch):
    client, properties = monitor(monkeypatch)
    assert "Amber.ShuttingDown" not in properties
    assert client.wait_for_stop(12)
    assert not client.abortRequested()
    assert properties["Amber.ShuttingDown"] == "true"
    with pytest.raises(SyncStopped):
        client.check_running()


def test_stop_and_wake_queue_sync_without_marking_kodi_as_quitting(monkeypatch):
    client, properties = monitor(monkeypatch)
    for notification in ("Player.OnStop", "System.OnWake"):
        client.pending.clear()
        client.onNotification("xbmc", notification, "{}")
        assert client.pending.is_set()
        assert not client.stopping()
        assert "Amber.ShuttingDown" not in properties


def test_native_abort_guards_skin_when_quit_announcement_is_not_delivered(monkeypatch):
    client, properties = monitor(monkeypatch)
    client.abortRequested = lambda: True
    assert client.wait_for_stop(12)
    assert properties["Amber.ShuttingDown"] == "true"


def test_upload_readback_wait_is_cancellable_without_acknowledging_it():
    client = Kra(lambda _: "private-placeholder", wait=lambda _: True)
    client._request = lambda *args, **kwargs: {
        "data": {"ident": "private-file", "link": "https://upload.kra.sk/create"}
    }
    client.session = SimpleNamespace(
        post=lambda *args, **kwargs: SimpleNamespace(status_code=201, headers={"Location": "/profile"}),
        patch=lambda *args, **kwargs: SimpleNamespace(status_code=204),
    )
    attempts = []

    def not_yet_resolvable(file):
        attempts.append(file)
        raise KraError("not yet available")

    client.download = not_yet_resolvable
    with pytest.raises(SyncStopped):
        client.upload("kodi-profile-v1-" + "a" * 32 + "-000000000001.json", b"{}")
    assert len(attempts) == 1


def test_quit_after_http_response_prevents_reauthentication_or_next_request():
    stopped = False

    def check():
        if stopped:
            raise SyncStopped()

    def request(*args, **kwargs):
        nonlocal stopped
        stopped = True
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"error": "expired"})

    client = Kra(lambda _: "private-placeholder", check_running=check)
    client.session = SimpleNamespace(post=request)
    client.login = lambda: pytest.fail("Do not reauthenticate after Quit")
    with pytest.raises(SyncStopped):
        client.list()


def test_existing_worker_follows_session_refreshed_by_stream_cinema():
    settings = {"kraska.token": "earlier-session"}
    client = Kra(settings.get)
    settings["kraska.token"] = "refreshed-session"
    sent = []

    def request(url, json, **kwargs):
        sent.append(json["session_id"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": []})

    client.session = SimpleNamespace(post=request)
    client.login = lambda: pytest.fail("Reuse the session already refreshed locally")
    assert client.list() == []
    assert sent == ["refreshed-session"]
