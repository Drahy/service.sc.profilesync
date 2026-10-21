"""The network worker has no player callbacks or playback controls."""

import time
from .engine import decode, encode
from .kra import NAME, PREFIX, KraError
from .local import write


class Worker:
    def __init__(self, engine, adapter, backend, checkpoint, playing=None, status=None):
        self.engine, self.adapter, self.backend = engine, adapter, backend
        self.checkpoint = checkpoint
        self.playing = playing or (lambda: False)
        self.status = status or (lambda value: None)
        self.downloaded = set()
        self.last_saved = None

    def save(self):
        state = self.engine.state()
        if state != self.last_saved:
            write(self.checkpoint, state)
            import copy

            self.last_saved = copy.deepcopy(state)

    def capture(self):
        snapshot, clocks = self.adapter.snapshot()
        if not self.engine.initialized or snapshot != self.engine.observed:
            self.engine.capture(snapshot, clocks)
            self.save()
        return snapshot

    def sync(self):
        self.capture()
        files = self.backend.list()
        for file in sorted(files, key=lambda f: f["name"], reverse=True):
            if file["ident"] in self.downloaded:
                continue
            try:
                data = decode(self.backend.download(file))
                match = NAME.fullmatch(file["name"])
                if data["device"] != match.group(1) or data["generation"] != int(match.group(2)):
                    continue
            except (ValueError, KeyError, KraError):
                continue
            if self.engine.generation == 0:
                # A newly added device must restore cloud preferences before its defaults.
                for key in data["records"]:
                    old = self.engine.records.get(key)
                    if key.startswith("setting|") and old and old["v"][0] == 0 and old["v"][2] == self.engine.device:
                        self.engine.records.pop(key)
            self.engine.merge(data["records"])
            self.downloaded.add(file["ident"])
        # Local viewing may have changed while a transfer was in flight.
        latest = self.capture()
        applied = self.adapter.apply(self.engine.records, latest, playing=self.playing())
        if applied:
            after, _ = self.adapter.snapshot()
            # Only acknowledge imported values. Concurrent local writes are captured next cycle.
            for key, value in after.items():
                if key not in self.adapter.imported_keys:
                    continue
                if key.startswith("list|"):
                    self.engine.observed[key] = value
                elif key in self.engine.records and value == self.engine.records[key]["value"]:
                    self.engine.observed[key] = value
            for key in set(self.engine.observed) - set(after):
                if key in self.adapter.imported_keys and self.engine.records[key]["value"] is None:
                    self.engine.observed.pop(key, None)
        if self.engine.dirty:
            if self.engine.generation == 0:
                # First-device preferences become authoritative for later fresh installs.
                for key, record in self.engine.records.items():
                    if key.startswith("setting|") and record["v"][0] == 0 and record["v"][2] == self.engine.device:
                        record["v"] = self.engine.version()
            self.engine.generation += 1
            self.save()  # Reserve the name before network I/O; interrupted uploads are not reused.
            raw = encode(self.engine.device, self.engine.generation, self.engine.records)
            name = PREFIX + self.engine.device + "-" + ("%012d" % self.engine.generation) + ".json"
            self.backend.upload(name, raw)
            self.engine.dirty = False
            self.save()
            self.backend.prune(self.engine.device)
        self.save()
        self.status({"ok": True, "last_success": time.time(), "records": len(self.engine.records), "applied": applied})
        return applied
