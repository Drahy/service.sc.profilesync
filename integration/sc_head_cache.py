"""Answer stream metadata requests without reopening an upstream video."""

import re
from urllib.parse import urlsplit


def _nonnegative_length(value):
    text = str(value)
    return int(text) if text.isascii() and text.isdigit() else None


def _response_metadata(response):
    """Normalize a ranged GET's length to the complete resource length."""
    status = response.getcode() if hasattr(response, 'getcode') else getattr(response, 'status', None)
    if status not in (200, 206):
        return None
    headers = response.headers
    content_range = headers.get('Content-Range')
    if status == 206:
        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', content_range or '')
        if not match:
            return None
        start, end, length = map(int, match.groups())
        if not 0 <= start <= end < length:
            return None
    else:
        length = _nonnegative_length(headers.get('Content-Length'))
        if length is None:
            return None
    content_type = headers.get('Content-Type')
    if content_type and ('\r' in content_type or '\n' in content_type):
        content_type = None
    return length, content_type


def install_cached_heads(server, log=None):
    """Keep GET/fallback handling intact; cache only immutable session metadata."""
    original_handler = server.RequestHandlerClass
    if getattr(original_handler, '_sc_cached_heads', False):
        return
    upstream_method = ('_open_upstream_with_fallback'
                       if hasattr(original_handler, '_open_upstream_with_fallback') else '_ouf')

    class CachedHeadHandler(original_handler):
        _sc_cached_heads = True

        def _cached_upstream(self, session, req_headers):
            response = getattr(super(), upstream_method)(session, req_headers)
            if response is not None:
                # Cache inspection must never prevent an otherwise valid GET.
                try:
                    metadata = _response_metadata(response)
                    if metadata is not None:
                        session._sc_head_metadata = metadata
                except (AttributeError, TypeError, ValueError):
                    pass
            return response

        def do_HEAD(self):
            parsed = urlsplit(self.path)
            # Preserve the existing semantics of ranged HEAD and other routes.
            if not parsed.path.startswith('/stream/') or self.headers.get('Range'):
                return super().do_HEAD()
            session = self.session_manager.get(parsed.path.split('/stream/', 1)[1])
            if session is None:
                self.send_error(404)
                return
            metadata = getattr(session, '_sc_head_metadata', None)
            if metadata is None:
                # Use the resolver's full file length when one is available.
                length = _nonnegative_length(getattr(session, 'content_length', None))
                if length is None or length == 0:
                    return super().do_HEAD()
                metadata = (length, None)
            length, content_type = metadata
            self.send_response(200)
            self.send_header('Content-Length', str(length))
            if content_type:
                self.send_header('Content-Type', content_type)
            self.send_header('Accept-Ranges', 'bytes')
            self.end_headers()
            if log is not None:
                try:
                    log('HEAD metadata served from the local playback session')
                except Exception:
                    pass

    setattr(CachedHeadHandler, upstream_method, CachedHeadHandler._cached_upstream)
    server.RequestHandlerClass = CachedHeadHandler
