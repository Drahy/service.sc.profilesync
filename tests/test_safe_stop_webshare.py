import ast
import json
from pathlib import Path
import sys
from types import SimpleNamespace

from integration.patch_safe_stop import transform


def test_target_is_prepared_before_playback_is_cancelled(monkeypatch):
    source = 'def main():\n    try:\n        pass\n    finally:\n        pass\n'
    tree=ast.parse(transform(source))
    fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='_request_webshare_return')
    values={'sc.webshare.origin':'plugin://plugin.video.sc.websharebridge/?action=episode',
            'SC:selected':json.dumps({'provider':'webshare'}),
            'SC.play_item':json.dumps({'info':{'id':'123','info':{'season':4,'episode':7}}})}
    window=SimpleNamespace(getProperty=lambda k:values.get(k,''),setProperty=lambda k,v:values.__setitem__(k,v),clearProperty=lambda k:values.pop(k,None))
    helper=Path(__file__).parents[1]/'integration/sc_episode_return.py'
    monkeypatch.setitem(sys.modules,'xbmcvfs',SimpleNamespace(translatePath=lambda path:str(helper)))
    scope={'xbmcgui':SimpleNamespace(Window=lambda i:window),'xbmc':SimpleNamespace(log=lambda *a:None,LOGWARNING=1)}
    exec(compile(ast.Module(body=[fn],type_ignores=[]),'<stop>','exec'),scope)
    scope['_request_webshare_return']()
    request=json.loads(values['sc.profile.browse.open'])
    assert request['target']=={'id':'123','url':'/FGet/123/4','resume_episode':'7'}
    main=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='main')
    assert ast.unparse(main.body[0])=='_request_webshare_return()'
