"""Durable local checkpoints; no account secrets are stored here."""

import json
import os
from pathlib import Path
import uuid


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".new")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, ensure_ascii=False, sort_keys=True, allow_nan=False)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def identity(directory):
    path = Path(directory) / "device.json"
    saved = read(path)
    if saved:
        value = saved.get("id", "")
        if len(value) == 32 and all(c in "0123456789abcdef" for c in value):
            return value
        raise ValueError("Invalid local synchronization identity")
    value = uuid.uuid4().hex
    write(path, {"id": value})
    return value
