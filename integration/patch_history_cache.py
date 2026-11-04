"""Cache resolved Last Seen details locally and suppress repeated outage requests."""

MARKER = '# SC history detail cache v1'


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        return source.replace('\n', newline)
    combined = "                _title_stores = {}\n                for category in _categories:\n"
    loaded = "                    _titles[category] = dict(_cached) if isinstance(_cached, dict) else {}\n"
    use = "                    page=int(self.args.get('page', '0')), titles=_titles)\n"
    persist = "                        _title_stores[category]['titles'] = _titles[category]\n"
    single = "                titles = dict(saved_titles) if isinstance(saved_titles, dict) else {}\n"
    single_use = "                    ADDON.getLocalizedString(30312), page=int(self.args.get('page', '0')), titles=titles)\n"
    single_persist = "                if titles_store is not None and titles != saved_titles:\n"
    anchors = (combined, loaded, use, persist, single, single_use, single_persist)
    if any(source.count(anchor) != 1 for anchor in anchors):
        raise ValueError('Incompatible Stream Cinema history integration')
    source = source.replace(combined, '''                # SC history detail cache v1
                import copy as _history_copy
                _title_stores = {}
                _details = {}
                for category in _categories:
''', 1)
    source = source.replace(loaded, loaded + '''                    _saved_details = _title_stores[category].get('details') or {}
                    _allowed = set(map(str, dict(_lists).get(category, [])))
                    _details[category] = ({k: _history_copy.deepcopy(v) for k, v in _saved_details.items() if k in _allowed}
                                          if isinstance(_saved_details, dict) else {})
''', 1)
    source = source.replace(use, "                    page=int(self.args.get('page', '0')), titles=_titles, details=_details)\n", 1)
    source = source.replace(persist, persist + '''                    if _details[category] != (_title_stores[category].get('details') or {}):
                        _title_stores[category]['details'] = _details[category]
''', 1)
    source = source.replace(single, '''                import copy as _history_copy
                try:
                    saved_details = (titles_store.get('details') or {}) if titles_store is not None else {}
                except Exception:
                    saved_details = {}
                allowed = set(map(str, history_ids))
                details = {k: _history_copy.deepcopy(v) for k, v in saved_details.items() if k in allowed} if isinstance(saved_details, dict) else {}
''' + single, 1)
    source = source.replace(single_use, "                    ADDON.getLocalizedString(30312), page=int(self.args.get('page', '0')), "
                            "titles=titles, details=details)\n", 1)
    source = source.replace(single_persist, '''                if titles_store is not None and details != saved_details:
                    try:
                        titles_store['details'] = details
                    except Exception:
                        debug('Could not cache Last Seen details')
''' + single_persist, 1)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
