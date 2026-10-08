"""The candidate HA wheel, not stale repository pins, owns HA requirements."""

import hashlib
import io
import json
from zipfile import ZipFile

import pytest

from script.ha_distribution import load_ha_constraints


def _wheel(*, conflicting=False):
    buffer = io.BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("homeassistant/package_constraints.txt", "uv==0.12.23\n")
        archive.writestr(
            "homeassistant/components/conversation/manifest.json",
            json.dumps({"requirements": ["hassil==3.12.1"]}),
        )
        if conflicting:
            archive.writestr(
                "homeassistant/components/assist_satellite/manifest.json",
                json.dumps({"requirements": ["hassil==3.12.0"]}),
            )
    return buffer.getvalue()


def _metadata(payload, *, url="https://files.pythonhosted.org/packages/ha.whl", digest=None):
    return {
        "urls": [
            {
                "filename": "homeassistant-2026.10.0-py3-none-any.whl",
                "url": url,
                "size": len(payload),
                "yanked": False,
                "digests": {"sha256": digest or hashlib.sha256(payload).hexdigest()},
            }
        ]
    }


def test_verified_candidate_wheel_supplies_core_and_optional_exact_pins():
    payload = _wheel()
    result = load_ha_constraints(
        "2026.10.0",
        frozenset({"uv", "hassil"}),
        fetch_json=lambda url: _metadata(payload),
        download=lambda url, limit: payload,
    )
    assert b"uv==0.12.23\n" in result
    assert b"hassil==3.12.1\n" in result


@pytest.mark.parametrize(
    "metadata_change",
    [
        {"url": "https://example.invalid/ha.whl"},
        {"digest": "0" * 64},
    ],
)
def test_untrusted_wheel_location_or_digest_denies(metadata_change):
    payload = _wheel()
    with pytest.raises(ValueError):
        load_ha_constraints(
            "2026.10.0",
            frozenset({"uv", "hassil"}),
            fetch_json=lambda url: _metadata(payload, **metadata_change),
            download=lambda url, limit: payload,
        )


def test_missing_or_conflicting_optional_pin_denies():
    for payload, roots in [
        (_wheel(), frozenset({"uv", "infrared-protocols"})),
        (_wheel(conflicting=True), frozenset({"uv", "hassil"})),
    ]:
        with pytest.raises(ValueError):
            load_ha_constraints(
                "2026.10.0",
                roots,
                fetch_json=lambda url: _metadata(payload),
                download=lambda url, limit: payload,
            )
