"""
push_to_cloudflare.py

Pushes the enriched pipeline output to Cloudflare KV and D1.

Required environment variables:
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_KV_NAMESPACE_ID
  D1_DATABASE_ID

Actual D1 schema (queried from live DB):
  roles(id, display_name, description, is_privileged, is_built_in,
        permissions, first_seen, last_updated)
  tasks(id AUTOINCREMENT, feature_area, task_description, min_role_id,
        alt_role_ids, notes, source_url, last_verified)
  role_changes(id AUTOINCREMENT, change_date, change_type, role_id,
               role_name, field_changed, old_value, new_value)
  task_search(task_id FK->tasks.id, keyword, weight)
"""

import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_PATH = DATA_DIR / "master.json"
CHANGELOG_PATH = DATA_DIR / "changelog.json"

CF_BASE = "https://api.cloudflare.com/client/v4"
D1_WORKERS = 8

TODAY = date.today().isoformat()
NOW = datetime.now(timezone.utc).isoformat()

STOP_WORDS = {
    "a", "an", "the", "is", "are", "in", "on", "at", "to", "for", "of",
    "or", "and", "but", "not", "with", "by", "from", "that", "this", "all",
    "as", "be", "can", "do", "has", "have", "it", "its", "no", "so", "up",
    "was", "will", "if", "how", "when", "where", "which", "who", "you",
    "your", "via", "using", "into", "its", "their", "any", "each",
}


# ---------------------------------------------------------------------------
# Env / helpers
# ---------------------------------------------------------------------------

def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: env var {name} not set", file=sys.stderr)
        sys.exit(1)
    return val


def extract_keywords(text: str) -> list[str]:
    """Return deduplicated lowercase words, stop-words removed."""
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return list({w for w in words if w not in STOP_WORDS})


# ---------------------------------------------------------------------------
# KV
# ---------------------------------------------------------------------------

def kv_put(account_id: str, namespace_id: str, token: str,
           key: str, value: str) -> None:
    url = (f"{CF_BASE}/accounts/{account_id}/storage/kv"
           f"/namespaces/{namespace_id}/values/{key}")
    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data=value.encode("utf-8"),
        timeout=30,
    )
    print(f"  KV PUT {key!r}: HTTP {resp.status_code}")
    if not resp.ok:
        print(f"    {resp.text}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# D1 — one statement per /query call
# ---------------------------------------------------------------------------

def d1_exec(account_id: str, database_id: str, token: str,
            sql: str, params: list | None = None) -> list[dict]:
    """Execute one SQL statement; return result rows.

    Cloudflare D1 REST response shape:
      {"success": true, "result": [{"success": true, "results": [...rows...], "meta": {...}}]}
    """
    url = f"{CF_BASE}/accounts/{account_id}/d1/database/{database_id}/query"
    body: dict = {"sql": sql}
    if params:
        body["params"] = params
    resp = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    if not resp.ok:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text}")
    data = resp.json()
    # Top-level success check
    if not data.get("success"):
        raise RuntimeError(f"D1 error: {json.dumps(data.get('errors', data))}")
    # Navigate to inner result set
    inner = data.get("result", [])
    if not inner:
        return []
    first = inner[0]
    if not first.get("success"):
        raise RuntimeError(f"D1 error: {json.dumps(first.get('errors', first))}")
    return first.get("results", [])


