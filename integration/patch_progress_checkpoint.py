"""Install local playback checkpoints into the reviewed Stream Cinema player."""

MARKER = '# SC local progress checkpoint v1'


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        return source.replace('\n', newline)

    def replace(old, new):
        nonlocal source
        if source.count(old) != 1:
            raise ValueError('Incompatible Stream Cinema player checkpoint integration')
        source = source.replace(old, new, 1)

    replace('        self._last_seen_tracker = None\n        self.settings = settings\n',
            '        # SC local progress checkpoint v1\n        self._progress_checkpoint = None\n'
            '        self._progress_tracker = None\n'
            '        self._last_seen_tracker = None\n        self.settings = settings\n')
    replace('            self.movie = None\n            self.my_id = None\n',
            '            self._close_progress_checkpoint()\n            self.movie = None\n            self.my_id = None\n')
    replace('            # Record the visit only after ten seconds of real playback.\n',
            '            from resources.lib.common.progress_checkpoint import ProgressCheckpoint\n'
            '            from resources.lib.common.last_seen import PlaybackTracker\n'
            '            self._progress_checkpoint = ProgressCheckpoint(self.movie)\n'
            '            self._progress_tracker = PlaybackTracker(None)\n'
            '            # Record the visit only after ten seconds of real playback.\n')
    replace("        debug('player onPlayBackPaused')\n", "        self._save_progress_checkpoint(force=True)\n"
            "        debug('player onPlayBackPaused')\n")
    replace("        debug('player onPlayBackSeek {} {}'.format(time, seekOffset))\n",
            "        if self._progress_checkpoint is not None:\n            self._progress_checkpoint.reschedule()\n"
            "        debug('player onPlayBackSeek {} {}'.format(time, seekOffset))\n")
    replace("        debug('player onPlayBackSeekChapter {}'.format(chapter))\n",
            "        if self._progress_checkpoint is not None:\n            self._progress_checkpoint.reschedule()\n"
            "        debug('player onPlayBackSeekChapter {}'.format(chapter))\n")
    replace('    def end_playback(self):\n        self._update_last_seen()\n',
            '    def end_playback(self):\n        self._close_progress_checkpoint()\n        self._update_last_seen()\n')
    sample = '        if tracker is not None:\n            tracker.reset_sample()\n'
    if source.count(sample) != 5:
        raise ValueError('Incompatible playback event callbacks')
    source = source.replace(sample, sample + '        progress_tracker = getattr(self, "_progress_tracker", None)\n'
                            '        if progress_tracker is not None:\n            progress_tracker.reset_sample()\n')
    replace('    def _update_last_seen(self, position=None):\n', '''    def _close_progress_checkpoint(self):
        checkpoint = getattr(self, '_progress_checkpoint', None)
        if checkpoint is not None:
            checkpoint.close()
        self._progress_checkpoint = None
        self._progress_tracker = None

    def _save_progress_checkpoint(self, force=False):
        checkpoint = getattr(self, '_progress_checkpoint', None)
        tracker = getattr(self, '_progress_tracker', None)
        if checkpoint is None or tracker is None:
            return
        try:
            position = self.getTime() if force else self.current_time
            duration = self.getTotalTime() if force else self.total_time
            checkpoint.save(position, duration, tracker.elapsed, force=force)
        except Exception:
            debug('Could not save local playback checkpoint')

    def _update_last_seen(self, position=None):
''')
    replace('            if percent_played > 80:\n',
            '            if percent_played >= 80:\n                self._close_progress_checkpoint()\n')
    replace('        self.total_time = self.getTotalTime()\n\n        if get_setting_as_bool(',
            '        self.total_time = self.getTotalTime()\n'
            '        if self._progress_tracker is not None:\n'
            '            self._progress_tracker.observe(self.current_time)\n'
            '        self._save_progress_checkpoint()\n\n'
            '        if get_setting_as_bool(')
    compile(source, 'player.py', 'exec')
    return source.replace('\n', newline)
