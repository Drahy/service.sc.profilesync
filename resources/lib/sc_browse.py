"""Portable Last seen browsing bridge, copied into SC common/resume_browse.py."""

import json
import copy
import re
import time
from urllib.parse import urlsplit, urlunsplit

FOCUS_PROPERTY = "sc.profile.browse.focus"
SERIES = re.compile(r"^/FGet/(\d+)$")
SEASON = re.compile(r"^/FGet/(\d+)/(\d+)$")
LAST = re.compile(r"^(\d+)x([1-9]\d*)$")


def history_response(ids, load, list_id, title, next_title, page=0, size=20):
    """Rebuild local history through supported detail routes, without legacy /Last."""
    ids = list(dict.fromkeys(str(value) for value in ids if str(value).isdigit()))
    page = max(0, int(page))
    selected = ids[page * size : (page + 1) * size]
    menu = []
    for show in selected:
        response = load("/FGet/" + show)
        if not isinstance(response, dict):
            continue
        system = response.get("system", {})
        if system.get("setContent") in ("seasons", "episodes"):
            seasons = response.get("menu") or []
            if not seasons:
                if list_id.endswith("lasts"):
                    continue
                response = load("/Play/" + show)
                if not isinstance(response, dict):
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
            continue
        menu.append(item)
    if selected and not menu:
        raise ValueError("No history metadata is currently available")
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
