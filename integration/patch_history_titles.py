"""Keep local Last Seen titles visible when catalogue details are unavailable."""


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    old = '''            try:
                self.response = resume_browse.history_response(
                    st.get(), load_history_detail, lid, ADDON.getLocalizedString(30991),
                    ADDON.getLocalizedString(30312), page=int(self.args.get('page', '0')))
            except Exception:
'''
    new = '''            try:
                history_ids = st.get()
                titles_store = None
                try:
                    titles_store = Storage('sc_history_titles_' + lid)
                    saved_titles = titles_store.get('titles') or {}
                except Exception:
                    saved_titles = {}
                titles = dict(saved_titles) if isinstance(saved_titles, dict) else {}
                titles = {key: value for key, value in titles.items() if key in set(map(str, history_ids))}
                self.response = resume_browse.history_response(
                    history_ids, load_history_detail, lid, ADDON.getLocalizedString(30991),
                    ADDON.getLocalizedString(30312), page=int(self.args.get('page', '0')), titles=titles)
                if titles_store is not None and titles != saved_titles:
                    try:
                        titles_store['titles'] = titles
                    except Exception:
                        debug('Could not cache Last Seen titles')
            except Exception:
'''
    if source.count(old) != 1:
        raise ValueError('Incompatible Stream Cinema history; no changes made')
    result = source.replace(old, new, 1)
    compile(result, 'streamcinema.py', 'exec')
    return result.replace('\n', newline)
