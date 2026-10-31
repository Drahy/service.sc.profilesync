"""Keep a proxy session alive while an HTTP stream request still owns it."""
import threading


class _StreamLease:
    def __init__(self, session):
        self.session = session
        self.expiry_method = 'is_expired' if hasattr(session, 'is_expired') else '_ie'
        self.original_expired = getattr(session, self.expiry_method)
        self.lock = threading.Lock()
        self.requests = 0

    def is_expired(self, age):
        with self.lock:
            return False if self.requests else self.original_expired(age)

    def acquire(self):
        with self.lock:
            self.requests += 1

    def release(self):
        with self.lock:
            # Resume/reconnect gets the normal idle interval after the last
            # active request ends. Unused sessions retain their usual expiry.
            self.session.touch()
            self.requests -= 1


def install_stream_leases(server, log=None):
    """Preserve bounded idle cleanup, cached HEADs and explicit Stop handling."""
    original = server.RequestHandlerClass
    if getattr(original, '_sc_stream_leases', False):
        return
    stream_method = '_handle_stream' if hasattr(original, '_handle_stream') else '_hs'
    install_lock = threading.Lock()

    class LeasedStreamHandler(original):
        _sc_stream_leases = True

        def _leased_stream(self, parsed):
            if not parsed.path.startswith('/stream/'):
                return getattr(super(), stream_method)(parsed)
            session_id = parsed.path[len('/stream/'):]
            session = self.session_manager.get(session_id)
            if session is None:
                return getattr(super(), stream_method)(parsed)
            with install_lock:
                lease = getattr(session, '_sc_stream_lease', None)
                if lease is None:
                    lease = _StreamLease(session)
                    setattr(session, lease.expiry_method, lease.is_expired)
                    session._sc_stream_lease = lease
                lease.acquire()
            try:
                return getattr(super(), stream_method)(parsed)
            finally:
                lease.release()

    setattr(LeasedStreamHandler, stream_method, LeasedStreamHandler._leased_stream)
    server.RequestHandlerClass = LeasedStreamHandler
    if log is not None:
        log('Active stream requests retain their proxy session; idle expiry is unchanged')
