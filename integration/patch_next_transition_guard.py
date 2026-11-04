"""Guard duplicate Up Next callbacks in the reviewed Stream Cinema build."""


def transform_monitor(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    marker = '# SC next transition guard v1'
    if marker in source:
        return source.replace('\n', newline)
    old = "            exec_build_in(continuous_resume.play_command(loads(b64decode(data)), create_plugin_url))\n"
    new = '''            # SC next transition guard v1
            _next_info = loads(b64decode(data))
            _next_token = continuous_resume.claim_transition(_next_info)
            if _next_token is None:
                debug('Monitor: Ignoring duplicate next-episode transition')
                return
            try:
                exec_build_in(continuous_resume.play_command(_next_info, create_plugin_url, _next_token))
            except BaseException:
                _next_args = dict(_next_info, sc_next_resume='1', sc_next_token=_next_token)
                continuous_resume.finish_transition(_next_args, False)
                raise
'''
    if source.count(old) != 1:
        raise ValueError('Incompatible Stream Cinema Up Next callback')
    source = source.replace(old, new, 1)
    compile(source, 'monitor.py', 'exec')
    return source.replace('\n', newline)


def transform_plugin(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    marker = '# SC next transition guard v1'
    if marker in source:
        return source.replace('\n', newline)
    old = '    def run(self):\n\n        if SC.ITEM_URL in self.args:\n'
    new = '''    def run(self):
        # SC next transition guard v1
        from resources.lib.common import continuous_resume
        self._next_transition_completed = False
        _next_heartbeat = continuous_resume.start_heartbeat(self.args)
        try:
            return self._run_next_transition()
        finally:
            continuous_resume.stop_heartbeat(_next_heartbeat)
            continuous_resume.finish_transition(self.args, getattr(self, '_next_transition_completed', False))

    def _run_next_transition(self):

        if SC.ITEM_URL in self.args:
'''
    if source.count(old) != 1:
        raise ValueError('Incompatible Stream Cinema request handler')
    source = source.replace(old, new, 1)
    playback_end = '''                xbmcplugin.setResolvedUrl(params.handle, True, li)
                self.end_of_directory()
        except UserCancelledException as e:
'''
    if source.count(playback_end) != 1:
        raise ValueError('Incompatible Stream Cinema playback completion')
    source = source.replace(playback_end, '''                xbmcplugin.setResolvedUrl(params.handle, True, li)
                self.end_of_directory()
            self._next_transition_completed = True
        except UserCancelledException as e:
''', 1)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
