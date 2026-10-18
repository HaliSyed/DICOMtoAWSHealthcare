#!/usr/bin/env python3
"""
sync_to_main.py -- push the current branch, open a PR into main, merge it.

Steps (each one stops the run on failure):
  1. Refuse to run on main or with uncommitted changes.
  2. Run the test suite; any failure stops the sync.
  3. Secret scan: .env must not be tracked, no tracked file may match an
     ignore rule (.gitignore or the local .git/info/exclude), and neither the
     real token nor any GitHub-token-shaped string may appear in the commits
     being pushed.
  4. Push the branch (token used for this one command only -- never written
     to .git/config, the remote URL, or a credential store).
  5. Open a pull request into main (or reuse an open one), then merge it.
  6. Delete the remote branch and fast-forward the local branch to main.

The token is read from GITHUB_TOKEN in the environment or in .env, and is
never printed.

Usage (from the repo root):
    python tools/sync_to_main.py --title "Short summary of the changes"
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

OWNER_REPO = "HaliSyed/DICOMtoAWSHealthcare"
API = f"https://api.github.com/repos/{OWNER_REPO}"
BASE = "main"
TOKEN_SHAPES = re.compile(r"github_pat_[A-Za-z0-9_]{50,}|gh[pousr]_[A-Za-z0-9]{30,}")


def fail(msg: str) -> None:
    print(f"STOP: {msg}")
    sys.exit(1)


def read_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    env_file = Path(".env")
    if not token and env_file.is_file():
        m = re.search(r"^GITHUB_TOKEN=(.+)$", env_file.read_text(encoding="utf-8"), re.MULTILINE)
        token = m.group(1).strip() if m else ""
    if not token:
        fail("no GITHUB_TOKEN in the environment or .env")
    return token


def git(*args: str, token: str = "", env: dict | None = None, check: bool = True) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True, env=env)
    out = (result.stdout + result.stderr).strip()
    if token:
        out = out.replace(token, "***")
    if check and result.returncode != 0:
        fail(f"git {' '.join(args)} failed:\n{out}")
    return out


def github(token: str, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        API + path, method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "sync-to-main"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--title", required=True, help="pull request title")
    parser.add_argument("--body", default="", help="pull request description (markdown)")
    args = parser.parse_args()

    # 1. preconditions
    branch = git("branch", "--show-current")
    if branch in ("", BASE):
        fail(f"run this from a work branch, not '{branch or 'detached HEAD'}'")
    if git("status", "--porcelain"):
        fail("uncommitted changes -- commit them first")
    token = read_token()
    git("fetch", "--quiet", "--prune", "origin")
    commits = git("rev-list", f"origin/{BASE}..HEAD").split()
    if not commits:
        print(f"Nothing to sync: {branch} has no commits that are not already in {BASE}.")
        return 0
    print(f"{len(commits)} commit(s) on '{branch}' to sync into {BASE}.")

    # 2. tests
    print("Running tests...")
    tests = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
    summary = (tests.stdout.strip().splitlines() or ["(no output)"])[-1]
    if tests.returncode != 0:
        fail(f"tests failed -- nothing pushed.\n{tests.stdout[-3000:]}")
    print(f"  {summary}")

    # 3. secret scan
    if git("ls-files", ".env", ".env.local"):
        fail(".env is tracked by git")
    ignored_but_tracked = git("ls-files", "--cached", "--ignored", "--exclude-standard")
    if ignored_but_tracked:
        fail(f"tracked files match ignore rules and must not be published:\n{ignored_but_tracked}")
    for commit in commits:
        if git("grep", "-c", "-F", token, commit, check=False):
            fail(f"the GitHub token is inside commit {commit[:7]}")
        shapes = git("grep", "-l", "-E", TOKEN_SHAPES.pattern, commit, check=False)
        if shapes:
            fail(f"a GitHub-token-shaped string is in commit {commit[:7]}: {shapes}")
    print("  Secret scan: clean")

    # 4. push, authenticating for this command only
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    push_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {auth}",
                "GIT_CONFIG_KEY_1": "credential.helper", "GIT_CONFIG_VALUE_1": ""}
    git("push", "--quiet", "origin", f"HEAD:refs/heads/{branch}", token=token, env=push_env)
    print(f"  Pushed '{branch}'")

    # 5. PR + merge
    owner = OWNER_REPO.split("/")[0]
    status, open_prs = github(token, "GET", f"/pulls?head={owner}:{branch}&base={BASE}&state=open")
    if status == 200 and open_prs:
        pr = open_prs[0]
    else:
        body = (args.body.strip() + "\n\n" if args.body.strip() else "") + f"Tests: {summary}"
        status, pr = github(token, "POST", "/pulls", {"title": args.title, "head": branch, "base": BASE, "body": body})
        if status != 201:
            fail(f"could not create PR ({status}): {pr.get('message')} {pr.get('errors', '')}")
    print(f"  PR #{pr['number']}: {pr['html_url']}")

    status, merged = github(token, "PUT", f"/pulls/{pr['number']}/merge", {"merge_method": "merge"})
    if status != 200:
        fail(f"PR #{pr['number']} left open -- merge refused ({status}): {merged.get('message')}")
    print(f"  Merged into {BASE} ({merged.get('sha', '')[:7]})")

    # 6. clean up
    github(token, "DELETE", f"/git/refs/heads/{branch}")
    git("fetch", "--quiet", "--prune", "origin")
    git("merge", "--quiet", "--ff-only", f"origin/{BASE}")
    print(f"  Remote branch deleted; local '{branch}' now matches {BASE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
