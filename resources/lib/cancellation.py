"""Shared cancellation signal without importing Kodi or networking."""


class SyncStopped(Exception):
    """An intentional stop, without acknowledging unfinished synchronization."""
