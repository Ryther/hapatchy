"""Boot disposable Home Assistant with HAPatchY's real YAML schema."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
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
    (root / "scripts" / "editor.txt").write_text("before\n")
    (root / "scripts" / "failure.txt").write_text("safe\n")
    (root / "scripts" / "ambiguous.txt").write_text("before\n")
    (root / "www").mkdir()
    (root / "www" / "denied.txt").write_text("untouched\n")
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


def api_request(
    base: str, path: str, data: dict | None = None, *, token: str = "", form: bool = False
) -> dict | list:
    body = None
    headers = {}
    if data is not None:
        body = (
            urllib.parse.urlencode(data).encode()
            if form
            else json.dumps(data).encode()
        )
        headers["Content-Type"] = "application/x-www-form-urlencoded" if form else "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base + path, body, headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        try:
            message = json.load(error).get("message", "")
        except (ValueError, AttributeError):
            message = ""
        raise RuntimeError(f"HA API {path} returned HTTP {error.code}: {message}") from None


def onboard(base: str) -> str:
    client_id = base + "/"
    result = api_request(
        base,
        "/api/onboarding/users",
        {
            "name": "HAPatchY CI",
            "username": "hapatchy_ci",
            "password": secrets.token_urlsafe(32),
            "client_id": client_id,
            "language": "en",
        },
    )
    token = api_request(
        base,
        "/auth/token",
        {
            "grant_type": "authorization_code",
            "code": result["auth_code"],
            "client_id": client_id,
        },
        form=True,
    )["access_token"]
    for path, data in (
        ("core_config", {}),
        ("analytics", {}),
    ):
        api_request(base, "/api/onboarding/" + path, data, token=token)
    return token


def verify_patch_flow(base: str, root: Path) -> None:
    token = onboard(base)
    result = api_request(base, "/api/config/config_entries/flow", {"handler": "hapatchy"}, token=token)
    if result["type"] == "form":
        result = api_request(
            base, "/api/config/config_entries/flow/" + result["flow_id"], {}, token=token
        )
    if result["type"] != "create_entry":
        raise RuntimeError("HAPatchY integration flow did not create an entry")
    entries = api_request(base, "/api/config/config_entries/entry", token=token)
    entry = next(item["entry_id"] for item in entries if item["domain"] == "hapatchy")
    flow = api_request(
        base, "/api/config/config_entries/subentries/flow", {"handler": [entry, "patch"]}, token=token
    )["flow_id"]
    path = "/api/config/config_entries/subentries/flow/" + flow
    result = api_request(
        base,
        path,
        {
            "name": "CI smoke",
            "target_path": "scripts/smoke.txt",
            "source_type": "managed",
            "watch_root": "scripts",
            "watch_pattern": "",
        },
        token=token,
    )
    if result.get("step_id") != "editor":
        raise RuntimeError("Managed patch flow did not open the editor")
    result = api_request(
        base,
        path,
        {
            "patch_text": "--- a/scripts/smoke.txt\n+++ b/scripts/smoke.txt\n"
            "@@ -1 +1 @@\n-original\n+patched\n"
        },
        token=token,
    )
    if result.get("step_id") != "options":
        raise RuntimeError("Managed patch flow did not open options")
    result = api_request(
        base,
        path,
        {
            "enabled": True,
            "auto_apply": False,
            "reconcile_on_startup": True,
            "backup_before_apply": True,
            "source_sha256": "",
            "debounce_seconds": 1.5,
        },
        token=token,
    )
    if result.get("type") != "create_entry":
        raise RuntimeError("Managed patch flow did not save the patch")
    target = root / "scripts" / "smoke.txt"
    if target.read_bytes() != b"original\n":
        raise RuntimeError("Target changed before explicit Apply")
    deadline = time.monotonic() + 30
    state = None
    while time.monotonic() < deadline:
        states = api_request(base, "/api/states", token=token)
        state = next(
            (item for item in states if item["entity_id"].startswith("sensor.ci_smoke")), None
        )
        if state is not None and state["state"] == "applicable":
            break
        time.sleep(0.25)
    if state is None or state["state"] != "applicable":
        observed = state["state"] if state else "missing"
        raise RuntimeError(f"Managed patch did not become applicable: {observed}")
    patch_id = state["attributes"]["patch_id"]
    api_request(base, "/api/services/hapatchy/apply", {"patch_id": patch_id}, token=token)
    if target.read_bytes() != b"patched\n":
        raise RuntimeError("Apply did not change target bytes")
    api_request(base, "/api/services/hapatchy/revert", {"patch_id": patch_id}, token=token)
    if target.read_bytes() != b"original\n":
        raise RuntimeError("Revert did not restore target bytes")
    denied_flow = api_request(
        base, "/api/config/config_entries/subentries/flow", {"handler": [entry, "patch"]}, token=token
    )["flow_id"]
    denied = api_request(
        base,
        "/api/config/config_entries/subentries/flow/" + denied_flow,
        {
            "name": "Denied CI smoke",
            "target_path": "www/denied.txt",
            "source_type": "managed",
            "watch_root": "www",
            "watch_pattern": "",
        },
        token=token,
    )
    if denied.get("type") != "form" or not denied.get("errors"):
        raise RuntimeError("Unlisted target was not rejected by the native flow")
    if (root / "www" / "denied.txt").read_bytes() != b"untouched\n":
        raise RuntimeError("Unlisted target changed")

    editor_flow = api_request(
        base, "/api/config/config_entries/subentries/flow", {"handler": [entry, "patch"]}, token=token
    )["flow_id"]
    editor_path = "/api/config/config_entries/subentries/flow/" + editor_flow
    editor = api_request(
        base,
        editor_path,
        {
            "name": "CI editor",
            "target_path": "scripts/editor.txt",
            "source_type": "edit_file",
            "watch_root": "scripts",
            "watch_pattern": "",
        },
        token=token,
    )
    if editor.get("step_id") != "edit_file":
        raise RuntimeError("File editor did not open")
    fields = editor.get("data_schema", [])
    if not any(field.get("name") == "edited_text" and field.get("default") == "before\n" for field in fields):
        raise RuntimeError("File editor did not show the authorized original bytes")
    result = api_request(base, editor_path, {"edited_text": "after\n"}, token=token)
    if result.get("type") != "create_entry":
        raise RuntimeError("File editor did not save the generated patch")
    target = root / "scripts" / "editor.txt"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and target.read_bytes() != b"after\n":
        time.sleep(0.25)
    if target.read_bytes() != b"after\n":
        raise RuntimeError("Editor patch was not applied automatically")
    states = api_request(base, "/api/states", token=token)
    editor_state = next(
        (item for item in states if item["entity_id"].startswith("sensor.ci_editor")), None
    )
    if editor_state is None or editor_state["state"] != "applied":
        raise RuntimeError("Editor patch did not report applied status")
    backup_root = root / ".hapatchy" / "backups"
    if not any(
        path.read_bytes() == b"before\n"
        and json.loads(path.with_name("metadata.json").read_text()).get("target_path")
        == "scripts/editor.txt"
        for path in backup_root.glob("*/*/target")
    ):
        raise RuntimeError("Editor Apply did not retain the original target bytes")
    api_request(
        base,
        "/api/services/hapatchy/revert",
        {"patch_id": editor_state["attributes"]["patch_id"]},
        token=token,
    )
    if target.read_bytes() != b"before\n":
        raise RuntimeError("Editor-generated patch did not revert to original bytes")

    retry_flow = api_request(
        base, "/api/config/config_entries/subentries/flow", {"handler": [entry, "patch"]}, token=token
    )["flow_id"]
    retry_path = "/api/config/config_entries/subentries/flow/" + retry_flow
    retry = api_request(
        base,
        retry_path,
        {
            "name": "CI retry",
            "target_path": "scripts/ambiguous.txt",
            "source_type": "edit_file",
            "watch_root": "scripts",
            "watch_pattern": "",
        },
        token=token,
    )
    if retry.get("step_id") != "edit_file":
        raise RuntimeError("Retry-case editor did not open")
    retry = api_request(base, retry_path, {"edited_text": "before\nafter\n"}, token=token)
    if retry.get("step_id") != "edit_file" or retry.get("errors", {}).get("base") != "editor_context_not_unique":
        raise RuntimeError("Ambiguous edit was not refused")
    if not any(
        field.get("name") == "edited_text" and field.get("default") == "before\nafter\n"
        for field in retry.get("data_schema", [])
    ):
        raise RuntimeError("Recoverable editor error discarded the user's edit")
    if (root / "scripts" / "ambiguous.txt").read_bytes() != b"before\n":
        raise RuntimeError("Rejected ambiguous edit changed target bytes")

    failure_flow = api_request(
        base, "/api/config/config_entries/subentries/flow", {"handler": [entry, "patch"]}, token=token
    )["flow_id"]
    failure_path = "/api/config/config_entries/subentries/flow/" + failure_flow
    failure = api_request(
        base,
        failure_path,
        {
            "name": "CI failure",
            "target_path": "scripts/failure.txt",
            "source_type": "edit_file",
            "watch_root": "scripts",
            "watch_pattern": "",
        },
        token=token,
    )
    if failure.get("step_id") != "edit_file":
        raise RuntimeError("Failure-case editor did not open")
    scripts = root / "scripts"
    scripts.chmod(0o500)
    try:
        failure = api_request(base, failure_path, {"edited_text": "unsafe\n"}, token=token)
        if failure.get("type") != "create_entry":
            raise RuntimeError("Failure-case patch was not configured")
        deadline = time.monotonic() + 30
        failure_state = None
        while time.monotonic() < deadline:
            states = api_request(base, "/api/states", token=token)
            failure_state = next(
                (item for item in states if item["entity_id"].startswith("sensor.ci_failure")),
                None,
            )
            if failure_state and failure_state["state"] == "apply_error":
                break
            time.sleep(0.25)
        if failure_state is None or failure_state["state"] != "apply_error":
            raise RuntimeError("Failed Apply was not reported by the sensor")
        if (scripts / "failure.txt").read_bytes() != b"safe\n":
            raise RuntimeError("Failed Apply changed target bytes")
    finally:
        scripts.chmod(0o700)


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
                verify_patch_flow(f"http://127.0.0.1:{port}", root)
                print(
                    "Disposable HA native editor, backed-up Apply, failed Apply status, "
                    "Revert, retry text retention, denied target and byte checks: PASS"
                )
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
