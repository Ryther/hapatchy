"""Configuration and bounded local/remote source safety."""

import asyncio
import hashlib
import importlib
import os
from pathlib import Path

import pytest


def api():
    assert Path("custom_components/hapatchy/patch_source.py").exists(), "Source adapter is missing"
    return (
        importlib.import_module("custom_components.hapatchy.models").PatchDefinition,
        importlib.import_module("custom_components.hapatchy.patch_source").PatchSourceClient,
    )


def definition(**changes):
    cls, _ = api()
    data = dict(
        name="Example",
        target_path="scripts/a.py",
        watch_root="scripts",
        source_type="local",
        source="patches/a.patch",
    )
    data.update(changes)
    return cls.from_mapping("patch1", data)


@pytest.mark.parametrize(
    "changes",
    [
        {"watch_root": "."},
        {"target_path": "other/a.py"},
        {"watch_pattern": "*.txt"},
        {"debounce_seconds": float("nan")},
        {"debounce_seconds": 0},
        {"debounce_seconds": 61},
        {"enabled": "false"},
        {"source_sha256": "bad"},
        {"source": "scripts/a.py"},
        {"source_type": "url", "source": "http://example.test/file"},
        {"source_type": "url", "source": "https://user:secret@example.test/file"},
        {"source_type": "url", "source": "https://example.test/file#fragment"},
    ],
)
def test_reject_unsafe_definition(changes):
    api()
    with pytest.raises(ValueError):
        definition(**changes)


def test_explicit_roots_and_default_pattern():
    item = definition(target_path="scripts/nested/a.py")
    assert item.watch_pattern == "nested/a.py"
    assert item.enabled and item.auto_apply and item.backup_before_apply
    assert item.debounce_seconds == 1.5


class Response:
    def __init__(self, chunks, status=200):
        self.chunks = chunks
        self.status = status
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class Session:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def get(self, url, **kwargs):
        # Disallow accidental redirect/auth behavior at the external boundary.
        assert kwargs["allow_redirects"] is False
        assert "auth" not in kwargs and "headers" not in kwargs
        return self.response


async def run(fn):
    return await asyncio.to_thread(fn)


def fake_session(monkeypatch, response):
    module = importlib.import_module("custom_components.hapatchy.patch_source")

    def create_session(**kwargs):
        assert kwargs["trust_env"] is False
        assert kwargs["connector"].use_dns_cache is False
        return Session(response)

    monkeypatch.setattr(module.aiohttp, "ClientSession", create_session)


@pytest.mark.parametrize(
    "host", ["raw.githubusercontent.com", "gist.githubusercontent.com", "example.test"]
)
async def test_https_exact_bytes_and_generic_hosts(tmp_path, host, monkeypatch):
    _, client = api()
    fake_session(monkeypatch, Response([b"body\r", b"\n"]))
    raw = b"body\r\n"
    item = definition(
        source_type="url",
        source=f"https://{host}/patch?token=private",
        source_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert await client(tmp_path, run).load(item) == raw


@pytest.mark.parametrize(
    ("chunks", "status", "reason"),
    [
        ([b"ok"], 302, "source_http_error"),
        ([b"a" * (2 * 1024 * 1024), b"b"], 200, "source_too_large"),
    ],
)
async def test_remote_failure_returns_controlled_error(tmp_path, chunks, status, reason, monkeypatch):
    _, client = api()
    fake_session(monkeypatch, Response(chunks, status))
    item = definition(source_type="url", source="https://example.test/private?secret=abc")
    with pytest.raises(ValueError, match=reason) as caught:
        await client(tmp_path, run).load(item)
    assert "secret" not in str(caught.value)


async def test_local_hash_is_exact(tmp_path):
    _, client = api()
    (tmp_path / "patches").mkdir()
    raw = b"body\r\n"
    (tmp_path / "patches/a.patch").write_bytes(raw)
    item = definition(source_sha256=hashlib.sha256(raw).hexdigest())
    assert await client(tmp_path, run).load(item) == raw
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        await client(tmp_path, run).load(definition(source_sha256="a" * 64))


@pytest.mark.parametrize("kind", ["fifo", "directory", "symlink", "hardlink"])
async def test_invalid_local_source_fails_without_blocking(tmp_path, kind):
    _, client = api()
    (tmp_path / "patches").mkdir()
    path = tmp_path / "patches/a.patch"
    if kind == "fifo":
        os.mkfifo(path)
    elif kind == "directory":
        path.mkdir()
    else:
        original = tmp_path / "original"
        original.write_bytes(b"x")
        if kind == "symlink":
            path.symlink_to(original)
        else:
            os.link(original, path)
    with pytest.raises(ValueError):
        await asyncio.wait_for(client(tmp_path, run).load(definition()), 1)


@pytest.mark.parametrize(
    "url", ["https://@example.test/patch", "https://:secret@example.test/patch"]
)
def test_empty_userinfo_is_still_forbidden(url):
    api()
    with pytest.raises(ValueError, match="invalid_source_url"):
        definition(source_type="url", source=url)


async def test_source_replacement_during_capture_is_rejected(tmp_path, monkeypatch):
    _, client = api()
    (tmp_path / "patches").mkdir()
    source = tmp_path / "patches/a.patch"
    source.write_bytes(b"old patch")
    real_read = os.read
    changed = False

    def replace_during_read(fd, count):
        nonlocal changed
        data = real_read(fd, count)
        if not changed:
            changed = True
            replacement = tmp_path / "patches/new"
            replacement.write_bytes(b"new patch")
            os.replace(replacement, source)
        return data

    monkeypatch.setattr(os, "read", replace_during_read)
    with pytest.raises(ValueError, match="invalid_local_source"):
        await client(tmp_path, run).load(definition())
    assert source.read_bytes() == b"new patch"


async def test_numeric_https_host_never_reaches_request_adapter(tmp_path):
    _, client = api()
    item = definition(source_type="url", source="https://127.0.0.1/patch")

    with pytest.raises(ValueError, match="source_network_denied"):
        await client(tmp_path, run).load(item)


async def test_private_dns_denial_never_changes_target(tmp_path, monkeypatch):
    from custom_components.hapatchy import patch_source
    from custom_components.hapatchy.network_policy import PublicDNSResolver
    from tests.test_network_policy import FakeResolver

    target = tmp_path / "scripts" / "a.py"
    target.parent.mkdir()
    target.write_bytes(b"original\n")
    monkeypatch.setattr(
        patch_source,
        "PublicDNSResolver",
        lambda: PublicDNSResolver(FakeResolver("169.254.169.254")),
    )
    item = definition(source_type="url", source="https://patch.example/private?secret=hidden")
    with pytest.raises(ValueError, match="source_network_denied") as caught:
        await patch_source.PatchSourceClient(tmp_path, run).load(item)
    assert caught.value.status.value == "security_error"
    assert "hidden" not in str(caught.value)
    assert target.read_bytes() == b"original\n"
