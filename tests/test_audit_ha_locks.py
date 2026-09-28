"""Full recent-lock advisory checks fail closed on unsafe candidates."""

import sys
from urllib.error import HTTPError

import pytest

from script import audit_ha_locks as audit


def _locks(tmp_path, *, tools="homeassistant==2026.9.4\ncryptography==48.0.1\n", runtime="homeassistant==2026.9.4\n"):
    paths = (tmp_path / "requirements-tools.txt", tmp_path / "requirements-ha.txt")
    paths[0].write_text(tools)
    paths[1].write_text(runtime)
    return paths


def _advisory(**changes):
    return {
        "ghsa_id": "GHSA-aaaa-bbbb-cccc",
        "severity": "high",
        "type": "reviewed",
        "withdrawn_at": None,
        "vulnerabilities": [
            {"package": {"ecosystem": "pip", "name": "cryptography"}}
        ],
        **changes,
    }


def test_unchanged_vulnerable_pin_blocks_candidate(tmp_path):
    locks = _locks(tmp_path)
    result = audit.audit(locks, lambda pairs: [_advisory()])
    assert result.blocked
    assert result.findings[0].package == "cryptography"
    assert result.findings[0].version == "48.0.1"


def test_clean_candidate_passes(tmp_path):
    result = audit.audit(_locks(tmp_path), lambda pairs: [])
    assert not result.blocked
    assert result.package_count == 2


def test_conflicting_pair_fails_closed(tmp_path):
    locks = _locks(tmp_path, runtime="homeassistant==2026.9.4\ncryptography==49.0.0\n")
    with pytest.raises(ValueError, match="Conflicting"):
        audit.audit(locks, lambda pairs: [])


def test_withdrawn_advisory_is_ignored(tmp_path):
    result = audit.audit(_locks(tmp_path), lambda pairs: [_advisory(withdrawn_at="2026-09-01")])
    assert not result.blocked


def test_malformed_api_result_fails_closed(tmp_path):
    with pytest.raises(ValueError, match="Malformed"):
        audit.audit(_locks(tmp_path), lambda pairs: [{"severity": "high"}])


def test_unchanged_lock_bytes_skip_existing_alerts(tmp_path):
    locks = _locks(tmp_path)
    base = tuple(path.read_bytes() for path in locks)
    called = False

    def client(pairs):
        nonlocal called
        called = True
        return [_advisory()]

    assert audit.audit_if_changed(locks, base, client) is None
    assert not called


def test_changed_ha_lock_reports_inherited_pin_without_blocking(tmp_path):
    locks = _locks(tmp_path)
    base = (b"homeassistant==2026.9.0\ncryptography==48.0.1\n", b"homeassistant==2026.9.0\n")
    result = audit.audit_if_changed(locks, base, lambda pairs: [_advisory()])
    assert result is not None
    assert not result.blocked
    assert result.inherited == (
        audit.Finding("cryptography", "48.0.1", "GHSA-aaaa-bbbb-cccc", "high"),
    )


def test_changed_pin_still_blocks_active_advisory(tmp_path):
    locks = _locks(tmp_path)
    base = (b"homeassistant==2026.9.0\ncryptography==47.0.0\n", b"homeassistant==2026.9.0\n")
    result = audit.audit_if_changed(locks, base, lambda pairs: [_advisory()])
    assert result is not None
    assert result.blocked


def test_api_failure_cannot_be_treated_as_clean(tmp_path):
    def unavailable(pairs):
        raise ValueError("Advisory API network failure")

    with pytest.raises(ValueError, match="network failure"):
        audit.audit(_locks(tmp_path), unavailable)


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
    result = audit.github_advisories([("cryptography", "48.0.1")], "token")
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


def test_command_fails_for_advisory_and_succeeds_for_unchanged_locks(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["audit_ha_locks.py", "--base-sha", "a" * 40])
    monkeypatch.setattr(audit, "_base_lock_bytes", lambda sha: (b"", b""))
    monkeypatch.setattr(
        audit,
        "audit_if_changed",
        lambda paths, baseline, client: audit.AuditResult(
            171, (audit.Finding("cryptography", "48.0.1", "GHSA-aaaa-bbbb-cccc", "high"),)
        ),
    )
    assert audit.main() == 1
    assert "cryptography==48.0.1" in capsys.readouterr().out
    monkeypatch.setattr(audit, "audit_if_changed", lambda paths, baseline, client: None)
    assert audit.main() == 0
    assert "unchanged" in capsys.readouterr().out
