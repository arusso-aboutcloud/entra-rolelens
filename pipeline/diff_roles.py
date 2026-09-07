"""
diff_roles.py

Compares today's data/master.json roles against data/previous_master.json to
detect added, removed, and modified built-in roles.

Diffs against master.json (the enriched, union-of-Graph-API-and-docs role
list that push_to_cloudflare.py actually pushes live) rather than the raw
docs-scraped roles.json. Microsoft's live Graph API sometimes grants a role
new permissions well before their public docs pages catch up (or without any
docs update at all) -- diffing the docs-only snapshot silently missed those
changes entirely, even though the live site already reflected them correctly
via enrich.py's Graph+docs union. See the "Application Developer" incident
(2026-09-07): a live change from 3 to 18 permissions was already correctly
served by the site but never appeared in "What's new" because the old baseline
was frozen on the stale docs-only permission count.

Writes data/changelog.json (appending new entries to any existing ones).
Writes today's master.json roles to previous_master.json for tomorrow's run.
"""

import json
import sys
from datetime import date
from pathlib import Path

MASTER_PATH = Path(__file__).parent.parent / "data" / "master.json"
PREV_MASTER_PATH = Path(__file__).parent.parent / "data" / "previous_master.json"
CHANGELOG_PATH = Path(__file__).parent.parent / "data" / "changelog.json"

TODAY = date.today().isoformat()


def load_json(path: Path) -> object:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_master_roles(path: Path) -> list[dict]:
    """previous_master.json stores a flat role list; master.json wraps roles
    in {"roles": [...], "tasks": [...], ...} -- unwrap it if present."""
    data = load_json(path)
    if isinstance(data, dict):
        return data.get("roles", [])
    return data


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


def compute_changes(old_roles: dict, new_roles: dict) -> list[dict]:
    changes = []

    for rid, role in new_roles.items():
        if rid not in old_roles:
            changes.append({
                "date": TODAY,
                "change_type": "ADDED",
                "role_id": rid,
                "role_name": role["displayName"],
                "field": None,
                "detail": f"New built-in role added: {role['displayName']}",
                # Permission count at add time — lets "What's new" show how much
                # the new role grants (0 = a workload role governed outside Entra).
                "permission_count": len(role.get("permissions", [])),
            })

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

    scalar_fields = ["displayName", "description", "isPrivileged"]
    for rid, new_role in new_roles.items():
        old_role = old_roles.get(rid)
        if old_role is None:
            continue

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
                        f"{json.dumps(old_role.get(field))} -> "
                        f"{json.dumps(new_role.get(field))}"
                    ),
                    # Structured before/after so the UI can render the change
                    # directly instead of parsing the detail string.
                    "old": old_role.get(field),
                    "new": new_role.get(field),
                })

        old_perms = old_role.get("permissions", [])
        new_perms = new_role.get("permissions", [])
        if set(old_perms) != set(new_perms):
            added = sorted(set(new_perms) - set(old_perms))
            removed = sorted(set(old_perms) - set(new_perms))
            entry = {
                "date": TODAY,
                "change_type": "MODIFIED",
                "role_id": rid,
                "role_name": new_role["displayName"],
                "field": "permissions",
                "detail": diff_permissions(old_perms, new_perms),
            }
            # Persist the actual permission names that changed so "What's new"
            # can show exactly what Microsoft added/removed, not just a count.
            if added:
                entry["added_permissions"] = added
            if removed:
                entry["removed_permissions"] = removed

            # This "date" is when RoleLens detected the change, NOT when
            # Microsoft actually granted it live -- neither the Graph API nor
            # the docs expose that. What we CAN verify: whether the specific
            # added permissions are actually listed on Microsoft's own docs
            # page right now, and if so, that page's own ms.date (its last
            # reviewed date, not necessarily this permission's date either --
            # a page can be touched for unrelated reasons and still miss a
            # live grant, so this is only trusted when the exact permission
            # string is present in that page's current content).
            docs_perms = set(new_role.get("permissionsInDocs", []))
            undocumented = sorted(set(added) - docs_perms) if added else []
            if added and undocumented != added:
                # At least one added permission IS in the current docs.
                entry["docs_reviewed_date"] = new_role.get("docsReviewedDate")
            if undocumented:
                entry["undocumented_permissions"] = undocumented
            changes.append(entry)

    return changes


def load_existing_changelog() -> list[dict]:
    if CHANGELOG_PATH.exists():
        return load_json(CHANGELOG_PATH)
    return []


def write_previous_master(roles: list[dict]) -> None:
    with PREV_MASTER_PATH.open("w", encoding="utf-8") as fh:
        json.dump(roles, fh, indent=2, ensure_ascii=False)


def main() -> None:
    if not MASTER_PATH.exists():
        print(f"ERROR: {MASTER_PATH} not found -- run enrich.py first", file=sys.stderr)
        sys.exit(1)

    today_roles = load_master_roles(MASTER_PATH)

    if not PREV_MASTER_PATH.exists():
        write_previous_master(today_roles)
        existing = load_existing_changelog()
        with CHANGELOG_PATH.open("w", encoding="utf-8") as fh:
            json.dump(existing, fh, indent=2, ensure_ascii=False)
        print("First run -- baseline set")
        print("Diff complete -- 0 added, 0 removed, 0 modified")
        return

    prev_roles = load_master_roles(PREV_MASTER_PATH)
    old_by_id = roles_by_id(prev_roles)
    new_by_id = roles_by_id(today_roles)

    new_changes = compute_changes(old_by_id, new_by_id)

    existing = load_existing_changelog()
    combined = existing + new_changes

    with CHANGELOG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(combined, fh, indent=2, ensure_ascii=False)

    write_previous_master(today_roles)

    added = sum(1 for c in new_changes if c["change_type"] == "ADDED")
    removed = sum(1 for c in new_changes if c["change_type"] == "REMOVED")
    modified = sum(1 for c in new_changes if c["change_type"] == "MODIFIED")
    print(f"Diff complete -- {added} added, {removed} removed, {modified} modified")


if __name__ == "__main__":
    main()
