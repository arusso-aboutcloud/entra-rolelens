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
import math
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
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


def extract_keywords_with_repetition(text: str) -> list[str]:
    """Like extract_keywords but preserves duplicates for term-frequency math.

    The existing extract_keywords() deduplicates via a set comprehension,
    which is correct for the existing keyword-index use case but loses
    information needed for BM25 term frequency. This sibling preserves
    repetition. Used only by compute_bm25_stats — existing callers
    continue using extract_keywords().
    """
    words = re.findall(r"[a-zA-Z]{3,}", text.lower())
    return [w for w in words if w not in STOP_WORDS]


def compute_bm25_stats(tasks: list[dict]) -> tuple[dict, dict, dict]:
    """Compute BM25 statistics for the task corpus.

    Args:
        tasks: list of {"id": int, "task_description": str, "feature_area": str}

    Returns:
        tf_per_task:  {task_id: {keyword: term_frequency}}
        doc_lengths:  {task_id: token_count}
        corpus: {
            "total_docs": int,
            "avg_doc_length": float,
            "idf_per_keyword": {keyword: idf_score},
        }

    IDF formula (smoothed Okapi BM25):
        IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1)
    """
    tf_per_task: dict = {}
    doc_lengths: dict = {}
    docs_containing: Counter = Counter()

    for task in tasks:
        task_id = task["id"]
        text = (task.get("task_description", "") + " " + task.get("feature_area", ""))
        tokens = extract_keywords_with_repetition(text)

        tf_counts = Counter(tokens)
        tf_per_task[task_id] = dict(tf_counts)
        doc_lengths[task_id] = len(tokens)

        for keyword in tf_counts.keys():
            docs_containing[keyword] += 1

    total_docs = len(tasks)
    avg_doc_length = (
        sum(doc_lengths.values()) / total_docs if total_docs > 0 else 0.0
    )

    idf_per_keyword: dict = {}
    for keyword, df in docs_containing.items():
        idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1)
        idf_per_keyword[keyword] = idf

    corpus = {
        "total_docs": total_docs,
        "avg_doc_length": avg_doc_length,
        "idf_per_keyword": idf_per_keyword,
    }

    return tf_per_task, doc_lengths, corpus


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
        "permissions, permission_count, first_seen, last_updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET "
        "display_name=excluded.display_name, "
        "description=excluded.description, "
        "is_privileged=excluded.is_privileged, "
        "permissions=excluded.permissions, "
        "permission_count=excluded.permission_count, "
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
                len(r.get("permissions", [])),
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
    in_scope     = [t for t in tasks if t.get("role_id")]
    out_of_scope = [t for t in tasks if not t.get("role_id") and t.get("out_of_scope")]
    dropped      = [t for t in tasks
                    if not t.get("role_id") and not t.get("out_of_scope")]
    if dropped:
        print(f"  Dropping {len(dropped)} tasks with unrecognised min_role "
              f"(investigate: {sorted({t['min_role'] for t in dropped})[:5]})")
    print(f"  In-scope tasks: {len(in_scope)} | Out-of-scope (Azure RBAC/non-role): {len(out_of_scope)}")

    valid = in_scope + out_of_scope
    print(f"Replacing {len(valid)} tasks in D1...")

    # Delete all existing tasks (task_search cascades)
    d1_exec(account_id, database_id, token, "DELETE FROM tasks")

    sql = (
        "INSERT INTO tasks "
        "(feature_area, task_description, min_role_id, alt_role_ids, "
        "source_url, last_verified, out_of_scope, out_of_scope_role) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
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
                t.get("role_id"),                       # may be None for out-of-scope
                json.dumps(resolve_guids(t.get("alt_roles", []))),
                t.get("source_url", ""),
                TODAY,
                t.get("out_of_scope"),
                t.get("out_of_scope_role"),
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
    Also computes and persists BM25 statistics (tf, idf, doc_length, corpus_stats).
    """
    print("  Building task_search keyword index (with BM25 stats)...")
    rows = d1_exec(
        account_id, database_id, token,
        "SELECT id, task_description, feature_area FROM tasks",
    )
    if not rows:
        print("  No tasks found — skipping task_search")
        return

    tf_per_task, doc_lengths, corpus = compute_bm25_stats(rows)

    sql = "INSERT INTO task_search (task_id, keyword, weight, tf, idf) VALUES (?, ?, ?, ?, ?)"
    statements = []
    for row in rows:
        task_id = row["id"]
        desc_kws = extract_keywords(row.get("task_description", ""))
        area_kws = extract_keywords(row.get("feature_area", ""))
        for kw in desc_kws:
            tf = tf_per_task.get(task_id, {}).get(kw, 1.0)
            idf = corpus["idf_per_keyword"].get(kw, 0.0)
            statements.append({"sql": sql, "params": [task_id, kw, 1.0, tf, idf]})
        for kw in area_kws:
            if kw not in set(desc_kws):
                tf = tf_per_task.get(task_id, {}).get(kw, 1.0)
                idf = corpus["idf_per_keyword"].get(kw, 0.0)
                statements.append({"sql": sql, "params": [task_id, kw, 0.5, tf, idf]})

    d1_run_many(account_id, database_id, token, statements, "task_search insert")
    print(f"  Indexed {len(rows)} tasks → {len(statements)} keyword entries")

    update_sql = "UPDATE tasks SET doc_length = ? WHERE id = ?"
    update_statements = [
        {"sql": update_sql, "params": [doc_lengths.get(row["id"], 0), row["id"]]}
        for row in rows
    ]
    d1_run_many(account_id, database_id, token, update_statements, "doc_length update")

    stats_sql = "INSERT OR REPLACE INTO corpus_stats (key, value) VALUES (?, ?)"
    stats_statements = [
        {"sql": stats_sql, "params": ["total_docs", corpus["total_docs"]]},
        {"sql": stats_sql, "params": ["avg_doc_length", corpus["avg_doc_length"]]},
    ]
    d1_run_many(account_id, database_id, token, stats_statements, "corpus_stats")

    print(f"  BM25 stats: {len(corpus['idf_per_keyword'])} unique keywords, "
          f"avg_doc_length={corpus['avg_doc_length']:.2f}")


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
# README What's New
# ---------------------------------------------------------------------------

def update_readme_whats_new(changelog_path: Path, readme_path: Path) -> None:
    if not changelog_path.exists():
        return
    with open(changelog_path, encoding="utf-8") as f:
        changelog = json.load(f)

    cutoff = (datetime.utcnow() - timedelta(days=30)).date().isoformat()
    recent = [c for c in changelog if c.get("date", "") >= cutoff]

    if not recent:
        return

    lines = [""]
    for change in recent[:10]:
        emoji = {"ADDED": "✅", "REMOVED": "❌", "MODIFIED": "🔄"}.get(
            change.get("change_type", "").upper(), "•"
        )
        lines.append(
            f"- {emoji} **{change['role_name']}** — "
            f"{change['change_type'].lower()} "
            f"({change['date']})"
        )
    lines.append("")

    new_section = "\n".join(lines)

    with open(readme_path, encoding="utf-8") as f:
        readme = f.read()

    updated = re.sub(
        r"<!-- WHATS_NEW_START -->.*?<!-- WHATS_NEW_END -->",
        f"<!-- WHATS_NEW_START -->{new_section}<!-- WHATS_NEW_END -->",
        readme,
        flags=re.DOTALL,
    )

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(updated)

    print("  README What's New section updated")


# ---------------------------------------------------------------------------
# README Data Quality
# ---------------------------------------------------------------------------

def update_readme_data_quality(master_path: Path, readme_path: Path) -> None:
    if not master_path.exists():
        return
    with open(master_path, encoding="utf-8") as f:
        master = json.load(f)

    role_count    = master.get("role_count", 0)
    task_count    = master.get("task_count", 0)
    shadow_count  = master.get("shadow_role_count", 0)
    partial_count = master.get("partial_role_count", 0)

    new_section = (
        f"\n"
        f"- **{role_count}+ built-in roles** - covers all named "
        f"Entra ID built-in roles including preview roles\n"
        f"- **{task_count} task mappings** - sourced from "
        f"Microsoft's official documentation and community contributions\n"
        f"- **{shadow_count} unlisted roles** - present in the "
        f"Graph API but not yet in Microsoft's public documentation\n"
        f"- **{partial_count} partially documented roles** - in "
        f"roles reference but missing from task mappings\n"
        f"- **Nightly diff** - every permission change Microsoft "
        f"makes is logged to the role_changes D1 table\n"
        f"- **Self-healing pipeline** - validation gate prevents "
        f"bad data reaching production\n"
    )

    with open(readme_path, "r", encoding="utf-8") as f:
        readme = f.read()

    start_marker = "## Data quality"
    end_marker   = "\n## "

    start_idx = readme.find(start_marker)
    if start_idx == -1:
        print("WARNING: Data quality section not found in README")
        return

    end_idx = readme.find(end_marker, start_idx + len(start_marker))
    if end_idx == -1:
        end_idx = len(readme)

    new_readme = readme[:start_idx] + start_marker + new_section + readme[end_idx:]

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print(
        f"  README Data quality updated: {role_count} roles, "
        f"{task_count} tasks, {shadow_count} unlisted"
    )


# ---------------------------------------------------------------------------
# README Sentrux quality -- backed by SVG dashboard
# ---------------------------------------------------------------------------

def update_readme_sentrux(readme_path: Path) -> None:
    """No-op. The README Sentrux block now embeds an SVG dashboard.

    The SVG is regenerated nightly by:
      pipeline/sentrux_parser.py        (gate stdout -> quality.json)
      pipeline/sentrux_dashboard_svg.py (quality.json -> assets/quality-dashboard.svg)

    Both run in the workflow Sentrux step before push_to_cloudflare.py.
    The SVG is committed by the existing workflow commit step.
    """
    pass


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
    readme_path = Path(__file__).parent.parent / "README.md"
    update_readme_whats_new(CHANGELOG_PATH, readme_path)
    update_readme_data_quality(MASTER_PATH, readme_path)
    update_readme_sentrux(readme_path)

    print("Push complete")


if __name__ == "__main__":
    main()
