"""Keep useful local Stream Cinema root actions available during catalogue failures."""

MARKER = '# SC independent root actions v1'


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        return source.replace('\n', newline)
    anchor = "            # Unified movie and series search; existing category histories remain untouched.\n"
    failure = "        except Exception as error:\n            debug('CALL URL ERR: {}'.format(traceback.format_exc()))\n"
    request = '        self.call_url()\n        if self.args.get(\'resume_episode\')'
    if any(source.count(value) != 1 for value in (anchor, failure, request)):
        raise ValueError('Incompatible Stream Cinema root integration')
    source = source.replace(anchor, '''            # SC independent root actions v1
            if xbmc.getCondVisibility('System.HasAddon(plugin.video.sc.websharebridge)'):
                _webshare = xbmcgui.ListItem(label='[B]Search Webshare[/B]')
                _webshare.setProperty('SpecialSort', GUI.TOP)
                self.items_pinned.append(('plugin://plugin.video.sc.websharebridge/', _webshare, True))
            if xbmc.getCondVisibility('System.HasAddon(service.upnext)'):
                _next = SCItem({SC.ITEM_TYPE:'action', SC.ITEM_TITLE:'[B]Up Next settings[/B]',
                                SC.ITEM_ACTION:SC.ACTION_CMD, SC.ITEM_URL:'cmd://Addon.OpenSettings(service.upnext)'})
                if _next.visible:
                    _next.li().setProperty('SpecialSort', GUI.TOP)
                    self.items_pinned.append(_next.get())

''' + anchor, 1)
    source = source.replace(failure, failure + '            self._catalog_connection_failed = True\n', 1)
    source = source.replace(request, '''        self.call_url()
        if (self.url == '/' and (getattr(self, '_catalog_connection_failed', False)
                or (not self.response.get('menu') and (self.response.get('system') or {}).get('msgERROR')))):
            self.response = {'menu': [], 'system': {}}
            if SC.ITEM_WIDGET not in self.args:
                xbmcgui.Dialog().notification('Stream Cinema', 'Catalogue unavailable; Webshare remains available')
        if self.args.get('resume_episode')''', 1)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