def d1_run_many(account_id: str, database_id: str, token: str,
                statements: list[dict], label: str) -> None:
    """Run a list of {sql, params} dicts, one per /query call, parallelised."""
    errors: list[str] = []

    def run_one(stmt: dict) -> None:
        d1_exec(account_id, database_id, token,
                stmt["sql"], stmt.get("params"))

    with ThreadPoolExecutor(max_workers=D1_WORKERS) as pool:
        futures = {pool.submit(run_one, s): i for i, s in enumerate(statements)}
        for future in as_completed(futures):
            try:
                future.result()
            except RuntimeError as exc:
                errors.append(str(exc))

    print(f"  D1 {label}: {len(statements)} stmts, {len(errors)} errors")
    if errors:
        for e in errors[:5]:
            print(f"    {e}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Push: KV
# ---------------------------------------------------------------------------

def push_kv(account_id: str, namespace_id: str, token: str,
            master: dict) -> None:
    print("Pushing to Cloudflare KV...")
    kv_put(account_id, namespace_id, token,
           "master", json.dumps(master, ensure_ascii=False))
    kv_put(account_id, namespace_id, token,
           "pipeline_status", json.dumps({
               "last_updated": TODAY,
               "role_count": master["role_count"],
               "task_count": master["task_count"],
               "shadow_role_count": master.get("shadow_role_count", 0),
               "pipeline": "healthy",
           }))


# ---------------------------------------------------------------------------
# Push: roles
# ---------------------------------------------------------------------------

def push_roles(account_id: str, database_id: str, token: str,
               roles: list[dict]) -> None:
    print(f"Upserting {len(roles)} roles into D1...")
    sql = (
        "INSERT INTO roles "
        "(id, display_name, description, is_privileged, is_built_in, "
        "permissions, first_seen, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name, "
        "description=excluded.description, "
        "is_privileged=excluded.is_privileged, "
        "permissions=excluded.permissions, "
        "last_updated=excluded.last_updated"
        # first_seen is intentionally NOT updated — preserved from first insert
    )
    statements = [
        {
            "sql": sql,
            "params": [
                r["id"],
                r["displayName"],
                r.get("description", ""),
                1 if r.get("isPrivileged") else 0,
                1 if r.get("isBuiltIn", True) else 0,
                json.dumps(r.get("permissions", [])),
                TODAY,   # first_seen — ignored on update by ON CONFLICT clause
                NOW,     # last_updated — always refreshed
            ],
        }
        for r in roles
    ]
    d1_run_many(account_id, database_id, token, statements, "roles upsert")


# ---------------------------------------------------------------------------
# Push: tasks
# ---------------------------------------------------------------------------

def push_tasks(account_id: str, database_id: str, token: str,
               tasks: list[dict], role_index: dict[str, str]) -> None:
    """
    role_index: displayName.lower() -> id (GUID)
    Only tasks with a resolvable min_role_id are inserted (NOT NULL constraint).
    """
    valid = [t for t in tasks if t.get("role_id")]
    skipped = len(tasks) - len(valid)
    if skipped:
        print(f"  Skipping {skipped} tasks with no role_id (non-built-in min_role)")

    print(f"Replacing {len(valid)} tasks in D1...")

    # Delete all existing tasks (task_search cascades)
    d1_exec(account_id, database_id, token, "DELETE FROM tasks")

    sql = (
        "INSERT INTO tasks "
        "(feature_area, task_description, min_role_id, alt_role_ids, "
        "source_url, last_verified) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )

    def resolve_guids(names: list[str]) -> list[str]:
        return [role_index[n.lower()] for n in names
                if n.lower() in role_index]

    statements = [
        {
            "sql": sql,
            "params": [
                t["feature_area"],
                t["task"],                              # our field name
                t["role_id"],                           # already a GUID
                json.dumps(resolve_guids(t.get("alt_roles", []))),
                t.get("source_url", ""),
                TODAY,
            ],
        }
        for t in valid
    ]
    d1_run_many(account_id, database_id, token, statements, "tasks insert")


# ---------------------------------------------------------------------------
# Push: task_search keyword index
# ---------------------------------------------------------------------------

def push_task_search(account_id: str, database_id: str, token: str) -> None:
    """
    Build keyword index from tasks already in D1.
    Queries tasks table, extracts keywords, bulk-inserts into task_search.
    """
    print("  Building task_search keyword index...")
    rows = d1_exec(
        account_id, database_id, token,
        "SELECT id, task_description, feature_area FROM tasks",
    )
    if not rows:
        print("  No tasks found — skipping task_search")
        return

    sql = "INSERT INTO task_search (task_id, keyword, weight) VALUES (?, ?, ?)"
    statements = []
    for row in rows:
        task_id = row["id"]
        desc_kws = extract_keywords(row.get("task_description", ""))
        area_kws = extract_keywords(row.get("feature_area", ""))
        for kw in desc_kws:
            statements.append({"sql": sql, "params": [task_id, kw, 1.0]})
        for kw in area_kws:
            if kw not in set(desc_kws):
                statements.append({"sql": sql, "params": [task_id, kw, 0.5]})

    d1_run_many(account_id, database_id, token, statements, "task_search insert")
    print(f"  Indexed {len(rows)} tasks → {len(statements)} keyword entries")


# ---------------------------------------------------------------------------
# Push: changelog
# ---------------------------------------------------------------------------

def push_changelog(account_id: str, database_id: str, token: str,
                   changelog: list[dict]) -> None:
    today_entries = [c for c in changelog if c.get("date") == TODAY]
    print(f"Inserting {len(today_entries)} changelog entries for {TODAY}...")
    if not today_entries:
        return

    sql = (
        "INSERT OR IGNORE INTO role_changes "
        "(change_date, change_type, role_id, role_name, field_changed, "
        "old_value, new_value) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)"
    )
    statements = [
        {
            "sql": sql,
            "params": [
                c["date"],
                c["change_type"].lower(),   # schema expects lowercase
                c.get("role_id", ""),
                c.get("role_name", ""),
                c.get("field"),             # null for ADDED/REMOVED
                None,                       # old_value — diff detail is in new_value
                c.get("detail", ""),
            ],
        }
        for c in today_entries
    ]
    d1_run_many(account_id, database_id, token, statements, "changelog insert")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    account_id   = get_env("CLOUDFLARE_ACCOUNT_ID")
    api_token    = get_env("CLOUDFLARE_API_TOKEN")
    namespace_id = get_env("CLOUDFLARE_KV_NAMESPACE_ID")
    database_id  = get_env("D1_DATABASE_ID")

    if not MASTER_PATH.exists():
        print(f"ERROR: {MASTER_PATH} not found -- run enrich.py first", file=sys.stderr)
        sys.exit(1)

    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    changelog = (
        json.loads(CHANGELOG_PATH.read_text(encoding="utf-8"))
        if CHANGELOG_PATH.exists() else []
    )

    # Build name->id index for alt_role_id resolution
    role_index: dict[str, str] = {
        r["displayName"].lower(): r["id"]
        for r in master["roles"]
    }

    push_kv(account_id, namespace_id, api_token, master)
    push_roles(account_id, database_id, api_token, master["roles"])
    push_tasks(account_id, database_id, api_token, master["tasks"], role_index)
    push_task_search(account_id, database_id, api_token)
    push_changelog(account_id, database_id, api_token, changelog)

    print("Push complete")


if __name__ == "__main__":
    main()
