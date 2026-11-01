"""Local episode-directory targets; copied to SC common/episode_return.py."""

import json
import os
import re
import time
from urllib.parse import urlencode, parse_qs, urlsplit

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
        from resources.lib.common.resume_browse import most_recent_episode
        from resources.lib.gui.item import get_history_item_name

        history = List(get_history_item_name('lasts')).get()
        return target(history, lambda show: most_recent_episode(Storage('SCKODIItem-' + show).data), state)
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


def request_webshare_stop(window, item, show_id, now=None):
    """Return to a matched episode only when stopping a companion-owned stream."""
    try:
        origin = window.getProperty('sc.webshare.origin')
        selected = json.loads(window.getProperty('SC:selected'))
        if not origin.startswith('plugin://plugin.video.sc.websharebridge/') or selected.get('provider') != 'webshare':
            return False
        info = item.get('info', {})
        show, season, episode = str(show_id), int(info['season']), int(info['episode'])
        if not re.fullmatch(r'[1-9][0-9]{0,11}', show) or not 0 <= season <= 999 or not 1 <= episode <= 9999:
            return False
        target = {'id':show, 'url':'/FGet/%s/%s' % (show, season), 'resume_episode':str(episode)}
        selected_item = window.getProperty('sc.webshare.item')
        result = {'target':target, 'source':'webshare-stop',
                           'origin':origin, 'not_before':(now if now is not None else time.time()) + 2,
                           'expires':(now if now is not None else time.time()) + 90}
        if valid_webshare_result(origin, selected_item, show, season, episode):
            result['selected_item'] = selected_item
        window.setProperty(REQUEST_PROPERTY, json.dumps(result))
        return True
    except (TypeError, ValueError, KeyError, AttributeError):
        return False
    finally:
        window.clearProperty('sc.webshare.origin')
        window.clearProperty('sc.webshare.item')


def valid_webshare_result(origin, selected, show, season, episode):
    """Accept only a matching companion result, never an arbitrary Kodi command."""
    try:
        if any(not isinstance(v, str) or len(v) > 4096 or any(c in v for c in ('"', '\r', '\n')) for v in (origin, selected)):
            return False
        folder, entry = urlsplit(origin), urlsplit(selected)
        if any(p.scheme != 'plugin' or p.netloc != 'plugin.video.sc.websharebridge' or p.path != '/' or p.fragment for p in (folder, entry)):
            return False
        a, b = parse_qs(folder.query), parse_qs(entry.query)
        if any(len(values) != 1 for values in list(a.values()) + list(b.values())):
            return False
        return (a.get('action') == ['episode'] and b.get('action') == ['play']
                and a.get('sc_id') == b.get('sc_id') == [str(show)]
                and a.get('season') == b.get('season') == [str(season)]
                and a.get('episode') == b.get('episode') == [str(episode)]
                and a.get('show') == b.get('show') and bool(a.get('show'))
                and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,128}', b.get('ident', [''])[0])))
    except (ValueError, TypeError, IndexError):
        return False
