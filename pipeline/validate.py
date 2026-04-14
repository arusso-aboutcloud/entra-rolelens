"""
validate.py

Validates data/master.json against minimum quality thresholds.
On failure: prints the reason, opens a GitHub Issue, exits 1.
On success: prints "Validation passed".

Required env var on failure:
  GITHUB_TOKEN     — used only to open an issue; optional locally
  GITHUB_REPO      — owner/repo, e.g. "yourname/entra-rolelens"
                     falls back to GITHUB_REPOSITORY (set automatically
                     by GitHub Actions)
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

MASTER_PATH = Path(__file__).parent.parent / "data" / "master.json"

MIN_ROLES = 80
MIN_TASKS = 100

GH_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# GitHub issue helper
# ---------------------------------------------------------------------------

def open_github_issue(title: str, body: str) -> None:
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY")

    if not token or not repo:
        print("  (GITHUB_TOKEN / GITHUB_REPO not set — skipping issue creation)")
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
        issue = resp.json()
        print(f"  GitHub issue opened: {issue.get('html_url', '(unknown URL)')}")
    else:
        print(f"  Failed to open GitHub issue: HTTP {resp.status_code} {resp.text}",
              file=sys.stderr)


def fail(reason: str) -> None:
    print(f"Validation FAILED: {reason}", file=sys.stderr)
    title = "Pipeline validation failure"
    body = (
        f"## RoleLens pipeline validation failed\n\n"
        f"**Reason:** {reason}\n\n"
        f"**File checked:** `data/master.json`\n\n"
        f"Check the [latest workflow run]"
        f"(../../actions) for details."
    )
    open_github_issue(title, body)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_master(master: dict) -> None:
    # 1. generated_at is a valid ISO timestamp
    generated_at = master.get("generated_at")
    if not generated_at:
        fail("master.json missing 'generated_at' field")
    try:
        datetime.fromisoformat(generated_at)
    except (ValueError, TypeError):
        fail(f"'generated_at' is not a valid ISO timestamp: {generated_at!r}")

    # 2. Role count
    role_count = master.get("role_count", 0)
    roles = master.get("roles", [])
    if role_count < MIN_ROLES:
        fail(f"role_count={role_count} is below minimum {MIN_ROLES}")
    if len(roles) != role_count:
        fail(f"role_count={role_count} does not match len(roles)={len(roles)}")

    # 3. Task count
    task_count = master.get("task_count", 0)
    tasks = master.get("tasks", [])
    if task_count < MIN_TASKS:
        fail(f"task_count={task_count} is below minimum {MIN_TASKS}")
    if len(tasks) != task_count:
        fail(f"task_count={task_count} does not match len(tasks)={len(tasks)}")

    # 4. Every task has required fields
    required_task_fields = ("feature_area", "task", "min_role")
    bad_tasks = [
        t for t in tasks
        if any(not t.get(f) for f in required_task_fields)
    ]
    if bad_tasks:
        sample = bad_tasks[0]
        fail(
            f"{len(bad_tasks)} task(s) missing required fields. "
            f"First bad task: {json.dumps(sample)}"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not MASTER_PATH.exists():
        fail(f"{MASTER_PATH} does not exist — run enrich.py first")

    try:
        master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"master.json is not valid JSON: {exc}")

    check_master(master)
    print("Validation passed")


if __name__ == "__main__":
    main()
