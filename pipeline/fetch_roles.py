"""
fetch_roles.py

Fetches all Entra ID built-in role definitions from Microsoft's public
entra-docs GitHub repository — no authentication required.

Data source: github.com/MicrosoftDocs/entra-docs  (public, MIT-licensed docs)
  permissions-reference.md   → role list, template IDs, isPrivileged flag
  includes/{slug}.md         → per-role allowedResourceActions

The Microsoft Graph API (/roleDefinitions) requires a bearer token even for
read-only access, so this script uses the publicly mirrored documentation
instead, which Microsoft regenerates from the same internal source.
"""

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

BASE_URL = (
    "https://raw.githubusercontent.com/MicrosoftDocs/entra-docs/main"
    "/docs/identity/role-based-access-control"
)
INDEX_URL = f"{BASE_URL}/permissions-reference.md"
INCLUDE_URL = BASE_URL + "/includes/{slug}.md"
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "roles.json"

PRIVILEGED_MARKER = "privileged-label.png"
MAX_WORKERS = 8


class FetchError(Exception):
    pass


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def get(url: str) -> str:
    """Fetch URL text; raise FetchError on non-2xx."""
    try:
        resp = requests.get(url, timeout=30, headers={"Accept": "text/plain"})
    except requests.RequestException as exc:
        raise FetchError(f"Network error fetching {url}: {exc}") from exc

    if resp.status_code == 404:
        return ""  # caller decides whether 404 is fatal
    if not resp.ok:
        raise FetchError(f"HTTP {resp.status_code} fetching {url}")
    return resp.text


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_roles_table(md: str) -> list[dict]:
    """
    Parse the 'All roles' summary table from permissions-reference.md.

    Table format (markdown blockquote):
      > | [Display Name](#slug) | Description text | TemplateId-GUID |
    """
    roles = []
    row_re = re.compile(
        r"^\s*>\s*\|\s*"
        r"\[([^\]]+)\]\(#([^)]+)\)"   # group 1: displayName, group 2: slug/anchor
        r"\s*\|([^|]*)\|"              # group 3: description cell
        r"([^|]+)\|",                  # group 4: template ID cell
        re.MULTILINE,
    )
    for m in row_re.finditer(md):
        display_name = m.group(1).strip()
        slug = m.group(2).strip()
        raw_desc = m.group(3)
        template_id = m.group(4).strip()

        # Skip any header row that slipped through
        if template_id.lower() == "template id":
            continue
        # Basic GUID validation
        if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", template_id, re.I):
            continue

        is_privileged = PRIVILEGED_MARKER in raw_desc

        # Strip markdown images and links from description
        desc = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw_desc)   # ![alt](url)
        desc = re.sub(r"\[[^\]]*\]\([^)]*\)", "", desc)         # [text](url) and [](url)
        desc = re.sub(r"<br\s*/?>", " ", desc, flags=re.I)
        desc = " ".join(desc.split())  # collapse whitespace

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
    """
    Extract allowedResourceActions from a role include file.

    Rows look like:
      > | microsoft.directory/applications/create | Create all types... |
    """
    perm_re = re.compile(
        r"^\s*>\s*\|\s*(microsoft\.[A-Za-z0-9_./]+)\s*\|",
        re.MULTILINE,
    )
    return [m.group(1) for m in perm_re.finditer(md)]


# ---------------------------------------------------------------------------
# Per-role enrichment (runs in thread pool)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Fetching Entra ID role index from MicrosoftDocs/entra-docs…")

    index_md = get(INDEX_URL)
    if not index_md:
        print("ERROR: could not fetch permissions-reference.md", file=sys.stderr)
        sys.exit(1)

    roles = parse_roles_table(index_md)
    if not roles:
        print("ERROR: parsed 0 roles — markdown format may have changed", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(roles)} built-in roles — fetching per-role permissions…")

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

    privileged_count = sum(1 for r in enriched if r["isPrivileged"])
    print(f"Fetched {len(enriched)} roles ({privileged_count} privileged)")

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(enriched, fh, indent=2, ensure_ascii=False)

    print(f"Written -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
