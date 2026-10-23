from types import SimpleNamespace

import pytest

from integration import sc_continuous_resume as resume


def metadata():
    return {'id': '42', 'info': {'season': 3, 'episode': 2, 'duration': 1200}}


def test_provider_episode_request_bypasses_only_the_native_resume_prompt():
    original = {'url': '/Play/m_example/3/2'}
    assert resume.play_command(original, lambda value: 'plugin://sc/?url=encoded') == 'PlayMedia(plugin://sc/?url=encoded&sc_next_resume=31,noresume)'
    assert original == {'url': '/Play/m_example/3/2'}
    assert resume.play_command({'url': '/Play/42'}, lambda value: 'plugin://sc/movie') == 'PlayMedia(plugin://sc/movie)'


def test_idle_countdown_starts_at_visibility_and_defaults_to_beginning():
    decision = resume.Decision(83)
    assert decision.remaining(100) is None and not decision.finished
    decision.ready_at = 100
    assert decision.remaining(100) == 5
    assert decision.remaining(104.2) == 1
    assert decision.remaining(105) == 0
    assert decision.finished and decision.value == 0


def test_directional_input_pauses_the_deadline_for_a_deliberate_resume_choice():
    decision = resume.Decision(83)
    decision.ready_at = 100
    decision.action(2)
    assert decision.remaining(120) is None and not decision.finished
    decision.select(11)
    assert decision.finished and decision.value == 83


@pytest.mark.parametrize('action', [9, 10, 13, 92, 216])
def test_stop_back_and_escape_cancel_the_transition(action):
    decision = resume.Decision(83)
    decision.ready_at = 100
    decision.action(action)
    assert decision.finished and decision.value is None


@pytest.mark.parametrize('value', [None, 0, -1, 'bad', float('nan'), float('inf'), 1200, 1800])
def test_invalid_completed_or_missing_positions_start_from_beginning_without_a_prompt(value):
    assert resume.saved_position(metadata(), lambda namespace, key: value) == (0, 1200)


def test_lookup_uses_the_shared_episode_namespace_without_writes():
    calls = []
    def read(namespace, key):
        calls.append((namespace, key))
        return 83
    assert resume.saved_position(metadata(), read) == (83, 1200)
    assert calls == [('SCKODIItem-42', 'watched:3:2')]


def test_manual_playback_never_reads_or_changes_resume_metadata():
    assert resume.prepare(None, {}, {}, read=lambda *args: pytest.fail('Manual playback touched'))


@pytest.mark.parametrize('chosen,expected', [(0, (0.0, 1200)), (83, (83.0, 1200)), (None, None)])
def test_resolved_item_receives_only_the_explicit_choice(chosen, expected):
    calls = []
    item = SimpleNamespace(getVideoInfoTag=lambda: SimpleNamespace(setResumePoint=lambda *value: calls.append(value)))
    assert resume.prepare(item, metadata(), {resume.FLAG: '1'}, read=lambda *args: 83, choose=lambda position: chosen) is (chosen is not None)
    assert calls == ([] if expected is None else [expected])


def test_time_format_includes_hours_only_when_needed():
    assert resume.timestamp(83) == '01:23'
    assert resume.timestamp(3661) == '1:01:01'
