"""Count genuine playback before adding a Stream Cinema Last Seen entry."""
import re
import time

HISTORY_LISTS = {'lastf', 'lasts', 'lastd', 'lastk'}


def target(item, sc_id, parental=False):
    if not isinstance(item, dict):
        return None
    namespace = item.get('lid')
    ident = str(item.get('id') or '')
    if namespace not in HISTORY_LISTS or not re.fullmatch(r'[1-9][0-9]*', ident):
        return None
    if str(sc_id) != ident:
        return None
    return ('p-' + namespace if parental else namespace, ident)


def save(tracker, list_factory, movie, season, episode, remember):
    """Record a confirmed visit using existing SC lists and shared fields."""
    remember(movie, season, episode)
    list_factory(tracker.target[0]).add(tracker.target[1])
    tracker.saved()


class PlaybackTracker:
    """Accumulate normal forward media progress, never a seek or a pause."""
    def __init__(self, history_target, position=None, now=None):
        self.target = history_target
        self.elapsed = 0.0
        self.position = None
        self.when = None
        self.retry_after = 0.0
        self.done = False
        if position is not None:
            self.observe(position, now)

    def reset_sample(self):
        self.position = None
        self.when = None

    def observe(self, position, now=None):
        now = time.monotonic() if now is None else float(now)
        try:
            position = float(position)
        except (TypeError, ValueError, OverflowError):
            self.reset_sample()
            return False
        if position < 0 or not (position < float('inf')):
            self.reset_sample()
            return False
        if self.position is not None and self.when is not None:
            wall, progress = now - self.when, position - self.position
            if 0 < wall <= 5 and 0 < progress <= wall + 1:
                self.elapsed += min(wall, progress)
        self.position, self.when = position, now
        return not self.done and self.elapsed >= 10 and now >= self.retry_after

    def failed(self, now=None):
        self.retry_after = (time.monotonic() if now is None else float(now)) + 5

    def saved(self):
        self.done = True
