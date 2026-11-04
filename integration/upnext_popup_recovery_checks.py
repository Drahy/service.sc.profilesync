from datetime import date
from types import SimpleNamespace

import popup_recovery as recovery
from watchtimer import WatchTimer

import pytest


@pytest.fixture(autouse=True)
def recovery_window(monkeypatch):
    values = {}
    monkeypatch.setattr(recovery, "get_property", lambda key: values.get(key, ""))
    monkeypatch.setattr(recovery, "set_property", lambda key, value: values.__setitem__(key, value))
    monkeypatch.setattr(recovery, "clear_property", lambda key: values.pop(key, None))




def test_open_popup_restores_only_matching_playback_and_preserves_timer(monkeypatch):
    store = {}
    monkeypatch.setattr(recovery, 'get_property', lambda k: store.get(k, ''))
    monkeypatch.setattr(recovery, 'set_property', lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(recovery, 'clear_property', lambda k: store.pop(k, None))
    timer = WatchTimer()
    timer.elapsed = 125.0
    timer.bedtime_pending = date(2026, 11, 4)
    timer.bedtime_acknowledged = date(2026, 11, 3)
    state = SimpleNamespace(queued=False, played_in_a_row=4, current_tv_show_id='123', watch_timer=timer)
    api = SimpleNamespace(data={'next_episode': {'episodeid': 'e2'}, 'id': 'stream_play_action'}, encoding='base64')
    recovery.remember('stream-one', api, state)
    saved = recovery.read()
    assert 'stream-one' not in store[recovery.KEY]
    calls = []
    target_api = SimpleNamespace(addon_data_received=lambda data, encoding: calls.append((data, encoding)))
    target_state = SimpleNamespace(watch_timer=WatchTimer())
    player = SimpleNamespace(state=target_state, set_last_file=lambda f: calls.append(('last', f)),
                             enable_tracking=lambda: calls.append(('tracking', True)))
    assert not recovery.restore(saved, 'different-stream', target_api, player, False)
    assert calls == []
    assert recovery.restore(saved, 'stream-one', target_api, player, True)
    assert target_state.pause and target_state.played_in_a_row == 4
    assert target_state.watch_timer.elapsed == 125
    assert target_state.watch_timer.bedtime_pending == date(2026, 11, 4)
    assert target_state.watch_timer.bedtime_acknowledged == date(2026, 11, 3)
    assert calls[-2:] == [('last', None), ('tracking', True)]


def test_dismissed_popup_cannot_be_recreated_by_periodic_refresh(monkeypatch):
    store = {}
    monkeypatch.setattr(recovery, 'get_property', lambda k: store.get(k, ''))
    monkeypatch.setattr(recovery, 'set_property', lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(recovery, 'clear_property', lambda k: store.pop(k, None))
    state = SimpleNamespace(queued=False, played_in_a_row=1, current_tv_show_id=None, watch_timer=WatchTimer())
    api = SimpleNamespace(data={'next_episode': {'episodeid': 2}}, encoding='base64')
    recovery.remember('one', api, state)
    recovery.clear()
    recovery.remember('one', api, state, refresh=True)
    assert recovery.read() is None
    state.queued = True
    recovery.remember('one', api, state)
    assert recovery.read() is None


def test_monitor_recovers_once_when_same_file_becomes_ready(monkeypatch):
    import monitor
    state = SimpleNamespace(watch_timer=WatchTimer(), queued=False, played_in_a_row=2, current_tv_show_id=7)
    source = SimpleNamespace(data={'next_episode': {'episodeid': 2}}, encoding='base64')
    recovery.remember('one', source, state)
    loaded = []
    api = SimpleNamespace(data={}, has_addon_data=lambda: False,
                          addon_data_received=lambda data, encoding: loaded.append(data))
    player = SimpleNamespace(state=SimpleNamespace(watch_timer=WatchTimer()), getPlayingFile=lambda: 'one',
                             getTotalTime=lambda: 200, set_last_file=lambda value: None,
                             enable_tracking=lambda: loaded.append('tracking'))
    instance = object.__new__(monitor.UpNextMonitor)
    instance.api, instance.player, instance._recovering_popup = api, player, True
    instance.log = lambda *args: None
    monkeypatch.setattr(monitor, 'getCondVisibility', lambda _: True)
    instance.restore_popup_after_restart()
    instance.restore_popup_after_restart()
    assert loaded == [source.data, 'tracking']
    assert player.state.pause is True
    assert player.state.played_in_a_row == 2


def test_user_back_clears_snapshot_before_service_restart(monkeypatch):
    from popup import ACTION_NAV_BACK, Popup
    state = SimpleNamespace(queued=False, played_in_a_row=1, current_tv_show_id=1, watch_timer=WatchTimer())
    api = SimpleNamespace(data={'next_episode': {'episodeid': 'e2'}}, encoding='base64')
    recovery.remember('one', api, state)
    page = object.__new__(Popup)
    page.close = lambda: None
    page.onAction(ACTION_NAV_BACK)
    assert page.is_dismissed()
    assert recovery.read() is None


def test_wake_without_ready_player_keeps_snapshot_for_later(monkeypatch):
    import monitor
    state = SimpleNamespace(watch_timer=WatchTimer(), queued=False, played_in_a_row=2, current_tv_show_id=7)
    source = SimpleNamespace(data={'next_episode': {'episodeid': 2}}, encoding='base64')
    recovery.remember('one', source, state)
    ready = [False]
    api = SimpleNamespace(data={}, has_addon_data=lambda: False,
                          addon_data_received=lambda data, encoding: setattr(api, 'data', data))
    def filename():
        if not ready[0]:
            raise RuntimeError('player still sleeping')
        return 'one'
    player = SimpleNamespace(state=SimpleNamespace(watch_timer=WatchTimer()), getPlayingFile=filename,
                             getTotalTime=lambda: 200, set_last_file=lambda value: None,
                             enable_tracking=lambda: None)
    instance = object.__new__(monitor.UpNextMonitor)
    instance.api, instance.player, instance._recovering_popup = api, player, True
    instance.log = lambda *args: None
    monkeypatch.setattr(monitor, 'getCondVisibility', lambda _: False)
    instance.restore_popup_after_restart()
    assert instance._recovering_popup and recovery.read() is not None
    ready[0] = True
    instance.restore_popup_after_restart()
    assert api.data == source.data


def test_wake_request_exists_only_for_an_open_popup():
    state = SimpleNamespace(watch_timer=WatchTimer(), queued=False, played_in_a_row=2, current_tv_show_id=7)
    api = SimpleNamespace(data={'next_episode': {'episodeid': 2}}, encoding='base64')
    recovery.request_wake()
    assert not recovery.wake_requested()
    recovery.remember('one', api, state)
    recovery.request_wake()
    assert recovery.wake_requested()
    recovery.clear()
    assert not recovery.wake_requested()
