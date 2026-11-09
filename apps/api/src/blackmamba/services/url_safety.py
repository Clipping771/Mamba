"""SSRF protection for the archiver (FR-4).

Only http(s) URLs whose host resolves exclusively to public (globally routable) addresses are
allowed. The check runs when a job is requested AND for every request the browser makes, so
redirects or sub-resources cannot reach internal services (metadata endpoints, Redis, DB...).
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})
BLOCKED_HOSTNAMES = frozenset({"localhost", "metadata.google.internal", "metadata"})


class UnsafeUrlError(ValueError):
    pass


def _ip_is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def parse_http_url(url: str) -> tuple[str, str, int]:
    """Return (scheme, host, port) or raise UnsafeUrlError."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeUrlError("malformed URL") from exc
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError("only http and https URLs can be archived")
    if parts.username or parts.password:
        raise UnsafeUrlError("URLs with credentials are not allowed")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("URL has no host")
    if host in BLOCKED_HOSTNAMES or host.endswith((".localhost", ".internal", ".local")):
        raise UnsafeUrlError("internal host names are not allowed")
    return scheme, host, port or (443 if scheme == "https" else 80)


async def resolve_host(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("host name does not resolve") from exc
    return sorted({str(info[4][0]) for info in infos})


async def ensure_public_url(url: str, *, allow_private: bool = False) -> str:
    """Validate a URL for archiving. Returns the normalised URL."""
    _, host, port = parse_http_url(url)
    if allow_private:
        return url.strip()
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    addresses = [str(literal)] if literal is not None else await resolve_host(host, port)
    for address in addresses:
        if not _ip_is_public(ipaddress.ip_address(address.split("%")[0])):
            raise UnsafeUrlError("URL points to a private, loopback or reserved address")
    return url.strip()
