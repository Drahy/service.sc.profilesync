import ast
import os
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

from integration.last_seen_timing_patch import install, transform_item, transform_player
from integration import sc_last_seen, sc_last_viewed


def installed_source(relative):
    baseline = os.environ.get('SC_UNPATCHED_ADDON')
    if not baseline:
        pytest.skip('Set SC_UNPATCHED_ADDON to a compatible unpatched addon fixture')
    path = Path(baseline) / 'resources/lib' / relative
    if not path.exists():
        pytest.skip('Compatible Stream Cinema fixture unavailable')
    return path.read_bytes().decode('utf-8')


def test_existing_playback_and_webshare_hooks_are_preserved():
    source = installed_source('services/player.py')
    updated = transform_player(source)
    ast.parse(updated, feature_version=(3, 8))
    assert 'def _update_last_seen(' in updated
    assert "remember(self.movie, series, episode)" not in updated
    assert 'self._update_last_seen(self.current_time)' in updated
    assert "self.movie.scrobble(self.percent_played(), SCKODIItem.SCROBBLE_START)" in updated


def test_existing_stream_selection_no_longer_writes_history_at_resolve():
    source = installed_source('gui/item.py')
    updated = transform_item(source)
    ast.parse(updated, feature_version=(3, 8))
    assert 'st.add(res.getProperty(SC.ITEM_ID))' not in updated
    if '# SC Webshare Search integration v1' in source:
        assert '# SC Webshare Search integration v1' in updated
    assert 'self.item.setPath(url)' in updated


def test_unknown_stream_cinema_source_is_rejected():
    with pytest.raises(ValueError): transform_player('')
    with pytest.raises(ValueError): transform_item('')


def test_install_preflights_both_files_and_keeps_reversible_backups(tmp_path):
    root = tmp_path / 'addon'
    player = root / 'resources/lib/services/player.py'
    item = root / 'resources/lib/gui/item.py'
    player.parent.mkdir(parents=True)
    item.parent.mkdir(parents=True)
    original_player, original_item = installed_source('services/player.py'), installed_source('gui/item.py')
    player.write_bytes(original_player.encode('utf-8'))
    item.write_text('incompatible', encoding='utf-8')
    with pytest.raises(ValueError): install(root, tmp_path / 'backup')
    assert player.read_bytes() == original_player.encode('utf-8')
    item.write_bytes(original_item.encode('utf-8'))
    receipt = install(root, tmp_path / 'backup')
    assert len(receipt) == 2
    assert len(list((tmp_path / 'backup').glob('*.py'))) == 2
    assert 'def _update_last_seen(' in player.read_text(encoding='utf-8')
    assert 'st.add(res.getProperty(SC.ITEM_ID))' not in item.read_text(encoding='utf-8')


def test_real_player_tick_adds_episode_at_ten_seconds_and_only_once():
    tree = ast.parse(transform_player(installed_source('services/player.py')))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == 'SCPlayer')
    cls.body = [x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name in ('_update_last_seen', 'periodical_check')]
    cls.bases = []
    added, played, clock = [], [], [0.0]
    class History:
        def __init__(self, name): self.name = name
        def add(self, ident): added.append((self.name, ident))
    env = {'List':History, 'debug':lambda message:None, 'get_setting_as_bool':lambda key:False}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])), 'player-fixture.py', 'exec'), env)
    player = env['SCPlayer']()
    player.item = {'id':'42', 'lid':'lasts', 'info':{'season':2, 'episode':3}}
    player.movie = types.SimpleNamespace(set_last_played=played.append)
    player.is_my_plugin = True
    player.watched = False
    player.skip_button = types.SimpleNamespace(is_button_visible=False)
    player.isPlayback = lambda:True
    player.getTime = lambda:clock[0]
    player.getTotalTime = lambda:1200
    player._last_seen_tracker = sc_last_seen.PlaybackTracker(('lasts','42'), 0, 0)
    modules = {'resources.lib.common.last_seen':sc_last_seen, 'resources.lib.common.last_viewed':sc_last_viewed}
    with patch.dict(sys.modules, modules), patch.object(sc_last_seen.time, 'monotonic', lambda:clock[0]):
        for second in range(1, 10):
            clock[0] = second
            player.periodical_check()
        assert added == [] and played == []
        clock[0] = 10
        player.periodical_check()
        assert added == [('lasts','42')] and len(played) == 1
        clock[0] = 11
        player.periodical_check()
        assert added == [('lasts','42')] and len(played) == 1
