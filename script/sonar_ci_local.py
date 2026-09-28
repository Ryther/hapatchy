"""Compare a fork PR to its base with a disposable Sonar Community server."""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

if __package__:
    from .sonar_ci_report import export_analysis, introduced_issues
else:
    from sonar_ci_report import export_analysis, introduced_issues

SERVER = os.environ.get("HAPATCHY_SONAR_URL", "http://127.0.0.1:9000")
SCANNER = "sonarsource/sonar-scanner-cli@sha256:a3f4215076706c95a17a68c19322ee916e40a3acd081a8c1a1e839e0194afa57"


def request(path: str, params: dict[str, Any] | None = None, *, post: bool = False, token: str = "") -> dict[str, Any]:
    data = urllib.parse.urlencode(params or {}).encode() if post else None
    query = "" if post or not params else "?" + urllib.parse.urlencode(params)
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        credentials = base64.b64encode(b"admin:admin").decode()
        headers["Authorization"] = f"Basic {credentials}"
    with urllib.request.urlopen(urllib.request.Request(SERVER + path + query, data=data, headers=headers), timeout=30) as response:
        if response.status == 204:
            return {}
        return json.load(response)


def ready() -> None:
    for _ in range(120):
        try:
            if request("/api/system/status")["status"] == "UP":
                return
        except (OSError, KeyError, ValueError):
            pass
        time.sleep(2)
    raise RuntimeError("Disposable Sonar did not become healthy")


def projects() -> None:
    ready()
    for name in ("hapatchy-baseline", "hapatchy-candidate"):
        request("/api/projects/create", {"project": name, "name": name}, post=True)


def scan(source: Path, project: str, output: Path, token: str) -> int:
    task = output / (project + "-task")
    task.mkdir(parents=True)
    task.chmod(0o777)  # Scanner container UID 1000 writes its task receipt here.
    receipt = task / "report-task.txt"
    receipt.unlink(missing_ok=True)
    command = [
        "docker", "run", "--rm", "--network", "host", "-e", "SONAR_TOKEN",
        "-e", f"SONAR_HOST_URL={SERVER}", "-v", f"{source}:/usr/src:ro",
        "-v", f"{task}:/sonar-task", SCANNER,
        f"-Dsonar.projectKey={project}", "-Dsonar.working.directory=/sonar-task",
        "-Dsonar.scm.disabled=false", "-Dsonar.qualitygate.wait=true",
    ]
    if project == "hapatchy-candidate":
        command.append("-Dsonar.python.coverage.reportPaths=coverage.xml")
    with (output / (project + "-scanner.log")).open("w") as log:
        result = subprocess.run(command, env={**os.environ, "SONAR_TOKEN": token}, stdout=log, stderr=subprocess.STDOUT, check=False)
    if not receipt.exists():
        raise RuntimeError(f"{project} did not submit an analysis (scanner exit {result.returncode})")
    fields = {}
    for line in receipt.read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value
    task_id = fields["ceTaskId"]
    for _ in range(60):
        state = request("/api/ce/task", {"id": task_id}, token=token)["task"]["status"]
        if state == "SUCCESS":
            return result.returncode
        if state in {"FAILED", "CANCELED"}:
            raise RuntimeError(f"{project} compute task {state}")
        time.sleep(2)
    raise RuntimeError(f"{project} compute task timed out")


def candidate_scan_ok(exit_code: int, gate_status: str) -> bool:
    return exit_code == 0 and gate_status == "OK"


def compare(base: Path, candidate: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    token_name = "ephemeral-ci-" + secrets.token_hex(4)
    token = request("/api/user_tokens/generate", {"name": token_name}, post=True)["token"]
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{token}", flush=True)
    try:
        scan_codes = {}
        for project, source in (("hapatchy-baseline", base), ("hapatchy-candidate", candidate)):
            scan_codes[project] = scan(source, project, output, token)
            export_analysis(lambda path, params: request(path, params, token=token), project, output / project)
        before = json.loads((output / "hapatchy-baseline/issues.json").read_text())
        after = json.loads((output / "hapatchy-candidate/issues.json").read_text())
        introduced = introduced_issues(before, after)
        gate = json.loads((output / "hapatchy-candidate/gate.json").read_text())["projectStatus"]["status"]
        candidate_code = scan_codes["hapatchy-candidate"]
        (output / "introduced.json").write_text(json.dumps(introduced, indent=2) + "\n")
        lines = ["# Sonar Community PR comparison", "", f"Baseline open issues: {len(before)}", f"Candidate open issues: {len(after)}", f"Introduced issues: **{len(introduced)}**", f"Candidate quality gate: **{gate}**", f"Candidate scanner exit: **{candidate_code}**", "", "Full baseline and candidate reports, API JSON and scanner logs are included.", ""]
        for issue in introduced:
            lines.append(f"- `{issue.get('rule', '')}` · `{issue.get('component', '').partition(':')[2]}` · {issue.get('message', '')}")
        (output / "report.md").write_text("\n".join(lines) + "\n")
        if introduced:
            raise RuntimeError(f"{len(introduced)} Sonar issues introduced by this PR")
        if not candidate_scan_ok(candidate_code, gate):
            raise RuntimeError(f"Candidate Sonar scan failed (exit {candidate_code}, gate {gate})")
    finally:
        request("/api/user_tokens/revoke", {"name": token_name}, post=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--wait-and-create-projects", action="store_true")
    group.add_argument("--scan", nargs=2, type=Path, metavar=("BASE", "CANDIDATE"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.wait_and_create_projects:
        projects()
    else:
        if args.output is None:
            parser.error("--output is required with --scan")
        compare(*args.scan, args.output)


if __name__ == "__main__":
    main()
