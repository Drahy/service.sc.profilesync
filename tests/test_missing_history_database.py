import pytest

from resources.lib.engine import Engine
from resources.lib.profile import read_rows


def test_unavailable_database_cannot_be_interpreted_as_history_deletion(tmp_path):
    engine = Engine('device', now=lambda: 1000)
    key = 'list|lasts|42'
    engine.capture({key: {'rank': 0}})
    before = engine.state()
    with pytest.raises(FileNotFoundError):
        engine.capture(read_rows(tmp_path / 'missing.db'))
    assert engine.state() == before
