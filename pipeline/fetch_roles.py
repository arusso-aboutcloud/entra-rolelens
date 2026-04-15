"""
fetch_roles.py

Fetches all Entra ID built-in role definitions from:
1. Microsoft's public entra-docs GitHub repository (no auth required)
2. Microsoft Graph API (requires OIDC authentication via GitHub Actions)
"""

import json
import re
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from azure.identity import DefaultAzureCredential

# Constants for GitHub Scraping
BASE_URL = (
    "https://raw.githubusercontent.com/MicrosoftDocs/entra-docs/main"
    "/docs/identity/role-based-access-control"
)
INDEX_URL = f"{BASE_URL}/permissions-reference.md"
INCLUDE_URL = BASE_URL + "/includes/{slug}.md"

# Output Paths
DATA_DIR = Path(__file__).parent.parent / "data"
ROLES_JSON_PATH = DATA_DIR / "roles.json"
GRAPH_RAW_PATH = DATA_DIR / "roles_graph_raw.json"

PRIVILEGED_MARKER = "privileged-label.png"
MAX_WORKERS = 8


class FetchError(Exception):
    pass


def get(url: str) -> str:
    try:
        resp = requests.get(url, timeout=30, headers={"Accept": "text/plain"})
    except requests.RequestException as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc
    if resp.status_code == 404:
        return ""
    if not resp.ok:
        raise FetchError(f"HTTP {resp.status_code} fetching {url}")
    return resp.text


def fetch_graph_roles():
    """Fetches live role definitions from Microsoft Graph using OIDC/Federated Identity."""
    print("Connecting to Microsoft Graph via OIDC...")
    credential = DefaultAzureCredential()
    
    try:
        # Get token for Graph API
        token = credential.get_token("https://graph.microsoft.com/.default")
        headers = {
            'Authorization': f'Bearer {token.token}',
            'Content-Type': 'application/json'
        }

        # Fetch from v1.0 endpoint
        url = "https://graph.microsoft.com/v1.0/roleManagement/directory/roleDefinitions"
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        graph_roles = response.json().get('value', [])
        print(f"✅ Successfully fetched {len(graph_roles)} roles from live Graph API.")
        
        # Save raw graph data for debugging/comparison
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with GRAPH_RAW_PATH.open("w", encoding="utf-8") as f:
            json.dump(graph_roles, f, indent=2, ensure_ascii=False)
            
        return graph_roles

    except Exception as e:
        print(f"⚠️ Warning: Could not fetch from Graph API: {e}")
        return []


def parse_roles_table(md: str) -> list[dict]:
    roles = []
    row_re = re.compile(
        r"^\s*>\s*\|\s*"
        r"\[([^\]]+)\]\(#([^)]+)\)"
        r"\s*\|([^|]*)\|"
        r"([^|]+)\|",
        re.MULTILINE,
    )
    for m in row_re.finditer(md):
        display_name = m.group(1).strip()
        slug = m.group(2).strip()
        raw_desc = m.group(3)
        template_id = m.group(4).strip()

        if template_id.lower() == "template id":
            continue
        if not re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            template_id,
            re.I,
        ):
            continue

        is_privileged = PRIVILEGED_MARKER in raw_desc

        desc = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw_desc)
        desc = re.sub(r"\[[^\]]*\]\([^)]*\)", "", desc)
        desc = re.sub(r"<br\s*/?>", " ", desc, flags=re.I)
        desc = " ".join(desc.split())

        roles.append({
            "id": template_id,
            "displayName": display_name,
            "description": desc,
            "isBuiltIn": True,
            "isPrivileged": is_privileged,
            "_slug": slug,
        })
    return roles


def parse_permissions(md: str) -> list[str]:
    perm_re = re.compile(
        r"^\s*>\s*\|\s*(microsoft\.[A-Za-z0-9_./]+)\s*\|",
        re.MULTILINE,
    )
    return [m.group(1) for m in perm_re.finditer(md)]


def fetch_permissions(slug: str) -> list[str]:
    url = INCLUDE_URL.format(slug=slug)
    md = get(url)
    if not md:
        print(f"  WARN: no include file for '{slug}' — permissions will be empty",
              file=sys.stderr)
        return []
    return parse_permissions(md)


def enrich_role(role: dict) -> dict:
    slug = role.pop("_slug")
    permissions = fetch_permissions(slug)
    return {**role, "permissions": permissions}


def main() -> None:
    # 1. Fetch from Microsoft Graph API (The Live Source)
    graph_roles = fetch_graph_roles()

    # 2. Fetch from GitHub Docs (The Documentation Source)
    print("Fetching Entra ID role index from MicrosoftDocs/entra-docs...")
    index_md = get(INDEX_URL)
    if not index_md:
        print("ERROR: could not fetch permissions-reference.md", file=sys.stderr)
        sys.exit(1)

    roles = parse_roles_table(index_md)
    if not roles:
        print("ERROR: parsed 0 roles -- markdown format may have changed", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(roles)} built-in roles in docs -- fetching per-role permissions...")

    enriched: list[dict] = []
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(enrich_role, r): r["displayName"] for r in roles}
        for i, future in enumerate(as_completed(futures), 1):
            name = futures[future]
            try:
                result = future.result()
                enriched.append(result)
            except FetchError as exc:
                errors.append(f"{name}: {exc}")
            if i % 25 == 0 or i == len(roles):
                print(f"  {i}/{len(roles)} roles enriched")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)

    enriched.sort(key=lambda r: r["displayName"])

    # Final Stats
    privileged_count = sum(1 for r in enriched if r["isPrivileged"])
    print(f"Successfully processed {len(enriched)} roles ({privileged_count} privileged)")

    # Save final roles.json
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with ROLES_JSON_PATH.open("w", encoding="utf-8") as fh:
        json.dump(enriched, fh, indent=2, ensure_ascii=False)

    print(f"Written -> {ROLES_JSON_PATH}")


if __name__ == "__main__":
    main()
