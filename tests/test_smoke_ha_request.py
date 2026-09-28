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


def test_editor_smoke_waits_for_eventual_sensor_state(monkeypatch):
    responses = [[], [{"entity_id": "sensor.ci_editor", "state": "applied", "attributes": {"patch_id": "one"}}]]
    monkeypatch.setattr(smoke_ha, "api_request", lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(smoke_ha.time, "sleep", lambda seconds: None)
    state = smoke_ha.wait_for_editor_applied("http://127.0.0.1:8123", "token")
    assert state["attributes"]["patch_id"] == "one"
