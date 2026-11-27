from integration.sc_last_seen import PlaybackTracker, save, target
from integration.playback_identity_patch import transform_last_seen, unfinished_episode
from resources.lib.profile import apply_rows
from resources.lib.sc_browse import most_recent_episode


def test_direct_episode_without_category_still_appears_in_last_seen():
    from inspect import getsource
    from integration import sc_last_seen

    scope = {}
    exec(transform_last_seen(getsource(sc_last_seen)), scope)
    episode = {'id': '42', 'info': {'season': 6, 'episode': 14}}
    assert scope['target'](episode, 42) == ('lasts', '42')
    assert scope['target'](episode, 42, True) == ('p-lasts', '42')
    assert scope['target'](episode, 43) is None
    assert scope['target'](dict(episode, lid='unknown'), 42) is None
    assert scope['target']({'id': '42'}, 42) is None


def test_autoplay_uses_a_newer_unfinished_episode_in_the_same_show():
    data = {'last_ep': '6x8', 'last_played:6:8': '2026-11-27 12:00:00',
            'last_played:6:14': '2026-11-27 13:37:53', 'watched:6:14': 107}
    assert unfinished_episode(data, most_recent_episode) == (6, 14)

    # A completed newer episode or an invalid position is not resumable.
    data['last_played:6:15'] = '2026-11-27 14:00:00'
    assert unfinished_episode(data, most_recent_episode) is None
    data['watched:6:15'] = 'NaN'
    assert unfinished_episode(data, most_recent_episode) is None


def test_real_playback_registers_after_ten_seconds_and_only_once():
    tracker = PlaybackTracker(('lasts','42'), 0, 0)
    for second in range(1, 10):
        assert not tracker.observe(second, second)
    assert tracker.observe(10, 10)
    tracker.saved()
    assert not tracker.observe(11, 11)


def test_pauses_buffering_and_large_seeks_do_not_count():
    tracker = PlaybackTracker(('lastf','42'), 0, 0)
    assert not tracker.observe(4, 4)
    assert not tracker.observe(4, 20)  # paused or stalled
    assert not tracker.observe(1000, 21)  # seek forward
    assert not tracker.observe(1005, 26)
    assert tracker.elapsed == 9
    assert tracker.observe(1006, 27)


def test_seek_callback_drops_the_pending_sample_and_resume_offsets():
    tracker = PlaybackTracker(('lasts','42'), 900, 0)
    assert not tracker.observe(904, 4)
    tracker.reset_sample()
    assert not tracker.observe(1200, 5)
    assert not tracker.observe(1205, 10)
    assert tracker.observe(1206, 11)


def test_failed_write_can_retry_without_replaying_ten_seconds():
    tracker = PlaybackTracker(('lasts','42'), 0, 0)
    assert not tracker.observe(5, 5)
    assert tracker.observe(10, 10)
    tracker.failed(10)
    assert not tracker.observe(11, 11)
    assert tracker.observe(15, 15)


def test_history_target_is_restricted_to_matching_sc_identity():
    assert target({'lid':'lastf','id':'42'}, '42') == ('lastf','42')
    assert target({'lid':'lasts','id':42}, 42, True) == ('p-lasts','42')
    assert target({'lid':'lastf','id':'42'}, '43') is None
    assert target({'lid':'bad','id':'42'}, '42') is None
    assert target({'lid':'lastf','id':'../../42'}, '../../42') is None


def test_save_updates_only_the_expected_list_and_episode_start():
    events = []
    class History:
        def __init__(self, name): self.name = name
        def add(self, ident): events.append(('list', self.name, ident))
    tracker = PlaybackTracker(('lasts','42'), 0, 0)
    save(tracker, History, 'movie', 5, 20, lambda movie,s,e:events.append(('played', movie,s,e)))
    assert events == [('played','movie',5,20), ('list','lasts','42')]
    assert tracker.done


def test_removing_last_seen_entry_preserves_watched_and_resume_data():
    rows = {'lasts':{'list':['42','43']}, 'SCKODIItem-42':{'last_ep':'1x2','watched:1:2':75,'play_count:1:1':1}}
    records = {'list|lasts|42':{'value':None,'v':[10,1,'device']}}
    changes = apply_rows(rows, records)
    assert changes['lasts']['list'] == ['43']
    assert 'SCKODIItem-42' not in changes
