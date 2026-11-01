import ast
from types import SimpleNamespace

import pytest

from integration.patch_history_titles import transform
from resources.lib.sc_browse import history_response


def test_history_hook_retains_a_cached_title_when_catalogue_fails():
    source = '''class Scinema:
    def action_last(self):
        st = List('lasts')
        lid = 'lasts'
        def load_history_detail(route):
            raise TimeoutError()
        if True:
            try:
                self.response = resume_browse.history_response(
                    st.get(), load_history_detail, lid, ADDON.getLocalizedString(30991),
                    ADDON.getLocalizedString(30312), page=int(self.args.get('page', '0')))
            except Exception:
                self.response = {}
'''
    tree = ast.parse(transform(source))
    item = next(n for n in tree.body[0].body if isinstance(n, ast.FunctionDef))
    saved = {'titles': {'42': 'Remembered show', '99': 'Removed show'}}
    scope = {'List': lambda _: SimpleNamespace(get=lambda: ['42']),
             'Storage': lambda _: saved, 'resume_browse': SimpleNamespace(history_response=history_response),
             'ADDON': SimpleNamespace(getLocalizedString=lambda _: 'History'), 'debug': lambda _: None}
    exec(compile(ast.Module(body=[item], type_ignores=[]), '<history>', 'exec'), scope)
    instance = SimpleNamespace(args={})
    scope['action_last'](instance)
    assert instance.response['menu'][0]['info']['title'] == 'Remembered show'
    assert saved['titles'] == {'42': 'Remembered show'}


def test_history_hook_rejects_unknown_source():
    with pytest.raises(ValueError):
        transform('incompatible')
