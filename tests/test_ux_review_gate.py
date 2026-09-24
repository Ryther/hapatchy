"""The CI UX gate checks committed evidence, including renamed files."""

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "script" / "check_ux_review.py"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def setup_repo(root: Path) -> str:
    git(root, "init", "-q")
    git(root, "config", "user.name", "UX Gate Test")
    git(root, "config", "user.email", "ux-gate@example.invalid")
    product = root / "custom_components" / "hapatchy" / "feature.py"
    product.parent.mkdir(parents=True)
    product.write_text("old = True\n")
    docs = root / "docs" / "verification.md"
    docs.parent.mkdir()
    docs.write_text("Initial evidence\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "test: initial fixture")
    return git(root, "rev-parse", "HEAD")


def run_gate(root: Path, base: str | None = None) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(SCRIPT)]
    if base is not None:
        command += ["--base", base, "--head", "HEAD"]
    return subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)


@pytest.mark.parametrize("change", ["missing", "with_evidence", "deleted_evidence", "rename_out"])
def test_product_changes_require_current_verification(tmp_path, change):
    base = setup_repo(tmp_path)
    product = tmp_path / "custom_components" / "hapatchy" / "feature.py"
    docs = tmp_path / "docs" / "verification.md"
    if change == "rename_out":
        destination = tmp_path / "feature.py"
        product.rename(destination)
        git(tmp_path, "add", "-A")
    else:
        product.write_text("new = True\n")
        if change == "with_evidence":
            docs.write_text("Current observed evidence\n")
        elif change == "deleted_evidence":
            docs.unlink()
        git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "test: change fixture")
    result = run_gate(tmp_path, base)
    assert result.returncode == (0 if change == "with_evidence" else 1), result.stderr


def test_no_product_change_needs_no_verification_update(tmp_path):
    base = setup_repo(tmp_path)
    (tmp_path / "README.md").write_text("Documentation only\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "docs: fixture")
    assert run_gate(tmp_path, base).returncode == 0


def test_local_marker_blocks_completion_even_without_diff_base(tmp_path):
    setup_repo(tmp_path)
    (tmp_path / ".ux-review-required.md").write_text("unfinished\n")
    result = run_gate(tmp_path)
    assert result.returncode == 1


@pytest.mark.parametrize(
    "surface",
    ["hacs.json", "custom_components/hapatchy/manifest.json", "custom_components/hapatchy/brand/icon.png"],
)
def test_user_visible_metadata_and_brand_require_evidence(tmp_path, surface):
    base = setup_repo(tmp_path)
    changed = tmp_path / surface
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_bytes(b"changed")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "test: change product fixture")
    assert run_gate(tmp_path, base).returncode == 1
