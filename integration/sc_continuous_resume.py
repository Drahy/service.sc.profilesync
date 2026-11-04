"""A bounded resume choice for episode transitions initiated by Up Next."""

import math
import os
import re
import sqlite3
import threading
import time
import uuid

FLAG = 'sc_next_resume'
TOKEN = 'sc_next_token'
GRACE_SECONDS = 5
PENDING_LEASE_SECONDS = 60
HEARTBEAT_SECONDS = 15
COMPLETED_GRACE_SECONDS = 15
EPISODE_ROUTE = re.compile(r'/Play/[A-Za-z0-9_-]+/[0-9]+/[1-9][0-9]*')
ACTION_CANCEL = {9, 10, 13, 92, 216}


def play_command(play_info, make_uri, token=''):
    """The provider callback marks only episodes and bypasses Kodi's first prompt."""
    uri = make_uri(dict(play_info))
    if not EPISODE_ROUTE.fullmatch(str(play_info.get('url', ''))):
        return 'PlayMedia(%s)' % uri
    separator = '&' if '?' in uri else '?'
    token_arg = '&%s=%s' % (TOKEN, token.encode('ascii').hex()) if token else ''
    return 'PlayMedia(%s%s%s=31%s,noresume)' % (uri, separator, FLAG, token_arg)


def _guard_path():
    import xbmcvfs
    return xbmcvfs.translatePath('special://profile/addon_data/plugin.video.stream-cinema/sc_next_transition.db')


