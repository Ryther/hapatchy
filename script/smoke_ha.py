"""Boot disposable Home Assistant with HAPatchY's real YAML schema."""

from __future__ import annotations

import json
import os
import re
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
PATCH_FLOW_PATH = "/api/config/config_entries/subentries/flow"
PATCH_FLOW_PREFIX = PATCH_FLOW_PATH + "/"
STATES_PATH = "/api/states"
BEFORE_TEXT = "before\n"
BEFORE_BYTES = BEFORE_TEXT.encode("utf-8")
API_PATH = re.compile(r"/api(?:/[A-Za-z0-9_-]+)+\Z")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, url):
        return None


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def prepare_config(root: Path, port: int) -> None:
    """Use only synthetic, isolated configuration and authored integration files."""
    (root / "scripts").mkdir()
    (root / "scripts" / "smoke.txt").write_text("original\n")
    (root / "scripts" / "editor.txt").write_text(BEFORE_TEXT)
    (root / "scripts" / "failure.txt").write_text("safe\n")
    (root / "scripts" / "ambiguous.txt").write_text(BEFORE_TEXT)
    (root / "www").mkdir()
    (root / "www" / "denied.txt").write_text("untouched\n")
    (root / "automations.yaml").write_text("[]\n")
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
        "automation: !include automations.yaml\n"
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
            raise RuntimeError(
                f"Home Assistant exited before HTTP readiness ({process.returncode})"
            )
        try:
            urllib.request.urlopen(url, timeout=2)
        except urllib.error.HTTPError as error:
            if error.code == 401:
                return
        except OSError:
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
            raise RuntimeError(
                f"Home Assistant exited before HAPatchY setup ({process.returncode})"
            )
        time.sleep(0.5)
    raise RuntimeError("HAPatchY setup timed out")


def api_request(
    base: str, path: str, data: dict | None = None, *, token: str = "", form: bool = False
) -> dict | list:
    parsed = urllib.parse.urlsplit(base)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or base != f"http://127.0.0.1:{parsed.port}"
        or (path != "/auth/token" and not API_PATH.fullmatch(path))
    ):
        raise ValueError("Expected a local Home Assistant API path")
    body = None
    headers = {}
    if data is not None:
        body = urllib.parse.urlencode(data).encode() if form else json.dumps(data).encode()
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded" if form else "application/json"
        )
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(base + path, body, headers)
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=30) as response:
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


def _setup_entry(base: str, token: str) -> str:
    result = api_request(
        base, "/api/config/config_entries/flow", {"handler": "hapatchy"}, token=token
    )
    if result["type"] == "form":
        result = api_request(
            base, "/api/config/config_entries/flow/" + result["flow_id"], {}, token=token
        )
    if result["type"] != "create_entry":
        raise RuntimeError("HAPatchY integration flow did not create an entry")
    entries = api_request(base, "/api/config/config_entries/entry", token=token)
    entry = next(item["entry_id"] for item in entries if item["domain"] == "hapatchy")
    return entry


def _verify_manual_patch(base: str, root: Path, token: str, entry: str) -> None:
    flow = api_request(base, PATCH_FLOW_PATH, {"handler": [entry, "patch"]}, token=token)["flow_id"]
    path = PATCH_FLOW_PREFIX + flow
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
        states = api_request(base, STATES_PATH, token=token)
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
    (root / "automations.yaml").write_text(
        "- alias: CI changed automation\n  triggers: []\n  actions: []\n"
    )
    api_request(base, "/api/services/hapatchy/reconcile", {"patch_id": patch_id}, token=token)
    states = api_request(base, STATES_PATH, token=token)
    status = next(item for item in states if item["entity_id"].startswith("sensor.ci_smoke"))
    health = next(
        item for item in states if item["entity_id"].startswith("binary_sensor.ci_smoke")
    )
    if status["state"] != "applied" or health["state"] != "off":
        raise RuntimeError("Unrelated automation edit made the applied patch unhealthy")
    if target.read_bytes() != b"patched\n":
        raise RuntimeError("Automation edit changed the patched target")
    api_request(base, "/api/services/hapatchy/revert", {"patch_id": patch_id}, token=token)
    if target.read_bytes() != b"original\n":
        raise RuntimeError("Revert did not restore target bytes")


