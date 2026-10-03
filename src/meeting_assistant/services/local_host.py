"""Determine whether OBS shares this machine. Resolve DNS only in a worker."""

import ipaddress
import socket

import psutil


def normalized_address(value):
    try:
        address = ipaddress.ip_address(value.strip("[]").split("%", 1)[0])
        return (
            address.ipv4_mapped
            if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped
            else address
        )
    except ValueError:
        return None


def is_local_host(host, *, interfaces=None, resolver=None):
    host = host.strip().strip("[]").rstrip(".")
    if not host:
        return False
    direct = normalized_address(host)
    if direct is not None and direct.is_loopback:
        return True
    if host.casefold() == "localhost":
        return True
    local = set()
    try:
        networks = interfaces if interfaces is not None else psutil.net_if_addrs()
    except OSError:
        return False
    for addresses in networks.values():
        for item in addresses:
            address = normalized_address(item.address)
            if address is not None and not address.is_unspecified:
                local.add(address)
    if direct is not None:
        return direct in local
    try:
        resolved = (resolver or socket.getaddrinfo)(host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        addresses = {normalized_address(item[4][0]) for item in resolved}
        addresses.discard(None)
        return bool(addresses) and all(a.is_loopback or a in local for a in addresses)
    except (OSError, ValueError):
        return False
