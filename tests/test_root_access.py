from types import SimpleNamespace

import pytest

from integration.patch_root_access import transform


SOURCE = '''class Cinema:
    def pinned_custom(self):
        if self.url == '/':
            # Unified movie and series search; existing category histories remain untouched.
            pass
    def call_url_and_response(self):
        self.call_url()
        if self.args.get('resume_episode'):
            pass
        self.parse_response()
    def call_url(self):
        try:
            self.response = self.load()
        except Exception as error:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}
'''


class Item:
    def __init__(self, data):
        self.data = data
        self.visible = True
        self.properties = {}

    def setProperty(self, key, value):
        self.properties[key] = value

    def li(self):
        return self

    def get(self):
        return (self.data['url'], self, False)


@pytest.mark.parametrize('failure', [True, False])
def test_root_keeps_local_actions_when_catalogue_is_unavailable(failure):
    import traceback
    notifications = []
    sc = SimpleNamespace(ITEM_TYPE='type', ITEM_TITLE='title', ITEM_ACTION='action', ITEM_URL='url',
                         ACTION_CMD='cmd', ITEM_WIDGET='widget')
    scope = {'SC': sc, 'GUI': SimpleNamespace(TOP='top'), 'SCItem': Item,
             'xbmc': SimpleNamespace(getCondVisibility=lambda _: True),
             'xbmcgui': SimpleNamespace(ListItem=lambda label: Item({'label': label}),
                                        Dialog=lambda: SimpleNamespace(notification=lambda *x: notifications.append(x))),
             'traceback': traceback, 'debug': lambda _: None}
    patched = transform(SOURCE)
    assert transform(patched) == patched
    exec(patched, scope)
    cinema = scope['Cinema']()
    cinema.url, cinema.args, cinema.items_pinned = '/', {}, []
    cinema.parse_response = lambda: cinema.pinned_custom()
    cinema.load = lambda: (_ for _ in ()).throw(ConnectionError()) if failure else {'menu': []}
    cinema.call_url_and_response()
    assert cinema.response['menu'] == []
    assert cinema.items_pinned[0][0] == 'plugin://plugin.video.sc.websharebridge/'
    assert cinema.items_pinned[1][0] == 'cmd://Addon.OpenSettings(service.upnext)'
    assert bool(notifications) is failure


def test_unknown_root_source_is_rejected():
    with pytest.raises(ValueError):
        transform('unsupported source')
