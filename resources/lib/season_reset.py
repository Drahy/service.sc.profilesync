"""Scope a Stream Cinema history reset to one show and a starting season."""

import re


NAMESPACE = 'season_history_resets'
SEASON_ROUTE = re.compile(r'/FGet/([1-9][0-9]*)/([1-9][0-9]*)')
MARKER = re.compile(r'history\|([1-9][0-9]*)\|([1-9][0-9]*)\|-')
EPISODE_FIELD = re.compile(r'(?:watched|play_count|last_played):([0-9]+):([0-9]+)')
SEASON_FIELD = re.compile(r'series:([0-9]+)')
POINTER = re.compile(r'([0-9]+)x[0-9]+')


def marker_key(show, season):
    return 'history|%s|%s|-' % (show, season)


def affected_season(kind, value):
    if kind == 'current' and isinstance(value, str):
        match = POINTER.fullmatch(value)
        return int(match[1]) if match else None
    if kind == 'next' and isinstance(value, dict):
        season = value.get('s')
        return int(season) if str(season).isdigit() else None
    return None


def reset_rows(rows, show, start, when):
    """Return the local reset as one set of namespace changes."""
    namespace = 'SCKODIItem-' + show
    item = dict(rows.get(namespace, {}))
    watched = dict(rows.get('all_watched', {}))
    next_episodes = dict(rows.get('nextep', {}))
    markers = dict(rows.get(NAMESPACE, {}))
    for key in list(item):
        match = EPISODE_FIELD.fullmatch(key) or SEASON_FIELD.fullmatch(key)
        if match and int(match[1]) >= start:
            item.pop(key)
    season = affected_season('current', item.get('last_ep'))
    if season is not None and season >= start:
        item.pop('last_ep')
    for key in (show, namespace):
        season = affected_season('next', next_episodes.get(key))
        if season is not None and season >= start:
            next_episodes.pop(key)
    prefix = re.compile(re.escape(show) + r'/([0-9]+)/[0-9]+')
    if isinstance(watched.get('list'), list):
        watched['list'] = [value for value in watched['list']
                           if not ((match := prefix.fullmatch(str(value))) and int(match[1]) >= start)]
    key = marker_key(show, start)
    markers[key] = max(when, markers.get(key, 0) + 1)
    changes = {namespace: item, 'all_watched': watched, 'nextep': next_episodes, NAMESPACE: markers}
    return {key: value for key, value in changes.items() if value != rows.get(key, {})}
