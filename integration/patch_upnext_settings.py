"""Add an Up Next settings shortcut to compatible Stream Cinema installations."""

import xml.etree.ElementTree as ET

LABEL_ID = '30998'
ACTION = 'Addon.OpenSettings(service.upnext)'
ANCHOR = '        <setting type="bool" visible="false" id="stream.adv.exclude.dolbyvision" default="true"/>'
ENTRY = ('        <setting type="action" label="30998" '
         'visible="System.HasAddon(service.upnext)" action="Addon.OpenSettings(service.upnext)"/>')
TEXT = {
    'en_gb': 'Up Next settings',
    'cs_cz': 'Nastavení Up Next',
    'sk_sk': 'Nastavenia Up Next',
}


def settings(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    root = ET.fromstring(source)
    actions = [element for element in root.iter('setting') if element.get('action') == ACTION]
    if actions:
        if len(actions) != 1 or actions[0].get('label') != LABEL_ID:
            raise ValueError('Existing Up Next settings shortcut is incompatible')
        return source.replace('\n', newline)
    if any(element.get('label') == LABEL_ID for element in root.iter('setting')):
        raise ValueError('The label ID is already in use')
    if source.count(ANCHOR) != 1:
        raise ValueError('Stream Cinema settings are incompatible')
    result = source.replace(ANCHOR, ANCHOR + '\n' + ENTRY, 1)
    ET.fromstring(result)
    return result.replace('\n', newline)


def language(source, locale):
    if locale not in TEXT:
        raise ValueError('Unsupported language')
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    context = 'msgctxt "#' + LABEL_ID + '"'
    block = context + '\nmsgid "Up Next settings"\nmsgstr "' + TEXT[locale] + '"\n'
    if context in source:
        if source.count(context) != 1 or block.strip() not in source:
            raise ValueError('The translation ID is already in use')
        return source.replace('\n', newline)
    return (source.rstrip('\n') + '\n\n' + block).replace('\n', newline)
