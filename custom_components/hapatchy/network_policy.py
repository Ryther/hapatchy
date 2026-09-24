"""Constrain HTTPS patch downloads to globally reachable socket peers."""

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

from .models import PatchError, Status

_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\Z")


def _denied() -> PatchError:
    return PatchError("source_network_denied", Status.SECURITY_ERROR)


def checked_url(source: str) -> URL:
    """Return the exact URL to request after rejecting connector bypass hosts."""
    try:
        authority = urlsplit(source).netloc
        if "%" in authority or "\\" in authority or "@" in authority:
            raise _denied()
        url = URL(source)
        host = url.raw_host
        if url.scheme != "https" or not host or ":" in host:
            raise _denied()
        if not host.isascii() or len(host) > 253:
            raise _denied()
        labels = host.rstrip(".").split(".")
        if len(labels) < 2 or any(not _LABEL.fullmatch(label) for label in labels):
            raise _denied()
        try:
            socket.inet_aton(host.rstrip("."))
        except OSError:
            pass
        else:
            raise _denied()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise _denied()
        return url
    except PatchError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise _denied() from None


def _globally_routable(address: str) -> bool:
    if not isinstance(address, str) or "%" in address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not (
        ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


class PublicDNSResolver(AbstractResolver):
    """Validate the records used by aiohttp's connector, without preflight DNS."""

    def __init__(self, delegate: AbstractResolver | None = None) -> None:
        self._delegate = delegate or aiohttp.ThreadedResolver()

    async def resolve(
        self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET
    ) -> list[Any]:
        records = await self._delegate.resolve(host, port, family)
        if not records or any(
            not _globally_routable(record["host"]) for record in records
        ):
            raise _denied()
        return records

    async def close(self) -> None:
        await self._delegate.close()
