"""Portable Last seen browsing bridge, copied into SC common/resume_browse.py."""

import json
import copy
import re
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

FOCUS_PROPERTY = "sc.profile.browse.focus"
SERIES = re.compile(r"^/FGet/(\d+)$")
SEASON = re.compile(r"^/FGet/(\d+)/(\d+)$")
LAST = re.compile(r"^(\d+)x([1-9]\d*)$")
PLAYED_EPISODE = re.compile(r"^last_played:(\d+):([1-9]\d*)$")


def most_recent_episode(data):
    """Use a real playback timestamp; keep SC's completed-episode pointer intact."""
    if not isinstance(data, dict):
        return None
    fallback = data.get('last_ep')
    fallback = fallback if isinstance(fallback, str) and LAST.fullmatch(fallback) else None
    candidates = []
    for key, value in data.items():
        match = PLAYED_EPISODE.fullmatch(key) if isinstance(key, str) else None
        if not match or not isinstance(value, str):
            continue
        try:
            when = datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        episode = '%sx%s' % (int(match.group(1)), int(match.group(2)))
        candidates.append((when, episode == fallback, episode))
    return max(candidates)[2] if candidates else fallback


def history_response(ids, load, list_id, title, next_title, page=0, size=20, titles=None):
    """Rebuild local history through supported detail routes, without legacy /Last."""
    ids = list(dict.fromkeys(str(value) for value in ids if str(value).isdigit()))
    page = max(0, int(page))
    selected = ids[page * size : (page + 1) * size]
    menu = []
    titles = titles if isinstance(titles, dict) else {}

    def unavailable(show):
        name = titles.get(show)
        if not isinstance(name, str) or not name:
            return None
        series = list_id.endswith('lasts')
        return {'type': 'dir' if series else 'video', 'id': show,
                'url': ('/FGet/' if series else '/Play/') + show, 'lid': list_id,
                'info': {'title': name, 'mediatype': 'tvshow' if series else 'movie'}}
    for show in selected:
        try:
            response = load("/FGet/" + show)
        except Exception:
            response = None
        if not list_id.endswith("lasts") and (
            not isinstance(response, dict) or not (response.get("info") or response.get("menu"))
        ):
            try:
                response = load("/Play/" + show)
            except Exception:
                menu.append(unavailable(show))
                continue
        if not isinstance(response, dict):
            menu.append(unavailable(show))
            continue
        system = response.get("system") or {}
        if not isinstance(system, dict):
            system = {}
        if system.get("setContent") in ("seasons", "episodes"):
            seasons = response.get("menu") or []
            if not seasons:
                if list_id.endswith("lasts"):
                    menu.append(unavailable(show))
                    continue
                try:
                    response = load("/Play/" + show)
                except Exception:
                    menu.append(unavailable(show))
                    continue
                if not isinstance(response, dict):
                    menu.append(unavailable(show))
                    continue
                seasons = []
            seed = seasons[0] if seasons else None
        else:
            seed = None
        if seed:
            item = {
                key: copy.deepcopy(seed[key])
                for key in ("info", "i18n_art", "art", "cast", "unique_ids")
                if key in seed
            }
            info = item.setdefault("info", {})
            info.pop("season", None)
            info.pop("episode", None)
            info["mediatype"] = "tvshow"
            if system.get("setContent") == "episodes":
                info["title"] = info.get("tvshowtitle") or system.get("setPluginCategory") or show
            else:
                info["title"] = system.get("setPluginCategory") or info.get("tvshowtitle") or show
            item.update(type="dir", id=show, url="/FGet/" + show, lid=list_id)
        elif isinstance(response.get("info"), dict) and response.get("info"):
            seed = response["info"]
            if isinstance(seed.get("info"), dict):
                response = seed
            item = {
                key: copy.deepcopy(response[key])
                for key in ("info", "i18n_info", "i18n_art", "art", "cast", "unique_ids")
                if key in response
            }
            item.update(type="video", id=show, url="/Play/" + show, lid=list_id)
        else:
            menu.append(unavailable(show))
            continue
        item_title = (item.get('info') or {}).get('title')
        if isinstance(item_title, str) and item_title:
            titles[show] = item_title
        menu.append(item)
    menu = [item for item in menu if item is not None]
    if (page + 1) * size < len(ids):
        menu.append(
            {"type": "next", "title": next_title, "action": "last", "id": list_id, "url": "/", "page": str(page + 1)}
        )
    return {
        "menu": menu,
        "system": {
            "setContent": "tvshows" if list_id.endswith("lasts") else "videos",
            "setPluginCategory": title,
            "listType": "history",
            "addSortMethods": [0],
        },
    }


