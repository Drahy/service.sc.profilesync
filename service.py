"""Start the background profile worker in an isolated Kodi interpreter."""

from resources.lib.lifecycle import ProfileMonitor, SyncStopped

monitor = ProfileMonitor()
try:
    monitor.check_running()
    from resources.lib.runtime import Runtime

    monitor.check_running()
    Runtime(monitor).run()
except SyncStopped:
    pass
finally:
    import xbmc

    # waitForAbort returns before dispatching callbacks when abort is signalled.
    # Drain this thread's queue while its callback objects are still alive.
    xbmc.sleep(1)
    # Unregister native callbacks while this interpreter is still alive.
    monitor = None
