"""Outbound HTTPS destination policy, independent of real network services."""

import asyncio
import socket

import aiohttp
import pytest

from custom_components.hapatchy.models import PatchError, Status
from custom_components.hapatchy.network_policy import PublicDNSResolver, checked_url


class FakeResolver:
    def __init__(self, *addresses):
        self.addresses = addresses
        self.calls = 0

    async def resolve(self, host, port=0, family=socket.AF_INET):
        self.calls += 1
        return [
            {
                "hostname": host,
                "host": address,
                "port": port,
                "family": socket.AF_INET6 if ":" in address else socket.AF_INET,
                "proto": 0,
                "flags": 0,
            }
            for address in self.addresses
        ]

    async def close(self):
        return None


@pytest.mark.parametrize(
    "host",
    [
        "127.0.0.1",
        "127.1",
        "2130706433",
        "0x7f.0.0.1",
        "[::1]",
        "[::ffff:127.0.0.1]",
        "%31%32%37.0.0.1",
        "bad\\host.test",
    ],
)
def test_numeric_and_malformed_authorities_are_denied_before_connector(host):
    with pytest.raises(PatchError, match="source_network_denied") as caught:
        checked_url(f"https://{host}/patch?secret=hidden")
    assert caught.value.status == Status.SECURITY_ERROR
    assert "hidden" not in str(caught.value)


@pytest.mark.parametrize(
    "addresses",
    [
        ("127.0.0.1",),
        ("10.0.0.1",),
        ("169.254.169.254",),
        ("100.64.0.1",),
        ("224.0.0.1",),
        ("ff02::1",),
        ("::1",),
        ("::ffff:127.0.0.1",),
        ("2001:4860:4860::8888%eth0",),
        ("1.1.1.1", "127.0.0.1"),
        (),
    ],
)
async def test_resolver_denies_every_non_global_or_mixed_answer(addresses):
    delegate = FakeResolver(*addresses)
    resolver = PublicDNSResolver(delegate)
    with pytest.raises(PatchError, match="source_network_denied"):
        await resolver.resolve("patch.example", 443)
    assert delegate.calls == 1


async def test_connector_uses_only_guarded_dns_answer():
    delegate = FakeResolver("1.1.1.1", "2606:4700:4700::1111")
    connector = aiohttp.TCPConnector(resolver=PublicDNSResolver(delegate), use_dns_cache=False)
    try:
        resolved = await connector._resolve_host("patch.example", 443)
        assert {record["host"] for record in resolved} == set(delegate.addresses)
        assert delegate.calls == 1
    finally:
        await connector.close()


async def test_connector_refuses_private_answer_before_socket_attempt(monkeypatch):
    delegate = FakeResolver("169.254.169.254")
    connector = aiohttp.TCPConnector(resolver=PublicDNSResolver(delegate), use_dns_cache=False)
    attempts = []

    async def forbidden_dial(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("socket dial must not occur")

    monkeypatch.setattr(connector, "_wrap_create_connection", forbidden_dial)
    try:
        async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
            with pytest.raises(PatchError, match="source_network_denied"):
                async with session.get(
                    checked_url("https://patch.example/file"),
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=2),
                ):
                    pass
        assert delegate.calls == 1
        assert attempts == []
    finally:
        await connector.close()


async def test_connector_dials_only_vetted_public_answer(monkeypatch):
    delegate = FakeResolver("1.1.1.1")
    connector = aiohttp.TCPConnector(resolver=PublicDNSResolver(delegate), use_dns_cache=False)
    attempts = []

    async def observe_dial(*args, **kwargs):
        attempts.append((args, kwargs))
        raise OSError("synthetic dial stop")

    monkeypatch.setattr(connector, "_wrap_create_connection", observe_dial)
    try:
        async with aiohttp.ClientSession(connector=connector, trust_env=False) as session:
            # Older aiohttp releases propagate the synthetic dial exception directly.
            with pytest.raises((aiohttp.ClientError, OSError)):
                async with session.get(
                    checked_url("https://patch.example/file"),
                    allow_redirects=False,
                    timeout=aiohttp.ClientTimeout(total=2),
                ):
                    pass
        assert delegate.calls == 1
        assert attempts
        assert "1.1.1.1" in str(attempts)
        assert "127.0.0.1" not in str(attempts)
    finally:
        await connector.close()


async def test_policy_failure_leaves_synthetic_target_unchanged(tmp_path):
    target = tmp_path / "target.txt"
    target.write_bytes(b"original\n")
    resolver = PublicDNSResolver(FakeResolver("127.0.0.1"))
    with pytest.raises(PatchError, match="source_network_denied"):
        await asyncio.wait_for(resolver.resolve("patch.example", 443), 1)
    assert target.read_bytes() == b"original\n"
