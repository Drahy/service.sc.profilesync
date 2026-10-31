import threading
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest

from integration.sc_stream_leases import install_stream_leases


class Session:
    def __init__(self):
        self.idle = 0

    def touch(self):
        self.idle = 0

    def is_expired(self, age):
        return self.idle > age


def handler(session, action):
    class Handler:
        path = '/stream/example?ignored=query'
        session_manager = SimpleNamespace(get=lambda key: session if key == 'example' else None)

        def do_GET(self):
            return self._handle_stream(urlsplit(self.path))

        def _handle_stream(self, parsed):
            return action()

    server = SimpleNamespace(RequestHandlerClass=Handler)
    install_stream_leases(server)
    return server, server.RequestHandlerClass()


def test_active_request_survives_expiry_and_releases_to_normal_idle_cleanup():
    session = Session()

    def request():
        session.idle = 1801
        assert not session.is_expired(1800)
        return 'original response'

    _, instance = handler(session, request)
    assert instance.do_GET() == 'original response'
    assert session.idle == 0 and session._sc_stream_lease.requests == 0
    session.idle = 1801
    assert session.is_expired(1800)


def test_cancel_or_upstream_error_releases_the_request():
    session = Session()

    def request():
        raise ConnectionResetError('Explicit Stop')

    _, instance = handler(session, request)
    with pytest.raises(ConnectionResetError):
        instance.do_GET()
    session.idle = 1801
    assert session._sc_stream_lease.requests == 0 and session.is_expired(1800)


def test_concurrent_ranges_hold_the_session_until_the_last_request_finishes():
    session = Session()
    started = threading.Barrier(3)
    first, second = threading.Event(), threading.Event()

    def request():
        started.wait(timeout=2)
        assert (first if threading.current_thread().name == 'first' else second).wait(2)

    server, _ = handler(session, request)
    workers = [threading.Thread(target=server.RequestHandlerClass().do_GET, name=name)
               for name in ('first', 'second')]
    for worker in workers:
        worker.start()
    try:
        started.wait(timeout=2)
        assert session._sc_stream_lease.requests == 2
        first.set()
        workers[0].join(2)
        assert not workers[0].is_alive() and session._sc_stream_lease.requests == 1
        session.idle = 1801
        assert not session.is_expired(1800)
    finally:
        first.set()
        second.set()
        for worker in workers:
            worker.join(2)
    assert not any(worker.is_alive() for worker in workers)
    assert session._sc_stream_lease.requests == 0
    session.idle = 1801
    assert session.is_expired(1800)


@pytest.mark.parametrize('path', ['/stream/unknown', '/other'])
def test_unknown_sessions_and_other_routes_keep_the_original_response(path):
    server, instance = handler(Session(), lambda: 404)
    instance.path = path
    assert instance.do_GET() == 404
    assert not hasattr(instance.session_manager.get('example'), '_sc_stream_lease')
    original = server.RequestHandlerClass
    install_stream_leases(server)
    assert server.RequestHandlerClass is original
