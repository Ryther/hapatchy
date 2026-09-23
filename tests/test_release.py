"""Release artifact identity and refusal paths, using disposable Git repositories."""

import hashlib
import importlib.util
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pytest


def module(name):
    path = Path("script") / f"{name}.py"
    assert path.exists(), f"{name} is not implemented"
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@pytest.fixture
def release_repo(tmp_path):
    def write(name, text):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("custom_components/hapatchy/manifest.json", '{"version":"0.2.0"}')
    write("custom_components/hapatchy/__init__.py", '"""Example."""\n')
    write("pyproject.toml", '[project]\nversion = "0.2.0"\n')
    write(".release-please-manifest.json", '{".":"0.2.0"}')
    write("LICENSE", "Example test license\n")
    write(".gitignore", "dist/\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    return tmp_path


def test_archive_contains_only_tracked_product_and_license(release_repo):
    builder = module("build_release")
    (release_repo / "custom_components/hapatchy/untracked.py").write_text("secret = True")
    artifact, checksum = builder.build_archive(release_repo, expected_tag="v0.2.0")
    first = artifact.read_bytes()
    builder.build_archive(release_repo, expected_tag="v0.2.0")
    assert artifact.read_bytes() == first
    assert checksum.read_text() == f"{hashlib.sha256(first).hexdigest()}  {artifact.name}\n"
    with ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {
            "LICENSE",
            "custom_components/hapatchy/manifest.json",
            "custom_components/hapatchy/__init__.py",
        }


@pytest.mark.parametrize("version_file", ["pyproject.toml", ".release-please-manifest.json"])
def test_version_disagreement_prevents_build(release_repo, version_file):
    builder = module("build_release")
    p = release_repo / version_file
    p.write_text(p.read_text().replace("0.2.0", "0.3.0"))
    with pytest.raises(ValueError, match="versions"):
        builder.build_archive(release_repo)
    assert not (release_repo / "dist").exists()


@pytest.mark.parametrize("tag", ["v0.3.0", "0.2.0", "v0.2.0;echo bad", "v0.2.0\nmalicious"])
def test_tag_must_match_version_exactly(release_repo, tag):
    with pytest.raises(ValueError, match="tag"):
        module("build_release").build_archive(release_repo, expected_tag=tag)
    assert not (release_repo / "dist").exists()


def test_tracked_symlink_is_not_packaged(release_repo):
    path = release_repo / "custom_components/hapatchy/link.py"
    path.symlink_to(release_repo / "LICENSE")
    subprocess.run(["git", "-C", str(release_repo), "add", str(path)], check=True)
    with pytest.raises(ValueError, match="regular file"):
        module("build_release").build_archive(release_repo)


def test_documented_example_applies_and_reverts_exactly():
    from custom_components.hapatchy.patch_engine import UnifiedDiffEngine

    engine = UnifiedDiffEngine()
    target = Path("docs/examples/settings.txt").read_bytes()
    parsed = engine.parse(
        Path("docs/examples/interval.patch").read_bytes(), "hapatchy_demo/settings.txt"
    )
    inspection = engine.inspect(parsed, target)
    assert inspection.forward_output == b"mode=demo\ninterval=5\n"
    reverse = engine.inspect(parsed, inspection.forward_output)
    assert reverse.reverse_output == target


class FakeGitHub:
    def __init__(self, sha):
        self.release = {
            "id": 42,
            "tag_name": "v0.2.0",
            "target_commitish": sha,
            "draft": True,
            "assets": [],
        }
        self.writes = []
        self.ref = None

    def releases(self):
        return [self.release.copy()]

    def tag_commit(self, tag):
        return self.ref

    def upload(self, release_id, path):
        asset = {
            "name": path.name,
            "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        self.release["assets"].append(asset)
        self.writes.append(("upload", path.name))
        return asset

    def publish(self, release_id):
        self.writes.append(("publish", release_id))
        self.release["draft"] = False
        return self.release.copy()


@pytest.fixture
def committed_release_repo(release_repo):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(release_repo), *args]).decode().strip()

    git(
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "feat: example",
    )
    sha = git("rev-parse", "HEAD")
    git("update-ref", "refs/remotes/origin/main", sha)
    return release_repo, sha


@pytest.mark.parametrize("change", ["published", "wrong_sha", "wrong_tag", "wrong_id", "wrong_ref"])
def test_publish_refuses_wrong_release_identity(committed_release_repo, change):
    root, sha = committed_release_repo
    github = FakeGitHub(sha)
    if change == "published":
        github.release["draft"] = False
    elif change == "wrong_sha":
        github.release["target_commitish"] = "a" * 40
    elif change == "wrong_tag":
        github.release["tag_name"] = "v0.3.0"
    elif change == "wrong_id":
        github.release["id"] = 43
    else:
        github.ref = "a" * 40
    with pytest.raises(ValueError):
        module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert github.writes == []


def test_publish_refuses_uncommitted_source(committed_release_repo):
    root, sha = committed_release_repo
    (root / "custom_components/hapatchy/__init__.py").write_text("changed")
    github = FakeGitHub(sha)
    with pytest.raises(ValueError, match="clean"):
        module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert not github.writes


def test_publish_refuses_commit_outside_main(committed_release_repo):
    root, sha = committed_release_repo
    (root / "LICENSE").write_text("changed")
    subprocess.run(["git", "-C", str(root), "add", "LICENSE"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fix: other branch",
        ],
        check=True,
    )
    sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"]).decode().strip()
    github = FakeGitHub(sha)
    with pytest.raises(ValueError, match="main"):
        module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert not github.writes


def test_publish_uploads_both_assets_before_publication(committed_release_repo):
    root, sha = committed_release_repo
    github = FakeGitHub(sha)
    module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert github.writes == [
        ("upload", "hapatchy-0.2.0.zip"),
        ("upload", "hapatchy-0.2.0.zip.sha256"),
        ("publish", 42),
    ]
    assert not github.release["draft"]


def test_resume_preserves_matching_asset(committed_release_repo):
    root, sha = committed_release_repo
    artifact, _ = module("build_release").build_archive(root)
    github = FakeGitHub(sha)
    github.upload(42, artifact)
    github.writes.clear()
    # Build outputs are ignored in a normal repository.
    (root / ".git/info/exclude").write_text("dist/\n")
    module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert github.writes == [("upload", "hapatchy-0.2.0.zip.sha256"), ("publish", 42)]


def test_different_existing_asset_is_never_overwritten(committed_release_repo):
    root, sha = committed_release_repo
    github = FakeGitHub(sha)
    github.release["assets"] = [{"name": "hapatchy-0.2.0.zip", "digest": "sha256:" + "0" * 64}]
    with pytest.raises(ValueError, match="asset"):
        module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert not github.writes


def test_failed_upload_keeps_release_draft(committed_release_repo, monkeypatch):
    root, sha = committed_release_repo
    github = FakeGitHub(sha)

    def fail(*args):
        raise RuntimeError("upload failed")

    monkeypatch.setattr(github, "upload", fail)
    with pytest.raises(RuntimeError, match="upload failed"):
        module("release_github").publish_release(root, github, "v0.2.0", sha, 42)
    assert github.release["draft"] and not github.writes
