"""Integrate a unified, local Last Seen view into compatible Stream Cinema builds."""

MARKER = '# SC unified Last Seen integration v1'


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        return source.replace('\n', newline)
    action = '    def action_last(self):\n'
    browse = '    def call_url_and_response(self):\n'
    home = '            # Unified movie and series search; existing category histories remain untouched.\n'
    if any(source.count(anchor) != 1 for anchor in (action, browse, home)):
        raise ValueError('Incompatible Stream Cinema integration')
    source = source.replace(action, action + '''        # SC unified Last Seen integration v1
        if self.args.get(SC.ITEM_ID) == 'last-all':
            self.url = '/Last'
            try:
                _categories = [get_history_item_name(x) for x in ('lasts', 'lastf', 'lastd', 'lastk')]
                _lists = [(category, List(category).get()) for category in _categories]
                _titles = {}
                for category in _categories:
                    _cached = Storage('sc_history_titles_' + category).get('titles') or {}
                    _titles[category] = dict(_cached) if isinstance(_cached, dict) else {}
                self.response = resume_browse.combined_history_response(
                    _lists, Sc.get, lambda ident: Storage('SCKODIItem-' + ident).data,
                    'Last Seen', ADDON.getLocalizedString(30312),
                    page=int(self.args.get('page', '0')), titles=_titles)
                self.parse_response()
            except Exception:
                debug('Unified history unavailable: {}'.format(traceback.format_exc()))
                self.msg_error()
            return

''', 1)
    source = source.replace(browse, browse + '''        if self.url == '/FSeries/lastWatched':
            self.args[SC.ITEM_ID] = 'lasts'
            self.action_last()
            return

''', 1)
    source = source.replace(home, '''            _history = SCItem({SC.ITEM_TYPE:'action', SC.ITEM_TITLE:'[B]Last Seen[/B]',
                               SC.ITEM_ACTION:SC.ACTION_LAST, SC.ITEM_ID:'last-all'})
            if _history.visible:
                _history.li().setProperty('SpecialSort', GUI.TOP)
                self.items_pinned.insert(0, _history.get())

''' + home, 1)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
