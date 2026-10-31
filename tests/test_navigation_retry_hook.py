import ast
from types import SimpleNamespace

import pytest
import requests

from integration.sc_navigation_retry_patch import transform


SOURCE = '''from requests import HTTPError
class Scinema:
    def call_url_and_response(self):
        if self.args.get('resume_episode') and not self.response.get(SC.ITEM_MENU):
            pass
    def call_url(self):
        try:
            if self.payload is None:
                self.response = Sc.get(self.url)
            else:
                self.response = Sc.post(self.url, data=self.payload)
        except:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}

    def parse_response(self):
        pass
'''


def methods():
    tree = ast.parse(transform(SOURCE))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Scinema')
    names = {'call_url', 'parse_response', 'call_url_and_response'}
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in names}


@pytest.mark.parametrize('error,expected', [
    (requests.exceptions.Timeout(), True),
    (requests.exceptions.ConnectionError(), True),
    (requests.exceptions.HTTPError(response=SimpleNamespace(status_code=503)), True),
    (requests.exceptions.HTTPError(response=SimpleNamespace(status_code=404)), False),
    (ValueError('bad metadata'), False),
])
def test_only_automatic_transient_failures_are_signalled(error, expected):
    props = {}
    def get(_):
        raise error
    scope = dict(Sc=SimpleNamespace(get=get), HTTPError=requests.HTTPError,
                 RequestConnectionError=requests.exceptions.ConnectionError,
                 RequestTimeout=requests.exceptions.Timeout,
                 home_win=SimpleNamespace(setProperty=props.__setitem__),
                 debug=lambda *args: None, traceback=SimpleNamespace(format_exc=lambda: 'error'))
    exec(compile(ast.Module(body=[methods()['call_url']], type_ignores=[]), '<hook>', 'exec'), scope)
    item = SimpleNamespace(args={'navigation_restore': '1'}, payload=None, url='/FGet/123/5')
    scope['call_url'](item)
    assert bool(props) is expected
    assert item.response == {}
    assert bool(getattr(item, '_restore_transient_failure', False)) is expected
    props.clear()
    item = SimpleNamespace(args={}, payload=None, url='/FGet/123/5')
    scope['call_url'](item)
    assert not props


def test_invalid_source_is_rejected():
    with pytest.raises(ValueError):
        transform('not the expected addon')


def test_failed_automatic_return_keeps_directory_open_without_dialog():
    scope = {}
    exec(compile(ast.Module(body=[methods()['parse_response']], type_ignores=[]), '<hook>', 'exec'), scope)
    item = SimpleNamespace(_restore_transient_failure=True, succeeded=False)
    scope['parse_response'](item)
    assert item.succeeded is True
