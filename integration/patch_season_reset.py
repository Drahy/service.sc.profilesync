"""Apply the season reset context item and action to a compatible Stream Cinema build."""


def _insert(source, anchor, addition):
    if addition in source:
        return source
    if source.count(anchor) != 1:
        raise ValueError('Incompatible Stream Cinema season reset integration')
    return source.replace(anchor, addition + anchor)


def item(source):
    anchor = "        if self.data.get('resume_seasons'):\n"
    if anchor not in source:
        anchor = "        if 'listType' in params.args:\n"
        start, end = source.index('class SCDir(SCBaseItem):'), source.index('class SCHPDir(')
        return source[:start] + _insert(source[start:end], anchor, ITEM) + source[end:]
    return _insert(source, anchor, ITEM)


ITEM = """        from resources.lib.common import season_reset
        start_season = season_reset.context(self.data.get(SC.ITEM_URL), params.args.get('url'))
        if start_season:
            context_menu.append((season_reset.label(), 'RunPlugin({})'.format(create_plugin_url({
                SC.ITEM_ACTION: season_reset.ACTION,
                SC.ITEM_URL: start_season,
            }))))

"""


def streamcinema(source):
    anchor = '        if action == SC.ACTION_PLAY_URL:\n'
    addition = """        if action == 'reset_season_history':
            from resources.lib.common import season_reset
            season_reset.confirm(self.args.get(SC.ITEM_URL))
            return
"""
    return _insert(source, anchor, addition)
