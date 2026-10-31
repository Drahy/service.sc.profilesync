"""Refresh expired local stream handles using their original Stream Cinema item."""
import json
import threading
import time
from collections import OrderedDict
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen


def current_account_token():
    """Read Stream Cinema's current account session without storing or logging it."""
    try:
        import xbmcaddon  # Kodi is not available in isolated proxy tests.
        return xbmcaddon.Addon('plugin.video.stream-cinema').getSetting('kraska.token')
    except (ImportError, RuntimeError):
        return None


class _Recovery:
    def __init__(self, ident, server):
        self.ident = ident
        self.server = server
        self.lock = threading.Lock()
        self.failed_at = 0


class _Registry:
    def __init__(self, capacity=128):
        self.capacity = capacity
        self.entries = OrderedDict()
        self.lock = threading.Lock()

    def remember(self, handle, ident, server):
        with self.lock:
            self.entries.pop(handle, None)
            self.entries[handle] = _Recovery(ident, server)
            while len(self.entries) > self.capacity:
                self.entries.popitem(last=False)

    def get(self, handle):
        with self.lock:
            value = self.entries.get(handle)
            if value is not None:
                self.entries.move_to_end(handle)
            return value


def install_wake_streams(server, get_token, log=None):
    """Re-resolve known handles without persisting credentials or changing Kodi's URL."""
    original = server.RequestHandlerClass
    if getattr(original, '_sc_wake_streams', False):
        return
    registry = _Registry()

    class WakeStreamHandler(original):
        _sc_wake_streams = True
        _sc_wake_context = None

        def log_message(self, message, *args):
            # The core's request log otherwise includes the account token in
            # the /play query. Other routes retain the original logging.
            if urlsplit(self.path).path == '/play':
                return None
            return super().log_message(message, *args)

        def _handle_play(self, parsed):
            params = parse_qs(parsed.query)
            ident = params.get('ident', [None])[0]
            preferred = params.get('server', [None])[0]
            # Internal refreshes keep the original handle; do not add another
            # registry entry for their temporary handle.
            self._sc_wake_context = ((ident, preferred)
                                     if ident and len(ident) <= 4096 and 'sc_wake' not in params else None)
            try:
                return super()._handle_play(parsed)
            finally:
                self._sc_wake_context = None

        def _send_json(self, data, status=200):
            if self._sc_wake_context and status == 200 and isinstance(data, dict):
                parsed = urlsplit(data.get('url', ''))
                if parsed.hostname == '127.0.0.1' and parsed.path.startswith('/stream/'):
                    registry.remember(parsed.path[len('/stream/'):], *self._sc_wake_context)
            return super()._send_json(data, status)

        def _resolve_again(self, entry, token):
            params = {'ident': entry.ident, 'token': token, 'sc_wake': '1'}
            if entry.server:
                params['server'] = entry.server
            url = 'http://127.0.0.1:%d/play?%s' % (self.server.server_address[1], urlencode(params))
            with urlopen(url, timeout=8) as response:
                return json.load(response)

        def _resolve_after_wake(self, entry, token):
            try:
                return self._resolve_again(entry, token)
            except HTTPError as error:
                if error.code != 502:
                    raise
                # Profile Sync or Stream Cinema may refresh its account token
                # asynchronously after wake. Retry only if it really changed.
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and not getattr(self, '_sc_cancelled', False):
                    refreshed = get_token()
                    if refreshed and refreshed != 'False' and refreshed != token:
                        return self._resolve_again(entry, refreshed)
                    time.sleep(.1)
                raise

        def _recover_stream(self, parsed):
            if not parsed.path.startswith('/stream/'):
                return
            handle = parsed.path[len('/stream/'):]
            manager = self.session_manager
            if manager.get(handle) is not None:
                return
            entry = registry.get(handle)
            if entry is None:
                return
            with entry.lock:
                if manager.get(handle) is not None or getattr(self, '_sc_cancelled', False):
                    return
                if entry.failed_at and time.monotonic() - entry.failed_at < 3:
                    return
                try:
                    token = get_token()
                    if not token or token == 'False':
                        raise ValueError('No active account session')
                    payload = self._resolve_after_wake(entry, token)
                    refreshed = urlsplit(payload.get('url', ''))
                    if refreshed.hostname != '127.0.0.1' or not refreshed.path.startswith('/stream/'):
                        raise ValueError('Stream resolver did not return a local handle')
                    new_handle = refreshed.path[len('/stream/'):]
                    if getattr(self, '_sc_cancelled', False):
                        with manager._lock:
                            manager._sessions.pop(new_handle, None)
                        return
                    with manager._lock:  # The reviewed Android helper owns this map under the same lock.
                        session = manager._sessions.pop(new_handle, None)
                        if session is None:
                            raise ValueError('Refreshed stream session is unavailable')
                        session.session_id = handle
                        manager._sessions[handle] = session
                    entry.failed_at = 0
                    if log is not None:
                        log('Refreshed an expired playback session after wake')
                except (HTTPError, URLError, OSError, ValueError, TypeError, KeyError):
                    entry.failed_at = time.monotonic()
                    if log is not None:
                        log('Could not refresh an expired playback session')

        def _handle_stream(self, parsed):
            self._recover_stream(parsed)
            if getattr(self, '_sc_cancelled', False):
                return None
            return super()._handle_stream(parsed)

        def do_HEAD(self):
            self._recover_stream(urlsplit(self.path))
            if getattr(self, '_sc_cancelled', False):
                return None
            return super().do_HEAD()

    server.RequestHandlerClass = WakeStreamHandler
    if log is not None:
        log('Expired playback sessions can be refreshed using the current account session')
