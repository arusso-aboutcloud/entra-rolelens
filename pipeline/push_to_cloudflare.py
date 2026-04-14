"""
push_to_cloudflare.py

Pushes the enriched pipeline output to Cloudflare KV and D1.

Required environment variables:
  CLOUDFLARE_ACCOUNT_ID
  CLOUDFLARE_API_TOKEN
  CLOUDFLARE_KV_NAMESPACE_ID
  D1_DATABASE_ID

D1 REST API note: the /query endpoint accepts ONE statement per request
({sql, params} object). Statements are sent individually and parallelised
with a thread pool.
"""

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_PATH = DATA_DIR / "master.json"
CHANGELOG_PATH = DATA_DIR / "changelog.json"

CF_BASE = "https://api.cloudflare.com/client/v4"
D1_WORKERS = 8


def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


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
# D1 — one statement per request, parallelised
# ---------------------------------------------------------------------------

def d1_exec(account_id: str, database_id: str, token: str,
            sql: str, params: list | None = None) -> None:
    """Execute a single SQL statement against the D1 REST API."""
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
    result = resp.json()
    # D1 can return success:false even on HTTP 200
    results_list = result if isinstance(result, list) else [result]
    for r in results_list:
        if not r.get("success"):
            raise RuntimeError(f"D1 error: {json.dumps(r.get('errors', r))}")


def d1_run_many(account_id: str, database_id: str, token: str,
                statements: list[dict], label: str) -> None:
    """
    Execute a list of {"sql": ..., "params": [...]} dicts, each as a
    separate /query call, parallelised with a thread pool.
    """
    errors: list[str] = []
    completed = 0

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
# Push operations
# ---------------------------------------------------------------------------

def push_kv(account_id: str, namespace_id: str, token: str, master: dict) -> None:
    print("Pushing to Cloudflare KV...")
    kv_put(account_id, namespace_id, token,
           "master", json.dumps(master, ensure_ascii=False))
    status = {
        "last_updated": date.today().isoformat(),
        "role_count": master["role_count"],
        "task_count": master["task_count"],
        "pipeline": "healthy",
    }
    kv_put(account_id, namespace_id, token,
           "pipeline_status", json.dumps(status))


def push_roles(account_id: str, database_id: str, token: str,
               roles: list[dict]) -> None:
    print(f"Upserting {len(roles)} roles into D1...")
    sql = (
        "INSERT INTO roles "
        "(id, display_name, description, is_built_in, is_privileged, permissions) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name, "
        "description=excluded.description, "
        "is_privileged=excluded.is_privileged, "
        "permissions=excluded.permissions, "
        "updated_at=CURRENT_TIMESTAMP"
    )
    statements = [
        {
            "sql": sql,
            "params": [
                r["id"],
                r["displayName"],
                r.get("description", ""),
                1 if r.get("isBuiltIn") else 0,
                1 if r.get("isPrivileged") else 0,
                json.dumps(r.get("permissions", [])),
            ],
        }
        for r in roles
    ]
    d1_run_many(account_id, database_id, token, statements, "roles upsert")


def push_tasks(account_id: str, database_id: str, token: str,
               tasks: list[dict]) -> None:
    print(f"Upserting {len(tasks)} tasks into D1...")
    sql = (
        "INSERT INTO tasks "
        "(feature_area, task, min_role, role_id, alt_roles, is_privileged, source_url) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(feature_area, task) DO UPDATE SET "
        "min_role=excluded.min_role, "
        "role_id=excluded.role_id, "
        "alt_roles=excluded.alt_roles, "
        "is_privileged=excluded.is_privileged, "
        "source_url=excluded.source_url"
    )
    statements = [
        {
            "sql": sql,
            "params": [
                t["feature_area"],
                t["task"],
                t["min_role"],
                t.get("role_id"),
                json.dumps(t.get("alt_roles", [])),
                1 if t.get("is_privileged") else 0,
                t.get("source_url", ""),
            ],
        }
        for t in tasks
    ]
    d1_run_many(account_id, database_id, token, statements, "tasks upsert")

    # Rebuild FTS table (serial — order matters)
    print("  Rebuilding task_search FTS table...")
    d1_exec(account_id, database_id, token, "DELETE FROM task_search")
    d1_exec(
        account_id, database_id, token,
        "INSERT INTO task_search (rowid, task, feature_area, min_role) "
        "SELECT id, task, feature_area, min_role FROM tasks",
    )
    print("  task_search rebuilt: OK")


def push_changelog(account_id: str, database_id: str, token: str,
                   changelog: list[dict]) -> None:
    today = date.today().isoformat()
    today_entries = [c for c in changelog if c.get("date") == today]
    print(f"Inserting {len(today_entries)} changelog entries for {today}...")
    if not today_entries:
        return
    sql = (
        "INSERT OR IGNORE INTO role_changes "
        "(change_date, change_type, role_id, role_name, field, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)"
    )
    statements = [
        {
            "sql": sql,
            "params": [
                c["date"], c["change_type"],
                c.get("role_id", ""), c.get("role_name", ""),
                c.get("field") or "", c.get("detail", ""),
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

    push_kv(account_id, namespace_id, api_token, master)
    push_roles(account_id, database_id, api_token, master["roles"])
    push_tasks(account_id, database_id, api_token, master["tasks"])
    push_changelog(account_id, database_id, api_token, changelog)

    print("Push complete")


if __name__ == "__main__":
    main()
