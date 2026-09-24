"""The UX gate rejects unfinished review markers in a checkout or commit."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "script" / "check_ux_review.py"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def setup_repo(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "UX Gate Test")
    git(root, "config", "user.email", "ux-gate@example.invalid")
    (root / "README.md").write_text("Initial content\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "test: initial fixture")


def run_gate(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--head", git(root, "rev-parse", "HEAD")],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_checkout_passes(tmp_path):
    setup_repo(tmp_path)
    assert run_gate(tmp_path).returncode == 0


def test_untracked_marker_blocks_completion(tmp_path):
    setup_repo(tmp_path)
    (tmp_path / ".ux-review-required.md").write_text("unfinished\n")
    assert run_gate(tmp_path).returncode == 1


def test_committed_marker_blocks_completion(tmp_path):
    setup_repo(tmp_path)
    marker = tmp_path / ".ux-review-required.md"
    marker.write_text("unfinished\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: incomplete fixture")
    marker.unlink()
    assert run_gate(tmp_path).returncode == 1
