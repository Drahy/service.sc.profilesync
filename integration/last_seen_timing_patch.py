"""Qualify the ten-second Last Seen hook for compatible Stream Cinema files."""
import argparse
import hashlib
from pathlib import Path


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Incompatible Stream Cinema source; no changes made')
    return source.replace(old, new, 1)


def transform_player(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    source = replace_once(source, 'from resources.lib.common.lists import SCKODIItem\n',
                          'from resources.lib.common.lists import List, SCKODIItem\n')
    source = replace_once(source, '        self.settings = settings\n',
                          '        self._last_seen_tracker = None\n        self.settings = settings\n')
    old = '''            # Record the most recently played episode independently of completion.
            try:
                from resources.lib.common.last_viewed import remember
                remember(self.movie, series, episode)
            except Exception:
                debug('Could not save latest episode playback time')
'''
    new = '''            # Record the visit only after ten seconds of real playback.
            self._last_seen_tracker = None
            try:
                from resources.lib.common.last_seen import PlaybackTracker, target
                from resources.lib.gui.item import parental_history
                history_target = target(self.item, self.my_id, parental_history())
                if history_target:
                    try:
                        position = self.getTime()
                    except Exception:
                        position = None
                    self._last_seen_tracker = PlaybackTracker(history_target, position)
            except Exception:
                debug('Could not initialize Last Seen timer')
'''
    source = replace_once(source, old, new)
    source = replace_once(source, '''    def end_playback(self):
        try:
''', '''    def end_playback(self):
        self._update_last_seen()
        try:
''')
    source = replace_once(source, '''    def percent_played(self):
''', '''    def _update_last_seen(self, position=None):
        tracker = getattr(self, '_last_seen_tracker', None)
        if tracker is None or tracker.done:
            return
        try:
            if position is None:
                position = self.getTime()
            if tracker.observe(position):
                from resources.lib.common.last_seen import save
                from resources.lib.common.last_viewed import remember
                info = self.item.get('info', {})
                save(tracker, List, self.movie, info.get('season'), info.get('episode'), remember)
        except Exception:
            tracker.failed()
            debug('Could not save Last Seen entry; retrying')

    def percent_played(self):
''')
    source = replace_once(source, '''        self.current_time = self.getTime()
        self.total_time = self.getTotalTime()
''', '''        self.current_time = self.getTime()
        self._update_last_seen(self.current_time)
        self.total_time = self.getTotalTime()
''')
    source = replace_once(source, '''        debug('player SCPlayer Clean')
''', '''        debug('player SCPlayer Clean')
        self._last_seen_tracker = None
''')
    for method in ('onPlayBackPaused', 'onPlayBackResumed', 'onPlayBackSpeedChanged',
                   'onPlayBackSeek', 'onPlayBackSeekChapter'):
        marker = '    def ' + method + '('
        start = source.find(marker)
        if start < 0 or source.find(marker, start + 1) >= 0:
            raise ValueError('Incompatible playback callbacks; no changes made')
        line_end = source.index('\n', start)
        source = source[:line_end + 1] + '''        tracker = getattr(self, '_last_seen_tracker', None)
        if tracker is not None:
            tracker.reset_sample()
''' + source[line_end + 1:]
    compile(source, 'player.py', 'exec')
    return source.replace('\n', newline)


def transform_item(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    old = '''        if 'lid' in data:
            lid = 'p-{}'.format(data.get('lid')) if parental_history() else data.get('lid')
            # Keep Last seen entries until the user removes them.
            st = List(lid)
            st.add(res.getProperty(SC.ITEM_ID))
'''
    source = replace_once(source, old, '')
    compile(source, 'item.py', 'exec')
    return source.replace('\n', newline)


def install(addon_root, backup_dir):
    files = [
        (addon_root / 'resources/lib/services/player.py', transform_player),
        (addon_root / 'resources/lib/gui/item.py', transform_item),
    ]
    prepared = []
    for path, transform in files:
        before = path.read_bytes()
        after = transform(before.decode('utf-8')).encode('utf-8')
        prepared.append((path, before, after))
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path, before, _ in prepared:
        digest = hashlib.sha256(before).hexdigest()
        backup = backup_dir / (path.stem + '-' + digest + path.suffix)
        if backup.exists() and backup.read_bytes() != before:
            raise RuntimeError('Backup conflicts with source')
        if not backup.exists(): backup.write_bytes(before)
    if any(path.read_bytes() != before for path, before, _ in prepared):
        raise RuntimeError('Stream Cinema changed while preparing installation')
    written = []
    try:
        for path, before, after in prepared:
            if path.read_bytes() != before:
                raise RuntimeError('Stream Cinema changed before installation')
            temporary = path.with_name(path.name + '.lastseen.tmp')
            temporary.write_bytes(after)
            temporary.replace(path)
            written.append((path, before, after))
            if path.read_bytes() != after:
                raise RuntimeError('Installed file readback failed')
    except Exception:
        for path, before, after in reversed(written):
            if path.read_bytes() == after:
                temporary = path.with_name(path.name + '.lastseen-rollback.tmp')
                temporary.write_bytes(before)
                temporary.replace(path)
        raise
    return [(str(path), hashlib.sha256(before).hexdigest(), hashlib.sha256(after).hexdigest())
            for path, before, after in prepared]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('addon_root', type=Path)
    parser.add_argument('backup_dir', type=Path)
    args = parser.parse_args()
    for path, before, after in install(args.addon_root, args.backup_dir):
        print(path, before, after)
