import io
import json
import threading
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from integration import sc_wake_streams as wake


def setup_handler(monkeypatch, get_token=None):
    manager = SimpleNamespace(_sessions={}, _lock=threading.Lock())
    manager.get = lambda handle: manager._sessions.get(handle)
    calls = []

    class Handler:
        session_manager = manager
        server = SimpleNamespace(server_address=('127.0.0.1', 54321))

        def log_message(self, message, *args):
            return message, args

        def _handle_play(self, parsed):
            return self._send_json({'url': 'http://127.0.0.1:54321/stream/original'})

        def _send_json(self, data, status=200):
            return data, status

        def _handle_stream(self, parsed):
            return manager.get(parsed.path.rsplit('/', 1)[-1])

        def do_HEAD(self):  # pylint: disable=invalid-name
            return self._handle_stream(urlsplit(self.path))

    server = SimpleNamespace(RequestHandlerClass=Handler)
    wake.install_wake_streams(server, get_token or (lambda: 'new-fake-token'))
    handler = server.RequestHandlerClass()
    handler._handle_play(urlsplit('/play?ident=fake-ident&token=old&server=example'))

    def refresh(url, timeout):
        calls.append(url)
        assert timeout == 8
        manager._sessions['fresh'] = SimpleNamespace(session_id='fresh')
        return io.BytesIO(json.dumps({'url': 'http://127.0.0.1:54321/stream/fresh'}).encode())

    monkeypatch.setattr(wake, 'urlopen', refresh)
    return handler, manager, calls


def test_expired_handle_gets_new_session_and_current_credentials(monkeypatch):
    handler, manager, calls = setup_handler(monkeypatch)
    session = handler._handle_stream(urlsplit('/stream/original'))
    assert session is manager._sessions['original'] and session.session_id == 'original'
    assert len(calls) == 1 and 'token=new-fake-token' in calls[0]
    assert 'ident=fake-ident' in calls[0] and 'server=example' in calls[0]
    assert handler._handle_stream(urlsplit('/stream/original')) is session
    assert len(calls) == 1


def test_head_can_recover_and_unknown_handles_remain_missing(monkeypatch):
    handler, manager, calls = setup_handler(monkeypatch)
    handler.path = '/stream/unknown'
    assert handler.do_HEAD() is None and calls == []
    handler.path = '/stream/original'
    assert handler.do_HEAD() is manager._sessions['original']
    assert len(calls) == 1


def test_concurrent_requests_resolve_once(monkeypatch):
    handler, manager, calls = setup_handler(monkeypatch)
    entered, gate = threading.Event(), threading.Event()
    refresh = wake.urlopen

    def delayed(url, timeout):
        entered.set()
        assert gate.wait(2)
        return refresh(url, timeout)

    monkeypatch.setattr(wake, 'urlopen', delayed)
    results = []
    threads = [threading.Thread(target=lambda: results.append(handler._handle_stream(urlsplit('/stream/original'))))
               for _ in range(2)]
    for thread in threads:
        thread.start()
    try:
        assert entered.wait(2)
    finally:
        gate.set()
        for thread in threads:
            thread.join(2)
    assert len(results) == 2 and results[0] is results[1] is manager._sessions['original']
    assert len(calls) == 1 and not any(thread.is_alive() for thread in threads)


def test_missing_token_does_not_revive_or_change_account(monkeypatch):
    handler, manager, calls = setup_handler(monkeypatch)
    handler._handle_play(urlsplit('/play?ident=another&token=old&server=example'))
    # Use a separate instance with an unavailable account token.
    original = type(handler).__mro__[1]
    server = SimpleNamespace(RequestHandlerClass=original)
    wake.install_wake_streams(server, lambda: None)
    other = server.RequestHandlerClass()
    other._handle_play(urlsplit('/play?ident=fake-ident&token=old'))
    assert other._handle_stream(urlsplit('/stream/original')) is None
    assert not manager._sessions and calls == []


def test_failed_refresh_keeps_original_failure_and_avoids_retry_storm(monkeypatch):
    handler, manager, _ = setup_handler(monkeypatch)
    attempts = []

    def failed(url, timeout):
        attempts.append(True)
        raise URLError('offline')

    monkeypatch.setattr(wake, 'urlopen', failed)
    assert handler._handle_stream(urlsplit('/stream/original')) is None
    assert handler._handle_stream(urlsplit('/stream/original')) is None
    assert attempts == [True] and not manager._sessions


def test_resolver_retries_when_another_addon_refreshes_account_token(monkeypatch):
    tokens = iter(['old-fake-token', 'new-fake-token'])
    handler, manager, calls = setup_handler(monkeypatch, lambda: next(tokens))
    refresh = wake.urlopen

    def stale_then_refresh(url, timeout):
        if 'old-fake-token' in url:
            raise HTTPError('http://127.0.0.1', 502, 'unavailable', {}, None)
        return refresh(url, timeout)

    monkeypatch.setattr(wake, 'urlopen', stale_then_refresh)
    assert handler._handle_stream(urlsplit('/stream/original')) is manager._sessions['original']
    assert len(calls) == 1 and 'token=new-fake-token' in calls[0]


def test_stop_before_refresh_never_starts_a_new_resolve(monkeypatch):
    handler, manager, calls = setup_handler(monkeypatch)
    handler._sc_cancelled = True
    assert handler._handle_stream(urlsplit('/stream/original')) is None
    assert not manager._sessions and calls == []


def test_registry_retains_only_a_bounded_number_of_nonsecret_entries():
    registry = wake._Registry(capacity=2)  # pylint: disable=protected-access
    for index in range(3):
        registry.remember(str(index), 'ident', None)
    assert registry.get('0') is None and registry.get('2').ident == 'ident'


def test_play_query_with_account_token_is_not_written_to_request_log(monkeypatch):
    handler, _, _ = setup_handler(monkeypatch)
    handler.path = '/play?ident=fake&token=private-fake-token'
    assert handler.log_message('%s', handler.path) is None
    handler.path = '/stream/original'
    assert handler.log_message('%s', handler.path) == ('%s', ('/stream/original',))
