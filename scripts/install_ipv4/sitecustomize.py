"""Opt-in dependency download workaround for broken IPv6 routes; never used by kiosk runtime."""
import os
if os.environ.get('KIOSK_INSTALL_IPV4') == '1':
    import socket
    _getaddrinfo = socket.getaddrinfo
    def _ipv4(host, port, family=0, type=0, proto=0, flags=0):
        return _getaddrinfo(host, port, socket.AF_INET if family==socket.AF_UNSPEC else family, type, proto, flags)
    socket.getaddrinfo = _ipv4
