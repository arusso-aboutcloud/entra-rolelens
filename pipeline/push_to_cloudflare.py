"""
push_to_cloudflare.py

Pushes the enriched pipeline output to Cloudflare KV and D1.

Required environment variables:
  CLOUDFLARE_ACCOUNT_ID      — from Cloudflare dashboard
  CLOUDFLARE_API_TOKEN       — token with Workers KV + D1 write permissions
  CLOUDFLARE_KV_NAMESPACE_ID — KV namespace for runtime data
  D1_DATABASE_ID             — D1 database UUID for audit trail

Operations:
  1. KV: PUT master.json  (full roles+tasks payload for the Worker)
  2. KV: PUT pipeline_status  (lightweight health/freshness key)
  3. D1: UPSERT all roles into `roles` table
  4. D1: UPSERT all tasks into `tasks` table
  5. D1: INSERT new changelog entries into `role_changes` table
  6. D1: REBUILD `task_search` FTS table from tasks
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DATA_DIR = Path(__file__).parent.parent / "data"
MASTER_PATH = DATA_DIR / "master.json"
CHANGELOG_PATH = DATA_DIR / "changelog.json"

# ---------------------------------------------------------------------------
# Cloudflare API helpers
# ---------------------------------------------------------------------------

CF_BASE = "https://api.cloudflare.com/client/v4"


def get_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: environment variable {name} is not set", file=sys.stderr)
        sys.exit(1)
    return val


def cf_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def kv_put(session: requests.Session, account_id: str, namespace_id: str,
           token: str, key: str, value: str) -> None:
    """Write a string value to Cloudflare KV."""
    url = f"{CF_BASE}/accounts/{account_id}/storage/kv/namespaces/{namespace_id}/values/{key}"
    resp = session.put(
        url,
        headers={"Authorization": f"Bearer {token}"},
        data=value.encode("utf-8"),
    )
    print(f"  KV PUT {key!r}: HTTP {resp.status_code}")
    if not resp.ok:
        print(f"    Response: {resp.text}", file=sys.stderr)
        sys.exit(1)


def d1_query(session: requests.Session, account_id: str, database_id: str,
             token: str, sql: str, params: list | None = None) -> dict:
    """Execute a SQL statement against Cloudflare D1."""
    url = f"{CF_BASE}/accounts/{account_id}/d1/database/{database_id}/query"
    body: dict = {"sql": sql}
    if params:
        body["params"] = params
    resp = session.post(url, headers=cf_headers(token), json=body)
    if not resp.ok:
        print(f"  D1 query FAILED (HTTP {resp.status_code}): {resp.text}", file=sys.stderr)
        sys.exit(1)
    result = resp.json()
    # D1 API returns success:false even on HTTP 200 for SQL errors
    if not result.get("success"):
        print(f"  D1 query returned success:false: {json.dumps(result)}", file=sys.stderr)
        sys.exit(1)
    return result


def d1_batch(session: requests.Session, account_id: str, database_id: str,
             token: str, statements: list[dict]) -> None:
    """
    Execute multiple SQL statements in a single D1 batch request.
    Each statement: {"sql": "...", "params": [...]}
    """
    url = f"{CF_BASE}/accounts/{account_id}/d1/database/{database_id}/query"
    resp = session.post(url, headers=cf_headers(token), json=statements)
    print(f"  D1 batch ({len(statements)} stmts): HTTP {resp.status_code}")
    if not resp.ok:
        print(f"    Response: {resp.text}", file=sys.stderr)
        sys.exit(1)
    results = resp.json()
    # Batch response is a list; check each result
    if isinstance(results, list):
        for r in results:
            if not r.get("success"):
                print(f"  D1 batch statement failed: {json.dumps(r)}", file=sys.stderr)
                sys.exit(1)
    elif not results.get("success"):
        print(f"  D1 batch failed: {json.dumps(results)}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# Push operations
# ---------------------------------------------------------------------------

def push_kv(session, account_id, namespace_id, token, master: dict) -> None:
    print("Pushing to Cloudflare KV…")

    # 1. Full master payload
    kv_put(session, account_id, namespace_id, token,
           "master", json.dumps(master, ensure_ascii=False))

    # 2. Lightweight pipeline status key
    status = {
        "last_updated": date.today().isoformat(),
        "role_count": master["role_count"],
        "task_count": master["task_count"],
        "pipeline": "healthy",
    }
    kv_put(session, account_id, namespace_id, token,
           "pipeline_status", json.dumps(status))


def push_roles(session, account_id, database_id, token, roles: list[dict]) -> None:
    """UPSERT all roles into D1 `roles` table in batches of 25."""
    print(f"Upserting {len(roles)} roles into D1…")
    sql = """
        INSERT INTO roles (id, display_name, description, is_built_in, is_privileged, permissions)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          display_name  = excluded.display_name,
          description   = excluded.description,
          is_privileged = excluded.is_privileged,
          permissions   = excluded.permissions,
          updated_at    = CURRENT_TIMESTAMP
    """.strip()

    batch_size = 25
    total = 0
    for i in range(0, len(roles), batch_size):
        chunk = roles[i : i + batch_size]
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
            for r in chunk
        ]
        d1_batch(session, account_id, database_id, token, statements)
        total += len(chunk)

    print(f"  Upserted {total} roles")


def push_tasks(session, account_id, database_id, token, tasks: list[dict]) -> None:
    """UPSERT all tasks into D1 `tasks` table, then rebuild task_search."""
    print(f"Upserting {len(tasks)} tasks into D1…")
    upsert_sql = """
        INSERT INTO tasks (feature_area, task, min_role, role_id, alt_roles,
                           is_privileged, source_url)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(feature_area, task) DO UPDATE SET
          min_role      = excluded.min_role,
          role_id       = excluded.role_id,
          alt_roles     = excluded.alt_roles,
          is_privileged = excluded.is_privileged,
          source_url    = excluded.source_url
    """.strip()

    batch_size = 25
    total = 0
    for i in range(0, len(tasks), batch_size):
        chunk = tasks[i : i + batch_size]
        statements = [
            {
                "sql": upsert_sql,
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
            for t in chunk
        ]
        d1_batch(session, account_id, database_id, token, statements)
        total += len(chunk)

    print(f"  Upserted {total} tasks")

    # Rebuild FTS search table
    print("  Rebuilding task_search FTS table…")
    d1_query(session, account_id, database_id, token, "DELETE FROM task_search")
    insert_fts_sql = """
        INSERT INTO task_search (rowid, task, feature_area, min_role)
        SELECT id, task, feature_area, min_role FROM tasks
    """.strip()
    result = d1_query(session, account_id, database_id, token, insert_fts_sql)
    print(f"  task_search rebuilt: HTTP 200")


def push_changelog(session, account_id, database_id, token,
                   changelog: list[dict]) -> None:
    """Insert new changelog entries into D1 `role_changes` table."""
    if not changelog:
        print("No changelog entries to push")
        return

    # Only push entries dated today to avoid re-inserting historical rows
    today = date.today().isoformat()
    today_entries = [c for c in changelog if c.get("date") == today]
    print(f"Inserting {len(today_entries)} changelog entries for {today}…")

    if not today_entries:
        print("  No new entries for today")
        return

    sql = """
        INSERT OR IGNORE INTO role_changes
          (change_date, change_type, role_id, role_name, field, detail)
        VALUES (?, ?, ?, ?, ?, ?)
    """.strip()

    statements = [
        {
            "sql": sql,
            "params": [
                c["date"],
                c["change_type"],
                c.get("role_id", ""),
                c.get("role_name", ""),
                c.get("field", ""),
                c.get("detail", ""),
            ],
        }
        for c in today_entries
    ]

    batch_size = 25
    for i in range(0, len(statements), batch_size):
        d1_batch(session, account_id, database_id, token,
                 statements[i : i + batch_size])

    print(f"  Inserted {len(today_entries)} changelog entries")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    account_id   = get_env("CLOUDFLARE_ACCOUNT_ID")
    api_token    = get_env("CLOUDFLARE_API_TOKEN")
    namespace_id = get_env("CLOUDFLARE_KV_NAMESPACE_ID")
    database_id  = get_env("D1_DATABASE_ID")

    if not MASTER_PATH.exists():
        print(f"ERROR: {MASTER_PATH} not found — run enrich.py first", file=sys.stderr)
        sys.exit(1)

    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    changelog = json.loads(CHANGELOG_PATH.read_text(encoding="utf-8")) \
        if CHANGELOG_PATH.exists() else []

    session = requests.Session()

    push_kv(session, account_id, namespace_id, api_token, master)
    push_roles(session, account_id, database_id, api_token, master["roles"])
    push_tasks(session, account_id, database_id, api_token, master["tasks"])
    push_changelog(session, account_id, database_id, api_token, changelog)

    print("Push complete")


if __name__ == "__main__":
    main()
