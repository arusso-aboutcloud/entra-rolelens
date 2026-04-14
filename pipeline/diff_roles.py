"""
diff_roles.py

Compares today's data/roles.json against data/previous_roles.json to detect
added, removed, and modified built-in roles.

Writes data/changelog.json (appending to any existing entries).
Copies today's roles.json to previous_roles.json for tomorrow's run.

Change object schema:
  {
    "date":        "2026-04-14",
    "change_type": "ADDED" | "REMOVED" | "MODIFIED",
    "role_id":     "<template GUID>",
    "role_name":   "Authentication Administrator",
    "field":       "permissions" | "displayName" | ... | null,
    "detail":      "human-readable description of the change"
  }
"""

import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROLES_PATH = Path(__file__).parent.parent / "data" / "roles.json"
PREV_ROLES_PATH = Path(__file__).parent.parent / "data" / "previous_roles.json"
CHANGELOG_PATH = Path(__file__).parent.parent / "data" / "changelog.json"

TODAY = date.today().isoformat()


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def roles_by_id(roles: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in roles}


def diff_permissions(old: list[str], new: list[str]) -> str:
    old_set, new_set = set(old), set(new)
    added = len(new_set - old_set)
    removed = len(old_set - new_set)
    parts = []
    if added:
        parts.append(f"{added} permission{'s' if added != 1 else ''} added")
    if removed:
        parts.append(f"{removed} permission{'s' if removed != 1 else ''} removed")
    return ", ".join(parts) if parts else "permissions reordered"


def compute_changes(old_roles: dict[str, dict], new_roles: dict[str, dict]) -> list[dict]:
    changes = []

    # ADDED
    for rid, role in new_roles.items():
        if rid not in old_roles:
            changes.append({
                "date": TODAY,
                "change_type": "ADDED",
                "role_id": rid,
                "role_name": role["displayName"],
                "field": None,
                "detail": f"New built-in role added: {role['displayName']}",
            })

    # REMOVED
    for rid, role in old_roles.items():
        if rid not in new_roles:
            changes.append({
                "date": TODAY,
                "change_type": "REMOVED",
                "role_id": rid,
                "role_name": role["displayName"],
                "field": None,
                "detail": f"Built-in role removed: {role['displayName']}",
            })

    # MODIFIED
    scalar_fields = ["displayName", "description", "isPrivileged"]
    for rid, new_role in new_roles.items():
        old_role = old_roles.get(rid)
        if old_role is None:
            continue  # already recorded as ADDED

        for field in scalar_fields:
            if old_role.get(field) != new_role.get(field):
                changes.append({
                    "date": TODAY,
                    "change_type": "MODIFIED",
                    "role_id": rid,
                    "role_name": new_role["displayName"],
                    "field": field,
                    "detail": (
                        f"{field} changed: "
                        f"{json.dumps(old_role.get(field))} -> {json.dumps(new_role.get(field))}"
                    ),
                })

        old_perms = old_role.get("permissions", [])
        new_perms = new_role.get("permissions", [])
        if set(old_perms) != set(new_perms):
            changes.append({
                "date": TODAY,
                "change_type": "MODIFIED",
                "role_id": rid,
                "role_name": new_role["displayName"],
                "field": "permissions",
                "detail": diff_permissions(old_perms, new_perms),
            })

    return changes


def load_existing_changelog() -> list[dict]:
    if CHANGELOG_PATH.exists():
        return load_json(CHANGELOG_PATH)
    return []


def main() -> None:
    if not ROLES_PATH.exists():
        print(f"ERROR: {ROLES_PATH} not found — run fetch_roles.py first", file=sys.stderr)
        sys.exit(1)

    today_roles = load_json(ROLES_PATH)

    # First run: no previous baseline
    if not PREV_ROLES_PATH.exists():
        shutil.copy(ROLES_PATH, PREV_ROLES_PATH)
        existing = load_existing_changelog()
        with CHANGELOG_PATH.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)
        print("First run — baseline set")
        print("Diff complete — 0 added, 0 removed, 0 modified")
        return

    prev_roles = load_json(PREV_ROLES_PATH)

    old_by_id = roles_by_id(prev_roles)
    new_by_id = roles_by_id(today_roles)

    new_changes = compute_changes(old_by_id, new_by_id)

    # Merge with existing changelog (today's changes are new entries)
    existing = load_existing_changelog()
    combined = existing + new_changes

    with CHANGELOG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2, ensure_ascii=False)

    # Advance the baseline
    shutil.copy(ROLES_PATH, PREV_ROLES_PATH)

    added = sum(1 for c in new_changes if c["change_type"] == "ADDED")
    removed = sum(1 for c in new_changes if c["change_type"] == "REMOVED")
    modified = sum(1 for c in new_changes if c["change_type"] == "MODIFIED")
    print(f"Diff complete — {added} added, {removed} removed, {modified} modified")


if __name__ == "__main__":
    main()
