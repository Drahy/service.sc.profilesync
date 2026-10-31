import http.server
import json
import threading
import time
import urllib.request

from integration.sc_webshare_proxy import allowed_url, install_webshare_proxy


class Empty(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_POST(self):
        if self.path == '/cancel-playback':
            self.send_response(200); self.send_header('Content-Length', '0'); self.end_headers()
        else: self.send_error(404)


def request(url, data=None, method=None, headers=None):
    return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=headers or {}), timeout=3)


def test_local_heads_and_range_get_without_origin_head():
    events = []
    class Origin(Empty):
        def do_HEAD(self): events.append('HEAD'); self.send_error(500)
        def do_GET(self):
            events.append('GET')
            b = b'0123456789'
            if self.headers.get('Range'):
                b = b[3:]; self.send_response(206); self.send_header('Content-Range', 'bytes 3-9/10')
            else: self.send_response(200)
            self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    origin = http.server.ThreadingHTTPServer(('127.0.0.1',0), Origin)
    helper = http.server.ThreadingHTTPServer(('127.0.0.1',0), Empty)
    install_webshare_proxy(helper, check_url=lambda url:url.startswith('http://127.0.0.1:'))
    for server in (origin, helper):threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:%d' % helper.server_port
    try:
        data=json.dumps({'url':'http://127.0.0.1:%d/file' % origin.server_port,'size':10,'mime':'video/mp4'}).encode()
        with request(base+'/webshare-register',data) as r:path=json.load(r)['path']
        with request(base+path,method='HEAD') as r: assert r.headers['Content-Length']=='10'
        with request(base+path,method='HEAD',headers={'Range':'bytes=3-'}) as r:
            assert r.status==206 and r.headers['Content-Range']=='bytes 3-9/10'
        assert events==[]
        with request(base+path,headers={'Range':'bytes=3-'}) as r:
            assert r.status==206 and r.read()==b'3456789'
            assert r.headers['Content-Range']=='bytes 3-9/10'
        assert events==['GET']
        with request(base+'/cancel-playback',b'') as r:assert r.status==200
    finally:
        for server in (origin,helper):server.shutdown();server.server_close()


def test_only_allowed_webshare_hosts():
    assert allowed_url('https://free.3.dl.wsfiles.cz/file')
    assert not allowed_url('http://free.3.dl.wsfiles.cz/file')
    assert not allowed_url('https://wsfiles.cz.example.com/file')
    assert not allowed_url('https://user@wsfiles.cz/file')


def test_explicit_stop_closes_client_while_origin_is_stalled():
    ready = threading.Event()
    release = threading.Event()
    class Slow(Empty):
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Length','100000'); self.end_headers()
            self.wfile.write(b'x'); self.wfile.flush(); ready.set()
            release.wait(3)
    origin=http.server.ThreadingHTTPServer(('127.0.0.1',0), Slow)
    helper=http.server.ThreadingHTTPServer(('127.0.0.1',0), Empty)
    install_webshare_proxy(helper, check_url=lambda u:u.startswith('http://127.0.0.1:'))
    for server in (origin,helper): threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:%d' % helper.server_port
    try:
        data=json.dumps({'url':'http://127.0.0.1:%d/file'%origin.server_port,'size':100000}).encode()
        with request(base+'/webshare-register',data) as r: path=json.load(r)['path']
        finished=threading.Event()
        def reader():
            try:
                with request(base+path) as r: r.read()
            except Exception: pass
            finally:finished.set()
        threading.Thread(target=reader,daemon=True).start()
        assert ready.wait(2)
        started=time.monotonic()
        with request(base+'/cancel-playback',b'') as r: assert r.status==200
        assert finished.wait(1.5)
        assert time.monotonic()-started<1.5
    finally:
        release.set()
        for server in (origin,helper):server.shutdown();server.server_close()


def test_active_stream_survives_idle_expiry(monkeypatch):
    from types import SimpleNamespace
    import integration.sc_webshare_proxy as proxy
    clock = SimpleNamespace(value=0)
    monkeypatch.setattr(proxy, 'time', SimpleNamespace(monotonic=lambda:clock.value))
    ready, release = threading.Event(), threading.Event()
    class Slow(Empty):
        def do_GET(self):
            ready.set(); release.wait(3)
            try:self.send_response(200); self.send_header('Content-Length','1'); self.end_headers(); self.wfile.write(b'x')
            except OSError:pass
    origin=http.server.ThreadingHTTPServer(('127.0.0.1',0),Slow)
    helper=http.server.ThreadingHTTPServer(('127.0.0.1',0),Empty)
    install_webshare_proxy(helper,check_url=lambda u:u.startswith('http://127.0.0.1:'))
    for server in (origin,helper):threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:%d'%helper.server_port
    try:
        with request(base+'/webshare-register',json.dumps({'url':'http://127.0.0.1:%d/file'%origin.server_port,'size':1}).encode()) as r:path=json.load(r)['path']
        def reader():
            try:
                with request(base+path) as r:r.read()
            except Exception:pass
        threading.Thread(target=reader,daemon=True).start()
        assert ready.wait(2)
        clock.value=14401
        with request(base+path,method='HEAD') as r:assert r.status==200
    finally:
        release.set()
        for server in (origin,helper):server.shutdown();server.server_close()
