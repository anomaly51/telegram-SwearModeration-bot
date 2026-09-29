"""Merge the developer's code while retaining this repository's deployment configuration."""

import json
import os
import re
import subprocess
from pathlib import Path


PROTECTED = (".github", "DEPLOYMENT.md")


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def merge_upstream(revision):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Expected a full upstream commit SHA")
    if git("status", "--porcelain").stdout.strip():
        raise RuntimeError("Refusing to synchronize a checkout with local changes")
    if git("merge-base", "--is-ancestor", revision, "HEAD", check=False).returncode == 0:
        return False
    git("merge-base", "HEAD", revision)  # Never merge unrelated repositories.
    try:
        result = git("merge", "--no-commit", "--no-ff", revision, check=False)
        conflicts = git("diff", "--name-only", "--diff-filter=U").stdout.splitlines()
        unexpected = [
            path for path in conflicts
            if not any(path == item or path.startswith(item + "/") for item in PROTECTED)
        ]
        if unexpected or (result.returncode and not conflicts):
            raise RuntimeError("Upstream needs a manual merge: " + ", ".join(unexpected))
        git("restore", "--source=HEAD", "--staged", "--worktree", "--", *PROTECTED)
        git("diff", "--cached", "--check")
        git("commit", "-m", f"merge: sync upstream {revision[:12]}")
        return True
    except Exception:
        git("merge", "--abort", check=False)
        raise


def main():
    config = json.loads(Path(".github/upstream.json").read_text())
    repository, branch = config["repository"], config["branch"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid upstream repository")
    git("check-ref-format", "refs/heads/" + branch)
    git("fetch", "--no-tags", f"https://github.com/{repository}.git", f"refs/heads/{branch}")
    revision = git("rev-parse", "FETCH_HEAD").stdout.strip()
    changed = merge_upstream(revision)
    if changed:
        # A concurrent main update fails safely; the next run merges from fresh main.
        git("push", "origin", "HEAD:main")
    message = f"Upstream {repository}@{revision}: " + ("synchronized" if changed else "up to date")
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as file:
            file.write(message + "\n\nProduction still requires Promote production.\n")


if __name__ == "__main__":
    main()
