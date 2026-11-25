"""Version individual records, including deletions, without sharing databases."""

import copy
import hashlib
import json
import time
from .policy import shared_setting
from .profile import timestamp
from .season_reset import MARKER, affected_season

SCHEMA = 1
MAX_BYTES = 4 * 1024 * 1024
MAX_RECORDS = 50000


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def valid_key(key):
    if not isinstance(key, str) or len(key) > 300:
        return False
    parts = key.split("|")
    if parts[0] == "history":
        return len(parts) == 4 and all(p.isdigit() or p == "-" for p in parts[1:])
    if parts[0] in ("current", "next", "language"):
        return len(parts) == 2 and parts[1].isdigit()
    if parts[0] == "list":
        return (
            len(parts) == 3
            and parts[1] in ("lastf", "lasts", "lastd", "lastk", "lastf-p", "lasts-p", "lastd-p", "lastk-p")
            and parts[2].isdigit()
        )
    if parts[0] == "setting":
        return len(parts) == 3 and shared_setting(parts[1], parts[2])
    return False


def valid_record(key, record):
    if not valid_key(key) or not isinstance(record, dict) or set(record) != {"v", "value"}:
        return False
    v = record["v"]
    if not (
        isinstance(v, list)
        and len(v) == 3
        and type(v[0]) is int
        and type(v[1]) is int
        and isinstance(v[2], str)
        and 0 <= v[0] < 10**15
        and abs(v[1]) < 10**9
        and 1 <= len(v[2]) <= 64
    ):
        return False
    value = record["value"]
    if MARKER.fullmatch(key):
        return value is None
    if value is None:
        return True
    kind = key.split("|")[0]
    if kind == "list":
        return value is True
    if kind == "history":
        return (
            isinstance(value, dict)
            and set(value) == {"position", "count", "played_at", "watched"}
            and (
                value["position"] is None or type(value["position"]) in (int, float) and 0 <= value["position"] < 10**8
            )
            and (value["count"] is None or type(value["count"]) is int and 0 <= value["count"] < 10**7)
            and (value["played_at"] is None or isinstance(value["played_at"], str) and len(value["played_at"]) <= 60)
            and type(value["watched"]) is bool
        )
    if kind == "current":
        return isinstance(value, str) and len(value) < 40 and value.replace("x", "").isdigit()
    if kind == "next":
        return (
            isinstance(value, dict)
            and set(value) <= {"s", "e", "t"}
            and {"s", "e"} <= set(value)
            and all(type(x) in (int, float) and x >= 0 for x in value.values())
        )
    if kind == "language":
        return isinstance(value, str) and 1 <= len(value) <= 12 and value.replace("-", "").isalpha()
    return type(value) in (str, bool, int, float, list) and len(canonical(value)) <= 2048


def encode(device, generation, records):
    if not all(valid_record(k, v) for k, v in records.items()):
        raise ValueError("Invalid profile record")
    data = {"schema": SCHEMA, "device": device, "generation": generation, "records": records}
    wrapper = {"data": data, "sha256": hashlib.sha256(canonical(data)).hexdigest()}
    result = canonical(wrapper)
    if len(result) > MAX_BYTES:
        raise ValueError("Profile exceeds the size limit")
    return result


