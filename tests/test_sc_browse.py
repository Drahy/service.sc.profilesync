import copy

import pytest

from resources.lib.sc_browse import all_seasons, focus_request, history_response, last_seen_item


def test_last_seen_opens_the_exact_shared_season_without_starting_video():
    original = {"type": "dir", "url": "/FGet/42?dub=1", "id": "42", "title": "Show"}
    item = last_seen_item(original, lambda show: "9x3" if show == "42" else None)
    assert item["url"] == "/FGet/42/9?dub=1"
    assert item["resume_episode"] == "3"
    assert item["resume_seasons"] == original["url"]
    assert "resume_episode" not in original
    assert focus_request(item["url"], item["resume_episode"]) == {"route": "/FGet/42/9", "item": "/Play/42/9/3"}


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
    with pytest.raises(ValueError):
        history_response(ids, lambda route: {}, "lasts", "Last seen", "Next Page")


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
