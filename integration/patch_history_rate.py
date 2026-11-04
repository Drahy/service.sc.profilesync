"""Persist a local Last Seen cooldown after a catalogue rate-limit response."""

MARKER = '# SC history rate guard v1'


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    if MARKER in source:
        return source.replace('\n', newline)
    start = '    def action_last(self):\n'
    combined = "                    page=int(self.args.get('page', '0')), titles=_titles, details=_details)\n"
    single = "titles=titles, details=details)\n"
    if any(source.count(value) != 1 for value in (start, combined, single)):
        raise ValueError('Incompatible Stream Cinema history cache integration')
    source = source.replace(start, start + '''        # SC history rate guard v1
        try:
            _history_rate = Storage('sc_history_rate_guard')
        except Exception:
            _history_rate = None
''', 1)
    source = source.replace(combined, "                    page=int(self.args.get('page', '0')), titles=_titles, "
                            "details=_details, rate_state=_history_rate)\n", 1)
    source = source.replace(single, 'titles=titles, details=details, rate_state=_history_rate)\n', 1)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
