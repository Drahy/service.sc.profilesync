"""Apply bounded transactions with an optimistic check against current local edits."""

import json
import sqlite3
import copy
from .profile import apply_rows, export, read_rows


class Adapter:
    def __init__(self, database, preferences, apply_preference, invalidate=None, persist_preferences=None):
        self.database = database
        self.preferences = preferences
        self.apply_preference = apply_preference
        self.invalidate = invalidate or (lambda namespaces: None)
        self.persist_preferences = persist_preferences or (lambda preferences: None)
        self.persisted = None

    def persist(self, preferences):
        native = {key: preferences.get(key, {}) for key in ("kodi", "skin.amber")}
        if native != self.persisted:
            self.persist_preferences(native)
            self.persisted = copy.deepcopy(native)

    def snapshot(self):
        preferences = self.preferences()
        self.persist(preferences)
        return export(read_rows(self.database), preferences)

    def apply(self, records, expected, playing=False):
        self.imported_keys = set()
        if playing:
            return 0
        connection = sqlite3.connect(str(self.database), timeout=0.1)
        try:
            connection.execute("BEGIN IMMEDIATE")
            rows = {k: json.loads(v) for k, v in connection.execute("SELECT item_key,item_value FROM storage")}
            fresh, _ = export(rows)
            eligible = {
                key for key in records if not key.startswith("setting|") and fresh.get(key) == expected.get(key)
            }
            changed = apply_rows(rows, records, eligible)
            for namespace, value in changed.items():
                connection.execute(
                    "INSERT OR REPLACE INTO storage(item_key,item_value) VALUES(?,?)",
                    (namespace, json.dumps(value, ensure_ascii=False)),
                )
            connection.commit()
            self.imported_keys.update(eligible)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        if changed:
            self.invalidate(sorted(changed))
        preferences, _ = export({}, self.preferences())
        settings_applied = 0
        for key, record in records.items():
            if not key.startswith("setting|") or record["value"] is None:
                continue
            if preferences.get(key) == expected.get(key) and preferences.get(key) != record["value"]:
                _, addon, setting = key.split("|")
                if self.apply_preference(addon, setting, record["value"]):
                    settings_applied += 1
                    self.imported_keys.add(key)
        if settings_applied:
            # A crash after acknowledgement must not restore the previous core value.
            self.persist(self.preferences())
        return len(changed) + settings_applied
