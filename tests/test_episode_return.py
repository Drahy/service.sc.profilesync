import json
import sys
from types import SimpleNamespace

import pytest

from integration import sc_episode_return as entry


def test_shared_last_watched_episode_wins_over_a_browsed_row():
    saved = {'checkpoint': {'item': '/Play/42/3/7'}}
    target = entry.target(['99', '42'], lambda show: '5x4' if show == '99' else '3x2', saved)
    assert target == {'id': '99', 'url': '/FGet/99/5', 'resume_episode': '4', 'navigation_restore': '1'}


def test_last_episode_survives_return_to_the_main_menu():
    saved = {'episode': {'item': '/Play/42/0/2'}, 'checkpoint': {'item': '/Catalogue'}}
    assert entry.target([], lambda show: None, saved)['url'] == '/FGet/42/0'


@pytest.mark.parametrize('item', ['/Play/42', '/FGet/42/3', 'https://example.org/', '/Play/42/3/0'])
def test_unknown_or_playable_movie_checkpoint_cannot_start_a_video(item):
    assert entry.target([], lambda show: None, {'checkpoint': {'item': item}}) is None


def test_new_device_can_open_shared_history_without_a_local_navigation_checkpoint():
    assert entry.target(['42'], lambda show: '3x2', {})['resume_episode'] == '2'


def test_fresh_main_entry_redirects_but_normal_back_to_menu_does_not(tmp_path, monkeypatch):
    props = {}
    window = SimpleNamespace(getProperty=lambda key: props.get(key, ''), setProperty=lambda key, val: props.__setitem__(key, val))
    monkeypatch.setitem(sys.modules, 'xbmc', SimpleNamespace(Player=lambda: SimpleNamespace(isPlaying=lambda: False)))
    monkeypatch.setitem(sys.modules, 'xbmcgui', SimpleNamespace(Window=lambda identifier: window))
    monkeypatch.setitem(sys.modules, 'xbmcvfs', SimpleNamespace(translatePath=lambda path: path))
    monkeypatch.setitem(sys.modules, 'resources.lib.constants', SimpleNamespace(ADDON=SimpleNamespace(getAddonInfo=lambda key: str(tmp_path))))
    (tmp_path / 'navigation-state.json').write_text(json.dumps({'episode': {'item': '/Play/42/3/2'}}))
    monkeypatch.setattr(entry, 'load_target', lambda state: entry.target([], lambda show: None, state))
    assert entry.prepare_entry({})['url'] == '/FGet/42/3'
    assert entry.prepare_entry({}) is None


@pytest.mark.parametrize('args', [{'action': 'last'}, {'widget': 'true'}, {'url': '/FGet/42'}, {'play': '/Play/42'}])
def test_normal_routes_actions_and_widgets_are_not_redirected(args):
    assert entry.prepare_entry(args) is None
