# -*- coding: utf-8 -*-
"""Restore Stream Cinema episode selection on startup, reentry and wake."""

import json
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib.constants import ADDON, ADDON_ID
from resources.lib.common.logger import debug
from resources.lib.common import resume_browse
from resources.lib.common import episode_return


RESTORE_PARAMETER = 'navigation_restore'
VIDEO_WINDOW = 10025


def route_args(uri):
    parts = urlsplit(uri)
    if parts.scheme != 'plugin' or parts.netloc != ADDON_ID:
        return {}
    result = {}
    for key, value in parse_qsl(parts.query):
        try:
            value = bytes.fromhex(value).decode('utf-8')
        except (ValueError, UnicodeError):
            pass
        result[key] = value
    return result


def canonical_uri(uri):
    if not isinstance(uri, str) or any(char in uri for char in ('"', '\r', '\n')):
        return ''
    parts = urlsplit(uri)
    if parts.scheme != 'plugin' or parts.netloc != ADDON_ID:
        return ''
    query = [(key, value) for key, value in parse_qsl(parts.query) if key != RESTORE_PARAMETER]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(sorted(query)), ''))


def safe_folder(uri):
    uri = canonical_uri(uri)
    if not uri:
        return ''
    args = route_args(uri)
    route = args.get('url', '/')
    if not route.startswith('/') or route.startswith('/Play/'):
        return ''
    if args.get('action') in ('cmd', 'play', 'play_url', 'force_select_stream'):
        return ''
    return uri


def restoring_uri(uri):
    parts = urlsplit(safe_folder(uri))
    if not parts.scheme:
        return ''
    query = parse_qsl(parts.query) + [(RESTORE_PARAMETER, '1'.encode('utf-8').hex())]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def item_key(uri):
    canonical = canonical_uri(uri)
    if not canonical:
        return ''
    args = route_args(canonical)
    route = args.get('url', '')
    if re.fullmatch(r'/Play/\d+(?:/\d+/\d+)?', route):
        return route
    alias = re.fullmatch(r'/Play/[A-Za-z0-9_-]+(/\d+/\d+)?', route)
    if alias and str(args.get('id', '')).isdigit():
        return '/Play/' + str(args['id']) + (alias.group(1) or '')
    return canonical


