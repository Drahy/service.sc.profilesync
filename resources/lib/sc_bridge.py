"""Local cache bridge copied into SC; it performs no network operations."""

import copy
import json
import re
import sqlite3
from xbmcgui import Window

_revisions = {}
_snapshots = {}
_home = None


def tracked(name):
    return bool(re.fullmatch(r"SCKODIItem-\d+|all_watched|nextep|pref_lang\.\{\}|last[fsdk](?:-p)?", name))


def revision(name):
    if not tracked(name):
        return ""
    global _home
    if _home is None:
        _home = Window(10000)
    return _home.getProperty("sc.profile.sync." + name)


def three_way(base, local, remote):
    if isinstance(base, dict) and isinstance(local, dict) and isinstance(remote, dict):
        result = copy.deepcopy(remote)
        for key in set(base) | set(local):
            if key not in local:
                result.pop(key, None)
            elif key not in base:
                result[key] = copy.deepcopy(local[key])
            elif local[key] != base[key]:
                result[key] = three_way(base[key], local[key], remote.get(key))
        return result
    if isinstance(base, list) and isinstance(local, list) and isinstance(remote, list):
        removed = [x for x in base if x not in local]
        moved = local[:1] if local and (not base or local[0] != base[0]) else []
        result = [copy.deepcopy(x) for x in local if x not in base or x in remote or x in moved]
        result.extend(x for x in remote if x not in result and x not in removed)
        return result
    return copy.deepcopy(local)


def force_reload(storage, force):
    token = revision(storage._name)
    if not tracked(storage._name):
        return force
    storage._profile_sync_revision = token
    changed = _revisions.get(storage._name, "") != token
    _revisions[storage._name] = token
    return force or changed


def remember(storage):
    if tracked(storage._name):
        snapshot = _snapshots.get(storage._name)
        if snapshot is None or snapshot[0] is not storage._data:
            # Readers share the same cached data object. Keep one independent,
            # immutable merge base until a load/save replaces that object.
            snapshot = (storage._data, copy.deepcopy(storage._data))
            _snapshots[storage._name] = snapshot
        storage._profile_sync_base = snapshot[1]


def read_refresh(storage, cache):
    if not tracked(storage._name):
        return
    token = revision(storage._name)
    if token == getattr(storage, "_profile_sync_revision", ""):
        return
    row = storage._db.execute(storage._sql_get, storage._name).fetchone()
    remote = json.loads(row[0]) if row else {}
    base = getattr(storage, "_profile_sync_base", storage._data)
    storage._data = three_way(base, storage._data, remote)
    storage._profile_sync_base = copy.deepcopy(remote)
    storage._profile_sync_revision = token
    cache[storage._name] = storage._data
    _revisions[storage._name] = token


def before_save(storage, cache):
    read_refresh(storage, cache)


def save(storage, cache):
    if not tracked(storage._name):
        return False
    connection = sqlite3.connect(storage._db._path, timeout=0.2)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(storage._sql_get, (storage._name,)).fetchone()
        remote = json.loads(row[0]) if row else {}
        base = getattr(storage, "_profile_sync_base", storage._data)
        merged = three_way(base, storage._data, remote)
        connection.execute(storage._sql_set, (storage._name, json.dumps(merged)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    storage._data = merged
    storage._last_saved = merged
    cache[storage._name] = merged
    storage._profile_sync_revision = revision(storage._name)
    _revisions[storage._name] = storage._profile_sync_revision
    remember(storage)
    return True
