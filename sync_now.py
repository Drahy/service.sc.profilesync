"""Request background synchronization without blocking the caller."""

import xbmcgui

xbmcgui.Window(10000).setProperty("sc.profile.sync.request", "true")