class NavigationRecovery:
    START_DELAY = 3
    RESTORE_TIMEOUT = 90

    def __init__(self, monitor, player):
        self.monitor = monitor
        self.player = player
        profile = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
        os.makedirs(profile, exist_ok=True)
        self.filename = os.path.join(profile, 'navigation-state.json')
        self.state = self._read()
        previous = self.state.get('session', {})
        checkpoint = self.state.get('checkpoint', {})
        target = episode_return.load_target(self.state)
        interrupted = previous.get('clean') is False and checkpoint.get('active')
        self.pending = bool((interrupted or target) and previous.get('pid') != os.getpid()
                            and not previous.get('restoring')
                            and (target or safe_folder(checkpoint.get('folder', ''))))
        if self.pending and target:
            self.state['checkpoint'] = self._target_checkpoint(target)
        self.started = time.monotonic()
        self.issued = False
        self.deadline = None
        self.force_entry = False
        self.wake_serial = getattr(monitor, 'navigation_wake', 0)
        self.sleeping = monitor.is_DPMS or monitor.is_screensaver
        self.last_tick = time.time()
        self.state['session'] = {'pid': os.getpid(), 'clean': False, 'restoring': False}
        self._save()

    def _target_checkpoint(self, target):
        previous = self.state.get('episode') or self.state.get('checkpoint', {})
        return {'folder': canonical_uri(episode_return.folder_uri(target)),
                'item': '/Play/%s/%s/%s' % (target['id'], target['url'].rsplit('/', 1)[-1], target['resume_episode']),
                'control': previous.get('control', 50), 'active': True}

    def _read(self):
        try:
            with open(self.filename, encoding='utf-8') as source:
                state = json.load(source)
            if (isinstance(state, dict) and state.get('version') == 1
                    and isinstance(state.get('session'), dict) and isinstance(state.get('checkpoint'), dict)):
                old_item = state['checkpoint'].get('item', '')
                if isinstance(old_item, str) and old_item.startswith('plugin://'):
                    state['checkpoint']['item'] = item_key(old_item)
                return state
        except (OSError, ValueError, TypeError):
            pass
        return {'version': 1, 'checkpoint': {}}

    def _save(self):
        temporary = self.filename + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as output:
            json.dump(self.state, output, ensure_ascii=False, sort_keys=True)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, self.filename)

    def _update(self, checkpoint):
        changed = self.state.get('checkpoint') != checkpoint
        if episode_return.EPISODE.fullmatch(checkpoint.get('item', '')):
            if self.state.get('episode') != checkpoint:
                self.state['episode'] = dict(checkpoint)
                changed = True
        if changed:
            self.state['checkpoint'] = checkpoint
            self._save()

    def lifecycle(self):
        sleeping = self.monitor.is_DPMS or self.monitor.is_screensaver
        serial = getattr(self.monitor, 'navigation_wake', 0)
        now = time.time()
        # Android can suspend the interpreter without a Kodi DPMS announcement.
        woke = serial != self.wake_serial or (self.sleeping and not sleeping) or now - self.last_tick > 15
        self.wake_serial, self.sleeping, self.last_tick = serial, sleeping, now
        if not woke or sleeping:
            return
        xbmcgui.Window(10000).clearProperty(episode_return.INSIDE_PROPERTY)
        if self.player.isPlayback():
            return
        target = episode_return.load_target(self.state)
        if target:
            self.state['checkpoint'] = self._target_checkpoint(target)
            self.pending, self.issued, self.force_entry = True, False, True
            self.started = time.monotonic() - self.START_DELAY

    @staticmethod
    def _list_control(window, preferred=None):
        for identifier in dict.fromkeys([window.getFocusId(), preferred]):
            if identifier is None:
                continue
            try:
                control = window.getControl(identifier)
                if hasattr(control, 'selectItem') and control.isVisible():
                    return identifier, control
            except (RuntimeError, TypeError):
                pass
        return None, None

    def capture(self):
        if self.monitor.is_DPMS or self.monitor.is_screensaver:
            return
        checkpoint = dict(self.state.get('checkpoint', {}))
        window_id = xbmcgui.getCurrentWindowId()
        home = xbmcgui.Window(10000)
        inside = window_id == VIDEO_WINDOW and safe_folder(xbmc.getInfoLabel('Container.FolderPath'))
        # Only the plugin invocation marks entry. During window activation Kodi
        # can still expose the previous season before the new root request runs.
        if not inside and not (self.player.is_my_plugin and self.player.isPlayback()):
            home.clearProperty(episode_return.INSIDE_PROPERTY)
        if window_id == VIDEO_WINDOW:
            folder = safe_folder(xbmc.getInfoLabel('Container.FolderPath'))
            if folder and not xbmc.getCondVisibility('Container.IsUpdating'):
                window = xbmcgui.Window(VIDEO_WINDOW)
                identifier, control = self._list_control(window, checkpoint.get('control'))
                if control is not None:
                    # Native media containers do not populate Python ControlList.vecItems.
                    position = xbmc.getInfoLabel('Container(%s).CurrentItem' % identifier)
                    key = item_key(xbmc.getInfoLabel('ListItem.FileNameAndPath'))
                    if key:
                        self._update({'folder': folder, 'item': key, 'index': position,
                                      'control': identifier, 'active': True})
                        return
        if self.player.is_my_plugin and self.player.isPlayback():
            info = (self.player.item or {}).get('info', {})
            show, season, episode = self.player.my_id, info.get('season'), info.get('episode')
            previous = re.fullmatch(r'/Play/(\d+)/(\d+)/(\d+)', checkpoint.get('item', ''))
            if previous and show is not None and season is not None and episode is not None:
                old_show, old_season, _ = previous.groups()
                if str(show) == old_show:
                    if str(season) != old_season:
                        # Only infer a new season from the exact observed show/season route.
                        folder_parts = urlsplit(checkpoint['folder'])
                        values = parse_qsl(folder_parts.query)
                        route = route_args(checkpoint['folder']).get('url', '')
                        suffix = '/%s/%s' % (old_show, old_season)
                        if route.endswith(suffix):
                            route = route[:-len(old_season)] + str(season)
                            values = [(key, route.encode('utf-8').hex() if key == 'url' else value)
                                      for key, value in values]
                            checkpoint['folder'] = urlunsplit((folder_parts.scheme, folder_parts.netloc,
                                                              folder_parts.path, urlencode(values), ''))
                        else:
                            return
                    checkpoint['item'] = '/Play/%s/%s/%s' % (show, season, episode)
            if checkpoint:
                checkpoint['active'] = True
                self._update(checkpoint)
            return
        if window_id not in (VIDEO_WINDOW, 12005) or not safe_folder(xbmc.getInfoLabel('Container.FolderPath')):
            if checkpoint.get('active'):
                checkpoint['active'] = False
                self._update(checkpoint)

    def _finish_restore(self):
        self.pending = False
        self.state['session']['restoring'] = False
        self._save()

    def entry_requested(self):
        home = xbmcgui.Window(10000)
        raw = home.getProperty(episode_return.REQUEST_PROPERTY)
        if not raw:
            return False
        try:
            data = json.loads(raw)
            target = data['target']
            focus = resume_browse.focus_request(target['url'], target['resume_episode'])
            if (not focus or str(target['id']) != focus['item'].split('/')[2]
                    or float(data['expires']) < time.time() or self.player.isPlayback()):
                raise ValueError('Expired or invalid episode entry')
            target = {'id': str(target['id']), 'url': focus['route'],
                      'resume_episode': target['resume_episode'], 'navigation_restore': '1'}
        except (ValueError, TypeError, KeyError, AttributeError):
            home.clearProperty(episode_return.REQUEST_PROPERTY)
            return False
        if self.monitor.is_DPMS or self.monitor.is_screensaver or xbmc.getCondVisibility('Container.IsUpdating'):
            return True
        window = xbmcgui.getCurrentWindowId()
        folder = xbmc.getInfoLabel('Container.FolderPath')
        if window not in (10000, VIDEO_WINDOW) or (window == VIDEO_WINDOW and folder.startswith('plugin://') and not safe_folder(folder)):
            home.clearProperty(episode_return.REQUEST_PROPERTY)
            return False
        home.clearProperty(episode_return.REQUEST_PROPERTY)
        self.state['checkpoint'] = self._target_checkpoint(target)
        self.pending, self.issued, self.force_entry = True, False, True
        self.started = time.monotonic() - self.START_DELAY
        # Let the root directory finish before posting the new window request.
        return True

    def focus_requested(self):
        home = xbmcgui.Window(10000)
        raw = home.getProperty(resume_browse.FOCUS_PROPERTY)
        if not raw:
            return False
        try:
            request = json.loads(raw)
            expected = resume_browse.focus_request(request['route'], request['item'].rsplit('/', 1)[-1])
            if (not expected or expected['item'] != request['item']
                    or float(request['expires']) < time.time() or self.player.isPlayback()):
                home.clearProperty(resume_browse.FOCUS_PROPERTY)
                return False
        except (ValueError, TypeError, KeyError, AttributeError):
            home.clearProperty(resume_browse.FOCUS_PROPERTY)
            return False
        if xbmcgui.getCurrentWindowId() != VIDEO_WINDOW or xbmc.getCondVisibility('Container.IsUpdating'):
            return False
        current = safe_folder(xbmc.getInfoLabel('Container.FolderPath'))
        if urlsplit(route_args(current).get('url', '')).path != expected['route']:
            return False
        window = xbmcgui.Window(VIDEO_WINDOW)
        identifier, control = self._list_control(window)
        if control is None:
            return False
        count = (xbmc.getInfoLabel('Container(%s).NumAllItems' % identifier)
                 or xbmc.getInfoLabel('Container(%s).NumItems' % identifier))
        if not count or int(count) == 0:
            return False
        for index in range(int(count) + 1):
            uri = xbmc.getInfoLabel('Container(%s).ListItemAbsolute(%s).FileNameAndPath' % (identifier, index))
            if item_key(uri) == expected['item']:
                window.setFocusId(identifier)
                control.selectItem(index)
                home.clearProperty(resume_browse.FOCUS_PROPERTY)
                return True
        home.clearProperty(resume_browse.FOCUS_PROPERTY)
        return False

    def restore(self):
        now = time.monotonic()
        if self.monitor.is_DPMS or self.monitor.is_screensaver:
            return
        if now - self.started < self.START_DELAY:
            return
        if self.player.isPlayback():
            self._finish_restore()
            return
        if xbmc.getCondVisibility('System.HasModalDialog') or xbmc.getCondVisibility('Container.IsUpdating'):
            if now - self.started > self.RESTORE_TIMEOUT:
                self._finish_restore()
            return
        checkpoint = self.state['checkpoint']
        window_id = xbmcgui.getCurrentWindowId()
        current = safe_folder(xbmc.getInfoLabel('Container.FolderPath'))
        if not self.issued:
            foreign = xbmc.getInfoLabel('Container.FolderPath').startswith('plugin://') and not current
            if (window_id not in (10000, VIDEO_WINDOW) or foreign
                    or (not self.force_entry and current and route_args(current).get('url', '/') != '/')):
                self._finish_restore()
                return
            self.state['session']['restoring'] = True
            self._save()
            self.issued = True
            self.deadline = now + self.RESTORE_TIMEOUT
            xbmc.executebuiltin('ActivateWindow(videos,"%s",return)' % restoring_uri(checkpoint['folder']))
            return
        if now > self.deadline or window_id not in (10000, VIDEO_WINDOW):
            self._finish_restore()
            return
        if window_id != VIDEO_WINDOW or not current:
            return
        if current != checkpoint['folder']:
            if route_args(current).get('url', '/') == '/':
                return
            self._finish_restore()
            return
        window = xbmcgui.Window(VIDEO_WINDOW)
        identifier, control = self._list_control(window, checkpoint.get('control'))
        if control is None:
            return
        count = (xbmc.getInfoLabel('Container(%s).NumAllItems' % identifier)
                 or xbmc.getInfoLabel('Container(%s).NumItems' % identifier))
        if not count or int(count) == 0:
            return
        position = None
        for index in range(int(count) + 1):
            uri = xbmc.getInfoLabel('Container(%s).ListItemAbsolute(%s).FileNameAndPath' % (identifier, index))
            if item_key(uri) == checkpoint['item']:
                position = index
                break
        if position is not None:
            window.setFocusId(identifier)
            control.selectItem(position)
        self._finish_restore()
        debug('Navigation recovery finished' if position is not None else 'Navigation recovery: saved item unavailable')

    def run(self):
        while not self.monitor.abortRequested():
            try:
                self.lifecycle()
                if self.entry_requested():
                    pass
                elif self.focus_requested():
                    pass
                elif self.pending:
                    self.restore()
                else:
                    self.capture()
            except Exception:
                debug('Navigation recovery: state update deferred')
            if self.monitor.waitForAbort(1):
                break
        self.state['session']['clean'] = True
        try:
            self._save()
        except OSError:
            debug('Navigation recovery: clean shutdown marker unavailable')
