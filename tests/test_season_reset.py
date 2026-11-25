import copy

from integration import patch_season_reset
from resources.lib.engine import Engine, decode, encode
from resources.lib.profile import apply_rows, export
from resources.lib.season_reset import NAMESPACE, reset_rows


def history(played_at=None, watched=True):
    return {"position": 22, "count": int(watched), "played_at": played_at, "watched": watched}


def test_reset_changes_only_the_chosen_show_from_the_chosen_season():
    rows = {
        "SCKODIItem-9": {
            "watched:4:3": 15, "play_count:4:3": 1, "series:4": {"3": True},
            "watched:5:2": 325, "play_count:5:2": 2, "last_played:5:2": "2026-01-01",
            "series:5": {"2": True}, "series:37": {"3": True}, "last_ep": "37x3", "custom": 7,
        },
        "SCKODIItem-10": {"play_count:5:2": 1},
        "all_watched": {"list": ["9/4/3", "9/5/2", "9/37/3", "10/5/2", "9"]},
        "lasts": {"list": ["9", "10"]},
        "nextep": {"9": {"s": 37, "e": 3}, "10": {"s": 5, "e": 2}},
    }
    original = copy.deepcopy(rows)
    reset = reset_rows(rows, "9", 5, 100)
    assert rows == original
    assert set(reset) == {"SCKODIItem-9", "all_watched", "nextep", NAMESPACE}
    assert reset["SCKODIItem-9"] == {
        "watched:4:3": 15, "play_count:4:3": 1, "series:4": {"3": True}, "custom": 7,
    }
    assert reset["all_watched"]["list"] == ["9/4/3", "10/5/2", "9"]
    assert reset["nextep"] == {"10": {"s": 5, "e": 2}}
    assert reset[NAMESPACE] == {"history|9|5|-": 100}


def test_reset_publishes_a_range_and_does_not_destroy_another_devices_new_viewing():
    engine = Engine("resetting", now=lambda: 3000)
    engine.capture({"history|9|5|2": history()})
    snapshot, clocks = export({NAMESPACE: {"history|9|5|-": 1000}})
    engine.capture(snapshot, clocks)
    assert engine.records["history|9|5|2"]["v"][0] == 1000
    another = {
        "history|9|5|2": {"v": [1500, 1, "remote"], "value": history()},
        "history|9|37|7": {"v": [100, 1, "remote"], "value": history()},
        "history|9|4|1": {"v": [100, 1, "remote"], "value": history()},
        "history|10|5|1": {"v": [100, 1, "remote"], "value": history()},
        "current|9": {"v": [200, 1, "remote"], "value": "37x7"},
    }
    engine.merge(another)
    assert engine.apply_season_resets() == 0
    shared = decode(encode("resetting", 1, engine.records))["records"]
    assert shared["history|9|5|-"]["value"] is None
    assert shared["history|9|37|7"]["value"] is None
    assert shared["current|9"]["value"] is None
    for key in ("history|9|5|2", "history|9|4|1", "history|10|5|1"):
        assert shared[key] == another[key]
    rows = apply_rows({}, shared)
    assert "series:5" in rows["SCKODIItem-9"]
    assert "last_played:5:-" not in rows["SCKODIItem-9"]


def test_delayed_old_play_timestamps_are_removed_but_a_new_replay_counts_again():
    key = "history|9|5|2"
    reset = 1_760_000_000_000
    engine = Engine("viewer")
    engine.merge({
        key: {"v": [reset + 2000, 1, "offline"], "value": history("2025-01-01T00:00:00Z")},
        "history|9|5|-": {"v": [reset, 0, "resetting"], "value": None},
    })
    assert engine.records[key]["value"] is None
    fresh = {"v": [reset + 1000, 1, "viewer"], "value": history("2026-01-01T00:00:00Z")}
    engine.merge({key: fresh})
    assert engine.apply_season_resets() == 0
    assert engine.records[key] == fresh


def test_integration_only_adds_a_season_action():
    original = """class SCDir(SCBaseItem):
    def make_ctx(self):
        context_menu = []
        if 'listType' in params.args:
            pass

class SCHPDir(SCDir):
    pass
"""
    installed = patch_season_reset.item(original)
    assert installed.count("season_reset.context") == 1
    assert patch_season_reset.item(installed) == installed
    route = """    def action(self):
        action = self.args.get(SC.ITEM_ACTION)
        if action == SC.ACTION_PLAY_URL:
            return
"""
    new_route = patch_season_reset.streamcinema(route)
    assert 'season_reset.confirm' in new_route
    assert patch_season_reset.streamcinema(new_route) == new_route
