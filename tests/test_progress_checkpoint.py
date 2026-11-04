from types import SimpleNamespace

from integration.sc_progress_checkpoint import ProgressCheckpoint
from integration.patch_progress_checkpoint import transform


def test_checkpoints_are_local_periodic_and_honor_seeks_and_pause():
    clock = [0]
    positions = []
    checkpoint = ProgressCheckpoint(SimpleNamespace(set_watched=positions.append), clock=lambda: clock[0])
    assert not checkpoint.save(120, 1000, 9)
    assert checkpoint.save(121, 1000, 10)
    clock[0] = 14
    assert not checkpoint.save(135, 1000, 24)
    clock[0] = 15
    assert checkpoint.save(136, 1000, 25)
    checkpoint.reschedule()
    assert checkpoint.save(50, 1000, 25)
    assert checkpoint.save(52, 1000, 27, force=True)
    assert positions == [121, 136, 50, 52]


def test_completed_invalid_and_closed_checkpoints_never_write():
    positions = []
    checkpoint = ProgressCheckpoint(SimpleNamespace(set_watched=positions.append))
    for position, duration in [(800, 1000), (float('nan'), 1000), (100, 0)]:
        assert not checkpoint.save(position, duration, 10)
    checkpoint.close()
    assert not checkpoint.save(100, 1000, 10, force=True)
    assert positions == []


def test_player_patch_is_compatible_with_reviewed_fixture():
    from pathlib import Path
    import os
    player = Path(os.environ['APPDATA']) / 'Kodi/addons/plugin.video.stream-cinema/resources/lib/services/player.py'
    if not player.exists():
        return
    source = player.read_text(encoding='utf-8')
    patched = transform(source)
    assert transform(patched) == patched
    assert 'self._save_progress_checkpoint()' in patched
    assert 'self._close_progress_checkpoint()' in patched


def test_patched_player_checkpoints_and_keeps_completion_clear():
    import ast
    import os
    from pathlib import Path
    import pytest

    player = Path(os.environ['APPDATA']) / 'Kodi/addons/plugin.video.stream-cinema/resources/lib/services/player.py'
    if not player.exists():
        pytest.skip('Reviewed Stream Cinema player is not installed')
    tree = ast.parse(transform(player.read_text(encoding='utf-8')))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SCPlayer')
    names = {'periodical_check', '_save_progress_checkpoint', '_close_progress_checkpoint'}
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name in names]
    module = ast.Module(body=[ast.ClassDef(name='PlayerHarness', bases=[], keywords=[], body=methods, decorator_list=[])],
                        type_ignores=[])
    scope = {'get_setting_as_bool': lambda _: False, 'debug': lambda _: None}
    exec(compile(ast.fix_missing_locations(module), '<player integration>', 'exec'), scope)
    p = scope['PlayerHarness']()
    saved = []
    clock = [0]
    p._progress_checkpoint = ProgressCheckpoint(SimpleNamespace(set_watched=saved.append), clock=lambda: clock[0])
    p._progress_tracker = SimpleNamespace(elapsed=10, observe=lambda pos: None)
    p.skip_button = SimpleNamespace(is_button_visible=False)
    p.isPlayback = lambda: True
    p.is_my_plugin = True
    p._update_last_seen = lambda pos: None
    p.getTime = lambda: 100
    p.getTotalTime = lambda: 1000
    p.watched = False
    p.set_watched = lambda: (p._close_progress_checkpoint(), saved.append(None))
    p.periodical_check()
    assert saved == [100]
    p.getTime = lambda: 900
    p.periodical_check()
    assert saved == [100, None]
    p.getTime = lambda: 150
    p.periodical_check()
    assert saved == [100, None]
