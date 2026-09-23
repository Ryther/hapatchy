"""Prepare isolated development environments before Supervisor starts."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROL = Path("/tmp/hapatchy-dev")
IMAGE = Path("/usr/local/share/hapatchy-image.json")


def ensure_private_dir(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError(f"Expected an owned non-symlink directory: {path}")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise RuntimeError(f"Expected mode 0700: {path}")


def directory(path: Path, *, mutate: bool) -> None:
    if not path.exists() and not path.is_symlink():
        if not mutate:
            raise RuntimeError(f"Missing state {path}; restart the container")
        path.mkdir(mode=0o700)
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError(f"Refusing non-directory or symlink: {path}")


def prepare_config(root: Path, *, mutate: bool) -> None:
    state = root / ".devcontainer/state"
    directory(state, mutate=mutate)
    config_dir = state / "ha"
    directory(config_dir, mutate=mutate)
    config = config_dir / "configuration.yaml"
    if config.is_symlink():
        raise RuntimeError("Configuration must not be a symlink")
    if not config.exists():
        if not mutate:
            raise RuntimeError("Missing HA configuration; restart the container")
        with config.open("x") as target:
            target.write((root / ".devcontainer/configuration.yaml").read_text())
        config.chmod(0o600)
    if not config.is_file():
        raise RuntimeError("Expected a regular configuration.yaml")
    source = root / "custom_components/hapatchy"
    if not source.exists():
        return
    custom = config_dir / "custom_components"
    directory(custom, mutate=mutate)
    link = custom / "hapatchy"
    if link.is_symlink() and link.resolve() == source.resolve():
        return
    if link.exists() or link.is_symlink():
        raise RuntimeError(f"Conflicting development source path, preserved: {link}")
    if not mutate:
        raise RuntimeError("Source link required; restart the container")
    link.symlink_to(source, target_is_directory=True)


def environment_marker(lock: Path, image: dict) -> dict:
    return {
        "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "implementation": sys.implementation.name,
        "python": platform.python_version(),
        "cache_tag": sys.implementation.cache_tag,
        "platform": sysconfig.get_platform(),
        "architecture": platform.machine(),
        "image": image,
    }


def process_start(pid: int) -> str:
    return (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[19]


def running(pid_file: Path) -> bool:
    try:
        record = json.loads(pid_file.read_text())
        if isinstance(record, dict):
            pid = int(record["pid"])
            return pid > 0 and process_start(pid) == record["start_time"]
        # Supervisor's own pidfile is numeric. Verify the command, not PID alone.
        pid = int(record)
        if pid == os.getpid():
            return False
        if pid <= 0:
            raise ValueError("nonpositive PID")
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        return b"/supervisord" in command or (
            b"environment.py" in command and b"--entrypoint" in command
        )
    except (FileNotFoundError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise RuntimeError(f"Invalid managed process marker: {pid_file}") from error


def run(*args: str) -> None:
    subprocess.run(args, check=True, timeout=900)


def check_pins(venv: Path, lock: Path) -> None:
    expected = {}
    for line in lock.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([\w.-]+)==([^\s;]+)", line)
        if not match:
            raise RuntimeError(f"Unpinned requirement in {lock.name}")
        expected[re.sub(r"[-_.]+", "-", match[1]).lower()] = match[2]
    python = str(venv / "bin/python")
    data = subprocess.check_output(
        [
            python,
            "-c",
            'import importlib.metadata as m,json; print(json.dumps({d.metadata["Name"]:d.version for d in m.distributions()}))',
        ],
        text=True,
        timeout=30,
    )
    actual = {re.sub(r"[-_.]+", "-", k).lower(): v for k, v in json.loads(data).items()}
    if actual != expected:
        raise RuntimeError(
            f"{venv.name} packages differ from its lock; restart after correcting pins"
        )
    run(python, "-m", "pip", "check")


def prepare_venv(root: Path, name: str, lock_name: str, image: dict, *, live: bool) -> None:
    venv = root / name
    lock = root / ".devcontainer" / lock_name
    marker = environment_marker(lock, image)
    receipt = venv / ".hapatchy-environment.json"
    if venv.is_symlink():
        raise RuntimeError(f"Refusing a symlink environment: {venv}")
    try:
        current = json.loads(receipt.read_text())
    except (FileNotFoundError, ValueError):
        current = None
    if current != marker:
        if live:
            raise RuntimeError(f"{name} inputs changed; restart the container (no live installs)")
        if venv.exists():
            if not venv.is_dir() or not (venv / "pyvenv.cfg").is_file():
                raise RuntimeError(f"Refusing to remove a non-venv path: {venv}")
            shutil.rmtree(venv)
        run(sys.executable, "-m", "venv", str(venv))
        run(
            str(venv / "bin/python"),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--timeout",
            "20",
            "--retries",
            "2",
            "-r",
            str(lock),
        )
        check_pins(venv, lock)
        receipt.write_text(json.dumps(marker, sort_keys=True) + "\n")
    else:
        check_pins(venv, lock)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entrypoint", action="store_true")
    parser.add_argument("--service-alive", action="store_true")
    args = parser.parse_args()
    if args.service_alive:
        if not running(CONTROL / "service.pid"):
            raise RuntimeError("Managed service exited; inspect container logs")
        return
    if sys.version_info < (3, 14, 2):
        raise RuntimeError("Development container requires Python >=3.14.2")
    image = json.loads(IMAGE.read_text())
    ensure_private_dir(CONTROL)
    with (CONTROL / "bootstrap.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        live = running(CONTROL / "service.pid") or running(CONTROL / "supervisord.pid")
        if args.entrypoint:
            if live:
                raise RuntimeError("A managed service is already running")
            # exec keeps this PID: no mutation gap between bootstrap and Supervisor.
            (CONTROL / "service.pid").write_text(
                json.dumps({"pid": os.getpid(), "start_time": process_start(os.getpid())})
            )
        for name, requirements in [
            (".venv", "requirements-tools.txt"),
            (".venv-ha", "requirements-ha.txt"),
        ]:
            prepare_venv(ROOT, name, requirements, image, live=live)
        prepare_config(ROOT, mutate=not live)
    if args.entrypoint:
        command = str(ROOT / ".venv/bin/supervisord")
        os.execv(command, [command, "-n", "-c", str(ROOT / ".devcontainer/supervisord.conf")])
    print("Bootstrap verified; managed services were not restarted.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"Bootstrap failed: {error}", file=sys.stderr)
        sys.exit(1)
