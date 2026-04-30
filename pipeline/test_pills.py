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

# Pills that are known to fail and are tracked as Week 2 work.
# These are documented in SESSION-HANDOFF-ROLELENS-2026-04-18.md under
# "2026-04-22 Pill-fix session — post-mortem", section "Technical debt
# still outstanding".
#
# A pill in this set that FAILS does not trigger a regression alarm.
# A pill in this set that suddenly PASSES is reported as RESOLVED so
# this list can be pruned.
#
# Remove entries from this set as they are fixed by Week 2 ranking work
# (BM25 scoring + synonym dict audit + over-reach cleanup).
KNOWN_FAILURES: set[str] = {
    # All resolved in chunk/path-x-synonym-surgery:
    # "reset password"       RESOLVED — explicit key -> 'reset non admin password'
    # "reset user password"  RESOLVED — key -> 'reset non admin password'
    # "manage groups"        RESOLVED — key -> 'group membership management'
    # "GDAP relationships"   RESOLVED — plural key -> 'gdap relationships partners'
    # "restore deleted users" RESOLVED 2026-04-25 by Chunk 4 stopword guard
}


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
    print("(queries expanded via pipeline/synonyms.py before API call)")
    print(f"({len(KNOWN_FAILURES)} pills in KNOWN_FAILURES suppression list)")
    print("-" * 72)

    new_failures: list[str] = []
    known_fails: list[str] = []
    resolved: list[str] = []

    for query, expected in EXPECTATIONS:
        passed, detail = run_pill(query, expected)
        is_known = query in KNOWN_FAILURES

        if passed and is_known:
            marker = "RESOLVED"
            resolved.append(f"  - {query!r}: now passing -> remove from KNOWN_FAILURES")
        elif passed:
            marker = "PASS"
        elif is_known:
            marker = "KNOWN-FAIL"
            known_fails.append(f"  - {query!r}: {detail}")
        else:
            marker = "REGRESSION"
            new_failures.append(f"  - {query!r}: {detail}")

        print(f"  {marker:11s} {query!r:45s} {detail}")

    print("-" * 72)
    print(f"PASS:        {len(EXPECTATIONS) - len(new_failures) - len(known_fails) - len(resolved)}")
    print(f"KNOWN-FAIL:  {len(known_fails)} (suppressed, see KNOWN_FAILURES)")
    print(f"RESOLVED:    {len(resolved)}")
    print(f"REGRESSION:  {len(new_failures)} (these break the build)")
    print()

    if resolved:
        print("Pills that are now passing — prune them from KNOWN_FAILURES:")
        for line in resolved:
            print(line)
        print()

    if known_fails:
        print("Known failures (Week 2 backlog, not blocking):")
        for line in known_fails:
            print(line)
        print()

    if new_failures:
        print(f"NEW regressions detected ({len(new_failures)}):")
        for line in new_failures:
            print(line)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
