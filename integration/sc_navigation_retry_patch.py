"""Apply the bounded retry handshake to a compatible Stream Cinema client."""


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise ValueError('Incompatible Stream Cinema source; no changes made')
    return source.replace(old, new, 1)


def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    source = replace_once(source, 'from requests import HTTPError\n',
                          'from requests import HTTPError\nfrom requests.exceptions import ConnectionError as RequestConnectionError, Timeout as RequestTimeout\n')
    source = replace_once(source, "        if self.args.get('resume_episode') and not self.response.get(SC.ITEM_MENU):\n",
                          "        if self.args.get('resume_episode') and not self.response.get(SC.ITEM_MENU) and not getattr(self, '_restore_transient_failure', False):\n")
    old = '''        except:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}

    def parse_response(self):
'''
    new = '''        except Exception as error:
            debug('CALL URL ERR: {}'.format(traceback.format_exc()))
            self.response = {}
            status = getattr(getattr(error, 'response', None), 'status_code', None)
            transient = isinstance(error, (RequestConnectionError, RequestTimeout)) or (
                isinstance(error, HTTPError) and status in (429, 500, 502, 503, 504))
            if self.args.get('navigation_restore') == '1' and transient:
                self._restore_transient_failure = True
                home_win.setProperty('SC.navigation.restore.transient', self.url)

    def parse_response(self):
        if getattr(self, '_restore_transient_failure', False):
            self.succeeded = True
            return
'''
    source = replace_once(source, old, new)
    compile(source, 'streamcinema.py', 'exec')
    return source.replace('\n', newline)
