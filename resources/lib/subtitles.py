"""Apply language choices independently of network synchronization."""

from threading import Event, Thread

from .cancellation import SyncStopped
import time

import xbmc

CZECH = {"cs", "cz", "ces", "cze", "czech", "čeština"}
ENGLISH = {"en", "eng", "english"}


def language(value):
    return str(value or "").strip().lower().replace("_", "-").split("-")[0]


def choose_subtitle(streams):
    for languages in (CZECH, ENGLISH):
        candidates = [stream for stream in streams if language(stream.get("language")) in languages]
        if candidates:
            return min(
                candidates,
                key=lambda item: (
                    bool(item.get("isforced")),
                    bool(item.get("isimpaired")),
                    not bool(item.get("isdefault")),
                    item["index"],
                ),
            )["index"]
    return None


class SubtitleController:
    def __init__(self, rpc):
        self.rpc = rpc
        self.previous = None

    def apply(self, reset=False):
        active = next((item for item in self.rpc("Player.GetActivePlayers") if item["type"] == "video"), None)
        if not active:
            self.previous = None
            return
        player = active["playerid"]
        properties = self.rpc(
            "Player.GetProperties",
            {
                "playerid": player,
                "properties": ["currentaudiostream", "subtitles", "currentsubtitle", "subtitleenabled"],
            },
        )
        audio = properties.get("currentaudiostream", {})
        streams = properties.get("subtitles", [])
        signature = (
            player,
            audio.get("index"),
            language(audio.get("language")),
            tuple((item["index"], language(item.get("language"))) for item in streams),
        )
        enabled = properties.get("subtitleenabled", False)
        current = properties.get("currentsubtitle", {})
        if language(audio.get("language")) in CZECH:
            if enabled:
                self.rpc("Player.SetSubtitle", {"playerid": player, "subtitle": "off"})
        elif (
            reset
            or signature != self.previous
            or (enabled and language(current.get("language")) not in CZECH | ENGLISH)
        ):
            index = choose_subtitle(streams)
            if index is None:
                if enabled:
                    self.rpc("Player.SetSubtitle", {"playerid": player, "subtitle": "off"})
            elif current.get("index") != index:
                self.rpc("Player.SetSubtitle", {"playerid": player, "subtitle": index, "enable": True})
            elif not enabled:
                # Selecting the current index reopens its decoder in Kodi 21.
                # Visibility changes must not reload a live subtitle renderer.
                self.rpc("Player.SetSubtitle", {"playerid": player, "subtitle": "on"})
        self.previous = signature


class SubtitleMonitor(xbmc.Monitor):
    def __init__(self, pending, restart, stopped, closed=None):
        super().__init__()
        self.pending, self.restart, self.stopped = pending, restart, stopped
        self.closed = closed

    def onNotification(self, sender, method, data):
        if self.closed is not None and self.closed.is_set():
            return
        if method == "System.OnQuit" and self.closed is not None:
            self.closed.set()
            self.stopped.set()
            self.pending.clear()
            self.restart.clear()
            return
        if method in ("Player.OnPlay", "Player.OnAVStart"):
            self.stopped.clear()
            self.restart.set()
            self.pending.set()
        elif method in ("Player.OnAVChange", "Player.OnResume", "System.OnWake"):
            self.pending.set()
        elif method == "Player.OnStop":
            self.stopped.set()
            self.pending.clear()
            self.restart.clear()


class SubtitleService:
    def __init__(self, rpc, enabled):
        self.controller = SubtitleController(rpc)
        self.enabled = enabled
        self.pending, self.restart, self.closed = Event(), Event(), Event()
        self.stopped = Event()
        self.thread = Thread(target=self.run, name="SCProfileSubtitles", daemon=True)

    def start(self):
        self.restart.set()
        self.pending.set()
        self.thread.start()

    def run(self):
        # Deliver notifications on this thread independently of network waits.
        # Avoid registering another Player callback object during Stop cleanup.
        monitor = SubtitleMonitor(self.pending, self.restart, self.stopped, self.closed)
        settling = []
        try:
            self._watch(monitor, settling)
        finally:
            self.closed.set()
            # Kodi clears only the invoker thread's queue at interpreter exit.
            # Dispatch this worker's queued notifications before its thread state
            # disappears, including those skipped by waitForAbort on native abort.
            xbmc.sleep(1)
            del monitor

    def _watch(self, monitor, settling):
        while not self.closed.is_set() and not monitor.waitForAbort(0.5):
            if self.stopped.is_set():
                settling.clear()
                self.controller.previous = None
                continue
            now = time.monotonic()
            due = any(deadline <= now for deadline in settling)
            settling = [deadline for deadline in settling if deadline > now]
            if not self.pending.is_set() and not due:
                continue
            self.pending.clear()
            reset = self.restart.is_set()
            self.restart.clear()
            if reset:
                # Cover a provider enabling subtitles after its AVStarted callback.
                settling = [now + delay for delay in (1, 3, 6)]
            try:
                if self.enabled():
                    self.controller.apply(reset)
            except SyncStopped:
                break
            except (ValueError, KeyError, RuntimeError):
                # A player may disappear between GetActivePlayers and GetProperties.
                pass

    def close(self):
        self.closed.set()
        self.pending.set()
        self.thread.join(timeout=2)
