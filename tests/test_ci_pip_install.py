"""CI dependency installation retries transient package-index failures."""

import subprocess

import pytest

from script import install_ci_requirements


def test_retry_reuses_exact_lock_and_succeeds(monkeypatch):
    calls = []
    delays = []
    outcomes = iter((1, 0))

    def run(command, *, check):
        calls.append((command, check))
        return subprocess.CompletedProcess(command, next(outcomes))

    monkeypatch.setattr(install_ci_requirements.subprocess, "run", run)
    monkeypatch.setattr(install_ci_requirements.time, "sleep", delays.append)

    install_ci_requirements.install("tests/requirements-ha-min.txt")

    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert calls[0][0][-2:] == ["-r", "tests/requirements-ha-min.txt"]
    assert delays == [10]


def test_exhausted_retries_preserve_pip_failure(monkeypatch):
    calls = []
    delays = []

    def run(command, *, check):
        calls.append(command)
        return subprocess.CompletedProcess(command, 42)

    monkeypatch.setattr(install_ci_requirements.subprocess, "run", run)
    monkeypatch.setattr(install_ci_requirements.time, "sleep", delays.append)

    with pytest.raises(SystemExit) as failure:
        install_ci_requirements.install(".devcontainer/requirements-ha.txt")

    assert failure.value.code == 42
    assert len(calls) == 3
    assert delays == [10, 20]


def test_unknown_lock_is_rejected_without_running_pip(monkeypatch):
    calls = []
    monkeypatch.setattr(install_ci_requirements.subprocess, "run", calls.append)

    with pytest.raises(ValueError, match="Unsupported CI lock"):
        install_ci_requirements.install("../../requirements.txt")

    assert calls == []