def _connect(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    connection = sqlite3.connect(path, timeout=0.5)
    connection.execute('CREATE TABLE IF NOT EXISTS transitions '
                       '(route TEXT PRIMARY KEY, token TEXT NOT NULL, started REAL NOT NULL, expires REAL NOT NULL)')
    return connection


def claim_transition(play_info, path=None, now=None):
    """Atomically ignore repeated Up Next callbacks for a transition already in progress."""
    route = str(play_info.get('url', ''))
    if not EPISODE_ROUTE.fullmatch(route):
        return ''  # Preserve ordinary non-episode playback.
    now = time.time() if now is None else float(now)
    token = uuid.uuid4().hex
    try:
        connection = _connect(path or _guard_path())
        try:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT started, expires FROM transitions WHERE route = ?', (route,)).fetchone()
            if row and row[0] <= now < row[1]:
                connection.commit()
                return None
            connection.execute('DELETE FROM transitions WHERE expires <= ? OR started > ?', (now, now))
            connection.execute('INSERT OR REPLACE INTO transitions VALUES (?, ?, ?, ?)',
                               (route, token, now, now + PENDING_LEASE_SECONDS))
            connection.commit()
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        return ''  # Never prevent playback if local storage is unavailable.
    return token


def finish_transition(args, success, path=None, now=None):
    """Release a failed/cancelled request; briefly suppress duplicates after success."""
    route, token = str(args.get('url', '')), str(args.get(TOKEN, ''))
    if args.get(FLAG) != '1' or not EPISODE_ROUTE.fullmatch(route) or not re.fullmatch('[0-9a-f]{32}', token):
        return
    now = time.time() if now is None else float(now)
    try:
        connection = _connect(path or _guard_path())
        try:
            with connection:
                if success:
                    connection.execute('UPDATE transitions SET started = ?, expires = ? WHERE route = ? AND token = ?',
                                       (now, now + COMPLETED_GRACE_SECONDS, route, token))
                else:
                    connection.execute('DELETE FROM transitions WHERE route = ? AND token = ?', (route, token))
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        pass


def renew_transition(args, path=None, now=None):
    route, token = str(args.get('url', '')), str(args.get(TOKEN, ''))
    if args.get(FLAG) != '1' or not EPISODE_ROUTE.fullmatch(route) or not re.fullmatch('[0-9a-f]{32}', token):
        return
    now = time.time() if now is None else float(now)
    try:
        connection = _connect(path or _guard_path())
        try:
            with connection:
                connection.execute('UPDATE transitions SET started = ?, expires = ? WHERE route = ? AND token = ?',
                                   (now, now + PENDING_LEASE_SECONDS, route, token))
        finally:
            connection.close()
    except (OSError, sqlite3.Error):
        pass


def start_heartbeat(args):
    if args.get(FLAG) != '1' or not re.fullmatch('[0-9a-f]{32}', str(args.get(TOKEN, ''))):
        return None
    stopped = threading.Event()

    def run():
        while not stopped.wait(HEARTBEAT_SECONDS):
            renew_transition(args)

    thread = threading.Thread(target=run, name='sc-next-transition', daemon=True)
    thread.start()
    return stopped, thread


def stop_heartbeat(heartbeat):
    if heartbeat:
        stopped, thread = heartbeat
        stopped.set()
        thread.join(timeout=1)


def saved_position(data, read):
    info = data.get('info') or {}
    show = str(data.get('id', ''))
    try:
        season, episode = int(info['season']), int(info['episode'])
        duration = float(info.get('duration') or 0)
        if not re.fullmatch('[1-9][0-9]*', show) or season < 0 or episode <= 0:
            return 0.0, max(0, duration) if math.isfinite(duration) else 0.0
    except (ValueError, TypeError, KeyError, OverflowError):
        return 0.0, 0.0
    try:
        position = float(read('SCKODIItem-' + show, 'watched:%s:%s' % (season, episode)) or 0)
    except (ValueError, TypeError, OverflowError):
        return 0.0, max(0, duration) if math.isfinite(duration) else 0.0
    if not math.isfinite(position) or not math.isfinite(duration) or position <= 0 or (duration > 0 and position >= duration):
        return 0.0, max(0, duration) if math.isfinite(duration) else 0.0
    return position, max(0, duration)


def timestamp(seconds):
    value = max(0, int(seconds))
    hours, value = divmod(value, 3600)
    minutes, value = divmod(value, 60)
    return ('%d:%02d:%02d' % (hours, minutes, value)) if hours else ('%02d:%02d' % (minutes, value))


class Decision:
    def __init__(self, position):
        self.position = position
        self.ready_at = None
        self.interacted = False
        self.finished = False
        self.value = None

    def select(self, control):
        self.value = {10: 0.0, 11: self.position}.get(control)
        self.finished = True

    def action(self, identifier):
        if identifier in ACTION_CANCEL:
            self.select(12)
        elif identifier in (1, 2, 3, 4):
            self.interacted = True

    def remaining(self, now):
        if self.ready_at is None or self.interacted:
            return None
        remaining = max(0, GRACE_SECONDS - (now - self.ready_at))
        if remaining == 0:
            self.select(10)
        return int(math.ceil(remaining))


def choose_position(position):
    import xbmc
    import xbmcaddon
    import xbmcgui

    addon = xbmcaddon.Addon('plugin.video.stream-cinema')
    text = addon.getLocalizedString

    class ShutdownMonitor(xbmc.Monitor):
        quitting = False

        def onNotification(self, sender, method, data):
            if method == 'System.OnQuit':
                self.quitting = True

    class ResumeWindow(xbmcgui.WindowXMLDialog):
        def onInit(self):
            self.getControl(20).setLabel(text(30992))
            self.getControl(10).setLabel(text(30993))
            self.getControl(11).setLabel(text(30994).format(time=timestamp(position)))
            self.getControl(12).setLabel(text(30997))
            self.setFocusId(10)
            self.decision.ready_at = time.monotonic()

        def onClick(self, control):
            if control in (10, 11, 12):
                self.decision.select(control)

        def onAction(self, action):
            self.decision.action(action.getId())

    monitor = ShutdownMonitor()
    window = ResumeWindow('sc-next-resume.xml', addon.getAddonInfo('path'), 'default', '1080i')
    decision = window.decision = Decision(position)
    started = time.monotonic()
    label = None
    try:
        window.show()
        while not decision.finished and not monitor.quitting and not monitor.abortRequested():
            now = time.monotonic()
            remaining = decision.remaining(now)
            if decision.ready_at is None:
                if now - started > 10:
                    break
            else:
                message = text(30996) if decision.interacted else text(30995).format(seconds=remaining)
                if message != label:
                    window.getControl(21).setLabel(message)
                    label = message
            if monitor.waitForAbort(.1):
                break
        if monitor.quitting or monitor.abortRequested():
            return None
        return decision.value
    finally:
        window.close()
        # Drain native callbacks while their Python owners still exist.
        xbmc.sleep(1)
        monitor = None


def prepare(listitem, data, args, read=None, choose=None):
    """Leave manual playback unchanged; never erase the shared resume value."""
    if args.get(FLAG) != '1':
        return True
    if read is None:
        from resources.lib.common.storage import Storage
        read = lambda namespace, field: Storage(namespace).get(field)
    position, duration = saved_position(data, read)
    chosen = (choose or choose_position)(position) if position else 0.0
    if chosen is None:
        return False
    listitem.getVideoInfoTag().setResumePoint(float(chosen), duration)
    return True
