"""
test_pills.py

Runs the documented pill expectations against the live worker
and fails the nightly pipeline if any regress.

Opens a GitHub issue on failure so regressions don't go silent.
"""

import os
import sys
from urllib.parse import quote

import requests

from synonyms import expand_query

WORKER_URL = os.environ.get(
    "WORKER_URL",
    "https://rolelens-worker.russo-antonio76.workers.dev",
)

# Format: (query, expected_min_role_at_rank_1)
# When adding new pills to the frontend, add expectations here.
EXPECTATIONS: list[tuple[str, str]] = [
    ("configure passkeys",          "Authentication Policy Administrator"),
    ("backup",                      "Entra Backup Reader"),
    ("reset password",              "Password Administrator"),
    ("reset user password",         "Password Administrator"),
    ("manage conditional access",   "Conditional Access Administrator"),
    ("configure SSPR",              "Authentication Policy Administrator"),
    ("manage AI agents",            "Agent ID Administrator"),
    ("manage groups",               "Groups Administrator"),
    ("manage administrative units", "Groups Administrator"),
    ("manage Copilot governance",   "AI Administrator"),
    ("GDAP relationships",          "Tenant Governance Relationship Administrator"),
    ("restore deleted users",       "Entra Backup Administrator"),
    ("audit AI usage",              "AI Reader"),
    ("configure PIM",               "Privileged Role Administrator"),
    ("approve access review",       "Identity Governance Administrator"),
]


def run_pill(query: str, expected_role: str) -> tuple[bool, str]:
    """Returns (passed, detail_message)."""
    expanded = expand_query(query)
    url = f"{WORKER_URL}/api/search?q={quote(expanded)}"
    try:
        resp = requests.get(url, timeout=10)
    except requests.RequestException as exc:
        return False, f"network error: {exc}"

    if not resp.ok:
        return False, f"HTTP {resp.status_code}"

    results = resp.json()
    if not isinstance(results, list) or not results:
        return False, "no results returned"

    actual = results[0].get("min_role", "<missing>")
    if actual == expected_role:
        return True, f"OK -> {actual}"
    return False, f"expected {expected_role!r}, got {actual!r}"


def main() -> int:
    print(f"Running {len(EXPECTATIONS)} pill tests against {WORKER_URL}")
    print("-" * 72)
    failures: list[str] = []
    for query, expected in EXPECTATIONS:
        passed, detail = run_pill(query, expected)
        marker = "PASS" if passed else "FAIL"
        expanded = expand_query(query)
        suffix = f" [-> {expanded!r}]" if expanded != query else ""
        print(f"  {marker}  {query!r:45s}  {detail}{suffix}")
        if not passed:
            failures.append(f"  - {query!r}: {detail}")

    print("-" * 72)
    if failures:
        print(f"\n{len(failures)} pill regression(s) detected:")
        for line in failures:
            print(line)
        return 1

    print(f"\nAll {len(EXPECTATIONS)} pills passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
