"""Install the Webshare proxy inside a compatible SC Helper service."""

def transform(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    source = source.replace('\r\n', '\n')
    anchor = '    install_cancel_reads(server, _log_head)\n    port = server.server_address[1]\n'
    if source.count(anchor) != 2:
        raise ValueError('Incompatible SC Helper service; no changes made')
    source = source.replace(anchor, '    install_cancel_reads(server, _log_head)\n    from webshare_proxy import install_webshare_proxy\n    install_webshare_proxy(server, _log_head)\n    port = server.server_address[1]\n')
    compile(source, 'service.py', 'exec')
    return source.replace('\n', newline)
