"""A bounded resume choice for episode transitions initiated by Up Next."""

import math
import re
import time

FLAG = 'sc_next_resume'
GRACE_SECONDS = 5
EPISODE_ROUTE = re.compile(r'/Play/[A-Za-z0-9_-]+/[0-9]+/[1-9][0-9]*')
ACTION_CANCEL = {9, 10, 13, 92, 216}


def play_command(play_info, make_uri):
    """The provider callback marks only episodes and bypasses Kodi's first prompt."""
    uri = make_uri(dict(play_info))
    if not EPISODE_ROUTE.fullmatch(str(play_info.get('url', ''))):
        return 'PlayMedia(%s)' % uri
    separator = '&' if '?' in uri else '?'
    return 'PlayMedia(%s%s%s=31,noresume)' % (uri, separator, FLAG)


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
