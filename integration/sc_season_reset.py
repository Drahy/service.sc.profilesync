"""Stream Cinema's confirmed season reset action."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.common.season_reset_data import NAMESPACE, SEASON_ROUTE, reset_rows
from resources.lib.constants import ADDON


ACTION = 'reset_season_history'
PROFILE = 'service.sc.profilesync'


def destination(route):
    if not isinstance(route, str):
        return None
    parts = urlsplit(route)
    return SEASON_ROUTE.fullmatch(parts.path) if not (parts.scheme or parts.netloc) else None


def available():
    try:
        version = xbmcaddon.Addon(PROFILE).getAddonInfo('version')
        return tuple(int(part) for part in version.split('.')[:3]) >= (0, 1, 6)
    except (RuntimeError, ValueError):
        return False


def label():
    return xbmcaddon.Addon(PROFILE).getLocalizedString(30012)


def context(route, parent):
    target = destination(route)
    if target and isinstance(parent, str) and urlsplit(parent).path == '/FGet/' + target[1] and available():
        return target[0]
    return ''


def reset_database(database, show, start, when):
    namespaces = ('SCKODIItem-' + show, 'all_watched', 'nextep', NAMESPACE)
    with closing(sqlite3.connect(database.as_uri() + '?mode=rw', uri=True, timeout=1)) as connection:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            rows = {key: json.loads(raw) for key, raw in connection.execute(
                'SELECT item_key,item_value FROM storage WHERE item_key IN (?,?,?,?)', namespaces)}
            changes = reset_rows(rows, show, start, when)
            connection.executemany('INSERT OR REPLACE INTO storage(item_key,item_value) VALUES(?,?)',
                                   ((key, json.dumps(value, ensure_ascii=False)) for key, value in changes.items()))
    return changes


def confirm(route):
    target = destination(route)
    if not target or not available():
        return
    show, season = target.groups()
    start = int(season)
    text = xbmcaddon.Addon(PROFILE).getLocalizedString
    dialog = xbmcgui.Dialog()
    player = xbmc.Player()
    if player.isPlaying():
        dialog.ok(text(30012), text(30014))
        return
    if not dialog.yesno(text(30012), text(30013).format(season), yeslabel=text(30015)):
        return
    if player.isPlaying():
        dialog.ok(text(30012), text(30014))
        return
    database = Path(xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))) / 'storage.db'
    try:
        changes = reset_database(database, show, start, time.time_ns() // 1_000_000)
    except (OSError, TypeError, ValueError, sqlite3.Error):
        dialog.ok(text(30012), text(30016))
        return
    window = xbmcgui.Window(10000)
    token = str(time.time_ns())
    for namespace in changes:
        window.setProperty('sc.profile.sync.' + namespace, token)
    window.setProperty('sc.profile.sync.request', 'true')
    xbmc.executebuiltin('Container.Refresh')
