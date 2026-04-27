"""
compare_rankers.py — A/B comparison harness for BM25 vs keyword ranker.

Runs representative queries against the worker's debug=compare endpoint,
reports agreement/disagreement, and provides data for a promotion decision.
"""

import json
import os
import sys
from urllib.parse import quote

import requests

WORKER_URL = os.environ.get(
    "WORKER_URL",
    "https://rolelens-worker.russo-antonio76.workers.dev",
)

# 30 queries covering categorical breadth.
# 10 placeholder slots for user-added queries from real usage instinct.
COMPARISON_QUERIES = [
    # All 15 documented pills (matches test_pills.py expectations)
    "configure passkeys",
    "backup",
    "reset password",
    "reset user password",
    "manage conditional access",
    "configure SSPR",
    "manage AI agents",
    "manage groups",
    "manage administrative units",
    "manage Copilot governance",
    "GDAP relationships",
    "restore deleted users",
    "audit AI usage",
    "configure PIM",
    "approve access review",
    # Verb + noun (common patterns)
    "create user",
    "delete role",
    "view audit logs",
    "assign license",
    "invite guest user",
    # Acronyms (single-word queries)
    "FIDO2",
    "MFA",
    "PIM",
    "GSA",
    "SSPR",
    # Multi-word topic queries
    "named locations conditional access",
    "service principal management",
    "cross tenant access settings",
    "verifiable credentials",
    "self-service password reset configuration",

    # USER-ADDED QUERIES — Antonio adds 10 here based on real usage:
    # "<your query 1>",
    # ...
]


def run_compare(query: str) -> dict | None:
    url = f"{WORKER_URL}/api/search?q={quote(query)}&debug=compare"
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  ERROR for {query!r}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    print(f"A/B comparison: {len(COMPARISON_QUERIES)} queries")
    print(f"Endpoint: {WORKER_URL}")
    print("=" * 100)

    agree_count = 0
    disagree = []
    bm25_empty = []
    keyword_empty = []
    both_empty = 0
    errors = 0

    for query in COMPARISON_QUERIES:
        result = run_compare(query)
        if result is None:
            errors += 1
            continue

        kw_top   = result.get("keyword_ranker", {}).get("top_5", [])
        bm25_top = result.get("bm25_ranker",    {}).get("top_5", [])
        kw_role   = kw_top[0]["min_role"]   if kw_top   else None
        bm25_role = bm25_top[0]["min_role"] if bm25_top else None

        if kw_role == bm25_role and kw_role is not None:
            agree_count += 1
            print(f"  AGREE      {query!r:48s} -> {kw_role}")
        elif not kw_top and not bm25_top:
            both_empty += 1
            print(f"  BOTH EMPTY {query!r:48s}")
        elif not bm25_top:
            bm25_empty.append(query)
            print(f"  BM25 EMPTY {query!r:48s} (kw: {kw_role})")
        elif not kw_top:
            keyword_empty.append(query)
            print(f"  KW EMPTY   {query!r:48s} (bm25: {bm25_role})")
        else:
            disagree.append({
                "query":      query,
                "keyword":    kw_role,
                "bm25":       bm25_role,
                "kw_score":   kw_top[0].get("score"),
                "bm25_score": bm25_top[0].get("score"),
            })
            print(f"  DISAGREE   {query!r:48s}")
            print(f"       kw:   {kw_role} ({kw_top[0].get('score', 0):.1f})")
            print(f"       bm25: {bm25_role} ({bm25_top[0].get('score', 0):.1f})")

    print("=" * 100)
    print(f"Total queries:     {len(COMPARISON_QUERIES)}")
    print(f"Agree:             {agree_count}")
    print(f"Disagree:          {len(disagree)}")
    print(f"BM25 empty:        {len(bm25_empty)}")
    print(f"Keyword empty:     {len(keyword_empty)}")
    print(f"Both empty:        {both_empty}")
    print(f"Errors:            {errors}")

    if disagree:
        print("\nDisagreements (review carefully):")
        for d in disagree:
            print(f"  {d['query']!r}")
            print(f"    keyword: {d['keyword']} ({d['kw_score']:.1f})")
            print(f"    bm25:    {d['bm25']} ({d['bm25_score']:.1f})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
