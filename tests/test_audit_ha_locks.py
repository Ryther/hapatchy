"""The advisory gate covers HAPatchY-owned dependencies, not HA's lock graph."""

import sys
from importlib.metadata import requires, version
from urllib.error import HTTPError

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from script import audit_ha_locks as audit


def _candidate(
    tmp_path,
    *,
    tools="homeassistant==2026.9.4\ncryptography==48.0.1\npatch-ng==1.19.1\nwatchdog==6.0.0\n",
    runtime="homeassistant==2026.9.4\npatch-ng==1.19.1\nwatchdog==6.0.0\n",
    requirements='["patch-ng==1.19.1", "watchdog==6.0.0"]',
):
    paths = (tmp_path / "requirements-tools.txt", tmp_path / "requirements-ha.txt")
    paths[0].write_text(tools)
    paths[1].write_text(runtime)
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"requirements": ' + requirements + "}")
    return paths, manifest


def _advisory(package="patch-ng", **changes):
    return {
        "ghsa_id": "GHSA-aaaa-bbbb-cccc",
        "severity": "high",
        "type": "reviewed",
        "withdrawn_at": None,
        "vulnerabilities": [{"package": {"ecosystem": "pip", "name": package}}],
        **changes,
    }


def test_ha_only_dependency_never_reaches_advisory_client(tmp_path):
    paths, manifest = _candidate(tmp_path)
    seen = []

    def client(pairs):
        seen.extend(pairs)
        return []

    result = audit.audit(paths, manifest, client)
    assert seen == [("patch-ng", "1.19.1"), ("watchdog", "6.0.0")]
    assert result.package_count == 2
    assert not result.blocked


def test_ha_only_advisory_cannot_block_even_if_api_returns_it(tmp_path):
    paths, manifest = _candidate(tmp_path)
    result = audit.audit(paths, manifest, lambda pairs: [_advisory("cryptography")])
    assert not result.blocked
    assert result.findings == ()


def test_hapatchy_dependency_advisory_blocks_even_when_pin_unchanged(tmp_path):
    paths, manifest = _candidate(tmp_path)
    result = audit.audit(paths, manifest, lambda pairs: [_advisory()])
    assert result.blocked
    assert result.findings == (audit.Finding("patch-ng", "1.19.1", "GHSA-aaaa-bbbb-cccc", "high"),)


def test_shared_dependency_is_still_hapatchy_owned(tmp_path):
    paths, manifest = _candidate(tmp_path, tools="homeassistant==2026.9.4\nwatchdog==6.0.0\npatch-ng==1.19.1\n")
    result = audit.audit(paths, manifest, lambda pairs: [_advisory("watchdog")])
    assert result.blocked
    assert result.findings[0].package == "watchdog"


def test_product_requirements_have_no_unscanned_mandatory_transitives():
    paths = audit.LOCK_PATHS
    owned = audit._owned_pins(paths, audit.MANIFEST_PATH)
    for name, pin in owned.items():
        assert version(name) == pin
        for dependency in requires(name) or []:
            requirement = Requirement(dependency)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                assert canonicalize_name(requirement.name) in owned, (
                    f"{name} gained mandatory dependency {requirement.name}; extend the advisory gate"
                )


def test_missing_or_mismatched_owned_lock_pin_fails_closed(tmp_path):
    paths, manifest = _candidate(tmp_path, runtime="homeassistant==2026.9.4\nwatchdog==6.0.0\n")
    with pytest.raises(ValueError, match="patch-ng"):
        audit.audit(paths, manifest, lambda pairs: [])
    paths, manifest = _candidate(tmp_path, runtime="homeassistant==2026.9.4\npatch-ng==1.18.0\nwatchdog==6.0.0\n")
    with pytest.raises(ValueError, match="patch-ng"):
        audit.audit(paths, manifest, lambda pairs: [])


@pytest.mark.parametrize("requirements", ['["patch-ng>=1.19.1"]', '["patch-ng[extra]==1.19.1"]', '"patch-ng==1.19.1"'])
def test_ambiguous_manifest_requirements_fail_closed(tmp_path, requirements):
    paths, manifest = _candidate(tmp_path, requirements=requirements)
    with pytest.raises(ValueError, match="requirements"):
        audit.audit(paths, manifest, lambda pairs: [])


def test_withdrawn_advisory_is_ignored(tmp_path):
    paths, manifest = _candidate(tmp_path)
    result = audit.audit(paths, manifest, lambda pairs: [_advisory(withdrawn_at="2026-09-01")])
    assert not result.blocked


def test_malformed_api_result_fails_closed(tmp_path):
    paths, manifest = _candidate(tmp_path)
    with pytest.raises(ValueError, match="Malformed"):
        audit.audit(paths, manifest, lambda pairs: [{"severity": "high"}])


def test_api_failure_cannot_be_treated_as_clean(tmp_path):
    paths, manifest = _candidate(tmp_path)

    def unavailable(pairs):
        raise ValueError("Advisory API network failure")

    with pytest.raises(ValueError, match="network failure"):
        audit.audit(paths, manifest, unavailable)


def test_client_paginates_and_deduplicates(monkeypatch):
    calls = []

    def page(url, token):
        calls.append(url)
        if "type=reviewed" in url and "after=cursor" not in url:
            return [_advisory()], "https://api.github.com/advisories?after=cursor"
        if "after=cursor" in url:
            return [_advisory()], None
        return [], None

    monkeypatch.setattr(audit, "_request_page", page)
    result = audit.github_advisories([("patch-ng", "1.19.1")], "token")
    assert len(result) == 1
    assert len(calls) == 3


def test_page_reader_retries_transient_http_error(monkeypatch):
    calls = 0

    class Response:
        status = 200
        headers = {"Link": ""}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size):
            return b"[]"

    def open_once(request, timeout):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise HTTPError(request.full_url, 503, "unavailable", {}, None)
        return Response()

    monkeypatch.setattr(audit, "urlopen", open_once)
    monkeypatch.setattr(audit.time, "sleep", lambda delay: None)
    assert audit._request_page("https://api.github.com/advisories", "token") == ([], None)
    assert calls == 2


def test_command_reports_owned_advisory(monkeypatch, capsys, tmp_path):
    paths, manifest = _candidate(tmp_path)
    monkeypatch.setattr(sys, "argv", ["audit_ha_locks.py", "--candidate-root", str(tmp_path)])
    monkeypatch.setattr(audit, "LOCK_PATHS", tuple(path.relative_to(tmp_path) for path in paths))
    monkeypatch.setattr(audit, "MANIFEST_PATH", manifest.relative_to(tmp_path))
    monkeypatch.setattr(audit, "github_advisories", lambda pairs, token: [_advisory()])
    assert audit.main() == 1
    assert "patch-ng==1.19.1" in capsys.readouterr().out
