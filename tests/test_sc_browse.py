import copy

import pytest

from resources.lib.sc_browse import all_seasons, combined_history_response, focus_request, history_response, last_seen_item, most_recent_episode


def test_combined_history_orders_categories_and_preserves_membership():
    lists = [('lasts', ['1', '2']), ('lastf', ['3']), ('lastd', ['4'])]
    dates = {'1': {'last_played:1:2': '2026-01-01 12:00:00'},
             '2': {}, '3': {'last_played': '2026-01-02 12:00:00'}, '4': {}}
    titles = {'lasts': {'1':'Show one', '2':'Show two'}, 'lastf':{'3':'Movie'}, 'lastd':{'4':'Other'}}
    original = copy.deepcopy(lists)
    result = combined_history_response(lists, lambda route: {}, lambda ident: dates[ident],
                                       'Last Seen', 'Next', size=2, titles=titles)
    assert [(row['id'], row['lid']) for row in result['menu'][:2]] == [('3', 'lastf'), ('1', 'lasts')]
    assert result['menu'][2]['id'] == 'last-all'
    assert len(combined_history_response(lists, lambda route: {}, lambda ident: dates[ident],
                                         'Last Seen', 'Next', page=1, size=2, titles=titles)['menu']) == 2
    assert lists == original


def test_combined_history_caches_titles_and_uses_them_when_catalogue_is_down():
    cached = {'lastf': {}}
    movie = {'info': {'id':'3', 'info': {'title':'A Movie', 'mediatype':'movie'}}}
    combined_history_response([('lastf',['3'])], lambda _: movie, lambda _: {},
                              'Last Seen', 'Next', titles=cached)
    assert cached['lastf']['3'] == 'A Movie'
    down = combined_history_response([('lastf',['3'])], lambda _: {}, lambda _: {},
                                     'Last Seen', 'Next', titles=cached)
    assert down['menu'][0]['info']['title'] == 'A Movie'


def test_history_detail_cache_avoids_repeat_requests_and_preserves_art():
    calls, cache = [], {}

    def load(route):
        calls.append(route)
        return show_metadata()
    first = history_response(['42'], load, 'lasts', 'Last seen', 'Next', details=cache, now=100)
    second = history_response(['42'], load, 'lasts', 'Last seen', 'Next', details=cache, now=101)
    assert calls == ['/FGet/42']
    assert second['menu'] == first['menu']
    assert second['menu'][0]['i18n_art']
    history_response(['42'], load, 'lasts', 'Last seen', 'Next', details=cache, now=100 + 21600)
    assert len(calls) == 2


def test_combined_history_stops_requests_after_server_failure_and_uses_saved_details():
    from types import SimpleNamespace

    class Failure(Exception):
        response = SimpleNamespace(status_code=503)

    cache = {'lasts': {}}
    combined_history_response([('lasts', ['1', '2'])], lambda _: show_metadata(), lambda _: {},
                              'Last seen', 'Next', details=cache, now=1)
    calls = []

    def fail(route):
        calls.append(route)
        raise Failure()
    result = combined_history_response([('lasts', ['1', '2'])], fail, lambda _: {},
                                       'Last seen', 'Next', details=cache, now=30000)
    assert len(calls) == 1
    assert [item['id'] for item in result['menu']] == ['1', '2']


def test_item_not_found_does_not_suppress_remaining_history_requests():
    from types import SimpleNamespace

    class Missing(Exception):
        response = SimpleNamespace(status_code=404)

    calls = []

    def load(route):
        calls.append(route)
        if route.endswith('/1'):
            raise Missing()
        return show_metadata()
    result = history_response(['1', '2'], load, 'lasts', 'Last seen', 'Next')
    assert calls == ['/FGet/1', '/FGet/2']
    assert [item['id'] for item in result['menu']] == ['2']


