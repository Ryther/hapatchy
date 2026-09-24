"""Boot disposable Home Assistant with HAPatchY's real YAML schema."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 120


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def prepare_config(root: Path, port: int) -> None:
    """Use only synthetic, isolated configuration and authored integration files."""
    (root / "scripts").mkdir()
    (root / "scripts" / "smoke.txt").write_text("original\n")
    shutil.copytree(
        ROOT / "custom_components" / "hapatchy",
        root / "custom_components" / "hapatchy",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (root / "configuration.yaml").write_text(
        "homeassistant:\n"
        "  name: HAPatchY CI smoke\n"
        "  allowlist_external_dirs:\n"
        f"    - {root / 'scripts'}\n"
        "hapatchy:\n"
        "  allowed_directories:\n"
        "    - scripts\n"
        "http:\n"
        "  server_host: 127.0.0.1\n"
        f"  server_port: {port}\n"
        "api:\n"
        "logger:\n"
        "  default: warning\n"
        "  logs:\n"
        "    homeassistant.setup: debug\n",
        encoding="utf-8",
    )


def wait_for_api(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    url = f"http://127.0.0.1:{port}/api/"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Home Assistant exited before HTTP readiness ({process.returncode})")
        try:
            urllib.request.urlopen(url, timeout=2)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return
        except (OSError, TimeoutError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Home Assistant HTTP readiness timed out")


def wait_for_hapatchy(process: subprocess.Popen[bytes], log_path: Path) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        output = log_path.read_text(errors="replace")
        if "Setup of domain hapatchy took" in output:
            return
        if process.poll() is not None:
            raise RuntimeError(f"Home Assistant exited before HAPatchY setup ({process.returncode})")
        time.sleep(0.5)
    raise RuntimeError("HAPatchY setup timed out")


def run_smoke() -> None:
    hass = Path(sys.executable).with_name("hass")
    with tempfile.TemporaryDirectory(prefix="hapatchy-ha-smoke-") as temporary:
        root = Path(temporary)
        port = unused_port()
        prepare_config(root, port)
        log_path = root / "ha.log"
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                [str(hass), "--skip-pip", "-c", str(root)],
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
            try:
                wait_for_api(process, port)
                wait_for_hapatchy(process, log_path)
                log.flush()
                if (root / "scripts" / "smoke.txt").read_text() != "original\n":
                    raise RuntimeError("Smoke target changed unexpectedly")
                print("Disposable HA booted with HAPatchY YAML; API ready; target unchanged")
            except Exception:
                log.flush()
                print(log_path.read_text(errors="replace")[-5000:], file=sys.stderr)
                raise
            finally:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    run_smoke()
