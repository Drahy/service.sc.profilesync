from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from integration import sc_continuous_resume as resume


def metadata():
    return {'id': '42', 'info': {'season': 3, 'episode': 2, 'duration': 1200}}


def test_provider_episode_request_bypasses_only_the_native_resume_prompt():
    original = {'url': '/Play/m_example/3/2'}
    assert resume.play_command(original, lambda value: 'plugin://sc/?url=encoded') == 'PlayMedia(plugin://sc/?url=encoded&sc_next_resume=31,noresume)'
    assert original == {'url': '/Play/m_example/3/2'}
    assert resume.play_command({'url': '/Play/42'}, lambda value: 'plugin://sc/movie') == 'PlayMedia(plugin://sc/movie)'


def test_transition_token_survives_kodi_hex_encoded_parameters():
    token = '0123456789abcdef0123456789abcdef'
    cmd = resume.play_command({'url': '/Play/42/3/2'}, lambda _: 'plugin://sc/?url=encoded', token)
    encoded = cmd.split('sc_next_token=')[1].split(',')[0]
    assert bytes.fromhex(encoded).decode('ascii') == token


def test_duplicate_callbacks_are_atomic_and_cancellation_allows_retry(tmp_path):
    path = str(tmp_path / 'guard.db')
    info = {'url': '/Play/42/3/2'}
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: resume.claim_transition(info, path=path, now=100), range(8)))
    tokens = [value for value in claims if value]
    assert len(tokens) == 1 and claims.count(None) == 7
    args = {resume.FLAG: '1', resume.TOKEN: tokens[0], 'url': info['url']}
    resume.finish_transition(dict(args, sc_next_token='f' * 32), False, path=path, now=101)
    assert resume.claim_transition(info, path=path, now=102) is None
    resume.finish_transition(args, False, path=path, now=103)
    assert resume.claim_transition(info, path=path, now=104)


def test_completed_transition_blocks_late_duplicate_briefly_but_not_other_episodes(tmp_path):
    path = str(tmp_path / 'guard.db')
    info = {'url': '/Play/42/3/2'}
    token = resume.claim_transition(info, path=path, now=100)
    args = {resume.FLAG: '1', resume.TOKEN: token, 'url': info['url']}
    resume.finish_transition(args, True, path=path, now=109)
    assert resume.claim_transition(info, path=path, now=110) is None
    assert resume.claim_transition({'url': '/Play/42/3/3'}, path=path, now=110)
    assert resume.claim_transition(info, path=path, now=124)


def test_expired_or_clock_reset_leases_never_block_future_playback(tmp_path):
    path = str(tmp_path / 'guard.db')
    info = {'url': '/Play/42/3/2'}
    assert resume.claim_transition(info, path=path, now=100)
    assert resume.claim_transition(info, path=path, now=99)
    assert resume.claim_transition(info, path=path, now=99 + resume.PENDING_LEASE_SECONDS)
    assert resume.claim_transition({'url': '/Play/42'}, path=path, now=100) == ''


def test_active_transition_renews_while_the_viewer_decides(tmp_path):
    path = str(tmp_path / 'guard.db')
    info = {'url': '/Play/42/3/2'}
    token = resume.claim_transition(info, path=path, now=100)
    args = {resume.FLAG: '1', resume.TOKEN: token, 'url': info['url']}
    resume.renew_transition(args, path=path, now=150)
    assert resume.claim_transition(info, path=path, now=170) is None
    assert resume.claim_transition(info, path=path, now=210)


def test_manual_requests_never_start_a_guard_thread():
    assert resume.start_heartbeat({}) is None


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


def test_resume_dialog_has_wide_vertically_navigable_choices():
    from pathlib import Path
    import xml.etree.ElementTree as ET
    layout = Path(__file__).parents[1] / 'integration/skins/default/1080i/sc-next-resume.xml'
    root = ET.parse(layout).getroot()
    buttons = {int(control.get('id')): control for control in root.iter('control')
               if control.get('type') == 'button'}
    assert set(buttons) == {10, 11, 12}
    assert all(int(button.findtext('width')) >= 800 for button in buttons.values())
    assert [int(buttons[i].findtext('top')) for i in (10, 11, 12)] == sorted(
        int(buttons[i].findtext('top')) for i in (10, 11, 12))
    assert [buttons[i].findtext('ondown') for i in (10, 11, 12)] == ['11', '12', '10']