def _verify_denied_target(base: str, root: Path, token: str, entry: str) -> None:
    denied_flow = api_request(base, PATCH_FLOW_PATH, {"handler": [entry, "patch"]}, token=token)[
        "flow_id"
    ]
    denied = api_request(
        base,
        PATCH_FLOW_PREFIX + denied_flow,
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


def wait_for_editor_applied(base: str, token: str) -> dict:
    deadline = time.monotonic() + 30
    editor_state = None
    while time.monotonic() < deadline:
        states = api_request(base, STATES_PATH, token=token)
        editor_state = next(
            (item for item in states if item["entity_id"].startswith("sensor.ci_editor")), None
        )
        if editor_state is not None and editor_state["state"] == "applied":
            return editor_state
        time.sleep(0.25)
    observed = editor_state["state"] if editor_state else "missing"
    raise RuntimeError(f"Editor patch did not report applied status: {observed}")


def _verify_file_editor(base: str, root: Path, token: str, entry: str) -> None:
    editor_flow = api_request(base, PATCH_FLOW_PATH, {"handler": [entry, "patch"]}, token=token)[
        "flow_id"
    ]
    editor_path = PATCH_FLOW_PREFIX + editor_flow
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
    if not any(
        field.get("name") == "edited_text" and field.get("default") == BEFORE_TEXT
        for field in fields
    ):
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
    editor_state = wait_for_editor_applied(base, token)
    backup_root = root / ".hapatchy" / "backups"
    if not any(
        path.read_bytes() == BEFORE_BYTES
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
    if target.read_bytes() != BEFORE_BYTES:
        raise RuntimeError("Editor-generated patch did not revert to original bytes")


def _verify_editor_retry(base: str, root: Path, token: str, entry: str) -> None:
    retry_flow = api_request(base, PATCH_FLOW_PATH, {"handler": [entry, "patch"]}, token=token)[
        "flow_id"
    ]
    retry_path = PATCH_FLOW_PREFIX + retry_flow
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
    if (
        retry.get("step_id") != "edit_file"
        or retry.get("errors", {}).get("base") != "editor_context_not_unique"
    ):
        raise RuntimeError("Ambiguous edit was not refused")
    if not any(
        field.get("name") == "edited_text" and field.get("default") == "before\nafter\n"
        for field in retry.get("data_schema", [])
    ):
        raise RuntimeError("Recoverable editor error discarded the user's edit")
    if (root / "scripts" / "ambiguous.txt").read_bytes() != BEFORE_BYTES:
        raise RuntimeError("Rejected ambiguous edit changed target bytes")


def _verify_failed_apply(base: str, root: Path, token: str, entry: str) -> None:
    failure_flow = api_request(base, PATCH_FLOW_PATH, {"handler": [entry, "patch"]}, token=token)[
        "flow_id"
    ]
    failure_path = PATCH_FLOW_PREFIX + failure_flow
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
            states = api_request(base, STATES_PATH, token=token)
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


def verify_patch_flow(base: str, root: Path) -> None:
    token = onboard(base)
    entry = _setup_entry(base, token)
    _verify_manual_patch(base, root, token, entry)
    _verify_denied_target(base, root, token, entry)
    _verify_file_editor(base, root, token, entry)
    _verify_editor_retry(base, root, token, entry)
    _verify_failed_apply(base, root, token, entry)
    target = root / "scripts" / "smoke.txt"
    original = target.read_bytes()
    config = root / "configuration.yaml"
    config.write_text(config.read_text() + "\n# grant source changed after boot\n")
    states = api_request(base, STATES_PATH, token=token)
    patch_id = next(
        item["attributes"]["patch_id"]
        for item in states
        if item["entity_id"].startswith("sensor.ci_smoke")
    )
    # HA reports the refused administrator action as a service error. Its HTTP
    # response may fail; the sensor and unchanged bytes are the stable contract.
    try:
        api_request(base, "/api/services/hapatchy/reconcile", {"patch_id": patch_id}, token=token)
    except RuntimeError as error:
        if not str(error).startswith(
            "HA API /api/services/hapatchy/reconcile returned HTTP "
        ):
            raise
    states = api_request(base, STATES_PATH, token=token)
    status = next(item for item in states if item["entity_id"].startswith("sensor.ci_smoke"))
    if status["state"] != "security_error" or target.read_bytes() != original:
        raise RuntimeError("Changed grant source was not denied with unchanged target")


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
                    "Revert, automation/grant source checks, retry text retention, "
                    "denied target and byte checks: PASS"
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
