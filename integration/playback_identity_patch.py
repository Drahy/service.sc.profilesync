"""Keep Stream Cinema playback tracking tied to each resolved episode."""
from .last_seen_timing_patch import replace_once


def transform_player(source):
    if 'self._active_playback_context = json_data' in source:
        return source
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    source = replace_once(source, '        self.settings = settings\n',
                          '        self._active_playback_context = None\n        self.settings = settings\n')
    start = source.index('        self.up_next = False\n', source.index('    def set_item('))
    end = source.index('        if self.my_id is not None:\n', start)
    expected = source[start:end]
    for marker in ('self.my_id == new_sc_id', "getProperty('SC.play_item')",
                   'self._close_progress_checkpoint()', "loads(ids)"):
        if marker not in expected:
            raise ValueError('Incompatible Stream Cinema playback initialization')
    source = replace_once(source, expected, """        json_data = self.win.getProperty('SC.play_item')
        if not json_data or self._active_playback_context == json_data:
            return

        item_data = loads(json_data)
        new_item = item_data['info']
        info = new_item['info']
        unique_ids = info.get('unique_ids') or new_item.get('unique_ids') or {}
        stream = item_data['strms']
        linfo = stream.get('linfo')

        # The SC ID identifies the whole show. Each resolved stream has its own
        # context, including the season and episode used by the progress tracker.
        self._close_progress_checkpoint()
        self._last_seen_tracker = None
        self._active_playback_context = json_data
        self.item = new_item
        self.ids = unique_ids
        self.my_id = unique_ids.get('sc')
        self.movie = None
        self.is_my_plugin = False
        self.current_time = 0
        self.total_time = 0
        self.watched = False
        self.scrobbled_final = False
        self.up_next = False
        self.skip_start = False
        self.skip_time_start = False
        self.skip_time_end = False
""")
    source = replace_once(source, '            all_item_data = loads(self.win.getProperty(SC.SELECTED_ITEM))\n',
                          '            all_item_data = stream\n')
    start = source.index("        self.win.clearProperty('SC.play_item')\n", source.index('    def clean('))
    end = source.index('        self.current_time = 0\n', start)
    expected = source[start:end]
    for marker in ('SC.SELECTED_ITEM', 'script.trakt.ids', 'sc.webshare.origin'):
        if marker not in expected:
            raise ValueError('Incompatible Stream Cinema playback cleanup')
    source = replace_once(source, expected, """        pending = self.win.getProperty('SC.play_item')
        if not pending or pending == self._active_playback_context:
            self.win.clearProperty('SC.play_item')
            self.win.clearProperty('sc.webshare.origin')
            self.win.clearProperty(SC.SELECTED_ITEM)
            self.win.clearProperty('{}.ids'.format(ADDON_ID))
            self.win.clearProperty('script.trakt.ids')
        self._active_playback_context = None
""")
    compile(source, 'services/player.py', 'exec')
    return source.replace('\n', newline)


def transform_last_seen(source):
    if '# A direct episode route can omit its history category.' in source:
        return source
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    source = replace_once(source, "    namespace = item.get('lid')\n", """    namespace = item.get('lid')
    if not namespace:
        # A direct episode route can omit its history category.
        info = item.get('info') or {}
        if (re.fullmatch(r'[0-9]+', str(info.get('season')))
                and re.fullmatch(r'[1-9][0-9]*', str(info.get('episode')))):
            namespace = 'lasts'
""")
    compile(source, 'common/last_seen.py', 'exec')
    return source.replace('\n', newline)


def unfinished_episode(data, most_recent_episode):
    """Return the latest episode if it has a saved position to resume."""
    latest = most_recent_episode(data)
    if not latest:
        return None
    season, episode = (int(part) for part in latest.split('x'))
    try:
        position = float(data.get('watched:%d:%d' % (season, episode)) or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    return (season, episode) if 0 < position < float('inf') else None


def transform_streamcinema(source):
    if 'def unfinished_episode(data, most_recent_episode):' in source:
        return source
    import inspect

    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    source = replace_once(source, 'from resources.lib.common import resume_browse\n',
                          'from resources.lib.common import resume_browse\n\n\n'
                          + inspect.getsource(unfinished_episode) + '\n')
    source = replace_once(source, """                    and self.args.get('navigation_restore') != '1' and not self.args.get('resume_episode')):
""", """                    and not xbmc.Player().isPlaying()
                    and not self.args.get('resume_token')
                    and self.args.get('navigation_restore') != '1' and not self.args.get('resume_episode')):
""")
    source = replace_once(source, '                last_ep = ki.get_last_ep()\n',
                          '                unfinished = unfinished_episode(ki.data, resume_browse.most_recent_episode)\n'
                          '                last_ep = ki.get_last_ep()\n')
    source = replace_once(source, "                if last_ep and autoplay_done == '' and (stop is None or stop == ''):\n",
                          "                if (unfinished or last_ep) and not autoplay_done and not stop:\n")
    source = replace_once(source, """                    debug('Auto-play: Triggering for series {} at S{}E{}'.format(item_id, last_ep[0], last_ep[1]))
                    try:
                        # Použijeme EpisodeCache namiesto API volania
                        from resources.lib.services.episode_cache import episode_cache

                        current_season = int(last_ep[0])
                        current_episode = int(last_ep[1])

                        # Získaj ďalšiu epizódu z cache
                        next_ep = episode_cache.get_next_episode(item_id, current_season, current_episode)
""", """                    try:
                        if unfinished:
                            next_ep = unfinished
                        else:
                            from resources.lib.services.episode_cache import episode_cache
                            current_season, current_episode = map(int, last_ep)
                            next_ep = episode_cache.get_next_episode(item_id, current_season, current_episode)
""")
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
