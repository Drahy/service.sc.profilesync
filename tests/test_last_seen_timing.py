from integration.sc_last_seen import PlaybackTracker, save, target
from resources.lib.profile import apply_rows


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
