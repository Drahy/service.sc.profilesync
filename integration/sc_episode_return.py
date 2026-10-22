"""Local episode-directory targets; copied to SC common/episode_return.py."""

import json
import os
import re
import time
from urllib.parse import urlencode

INSIDE_PROPERTY = 'sc.profile.browse.inside'
REQUEST_PROPERTY = 'sc.profile.browse.open'
EPISODE = re.compile(r'/Play/([1-9][0-9]*)/([0-9]+)/([1-9][0-9]*)')
LAST = re.compile(r'([0-9]+)x([1-9][0-9]*)')


def target(history, read_last, state):
    """Prefer actual shared viewing history over an arbitrary browsed row."""
    for value in list(history)[:20]:
        show = str(value)
        if not re.fullmatch(r'[1-9][0-9]*', show):
            continue
        last = read_last(show)
        match = LAST.fullmatch(last) if isinstance(last, str) else None
        if match:
            season, episode = match.groups()
            break
    else:
        saved = state.get('episode') or state.get('checkpoint') or {}
        match = EPISODE.fullmatch(saved.get('item', ''))
        if not match:
            return None
        show, season, episode = match.groups()
    return {'id': show, 'url': '/FGet/%s/%s' % (show, int(season)),
            'resume_episode': str(int(episode)), 'navigation_restore': '1'}


def load_target(state):
    """Read existing local/shared storage without resolving a stream or API call."""
    try:
        from resources.lib.common.lists import List
        from resources.lib.common.storage import Storage
        from resources.lib.gui.item import get_history_item_name

        history = List(get_history_item_name('lasts')).get()
        return target(history, lambda show: Storage('SCKODIItem-' + show).get('last_ep'), state)
    except Exception:
        return target([], lambda show: None, state)


def folder_uri(args):
    return 'plugin://plugin.video.stream-cinema/?' + urlencode(
        {key: str(value).encode('utf-8').hex() for key, value in args.items()})


def prepare_entry(args):
    """Redirect a fresh main entry, while retaining ordinary Back-to-menu navigation."""
    if args.get('url', '/') != '/' or any(key in args for key in ('action', 'play', 'widget', 'navigation_restore')):
        return None
    import xbmc
    import xbmcgui
    import xbmcvfs
    from resources.lib.constants import ADDON

    home = xbmcgui.Window(10000)
    if home.getProperty(INSIDE_PROPERTY) == '1' or xbmc.Player().isPlaying():
        return None
    try:
        filename = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo('profile')), 'navigation-state.json')
        with open(filename, encoding='utf-8') as source:
            state = json.load(source)
        if not isinstance(state, dict):
            state = {}
    except (OSError, ValueError):
        state = {}
    result = load_target(state)
    if result:
        home.setProperty(INSIDE_PROPERTY, '1')
        home.setProperty(REQUEST_PROPERTY, json.dumps({'target': result, 'expires': time.time() + 90}))
    return result
