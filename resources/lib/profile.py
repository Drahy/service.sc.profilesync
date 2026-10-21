"""Translate supported SC records without exposing cache, stream URLs or accounts."""

import copy
from datetime import datetime
import json
import re
import sqlite3

from .policy import shared_setting

ITEM = re.compile(r"^SCKODIItem-(\d+)$")
FIELD = re.compile(r"^(watched|play_count|last_played)(?::(\d+):(\d+))?$")
LISTS = {"lastf", "lasts", "lastd", "lastk", "lastf-p", "lasts-p", "lastd-p", "lastk-p"}


def timestamp(value):
    try:
        if isinstance(value, (int, float)):
            return max(0, int(value * 1000))
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        # SC writes local ISO times; an explicit timezone is respected when present.
        return max(0, int(date.timestamp() * 1000))
    except (ValueError, TypeError, AttributeError, OverflowError):
        return 0


def read_rows(path):
    if not path.exists():
        return {}
    connection = sqlite3.connect(str(path), timeout=0.2)
    try:
        return {key: json.loads(value) for key, value in connection.execute("SELECT item_key,item_value FROM storage")}
    finally:
        connection.close()


def export(rows, preferences=None):
    result, clocks, visits = {}, {}, {}
    watched = set(str(x) for x in rows.get("all_watched", {}).get("list", []))
    groups = {}
    for key in watched:
        parts = key.split("/")
        if len(parts) not in (1, 3) or not all(x.isdigit() for x in parts):
            continue
        item = [parts[0], parts[1] if len(parts) == 3 else "-", parts[2] if len(parts) == 3 else "-"]
        groups["history|" + "|".join(item)] = {"position": None, "count": None, "played_at": None, "watched": True}
    for namespace, data in rows.items():
        match = ITEM.fullmatch(namespace)
        if not match or not isinstance(data, dict):
            continue
        item_id = match.group(1)
        for key, value in data.items():
            field = FIELD.fullmatch(key)
            if not field:
                continue
            record_key = "history|" + "|".join((item_id, field.group(2) or "-", field.group(3) or "-"))
            group = groups.setdefault(
                record_key, {"position": None, "count": None, "played_at": None, "watched": False}
            )
            if field.group(1) == "watched":
                try:
                    group["position"] = max(0, float(value))
                except (TypeError, ValueError):
                    pass
            elif field.group(1) == "play_count":
                try:
                    group["count"] = max(0, int(value))
                    group["watched"] = group["count"] > 0
                except (TypeError, ValueError):
                    pass
            elif isinstance(value, str):
                group["played_at"] = value
        if isinstance(data.get("last_ep"), str):
            result["current|" + item_id] = data["last_ep"]
    for key, value in groups.items():
        result[key] = value
        clocks[key] = timestamp(value["played_at"])
        item_id = key.split("|")[1]
        visits[item_id] = max(visits.get(item_id, 0), clocks[key])
    for key in result:
        if key.startswith("current|"):
            clocks[key] = visits.get(key.split("|")[1], 0)
    for namespace in LISTS:
        for rank, item_id in enumerate(rows.get(namespace, {}).get("list", [])):
            if str(item_id).isdigit():
                key = "list|" + namespace + "|" + str(item_id)
                result.setdefault(key, {"rank": rank})
                clocks[key] = visits.get(str(item_id), 0)
    for item_id, value in rows.get("nextep", {}).items():
        item_id = str(item_id)
        if item_id.startswith("SCKODIItem-"):
            item_id = item_id[len("SCKODIItem-") :]
        if item_id.isdigit() and isinstance(value, dict) and {"s", "e"} <= set(value):
            key = "next|" + item_id
            try:
                result[key] = {k: int(v) for k, v in value.items() if k in ("s", "e", "t")}
            except (ValueError, TypeError):
                continue
            clocks[key] = timestamp(value.get("t"))
            current = "current|" + item_id
            if current in result:
                clocks[current] = max(clocks.get(current, 0), clocks[key])
    for item_id, value in rows.get("pref_lang.{}", {}).items():
        if str(item_id).isdigit() and isinstance(value, str):
            result["language|" + str(item_id)] = value
    for addon, values in (preferences or {}).items():
        for key, value in values.items():
            if shared_setting(addon, key):
                result["setting|" + addon + "|" + key] = copy.deepcopy(value)
    return result, clocks


def apply_rows(rows, records, eligible=None):
    """Return changed namespaces; keep unrelated fields and explicit history deletions."""
    rows = copy.deepcopy(rows)
    before = copy.deepcopy(rows)
    watched = set(str(x) for x in rows.get("all_watched", {}).get("list", []))
    lists = {}
    for key, record in records.items():
        if eligible is not None and key not in eligible:
            continue
        parts, value = key.split("|"), record["value"]
        kind = parts[0]
        if kind == "history":
            _, item_id, season, episode = parts
            namespace = "SCKODIItem-" + item_id
            data = rows.setdefault(namespace, {})
            suffix = ":" + season + ":" + episode if season != "-" else ""
            member = item_id + ("/" + season + "/" + episode if season != "-" else "")
            for field, target in [("watched", "position"), ("play_count", "count"), ("last_played", "played_at")]:
                if value is None or value[target] is None:
                    data.pop(field + suffix, None)
                else:
                    data[field + suffix] = value[target]
            if value and value["watched"]:
                watched.add(member)
            else:
                watched.discard(member)
            if season != "-":
                series = data.setdefault("series:" + season, {})
                if value and value["watched"]:
                    series[episode] = True
                else:
                    series.pop(episode, None)
        elif kind == "list":
            lists.setdefault(parts[1], []).append((parts[2], record))
        elif kind in ("current", "next", "language"):
            if kind == "current":
                data, field = rows.setdefault("SCKODIItem-" + parts[1], {}), "last_ep"
            else:
                data, field = rows.setdefault("nextep" if kind == "next" else "pref_lang.{}", {}), parts[1]
            if value is None:
                data.pop(field, None)
            else:
                data[field] = copy.deepcopy(value)
    if any(key.startswith("history|") and (eligible is None or key in eligible) for key in records):
        rows.setdefault("all_watched", {})["list"] = sorted(watched)
    for namespace, entries in lists.items():
        ranked = sorted(entries, key=lambda item: tuple(item[1]["v"]), reverse=True)
        known = {item for item, _ in entries}
        retained = [str(x) for x in rows.get(namespace, {}).get("list", []) if str(x) not in known]
        rows.setdefault(namespace, {})["list"] = [item for item, record in ranked if record["value"]] + retained
    return {name: value for name, value in rows.items() if value != before.get(name)}
