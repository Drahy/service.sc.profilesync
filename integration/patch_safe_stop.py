"""Preserve matched Webshare return target before cancelling its stream."""


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    anchor = 'def main():\n    try:\n'
    replacement = '''def _request_webshare_return():
    try:
        import json
        import importlib.util
        import xbmcvfs
        window = xbmcgui.Window(10000)
        if not window.getProperty('sc.webshare.origin'):
            return
        data = json.loads(window.getProperty('SC.play_item'))
        item = data.get('info') or {}
        info = item.get('info') or {}
        show_id = item.get('id') or (info.get('unique_ids') or {}).get('sc')
        path = xbmcvfs.translatePath('special://home/addons/plugin.video.stream-cinema/resources/lib/common/episode_return.py')
        spec = importlib.util.spec_from_file_location('sc_webshare_stop_return', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.request_webshare_stop(window, item, show_id)
    except Exception:
        xbmc.log('[service.sc.helper] Webshare return target unavailable', xbmc.LOGWARNING)


def main():
    _request_webshare_return()
    try:
'''
    if source.count(anchor) != 1:
        raise ValueError('Incompatible safe Stop script; no changes made')
    source = source.replace(anchor, replacement, 1)
    compile(source, 'sc-safe-stop.py', 'exec')
    return source.replace('\n', newline)
