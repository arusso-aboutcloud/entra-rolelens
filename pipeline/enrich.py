"""
enrich.py

Cross-references roles.json and tasks.json to produce master.json.

For each task, looks up the min_role name in the roles catalog and injects:
  - role_id        (str | null)   the role's template GUID
  - is_privileged  (bool | null)  whether that role is marked privileged

Writes data/master.json with the combined dataset.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROLES_PATH = Path(__file__).parent.parent / "data" / "roles.json"
TASKS_PATH = Path(__file__).parent.parent / "data" / "tasks.json"
MASTER_PATH = Path(__file__).parent.parent / "data" / "master.json"


def load_json(path: Path) -> object:
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        sys.exit(1)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_role_index(roles: list[dict]) -> dict[str, dict]:
    return {r["displayName"].lower(): r for r in roles}


def enrich_tasks(tasks: list[dict], role_index: dict) -> tuple[list[dict], int]:
    enriched = []
    matched = 0
    unmatched: set[str] = set()

    for task in tasks:
        role = role_index.get(task["min_role"].lower())
        enriched_task = dict(task)
        if role:
            enriched_task["role_id"] = role["id"]
            enriched_task["is_privileged"] = role["isPrivileged"]
            matched += 1
        else:
            enriched_task["role_id"] = None
            enriched_task["is_privileged"] = None
            unmatched.add(task["min_role"])
        enriched.append(enriched_task)

    for name in sorted(unmatched):
        print(f"  WARN: min_role not found in roles catalog: '{name}'")

    return enriched, matched


def main() -> None:
    roles = load_json(ROLES_PATH)
    tasks = load_json(TASKS_PATH)

    role_index = build_role_index(roles)
    enriched_tasks, matched = enrich_tasks(tasks, role_index)

    master = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "role_count": len(roles),
        "task_count": len(tasks),
        "roles": roles,
        "tasks": enriched_tasks,
    }

    with MASTER_PATH.open("w", encoding="utf-8") as fh:
        json.dump(master, fh, indent=2, ensure_ascii=False)

    print(
        f"master.json built -- {len(roles)} roles, {len(tasks)} tasks, "
        f"{matched} tasks matched to role IDs"
    )


if __name__ == "__main__":
    main()
