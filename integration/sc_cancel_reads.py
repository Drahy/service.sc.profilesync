"""Release pending local stream reads when the viewer explicitly stops playback."""
import socket
import threading
from urllib.parse import urlsplit


def _shutdown_socket(connection):
    if connection is None:
        return
    try:
        connection.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass


def _upstream_socket(response):
    # urllib HTTPResponse owns the socket under a buffered SocketIO object.
    stream = getattr(response, 'fp', None)
    raw = getattr(stream, 'raw', None)
    return getattr(raw, '_sock', None)


def install_cancel_reads(server, log=None):
    original = server.RequestHandlerClass
    if getattr(original, '_sc_cancel_reads', False):
        return
    lock = threading.Lock()
    active = set()

    class CancelReadHandler(original):
        _sc_cancel_reads = True
        _sc_upstream = None
        _sc_cancelled = False

        def _handle_stream(self, parsed):
            self._sc_cancelled = False
            with lock:
                active.add(self)
            try:
                return super()._handle_stream(parsed)
            finally:
                with lock:
                    active.discard(self)

        def _open_upstream_with_fallback(self, session, req_headers):
            response = super()._open_upstream_with_fallback(session, req_headers)
            self._sc_upstream = response
            if response is not None and self._sc_cancelled:
                _shutdown_socket(_upstream_socket(response))
                response.close()
                return None
            return response

        def do_HEAD(self):
            if not urlsplit(self.path).path.startswith('/stream/'):
                return super().do_HEAD()
            self._sc_cancelled = False
            with lock:
                active.add(self)
            try:
                return super().do_HEAD()
            finally:
                with lock:
                    active.discard(self)

        def do_POST(self):
            if urlsplit(self.path).path != '/cancel-playback':
                return super().do_POST()
            with lock:
                pending = tuple(active)
            for handler in pending:
                handler._sc_cancelled = True
                # Shutdown, rather than close a buffered reader concurrently:
                # close() can wait for the same blocked read to release its lock.
                _shutdown_socket(handler.connection)
                _shutdown_socket(_upstream_socket(handler._sc_upstream))
            body = b'{"cancelled":%d}' % len(pending)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            if log is not None:
                log('Explicit Stop released %d pending stream request(s)' % len(pending))

    server.RequestHandlerClass = CancelReadHandler
