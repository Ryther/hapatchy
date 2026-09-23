"""Inspect and publish a verified GitHub draft; credentials come from GH_TOKEN."""

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import quote

from script.build_release import VERSION, build_archive, release_version

SHA = re.compile(r"[0-9a-f]{40}")


class GitHub:
    """Small gh CLI adapter; tests substitute this boundary without network access."""

    def __init__(self, repository: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Invalid GitHub repository")
        self.repository = repository
        self.base = f"repos/{repository}"

    @staticmethod
    def _json(*args: str, payload: dict | None = None):
        command = ["gh", "api", *args]
        if payload is not None:
            command += ["--input", "-"]
        result = subprocess.run(
            command,
            input=json.dumps(payload) if payload is not None else None,
            text=True,
            capture_output=True,
            check=True,
        )
        return json.loads(result.stdout)

    def releases(self) -> list[dict]:
        # List includes drafts; GitHub's get-by-tag endpoint is for published releases.
        pages = self._json("--paginate", "--slurp", f"{self.base}/releases?per_page=100")
        return [release for page in pages for release in page]

    def tag_commit(self, tag: str) -> str | None:
        refs = self._json(f"{self.base}/git/matching-refs/tags/{quote(tag, safe='')}")
        exact = [ref for ref in refs if ref["ref"] == f"refs/tags/{tag}"]
        if not exact:
            return None
        obj = exact[0]["object"]
        for _ in range(5):
            if obj["type"] == "commit":
                return obj["sha"]
            if obj["type"] != "tag" or not SHA.fullmatch(obj["sha"]):
                break
            obj = self._json(f"{self.base}/git/tags/{obj['sha']}")["object"]
        raise ValueError("Release tag does not resolve to a commit")

    def upload(self, release_id: int, path: Path) -> dict:
        url = f"https://uploads.github.com/{self.base}/releases/{release_id}/assets?name={quote(path.name)}"
        return self._json(
            "--method",
            "POST",
            "-H",
            "Content-Type: application/octet-stream",
            url,
            "--input",
            str(path),
        )

    def publish(self, release_id: int) -> dict:
        return self._json(
            "--method", "PATCH", f"{self.base}/releases/{release_id}", payload={"draft": False}
        )


def inspect_release(github: GitHub, tag: str) -> dict:
    if not tag.startswith("v") or not VERSION.fullmatch(tag[1:]):
        raise ValueError("Expected a stable vMAJOR.MINOR.PATCH tag")
    matching = [release for release in github.releases() if release["tag_name"] == tag]
    if len(matching) != 1:
        raise ValueError("Expected exactly one existing release for the tag")
    release = matching[0]
    if release["draft"] is not True:
        raise ValueError("Release is already published; refusing to modify it")
    if not SHA.fullmatch(release["target_commitish"]):
        raise ValueError("Draft target must be a full commit SHA, not a moving branch")
    if type(release["id"]) is not int or release["id"] <= 0:
        raise ValueError("Invalid release ID")
    return release


def verify_checkout(root: Path, sha: str) -> None:
    if not SHA.fullmatch(sha):
        raise ValueError("Invalid release commit SHA")

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    if git("rev-parse", "HEAD") != sha:
        raise ValueError("Checkout does not match the release commit")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("Release checkout must be clean")
    result = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "origin/main"], cwd=root)
    if result.returncode:
        raise ValueError("Release commit must belong to origin/main")


def _verified_draft(github: GitHub, tag: str, sha: str, release_id: int) -> dict:
    release = inspect_release(github, tag)
    if release["id"] != release_id or release["target_commitish"] != sha:
        raise ValueError("Draft release identity changed")
    if (existing := github.tag_commit(tag)) is not None and existing != sha:
        raise ValueError("Existing tag points to a different commit")
    return release


def publish_release(root: Path, github: GitHub, tag: str, sha: str, release_id: int) -> None:
    verify_checkout(root, sha)
    release_version(root, tag)
    release = _verified_draft(github, tag, sha, release_id)
    artifacts = build_archive(root, tag)
    for artifact in artifacts:
        digest = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
        matching = [asset for asset in release["assets"] if asset["name"] == artifact.name]
        if matching:
            if len(matching) != 1 or matching[0].get("digest") != digest:
                raise ValueError("Existing draft asset differs or has no verifiable digest")
        else:
            uploaded = github.upload(release_id, artifact)
            if uploaded.get("digest") != digest:
                raise ValueError("Uploaded asset digest does not match local bytes")
    # Re-read before the irreversible publish step, including hashes of both assets.
    release = _verified_draft(github, tag, sha, release_id)
    for artifact in artifacts:
        expected = "sha256:" + hashlib.sha256(artifact.read_bytes()).hexdigest()
        matches = [a for a in release["assets"] if a["name"] == artifact.name]
        if len(matches) != 1 or matches[0].get("digest") != expected:
            raise ValueError("Draft asset changed before publication")
    result = github.publish(release_id)
    if result["draft"] is not False:
        raise ValueError("GitHub did not publish the release")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["pending", "inspect", "publish"])
    parser.add_argument("--tag")
    parser.add_argument("--sha")
    parser.add_argument("--release-id", type=int)
    parser.add_argument("--output", type=Path, help="GitHub step output file for inspect")
    args = parser.parse_args()
    github = GitHub(os.environ.get("GITHUB_REPOSITORY", ""))
    try:
        if args.command == "pending":
            drafts = [
                r
                for r in github.releases()
                if r["draft"]
                and r["tag_name"].startswith("v")
                and VERSION.fullmatch(r["tag_name"][1:])
            ]
            if len(drafts) > 1:
                raise ValueError("Multiple release drafts exist; select one with resume_tag")
            if drafts:
                inspect_release(github, drafts[0]["tag_name"])
                if args.output:
                    with args.output.open("a") as output:
                        output.write(f"tag={drafts[0]['tag_name']}\n")
                print(drafts[0]["tag_name"])
            return
        if not args.tag:
            parser.error("inspect and publish require --tag")
        if args.command == "inspect":
            release = inspect_release(github, args.tag)
            outputs = {
                "tag": args.tag,
                "sha": release["target_commitish"],
                "release_id": release["id"],
            }
            if args.output:
                with args.output.open("a") as output:
                    output.write("".join(f"{key}={value}\n" for key, value in outputs.items()))
            print(json.dumps(outputs))
        else:
            if args.sha is None or args.release_id is None:
                parser.error("publish requires --sha and --release-id")
            publish_release(Path.cwd(), github, args.tag, args.sha, args.release_id)
            print(f"Published {args.tag} from {args.sha}")
    except (ValueError, KeyError) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
