"""Persist in-progress Stream Cinema playback locally, without network calls."""
import math
import threading
import time


class ProgressCheckpoint:
    def __init__(self, movie, clock=None, interval=15):
        self.movie = movie
        self.clock = clock or time.monotonic
        self.interval = interval
        self.last_save = None
        self.closed = False
        self.lock = threading.Lock()

    def save(self, position, duration, elapsed, force=False):
        try:
            position, duration, elapsed = float(position), float(duration), float(elapsed)
        except (TypeError, ValueError, OverflowError):
            return False
        if not all(math.isfinite(n) for n in (position, duration, elapsed)):
            return False
        if elapsed < 10 or position <= 0 or duration <= 0 or position / duration >= 0.8:
            return False
        with self.lock:
            now = self.clock()
            if self.closed or (not force and self.last_save is not None and now - self.last_save < self.interval):
                return False
            self.movie.set_watched(position)
            self.last_save = now
            return True

    def reschedule(self):
        with self.lock:
            self.last_save = None

    def close(self):
        with self.lock:
            self.closed = True
