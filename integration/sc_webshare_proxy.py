"""Serve Webshare streams through the existing loopback helper without remote HEADs."""
import json
import secrets
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler


def allowed_url(url):
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or '').lower()
        return (parsed.scheme == 'https' and not parsed.username and not parsed.password
                and (host == 'wsfiles.cz' or host.endswith('.wsfiles.cz')))
    except (ValueError, TypeError):
        return False


def _shutdown(sock):
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except (AttributeError, OSError):
        pass


def install_webshare_proxy(server, log=None, check_url=allowed_url, opener=None):
    """Add in-memory, capability-addressed streams; do not persist or log URLs."""
    parent = server.RequestHandlerClass
    if getattr(parent, '_sc_webshare_proxy', False):
        return
    lock, sessions, active = threading.Lock(), {}, set()

    class Redirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not check_url(newurl):
                raise ValueError('Untrusted redirect')
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    open_url = opener or build_opener(Redirect()).open

    class Handler(parent):
        _sc_webshare_proxy = True
        _ws_response = None
        _ws_entry = None
        _ws_cancelled = False

        def _lookup(self):
            path = urlsplit(self.path).path
            if not path.startswith('/webshare/'):
                return None
            with lock:
                entry = sessions.get(path[len('/webshare/'):])
                if not entry:
                    return None
                leased = any(handler._ws_entry is entry for handler in active)
                if entry['expires'] <= time.monotonic() and not leased:
                    return None
                entry['expires'] = time.monotonic() + 14400
                return entry

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == '/cancel-playback':
                with lock:
                    pending = tuple(active)
                for handler in pending:
                    handler._ws_cancelled = True
                    _shutdown(handler.connection)
                    response = handler._ws_response
                    _shutdown(getattr(getattr(getattr(response, 'fp', None), 'raw', None), '_sock', None))
                return super().do_POST()
            if path != '/webshare-register':
                return super().do_POST()
            if self.client_address[0] not in ('127.0.0.1', '::1'):
                self.send_error(403); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 1 <= length <= 16384:
                    raise ValueError('Invalid request')
                data = json.loads(self.rfile.read(length).decode('utf8'))
                url, size = data['url'], int(data['size'])
                if not check_url(url) or not 0 < size < 10**13:
                    raise ValueError('Invalid stream')
                mime = data.get('mime') or 'application/octet-stream'
                if mime not in ('video/mp4', 'video/x-matroska', 'video/webm', 'video/x-msvideo', 'video/mp2t', 'video/mpeg', 'video/quicktime', 'application/octet-stream'):
                    raise ValueError('Invalid type')
                key = secrets.token_urlsafe(24)
                with lock:
                    for old in [k for k, v in sessions.items() if v['expires'] <= time.monotonic()
                                and not any(handler._ws_entry is v for handler in active)]:
                        del sessions[old]
                    if len(sessions) >= 128:
                        raise ValueError('Too many sessions')
                    sessions[key] = {'url':url, 'size':size, 'mime':mime, 'expires':time.monotonic()+14400}
                body = json.dumps({'path':'/webshare/'+key}).encode()
                self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            except (KeyError, TypeError, ValueError, UnicodeError):
                self.send_error(400)

        def do_HEAD(self):
            if not urlsplit(self.path).path.startswith('/webshare/'):
                return super().do_HEAD()
            entry = self._lookup()
            if entry is None:
                self.send_error(404); return
            size = entry['size']
            header = self.headers.get('Range')
            start, end = 0, size - 1
            if header:
                import re
                match = re.fullmatch(r'bytes=(\d*)-(\d*)', header.strip())
                if not match or not (match.group(1) or match.group(2)):
                    self.send_error(416); return
                if not match.group(1):
                    count = int(match.group(2))
                    start = max(0, size - count)
                else:
                    start = int(match.group(1))
                    if match.group(2): end = min(end, int(match.group(2)))
                if start >= size or start > end:
                    self.send_error(416); return
                self.send_response(206)
                self.send_header('Content-Range', 'bytes %s-%s/%s' % (start, end, size))
            else:
                self.send_response(200)
            self.send_header('Content-Length',str(end-start+1)); self.send_header('Content-Type',entry['mime']); self.send_header('Accept-Ranges','bytes'); self.end_headers()

        def do_GET(self):
            if not urlsplit(self.path).path.startswith('/webshare/'):
                return super().do_GET()
            entry = self._lookup()
            if entry is None:
                self.send_error(404); return
            self._ws_cancelled = False
            self._ws_entry = entry
            with lock:
                active.add(self)
            sent = False
            try:
                headers = {'Accept-Encoding':'identity'}
                if self.headers.get('Range'):
                    headers['Range'] = self.headers['Range']
                response = open_url(Request(entry['url'], headers=headers), timeout=25)
                self._ws_response = response
                if self._ws_cancelled:
                    return
                self.send_response(response.getcode())
                for name in ('Content-Length','Content-Range','Content-Type','Accept-Ranges'):
                    value = response.headers.get(name)
                    if value and '\r' not in value and '\n' not in value:
                        self.send_header(name, value)
                self.end_headers()
                sent = True
                while not self._ws_cancelled:
                    block = response.read(65536)
                    if not block:
                        break
                    self.wfile.write(block)
            except (OSError, ValueError, HTTPError):
                if not self._ws_cancelled and not sent:
                    try:self.send_error(502)
                    except OSError:pass
                elif sent:
                    _shutdown(self.connection)
            finally:
                with lock:active.discard(self)
                self._ws_entry = None
                response = self._ws_response
                self._ws_response = None
                if response:
                    try:response.close()
                    except OSError:pass

    server.RequestHandlerClass = Handler
