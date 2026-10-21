"""Register shutdown before importing networking or starting profile work."""

from threading import Event
import time

import xbmc
import xbmcgui

from .cancellation import SyncStopped


class ProfileMonitor(xbmc.Monitor):
    """Callbacks signal work or shutdown; they never access storage or networking."""

    def __init__(self):
        super().__init__()
        self.pending = Event()
        self.settings_changed = Event()
        self.quitting = Event()
        self.window = xbmcgui.Window(10000)
        self.window.clearProperty("Amber.ShuttingDown")

    def onNotification(self, sender, method, data):
        if method == "System.OnQuit":
            self.quitting.set()
            # Skin unload hooks must not schedule a deferred save during teardown.
            self.window.setProperty("Amber.ShuttingDown", "true")
            xbmc.log("[service.sc.profilesync] Quit received; cancelling background work", xbmc.LOGINFO)
        elif method in ("Player.OnStop", "System.OnWake"):
            self.pending.set()

    def onScreensaverDeactivated(self):
        self.pending.set()

    def onDPMSDeactivated(self):
        self.pending.set()

    def onSettingsChanged(self):
        self.settings_changed.set()
        self.pending.set()

    def stopping(self):
        if self.quitting.is_set():
            return True
        if self.abortRequested():
            # Some platforms stop the announcement queue before delivering
            # OnQuit. Native abort still precedes skin unload. Amber ignores
            # this guard when the service was explicitly disabled in Kodi.
            self.quitting.set()
            self.window.setProperty("Amber.ShuttingDown", "true")
            return True
        return False

    def check_running(self):
        if self.stopping():
            raise SyncStopped()

    def wait_for_stop(self, seconds):
        # Kodi announces OnQuit before aborting each service in sequence. Waiting
        # only for this interpreter's abort lets work continue during shutdown.
        deadline = time.monotonic() + seconds
        while not self.stopping():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self.waitForAbort(min(remaining, 0.2)):
                return True
        return True
