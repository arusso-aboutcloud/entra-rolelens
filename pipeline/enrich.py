"""
enrich.py

Dual-source enrichment with shadow role detection.

Data sources:
  data/roles_graph_raw.json  — live Microsoft Graph API (source of truth)
  data/roles.json            — MicrosoftDocs scraper (descriptions, isPrivileged)
  data/tasks.json            — task → minimum role mappings

Cross-reference logic:
  - Roles in Graph API AND docs: merge, use docs isPrivileged + description
  - Roles in Graph API but NOT docs: flag isShadowRole: true
  - Permissions: flattened from Graph API rolePermissions[].allowedResourceActions

Output: data/master.json with shadow_role_count field added.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

GRAPH_ROLES_PATH = Path(__file__).parent.parent / "data" / "roles_graph_raw.json"
DOCS_ROLES_PATH  = Path(__file__).parent.parent / "data" / "roles.json"
TASKS_PATH       = Path(__file__).parent.parent / "data" / "tasks.json"
MASTER_PATH      = Path(__file__).parent.parent / "data" / "master.json"


def load_json(path: Path) -> object:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def flatten_graph_permissions(role: dict) -> list[str]:
    """Extract flat permission list from Graph API rolePermissions structure."""
    perms: list[str] = []
    for rp in role.get("rolePermissions", []):
        perms.extend(rp.get("allowedResourceActions", []))
    return perms


def build_merged_roles(
    roles_from_graph: list[dict],
    roles_from_docs: list[dict],
) -> tuple[list[dict], list[str]]:
    """
    Cross-reference Graph API roles against docs roles by ID.

    Returns:
        merged    — list of merged role dicts (schema matches existing master.json)
        shadow    — list of displayNames that are shadow roles
    """
    docs_by_id: dict[str, dict] = {r["id"]: r for r in roles_from_docs}
    shadow_names: list[str] = []
    merged: list[dict] = []

    for graph_role in roles_from_graph:
        role_id   = graph_role["id"]
        docs_role = docs_by_id.get(role_id)

        # Flatten permissions from Graph API structure
        permissions = flatten_graph_permissions(graph_role)

        if docs_role:
            # Known role — merge, prefer docs for isPrivileged and description
            merged.append({
                "id":           role_id,
                "displayName":  graph_role.get("displayName", docs_role.get("displayName", "")),
                "description":  docs_role.get("description") or graph_role.get("description", ""),
                "isBuiltIn":    graph_role.get("isBuiltIn", True),
                "isPrivileged": docs_role.get("isPrivileged", False),
                "permissions":  permissions,
                "isShadowRole": False,
            })
        else:
            # Shadow role — present in API, absent from docs
            display_name = graph_role.get("displayName", role_id)
            shadow_names.append(display_name)
            merged.append({
                "id":           role_id,
                "displayName":  display_name,
                "description":  graph_role.get("description", ""),
                "isBuiltIn":    graph_role.get("isBuiltIn", True),
                "isPrivileged": False,
                "permissions":  permissions,
                "isShadowRole": True,
            })

    return merged, shadow_names


def build_role_index(roles: list[dict]) -> dict[str, dict]:
    return {r["displayName"].lower(): r for r in roles}


def enrich_tasks(tasks: list[dict], role_index: dict) -> tuple[list[dict], int]:
    enriched: list[dict] = []
    matched = 0
    unmatched: set[str] = set()

    for task in tasks:
        role = role_index.get(task["min_role"].lower())
        enriched_task = dict(task)
        if role:
            enriched_task["role_id"]      = role["id"]
            enriched_task["is_privileged"] = role["isPrivileged"]
            matched += 1
        else:
            enriched_task["role_id"]      = None
            enriched_task["is_privileged"] = None
            unmatched.add(task["min_role"])
        enriched.append(enriched_task)

    for name in sorted(unmatched):
        print(f"  WARN: min_role not found in roles catalog: '{name}'")

    return enriched, matched


def main() -> None:
    roles_from_graph = load_json(GRAPH_ROLES_PATH)
    roles_from_docs  = load_json(DOCS_ROLES_PATH)
    tasks            = load_json(TASKS_PATH)

    # ── Shadow role detection + merge ──────────────────────────────────
    merged_roles, shadow_names = build_merged_roles(roles_from_graph, roles_from_docs)
    shadow_count = len(shadow_names)

    # ── Task enrichment (uses merged role index) ────────────────────────
    role_index = build_role_index(merged_roles)
    enriched_tasks, matched = enrich_tasks(tasks, role_index)

    # ── Write master.json ───────────────────────────────────────────────
    master = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "role_count":       len(merged_roles),
        "task_count":       len(tasks),
        "shadow_role_count": shadow_count,
        "roles":            merged_roles,
        "tasks":            enriched_tasks,
    }

    with MASTER_PATH.open("w", encoding="utf-8") as fh:
        json.dump(master, fh, indent=2, ensure_ascii=False)

    # ── Summary ─────────────────────────────────────────────────────────
    print(
        f"Enrichment complete: {len(merged_roles)} roles total, "
        f"{shadow_count} shadow role{'s' if shadow_count != 1 else ''} detected"
    )
    if shadow_names:
        print(f"Shadow roles: {shadow_names}")
    print(
        f"master.json built -- {len(merged_roles)} roles, {len(tasks)} tasks, "
        f"{matched} tasks matched to role IDs"
    )


if __name__ == "__main__":
    main()
