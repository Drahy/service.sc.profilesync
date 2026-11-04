import ast

from integration.patch_next_transition_guard import transform_monitor, transform_plugin


def test_monitor_guard_claims_before_playing_and_releases_failed_launch():
    source = '''def on_notification(data):
            exec_build_in(continuous_resume.play_command(loads(b64decode(data)), create_plugin_url))
'''
    result = transform_monitor(source)
    assert transform_monitor(result) == result
    tree = ast.parse(result)
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert 'claim_transition' in calls and 'finish_transition' in calls


def test_plugin_request_releases_guard_even_when_resolving_fails():
    source = '''class Scinema:
    def run(self):

        if SC.ITEM_URL in self.args:
            pass
    def play(self):
        try:
            if params.handle == -1:
                xbmc.Player().play(url, li)
            else:
                xbmcplugin.setResolvedUrl(params.handle, True, li)
                self.end_of_directory()
        except UserCancelledException as e:
            pass
'''
    result = transform_plugin(source)
    assert transform_plugin(result) == result
    tree = ast.parse(result)
    run = next(n for n in tree.body[0].body if isinstance(n, ast.FunctionDef) and n.name == 'run')
    guarded = next(node for node in run.body if isinstance(node, ast.Try))
    assert guarded.finalbody


def test_duplicate_real_monitor_callbacks_start_only_one_transition(tmp_path, monkeypatch):
    import base64
    import json
    import os
    from pathlib import Path
    from types import SimpleNamespace

    import pytest
    from integration import sc_continuous_resume as resume

    monitor_file = Path(os.environ['APPDATA']) / 'Kodi/addons/plugin.video.stream-cinema/resources/lib/services/monitor.py'
    if not monitor_file.exists():
        pytest.skip('Reviewed Stream Cinema monitor is not installed')
    module = ast.parse(transform_monitor(monitor_file.read_text(encoding='utf-8')))
    cls = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'Monitor')
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == 'onNotification')
    commands = []
    path = str(tmp_path / 'guard.db')
    clock = [100]
    real_claim, real_finish = resume.claim_transition, resume.finish_transition
    bridge = SimpleNamespace(
        claim_transition=lambda info: real_claim(info, path=path, now=clock[0]),
        play_command=resume.play_command,
        finish_transition=lambda args, success: real_finish(args, success, path=path, now=clock[0]),
    )
    scope = {'debug': lambda *args: None, 'decode': lambda value: value, 'ADDON_ID': 'plugin.video.stream-cinema',
             'loads': json.loads, 'continuous_resume': bridge, 'create_plugin_url': lambda _: 'plugin://sc/?url=encoded',
             'exec_build_in': commands.append}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), '<monitor>', 'exec'), scope)
    instance = SimpleNamespace(callback={}, win=SimpleNamespace(clearProperty=lambda key: None))
    payload = base64.b64encode(json.dumps({'url': '/Play/42/3/2'}).encode()).decode()
    scope['onNotification'](instance, 'upnextprovider.SIGNAL', 'Other.plugin.video.stream-cinema_play_action', payload)
    clock[0] += 9
    scope['onNotification'](instance, 'upnextprovider.SIGNAL', 'Other.plugin.video.stream-cinema_play_action', payload)
    assert len(commands) == 1
    assert 'sc_next_resume=31' in commands[0] and 'sc_next_token=' in commands[0]