def test_last_seen_opens_the_exact_shared_season_without_starting_video():
    original = {"type": "dir", "url": "/FGet/42?dub=1", "id": "42", "title": "Show"}
    item = last_seen_item(original, lambda show: "9x3" if show == "42" else None)
    assert item["url"] == "/FGet/42/9?dub=1"
    assert item["resume_episode"] == "3"
    assert item["resume_seasons"] == original["url"]
    assert "resume_episode" not in original
    assert focus_request(item["url"], item["resume_episode"]) == {"route": "/FGet/42/9", "item": "/Play/42/9/3"}


def test_latest_started_episode_wins_without_changing_completed_pointer():
    history = {'last_ep':'4x8', 'last_played:4:8':'2026-10-31 20:00:00',
               'last_played:5:2':'2026-10-31 21:00:00', 'watched:5:2':45}
    original = copy.deepcopy(history)
    assert most_recent_episode(history) == '5x2'
    assert history == original
    item = last_seen_item({'type':'dir','url':'/FGet/42'}, lambda _:most_recent_episode(history))
    assert item['url'] == '/FGet/42/5'
    assert item['resume_episode'] == '2'


def test_latest_episode_falls_back_to_existing_completed_pointer():
    assert most_recent_episode({'last_ep':'3x4', 'last_played:5:2':'bad'}) == '3x4'
    assert most_recent_episode({'last_ep':'bad'}) is None


def test_movies_unknown_history_and_season_entries_stay_unchanged():
    for route in ("/Play/42", "/FGet/42/9", "https://example.org/FGet/42"):
        item = {"type": "dir", "url": route}
        assert last_seen_item(item, lambda show: "9x3") is item
    item = {"type": "dir", "url": "/FGet/42"}
    for last in (None, "", "1x0", "bad", "9x-2"):
        assert last_seen_item(item, lambda show: last) is item


def test_specials_and_all_seasons_remain_available():
    item = last_seen_item({"type": "dir", "url": "/FGet/42"}, lambda show: "0x2")
    assert item["url"] == "/FGet/42/0"
    assert all_seasons("/FGet/42/0?dub=1") == "/FGet/42?dub=1"


def test_invalid_focus_targets_cannot_open_playback_or_foreign_folders():
    for route in ("/Play/42/9/3", "https://example.org/FGet/42/9", "/FGet/42", "/FGet/42/../9"):
        assert focus_request(route, "3") is None
    for episode in (None, "", "0", "3);PlayMedia(bad)"):
        assert focus_request("/FGet/42/9", episode) is None


def show_metadata():
    return {
        "system": {"setContent": "seasons", "setPluginCategory": "Example show"},
        "menu": [
            {
                "info": {
                    "title": "Season 1",
                    "tvshowtitle": "Example show",
                    "season": 1,
                    "episode": 12,
                    "mediatype": "season",
                    "year": 2000,
                },
                "i18n_art": {"en": {"poster": "https://images.example/show.jpg"}},
                "unique_ids": {"imdb": "tt123"},
            }
        ],
    }


def test_history_uses_detail_routes_preserves_order_and_does_not_mutate_cached_seasons():
    source = show_metadata()
    original = copy.deepcopy(source)
    calls = []

    def load(route):
        calls.append(route)
        return source

    response = history_response(["42", "43", "42"], load, "lasts", "Last seen", "Next Page")
    assert calls == ["/FGet/42", "/FGet/43"]
    assert [item["id"] for item in response["menu"]] == ["42", "43"]
    assert response["menu"][0]["info"]["title"] == "Example show"
    assert response["menu"][0]["info"]["mediatype"] == "tvshow"
    assert "season" not in response["menu"][0]["info"]
    assert source == original


def test_older_history_stays_reachable_without_fetching_every_page():
    calls = []

    def load(route):
        calls.append(route)
        return show_metadata()

    response = history_response(range(1, 26), load, "lasts", "Last seen", "Next Page", size=20)
    assert len(calls) == 20
    assert response["menu"][-1]["type"] == "next"
    assert response["menu"][-1]["page"] == "1"
    calls.clear()
    response = history_response(range(1, 26), load, "lasts", "Last seen", "Next Page", page=1, size=20)
    assert calls == ["/FGet/" + str(i) for i in range(21, 26)]
    assert all(item["type"] == "dir" for item in response["menu"])


