"""Keep expensive snapshots separate from lightweight event checks."""

import time

LOCAL_DEFAULT = 15
REMOTE_DEFAULT = 60
MAX_BACKOFF = 180


def interval(value, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, int(float(value))))
    except (TypeError, ValueError, OverflowError):
        return default


class Schedule:
    def __init__(self, local=LOCAL_DEFAULT, remote=REMOTE_DEFAULT, now=None):
        self.now = now or time.monotonic
        self.local_due = self.remote_due = 0
        self.request_due = None
        self.retry = 0
        self.configure(local, remote)

    def configure(self, local, remote):
        self.local = interval(local, LOCAL_DEFAULT, 5, 120)
        self.remote = interval(remote, REMOTE_DEFAULT, 30, 300)
        current = self.now()
        self.local_due = min(self.local_due, current + self.local)
        self.remote_due = min(self.remote_due, current + self.remote)

    def request(self, delay=0):
        due = self.now() + max(0, delay)
        self.request_due = due if self.request_due is None else min(self.request_due, due)

    def take(self):
        current = self.now()
        network = current >= self.remote_due or self.request_due is not None and current >= self.request_due
        local = network or current >= self.local_due
        if network:
            self.remote_due = current + self.remote
            self.request_due = None
        if local:
            self.local_due = current + self.local
        return local, network

    def success(self):
        self.retry = 0

    def failure(self):
        ceiling = max(MAX_BACKOFF, self.remote)
        self.retry = min((self.retry or self.remote) * 2, ceiling)
        self.remote_due = self.now() + self.retry
        return self.retry
