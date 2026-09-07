"""
generate_scenarios.py

For each ADDED changelog entry, computes deterministic "role facts" (is it
privileged, is it PIM-eligible, does it support administrative-unit-scoped
assignment, where is it configured) and -- for entries missing a "scenario"
-- calls Cloudflare Workers AI for a short real-world narrative that can
reference those facts. Rendered in the frontend's What's New panel: the
verified facts as badges (always accurate, since they're not AI-generated),
the narrative labeled "AI-generated" alongside them.

Role facts are recomputed for every ADDED entry on every run (pure local
computation, no network cost) so historical entries stay current too, not
just newly-added ones. Scenario generation stays idempotent/best-effort --
only entries missing "scenario" are (re)processed, so a failed AI call is
retried automatically next run without duplicating work, and a missing
scenario just means the panel falls back to the facts + description only.
Costs effectively nothing -- typically 0-3 new roles a month against
Workers AI's 10,000 free neurons/day.
"""

import json
import os
import sys
from pathlib import Path

import requests

DATA_DIR = Path(__file__).parent.parent / "data"
CHANGELOG_PATH = DATA_DIR / "changelog.json"
# master.json (enriched, union of live Graph API + docs) rather than the
# docs-only roles.json -- keeps role_facts/scenarios based on the same
# authoritative permission set diff_roles.py now diffs and push_to_cloudflare.py
# pushes live, instead of the docs snapshot that can lag Microsoft's live grants.
MASTER_PATH = DATA_DIR / "master.json"

CF_BASE = "https://api.cloudflare.com/client/v4"
MODEL = "@cf/meta/llama-3.3-70b-instruct-fp8-fast"

# Microsoft's exact, published list of built-in roles that support
# administrative-unit-scoped assignment (verified against
# learn.microsoft.com/entra/identity/role-based-access-control/
# administrative-units-role-assignment, updated 2026-02-19). This is NOT a
# guessable pattern -- most roles are tenant-scope only -- so it's hardcoded
# rather than left for the AI to infer.
AU_SCOPABLE_ROLES = frozenset({
    "Authentication Administrator",
    "Attribute Assignment Administrator",
    "Attribute Assignment Reader",
    "Cloud Device Administrator",
    "Groups Administrator",
    "Helpdesk Administrator",
    "License Administrator",
    "Password Administrator",
    "Printer Administrator",
    "Privileged Authentication Administrator",
    "SharePoint Administrator",
    "Teams Administrator",
    "Teams Devices Administrator",
    "User Administrator",
})


def compute_role_facts(role: dict) -> dict:
    """Deterministic, verified facts about a role -- no AI involved, so
    these are never wrong the way a generated sentence could be."""
    is_workload_role = len(role.get("permissions", [])) == 0
    return {
        "is_privileged": bool(role.get("isPrivileged")),
        # Workload roles (e.g. Purview content roles) grant zero Entra
        # directory actions and are governed in their own service portal,
        # not Entra RBAC -- so Entra PIM/admin-unit scoping don't apply.
        "is_workload_role": is_workload_role,
        "pim_eligible": not is_workload_role,
        "au_scopable": role.get("displayName") in AU_SCOPABLE_ROLES,
        "configured_via": (
            "its own service portal (not the Entra admin center)" if is_workload_role
            else "Microsoft Entra admin center (Roles & admins) or Microsoft Graph"
        ),
    }


def generate_scenario(role: dict, facts: dict, account_id: str, token: str) -> str | None:
    perms = role.get("permissions", [])
    perms_text = ", ".join(perms) if perms else "(none -- this role is governed outside Entra)"
    facts_text = (
        f"Privileged role: {'yes' if facts['is_privileged'] else 'no'}. "
        f"PIM-eligible for time-bound activation: {'yes' if facts['pim_eligible'] else 'not applicable -- governed outside Entra RBAC'}. "
        f"Administrative-unit-scoped assignment: {'supported' if facts['au_scopable'] else 'not supported -- tenant-wide only'}. "
        f"Configured via: {facts['configured_via']}."
    )
    prompt = (
        f"Role: {role['displayName']}\n"
        f"Official Microsoft description: {role.get('description', '')}\n"
        f"Exact Microsoft Entra permissions this role grants: {perms_text}\n"
        f"Verified facts about this role (state these accurately if you reference them -- do not "
        f"contradict or guess beyond them): {facts_text}\n\n"
        "Write one or two sentences describing a concrete, technically specific scenario in which "
        "a Microsoft Entra (Azure AD) tenant administrator would assign this role to someone on "
        "their IT, security, or compliance team. Ground the scenario in what the permissions above "
        "actually let the person do -- name a real operational trigger (e.g. an active security "
        "incident, a compliance audit, an access review, an AI/agent deployment, a Purview "
        "eDiscovery case), not a generic 'IT support' or vacation-coverage story. The role name is "
        "Microsoft's internal label for a permission set, not a job title -- never invent an "
        "unrelated real-world job from it (e.g. do not read \"Writer\" as a marketing content "
        "writer). Plain prose, no markdown, no preamble, do not restate the role name verbatim, do "
        "not restate the verified facts verbatim (they're shown separately) -- only weave them in "
        "naturally if it helps the scenario (e.g. 'because this is a privileged, PIM-eligible role...')."
    )
    url = f"{CF_BASE}/accounts/{account_id}/ai/run/{MODEL}"
    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"messages": [{"role": "user", "content": prompt}]},
            timeout=20,
        )
    except requests.RequestException as exc:
        print(f"  WARN: Workers AI request failed for {role['displayName']!r}: {exc}",
              file=sys.stderr)
        return None
    if not resp.ok:
        print(f"  WARN: Workers AI HTTP {resp.status_code} for {role['displayName']!r}: "
              f"{resp.text[:200]}", file=sys.stderr)
        return None
    try:
        text = resp.json().get("result", {}).get("response", "").strip()
    except (ValueError, AttributeError):
        return None
    return text or None


def main() -> None:
    if not CHANGELOG_PATH.exists() or not MASTER_PATH.exists():
        print("No changelog.json/master.json yet -- skipping scenario generation")
        return

    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    token = os.environ.get("CLOUDFLARE_API_TOKEN")

    changelog = json.loads(CHANGELOG_PATH.read_text(encoding="utf-8"))
    master = json.loads(MASTER_PATH.read_text(encoding="utf-8"))
    roles_by_id = {r["id"]: r for r in master.get("roles", master)}

    changed = False
    generated = 0
    facts_updated = 0
    for entry in changelog:
        if entry.get("change_type") != "ADDED":
            continue
        role = roles_by_id.get(entry.get("role_id"))
        if not role:
            continue

        # Deterministic, zero-cost -- recomputed every run so historical
        # entries stay current too, not just newly-added ones.
        facts = compute_role_facts(role)
        if entry.get("role_facts") != facts:
            entry["role_facts"] = facts
            changed = True
            facts_updated += 1

        if "scenario" in entry or not account_id or not token:
            continue
        scenario = generate_scenario(role, facts, account_id, token)
        if scenario:
            entry["scenario"] = scenario
            changed = True
            generated += 1
            print(f"  Generated scenario for {role['displayName']!r}")

    if not account_id or not token:
        print("CLOUDFLARE_ACCOUNT_ID/CLOUDFLARE_API_TOKEN not set -- skipped AI scenario generation "
              "(role facts still computed)")

    if changed:
        CHANGELOG_PATH.write_text(
            json.dumps(changelog, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    print(f"Scenario generation complete -- {generated} scenario(s) generated, "
          f"{facts_updated} role_facts entries updated")


if __name__ == "__main__":
    main()
