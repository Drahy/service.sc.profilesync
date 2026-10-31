from datetime import datetime

from integration.sc_last_viewed import remember
from resources.lib.profile import apply_rows, export
from resources.lib.sc_browse import most_recent_episode


def test_playback_start_keeps_completion_pointer_and_resume_untouched():
    data = {'last_ep':'1x2', 'play_count:1:2':1, 'watched:2:1':90}
    class Movie:
        def set_last_played(self, value): data['last_played:2:1'] = value
    assert remember(Movie(), 2, 1, lambda:datetime(2026,10,31,20,0))
    assert most_recent_episode(data) == '2x1'
    assert data['last_ep'] == '1x2'
    assert data['watched:2:1'] == 90
    assert data['play_count:1:2'] == 1


def test_episode_start_timestamp_uses_existing_compatible_sync_records():
    source = {'SCKODIItem-42':{'last_ep':'1x2', 'last_played:2:1':'2026-10-31 20:00:00'}}
    records, _ = export(source)
    assert 'history|42|2|1' in records
    changes = apply_rows({'SCKODIItem-42':{'last_ep':'1x2'}},
                         {k:{'value':v} for k,v in records.items()})
    assert most_recent_episode(changes['SCKODIItem-42']) == '2x1'
    assert changes['SCKODIItem-42']['last_ep'] == '1x2'


def test_films_and_invalid_episodes_do_not_write():
    class Movie:
        def set_last_played(self, value): raise AssertionError('unexpected write')
    for season, episode in ((None,None), (1,0), (-1,1), ('bad',1)):
        assert not remember(Movie(), season, episode)