def decode(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Profile exceeds the size limit")
    wrapper = json.loads(raw)
    data = wrapper["data"]
    if wrapper["sha256"] != hashlib.sha256(canonical(data)).hexdigest():
        raise ValueError("Profile checksum mismatch")
    if (
        data.get("schema") != SCHEMA
        or not isinstance(data.get("device"), str)
        or type(data.get("generation")) is not int
        or data["generation"] < 1
        or not isinstance(data.get("records"), dict)
        or len(data["records"]) > MAX_RECORDS
    ):
        raise ValueError("Invalid profile envelope")
    if not all(valid_record(k, v) for k, v in data["records"].items()):
        raise ValueError("Invalid profile record")
    return data


def reset_ranges(records):
    ranges = {}
    for key, version in records.items():
        match = MARKER.fullmatch(key)
        if match:
            ranges.setdefault(match[1], []).append((int(match[2]), version))
    return ranges


def reset_boundary(key, value, ranges):
    kind, show, *episode = key.split("|")
    if show not in ranges or value is None:
        return None
    if kind == "history" and len(episode) == 2 and all(part.isdigit() for part in episode):
        season = int(episode[0])
    else:
        season = affected_season(kind, value)
    if season is None:
        return None
    return max((version for start, version in ranges[show] if season >= start), default=None)


def expire_record(key, record, ranges):
    if not ranges:
        return record
    value = record["value"]
    boundary = reset_boundary(key, value, ranges)
    if not boundary:
        return record
    played = 0
    if key.startswith("history|"):
        played = timestamp(value["played_at"])
    elif key.startswith("next|"):
        played = timestamp(value.get("t"))
    older = played < boundary[0] if played else record["v"] <= boundary
    return {"v": boundary, "value": None} if older else record


class Engine:
    def __init__(self, device, saved=None, now=None):
        self.device = device
        self.now = now or (lambda: int(time.time() * 1000))
        self.records = copy.deepcopy((saved or {}).get("records", {}))
        self.observed = copy.deepcopy((saved or {}).get("observed", {}))
        self.initialized = (saved or {}).get("initialized", False)
        self.clock = (saved or {}).get("clock", 0)
        self.counter = (saved or {}).get("counter", 0)
        self.generation = (saved or {}).get("generation", 0)
        self.dirty = (saved or {}).get("dirty", False)

    def version(self):
        self.clock = max(self.clock, self.now())
        self.counter += 1
        return [self.clock, self.counter, self.device]

    def capture(self, snapshot, bootstrap_clocks=None):
        """Only actual local changes acquire a new version; imported values do not echo."""
        initial = not self.initialized
        clocks = bootstrap_clocks or {}
        version = self.version() if not initial else None
        new_ranges = reset_ranges({
            key: [value, 0, self.device] for key, value in snapshot.items()
            if type(value) is int and 0 < value < 10**15
            and value != self.observed.get(key) and MARKER.fullmatch(key)
        })
        changed = 0
        for key in sorted(set(snapshot) | set(self.observed)):
            value = snapshot.get(key)
            old = self.observed.get(key)
            if key.startswith("setting|") and key not in snapshot:
                continue  # An unavailable addon/settings file is not an explicit preference reset.
            if not valid_key(key) or (key in self.observed and value == old):
                continue
            if MARKER.fullmatch(key):
                # The reserved episode "-" is understood as a no-op deletion by
                # older readers. The timestamp lives in the existing version.
                saved = self.records.get(key)
                if type(value) is int and 0 < value < 10**15 and (not saved or value > saved["v"][0]):
                    self.records[key] = {"v": [value, 0, self.device], "value": None}
                    self.clock = max(self.clock, value)
                    changed += 1
                continue
            if (
                not initial
                and not key.startswith("list|")
                and key in self.records
                and self.records[key]["value"] == value
            ):
                continue  # An asynchronous Kodi setting has finished applying an imported value.
            if key.startswith("list|"):
                if value is not None and not initial and key in self.observed and value.get("rank") != 0:
                    continue  # Another item moved to the front; this item's visit time did not change.
                record_value = True if value is not None else None
                rank = value.get("rank", 0) if value else 0
            else:
                record_value = value
                rank = 0
            new_preference = key.startswith("setting|") and key not in self.observed and key not in self.records
            stamp = [int(clocks.get(key, 0)), -rank, self.device] if initial or new_preference else version
            if value is None and new_ranges:
                boundary = reset_boundary(key, old, new_ranges)
                if boundary:
                    stamp = boundary
            record = {"v": stamp, "value": copy.deepcopy(record_value)}
            if not valid_record(key, record):
                continue
            self.records[key] = record
            changed += 1
        self.observed = copy.deepcopy(snapshot)
        self.initialized = True
        self.dirty = self.dirty or bool(changed)
        return changed

    def merge(self, incoming):
        changed = 0
        for key, record in incoming.items():
            if not isinstance(key, str) or not MARKER.fullmatch(key) or not valid_record(key, record):
                continue
            old = self.records.get(key)
            if old is None or record["v"] > old["v"]:
                self.records[key] = copy.deepcopy(record)
                self.clock = max(self.clock, record["v"][0])
                changed += 1
        ranges = reset_ranges({key: record["v"] for key, record in self.records.items() if MARKER.fullmatch(key)})
        changed += self.apply_season_resets(ranges)
        for key, record in incoming.items():
            if not valid_record(key, record) or MARKER.fullmatch(key):
                continue
            effective = expire_record(key, record, ranges)
            old = self.records.get(key)
            if old is None or effective["v"] > old["v"]:
                self.records[key] = copy.deepcopy(effective)
                self.clock = max(self.clock, effective["v"][0])
                self.counter = max(self.counter, effective["v"][1])
                self.dirty = self.dirty or effective is not record
                changed += 1
        return changed

    def apply_season_resets(self, ranges=None):
        if ranges is None:
            ranges = reset_ranges({key: record["v"] for key, record in self.records.items() if MARKER.fullmatch(key)})
        if not ranges:
            return 0

        changed = 0
        for key, record in self.records.items():
            effective = expire_record(key, record, ranges)
            if effective is not record:
                self.records[key] = effective
                changed += 1
        self.dirty = self.dirty or bool(changed)
        return changed

    def after_apply(self, snapshot):
        self.observed = copy.deepcopy(snapshot)

    def state(self):
        return {
            key: getattr(self, key)
            for key in ("records", "observed", "initialized", "clock", "counter", "generation", "dirty")
        }