def test_unavailable_titles_are_not_deleted_from_saved_history():
    ids = ["42", "43"]
    response = history_response(
        ids, lambda route: {} if route.endswith("42") else show_metadata(), "lasts", "Last seen", "Next Page"
    )
    assert ids == ["42", "43"]
    assert [item["id"] for item in response["menu"]] == ["43"]
    result = history_response(ids, lambda route: {}, "lasts", "Last seen", "Next Page")
    assert result['menu'] == []
    assert [item['id'] for item in history_response(ids, lambda _: show_metadata(), 'lasts', 'Last seen', 'Next')['menu']] == ids


def test_one_failed_metadata_request_does_not_hide_other_history():
    ids = ['42', '43']
    def load(route):
        if route.endswith('42'):
            raise TimeoutError('temporary')
        return show_metadata()
    result = history_response(ids, load, 'lasts', 'Last seen', 'Next Page')
    assert [item['id'] for item in result['menu']] == ['43']
    assert ids == ['42', '43']


def test_next_page_remains_accessible_when_current_page_temporarily_fails():
    def load(_): raise TimeoutError('temporary')
    result = history_response(['42', '43'], load, 'lasts', 'Last seen', 'Next Page', size=1)
    assert result['menu'][0]['type'] == 'next'
    assert result['menu'][0]['page'] == '1'


def test_cached_title_survives_an_unavailable_catalogue_without_readding_removed_entries():
    titles = {}
    history_response(['42'], lambda _: show_metadata(), 'lasts', 'Last seen', 'Next', titles=titles)
    assert titles == {'42': 'Example show'}
    def offline(_): raise TimeoutError()
    result = history_response(['42'], offline, 'lasts', 'Last seen', 'Next', titles=titles)
    assert result['menu'][0]['info']['title'] == 'Example show'
    assert result['menu'][0]['url'] == '/FGet/42'
    assert history_response([], offline, 'lasts', 'Last seen', 'Next', titles=titles)['menu'] == []


def test_film_history_can_use_play_metadata_if_folder_lookup_fails():
    def load(route):
        if route.startswith('/FGet/'):
            raise TimeoutError('temporary')
        return {'info':{'info':{'title':'Film','mediatype':'movie'}}}
    result = history_response(['42'], load, 'lastf', 'Last seen', 'Next Page')
    assert result['menu'][0]['type'] == 'video'
    assert result['menu'][0]['url'] == '/Play/42'


def test_film_history_uses_play_metadata_when_folder_returns_empty():
    calls = []
    def load(route):
        calls.append(route)
        return {} if route.startswith('/FGet/') else {'info':{'info':{'title':'Film','mediatype':'movie'}}}
    result = history_response(['42'], load, 'lastf', 'Last seen', 'Next Page')
    assert calls == ['/FGet/42', '/Play/42']
    assert result['menu'][0]['info']['title'] == 'Film'


def test_movie_history_never_exposes_or_plays_resolved_stream_urls():
    movie = {
        "info": {"info": {"title": "Example film", "mediatype": "movie"}, "i18n_art": {"en": {"poster": "poster"}}},
        "strms": [{"url": "private-stream"}],
    }
    response = history_response(
        ["42"],
        lambda route: {"system": {"setContent": "seasons"}} if route.startswith("/FGet/") else movie,
        "lastf",
        "Last seen",
        "Next Page",
    )
    assert response["menu"][0]["type"] == "video"
    assert response["menu"][0]["url"] == "/Play/42"
    assert "strms" not in response["menu"][0]
    assert response["menu"][0]["info"]["title"] == "Example film"
    assert response["menu"][0]["i18n_art"]["en"]["poster"] == "poster"


def test_single_season_shows_use_episode_metadata_without_becoming_playable():
    source = show_metadata()
    source["system"]["setContent"] = "episodes"
    source["system"]["setPluginCategory"] = "Season 1"
    source["menu"][0]["info"]["mediatype"] = "episode"
    result = history_response(["42"], lambda route: source, "lasts", "Last seen", "Next Page")
    assert result["menu"][0]["info"]["title"] == "Example show"
    assert result["menu"][0]["type"] == "dir"
