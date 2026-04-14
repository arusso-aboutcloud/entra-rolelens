"""
validate.py

Validates data/master.json against minimum quality thresholds.
On failure: prints the reason, opens a GitHub Issue, exits 1.
On success: prints "Validation passed".

Required env vars (only needed on failure):
  GITHUB_TOKEN      -- used to open the issue
  GITHUB_REPO       -- owner/repo (falls back to GITHUB_REPOSITORY,
                       which GitHub Actions sets automatically)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import requests

MASTER_PATH = Path(__file__).parent.parent / "data" / "master.json"
MIN_ROLES = 80
MIN_TASKS = 100
GH_API = "https://api.github.com"


def open_github_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("  (GITHUB_TOKEN/GITHUB_REPO not set -- skipping issue creation)")
        return
    url = f"{GH_API}/repos/{repo}/issues"
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"title": title, "body": body, "labels": ["pipeline-failure"]},
        timeout=15,
    )
    if resp.ok:
        print(f"  GitHub issue opened: {resp.json().get('html_url', '')}")
    else:
        print(f"  Failed to open issue: HTTP {resp.status_code}", file=sys.stderr)


def fail(reason: str) -> None:
    print(f"Validation FAILED: {reason}", file=sys.stderr)
    open_github_issue(
        "Pipeline validation failure",
        f"## RoleLens pipeline validation failed\n\n**Reason:** {reason}\n\n"
        f"**File checked:** `data/master.json`\n\n"
        "Check the latest workflow run for details.",
    )
    sys.exit(1)


def main() -> None:
    if not MASTER_PATH.exists():
        fail(f"{MASTER_PATH} does not exist -- run enrich.py first")

    try:
        master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"master.json is not valid JSON: {exc}")

    # generated_at is a valid ISO timestamp
    generated_at = master.get("generated_at")
    if not generated_at:
        fail("master.json missing 'generated_at' field")
    try:
        datetime.fromisoformat(generated_at)
    except (ValueError, TypeError):
        fail(f"'generated_at' is not a valid ISO timestamp: {generated_at!r}")

    # role_count
    role_count = master.get("role_count", 0)
    roles = master.get("roles", [])
    if role_count < MIN_ROLES:
        fail(f"role_count={role_count} is below minimum {MIN_ROLES}")
    if len(roles) != role_count:
        fail(f"role_count={role_count} does not match len(roles)={len(roles)}")

    # task_count
    task_count = master.get("task_count", 0)
    tasks = master.get("tasks", [])
    if task_count < MIN_TASKS:
        fail(f"task_count={task_count} is below minimum {MIN_TASKS}")
    if len(tasks) != task_count:
        fail(f"task_count={task_count} does not match len(tasks)={len(tasks)}")

    # every task has required fields
    required = ("feature_area", "task", "min_role")
    bad = [t for t in tasks if any(not t.get(f) for f in required)]
    if bad:
        fail(
            f"{len(bad)} task(s) missing required fields. "
            f"First: {json.dumps(bad[0])}"
        )

    print("Validation passed")


if __name__ == "__main__":
    main()
