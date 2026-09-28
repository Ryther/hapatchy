"""The disposable HA smoke client never sends its token outside local API paths."""

import pytest

from script import smoke_ha


@pytest.mark.parametrize(
    ("base", "path"),
    [
        ("https://example.com", "/api/states"),
        ("http://127.0.0.1:8123", "/api/../auth/token"),
        ("http://127.0.0.1:8123", "/api/flow/%2e%2e/auth"),
        ("http://127.0.0.1:8123", "/api/flow/abc?redirect=https://example.com"),
        ("http://127.0.0.1:8123", "//example.com/api/states"),
    ],
)
def test_smoke_client_rejects_nonlocal_or_ambiguous_url(base, path, monkeypatch):
    def unexpected_request(*args, **kwargs):
        raise AssertionError("Network request was attempted")

    monkeypatch.setattr(smoke_ha.urllib.request, "urlopen", unexpected_request)
    with pytest.raises(ValueError, match="local Home Assistant API"):
        smoke_ha.api_request(base, path, token="smoke-token")
