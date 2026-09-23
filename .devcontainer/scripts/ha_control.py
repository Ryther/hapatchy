"""Control only the development HA managed by our Unix-socket Supervisor."""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
import xmlrpc.client
from pathlib import Path

from supervisor.xmlrpc import SupervisorTransport

ROOT = Path(__file__).resolve().parents[2]


def client():
    return xmlrpc.client.ServerProxy(
        "http://localhost",
        transport=SupervisorTransport(None, None, "unix:///tmp/hapatchy-dev/supervisor.sock"),
    ).supervisor


def owns_port(pid: int) -> bool:
    """Do not accept an unrelated listener while HA is still starting."""
    sockets = set()
    try:
        for fd in (Path("/proc") / str(pid) / "fd").iterdir():
            try:
                target = fd.readlink().as_posix()
            except FileNotFoundError:
                continue
            if target.startswith("socket:["):
                sockets.add(target[8:-1])
        for table in [Path("/proc/net/tcp"), Path("/proc/net/tcp6")]:
            for line in table.read_text().splitlines()[1:]:
                fields = line.split()
                if (
                    fields[3] == "0A"
                    and int(fields[1].split(":")[1], 16) == 8123
                    and fields[9] in sockets
                ):
                    return True
    except (OSError, ValueError):
        return False
    return False


def ready(supervisor, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    last = "unknown"
    while True:
        info = supervisor.getProcessInfo("ha")
        last = info["statename"]
        if last in ("FATAL", "EXITED", "BACKOFF", "STOPPED"):
            raise RuntimeError(f"HA is {last}; inspect .devcontainer/state/ha/ha.log")
        if last == "RUNNING" and owns_port(info["pid"]):
            try:
                with urllib.request.urlopen("http://127.0.0.1:8123/", timeout=2) as response:
                    if (
                        response.status == 200
                        and supervisor.getProcessInfo("ha")["pid"] == info["pid"]
                    ):
                        print(f"HA RUNNING and HTTP-ready (PID {info['pid']})")
                        return
            except OSError:
                pass
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"HA readiness timed out ({last}); inspect .devcontainer/state/ha/ha.log"
            )
        time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "restart", "status", "wait"])
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args()
    supervisor = client()
    state = supervisor.getProcessInfo("ha")["statename"]
    if args.action in ("stop", "restart"):
        if state not in ("STOPPED", "EXITED", "FATAL"):
            try:
                supervisor.stopProcess("ha", True)
            except xmlrpc.client.Fault as error:
                if error.faultCode != 70:  # NOT_RUNNING after a simultaneous exit
                    raise
        print("HA stopped")
        if args.action == "stop":
            return
        state = supervisor.getProcessInfo("ha")["statename"]
    if args.action in ("start", "restart"):
        deadline = time.monotonic() + 40
        while state == "STOPPING":
            if time.monotonic() >= deadline:
                raise RuntimeError("HA is still STOPPING")
            time.sleep(0.2)
            state = supervisor.getProcessInfo("ha")["statename"]
        if state not in ("RUNNING", "STARTING"):
            try:
                supervisor.startProcess("ha", False)
            except xmlrpc.client.Fault as error:
                if error.faultCode != 60:  # ALREADY_STARTED by another caller
                    raise
    ready(supervisor, timeout=0 if args.action == "status" else args.timeout)


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, xmlrpc.client.Error) as error:
        print(f"HA control failed: {error}", file=sys.stderr)
        sys.exit(1)
