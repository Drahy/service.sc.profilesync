"""Add an Up Next settings shortcut to compatible Stream Cinema installations."""

import xml.etree.ElementTree as ET

LABEL = 'Up Next'
ACTION = 'Addon.OpenSettings(service.upnext)'
ANCHOR = '        <setting type="bool" visible="false" id="stream.adv.exclude.dolbyvision" default="true"/>'
ENTRY = ('        <setting type="action" label="Up Next" '
         'visible="System.HasAddon(service.upnext)" action="Addon.OpenSettings(service.upnext)"/>')


def settings(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    root = ET.fromstring(source)
    actions = [element for element in root.iter('setting') if element.get('action') == ACTION]
    if actions:
        if len(actions) == 1 and actions[0].get('label') == '30998':
            old = ENTRY.replace('label="Up Next"', 'label="30998"')
            if source.count(old) != 1:
                raise ValueError('Existing Up Next settings shortcut is incompatible')
            return source.replace(old, ENTRY, 1).replace('\n', newline)
        if len(actions) != 1 or actions[0].get('label') != LABEL:
            raise ValueError('Existing Up Next settings shortcut is incompatible')
        return source.replace('\n', newline)
    if source.count(ANCHOR) != 1:
        raise ValueError('Stream Cinema settings are incompatible')
    result = source.replace(ANCHOR, ANCHOR + '\n' + ENTRY, 1)
    ET.fromstring(result)
    return result.replace('\n', newline)
