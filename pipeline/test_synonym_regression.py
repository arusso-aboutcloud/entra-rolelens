"""
test_synonym_regression.py

Detects synonym expansions that make pill queries WORSE than no expansion.

For each pill in PILLS, runs two queries against the worker:
  1. Raw query (no synonym expansion)
  2. Expanded query (after pipeline.synonyms.expand_query)

Reports any pill where:
  - Expanded result != expected role, AND
  - Raw result == expected role

Such a case means expansion is actively hurting that pill.

Informational only — exit 0 always. The output is a signal for human
review, not a CI gate. Synonyms have legitimate trade-offs across queries.
"""

import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from synonyms import expand_query
from test_pills import EXPECTATIONS

WORKER_URL = "https://rolelens-worker.russo-antonio76.workers.dev"


def fetch_top_role(query: str) -> str | None:
    try:
        resp = requests.get(
            f"{WORKER_URL}/api/search",
            params={"q": query},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
        return results[0].get("min_role") if results else None
    except Exception as exc:
        print(f"  ERROR fetching {query!r}: {exc}", file=sys.stderr)
        return None


def main() -> int:
    print(f"Synonym expansion regression check — {len(EXPECTATIONS)} pills")
    print(f"Endpoint: {WORKER_URL}")
    print("=" * 90)

    expansion_helps   = []
    expansion_hurts   = []
    expansion_neutral = []
    both_wrong        = []

    for query, expected in EXPECTATIONS:
        raw_role = fetch_top_role(query)
        expanded = expand_query(query)
        exp_role = fetch_top_role(expanded) if expanded != query else raw_role

        raw_ok = raw_role == expected
        exp_ok = exp_role == expected

        if exp_ok and not raw_ok:
            expansion_helps.append((query, expected, raw_role))
        elif raw_ok and not exp_ok:
            expansion_hurts.append((query, expected, exp_role, expanded))
        elif raw_ok and exp_ok:
            expansion_neutral.append(query)
        else:
            both_wrong.append((query, expected, raw_role, exp_role))

    print(f"Expansion HELPS:   {len(expansion_helps)}")
    print(f"Expansion HURTS:   {len(expansion_hurts)}")
    print(f"Expansion NEUTRAL: {len(expansion_neutral)} (both correct)")
    print(f"Both WRONG:        {len(both_wrong)} (search engine issue, not synonym)")
    print()

    if expansion_hurts:
        print("WARNING — expansion makes these pills WORSE (review synonym entries):")
        for q, expected, got, expanded in expansion_hurts:
            print(f"  {q!r}")
            print(f"    expected:    {expected}")
            print(f"    raw result:  correct")
            print(f"    expanded to: {expanded!r}")
            print(f"    exp result:  {got}")
            print()

    if expansion_helps:
        print("OK — expansion correctly helps these pills:")
        for q, expected, got_raw in expansion_helps:
            print(f"  {q!r}  (raw -> {got_raw!r}, expanded -> correct)")
        print()

    if both_wrong:
        print("INFO — both raw AND expanded queries fail (search/corpus issue, not synonym):")
        for q, expected, raw, exp in both_wrong:
            print(f"  {q!r}  expected={expected!r}  raw->{raw!r}  expanded->{exp!r}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