def combined_history_response(lists, load, read_item, title, next_title, page=0, size=20, titles=None):
    """Combine existing category lists without modifying their membership."""
    ranked = []
    seen = set()
    for category, ids in lists:
        for rank, raw in enumerate(ids):
            ident = str(raw)
            pair = (category, ident)
            if not ident.isdigit() or pair in seen:
                continue
            seen.add(pair)
            try:
                data = read_item(ident) or {}
            except Exception:
                data = {}
            visits = []
            for name, value in data.items():
                if name == 'last_played' or PLAYED_EPISODE.fullmatch(name):
                    try:
                        visits.append(datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp())
                    except (ValueError, TypeError, AttributeError, OverflowError, OSError):
                        pass
            ranked.append((max(visits, default=0), -rank, category, ident))
    ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    page = max(0, int(page))
    menu = []
    for _, _, category, ident in ranked[page * size:(page + 1) * size]:
        row = history_response([ident], load, category, title, next_title,
                               titles=(titles or {}).get(category, {}))
        menu.extend(row.get('menu') or [])
    if (page + 1) * size < len(ranked):
        menu.append({'type':'next', 'title':next_title, 'action':'last',
                     'id':'last-all', 'url':'/', 'page':str(page + 1)})
    return {'menu':menu, 'system':{'setContent':'videos', 'setPluginCategory':title,
                                    'listType':'history', 'addSortMethods':[0]}}


def last_seen_item(data, read_last):
    """Keep ordinary folders intact and never resolve a playable stream."""
    if not isinstance(data, dict) or data.get("type") != "dir" or not isinstance(data.get("url"), str):
        return data
    parts = urlsplit(data.get("url", ""))
    match = SERIES.fullmatch(parts.path)
    if parts.scheme or parts.netloc or not match:
        return data
    last = read_last(match.group(1))
    position = LAST.fullmatch(last) if isinstance(last, str) else None
    if not position:
        return data
    changed = dict(data)
    changed["resume_seasons"] = data["url"]
    changed["url"] = urlunsplit(("", "", parts.path + "/" + str(int(position.group(1))), parts.query, ""))
    changed["resume_episode"] = str(int(position.group(2)))
    return changed


def focus_request(route, episode):
    if not isinstance(route, str) or not isinstance(episode, str) or not re.fullmatch(r"[1-9][0-9]*", episode):
        return None
    parts = urlsplit(route)
    match = SEASON.fullmatch(parts.path)
    if parts.scheme or parts.netloc or not match:
        return None
    show, season = match.groups()
    return {"route": parts.path, "item": "/Play/%s/%s/%s" % (show, season, int(episode))}


def all_seasons(route):
    parts = urlsplit(route)
    match = SEASON.fullmatch(parts.path)
    if parts.scheme or parts.netloc or not match:
        return ""
    return urlunsplit(("", "", "/FGet/" + match.group(1), parts.query, ""))


def request_focus(route, episode):
    import xbmcgui  # Imported only in Kodi; all routing decisions remain independently testable.

    request = focus_request(route, episode)
    if request:
        request["expires"] = time.time() + 15
        xbmcgui.Window(10000).setProperty(FOCUS_PROPERTY, json.dumps(request))
