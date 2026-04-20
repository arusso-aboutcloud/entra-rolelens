"""
scrape_tasks.py

Scrapes the Microsoft Learn "least privileged role by task" page and writes
a structured task->role mapping to data/tasks.json.

Source:
  https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-by-task
"""

import json
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCE_URL = (
    "https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-by-task"
)
OUTPUT_PATH = Path(__file__).parent.parent / "data" / "tasks.json"
MIN_TASKS = 50

SKIP_HEADINGS = {"next steps", "feedback", "additional resources", "in this article"}
HEADING_SUFFIXES = [
    " least privileged roles",
    " least privileged role",
]


def fetch_page(url: str) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    if not resp.ok:
        print(f"ERROR: {url} returned {resp.status_code} {resp.reason}", file=sys.stderr)
        sys.exit(1)
    return resp.text


def clean_heading(text: str) -> str:
    text = text.strip()
    lower = text.lower()
    for suffix in HEADING_SUFFIXES:
        if lower.endswith(suffix):
            text = text[: len(text) - len(suffix)].strip()
            break
    return text


def cell_text(td) -> str:
    return td.get_text(separator=" ", strip=True)


def cell_roles(td) -> list[str]:
    links = td.find_all("a")
    if links:
        return [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
    text = td.get_text(separator="|", strip=True)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    return parts


def scrape(html: str) -> tuple[list[dict], set[str]]:
    soup = BeautifulSoup(html, "lxml")
    tasks = []
    feature_areas_seen = set()

    # Target the primary content container
    content = soup.find("main") or soup.find("div", id="main-column") or soup

    for h2 in content.find_all("h2"):
        heading_raw = h2.get_text(strip=True)
        if heading_raw.lower() in SKIP_HEADINGS:
            continue

        feature_area = clean_heading(heading_raw)
        if not feature_area:
            continue

        # Locate the table following the heading
        table = None
        for sibling in h2.find_next_siblings():
            if sibling.name == "table":
                table = sibling
                break
            if sibling.name in ("h2", "h3"):
                break
            inner = sibling.find("table") if hasattr(sibling, "find") else None
            if inner:
                table = inner
                break

        if table is None:
            continue

        feature_areas_seen.add(feature_area)
        
        # 1. Identify Column Indices dynamically from headers
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        try:
            task_idx = next(i for i, h in enumerate(headers) if "task" in h)
            role_idx = next(i for i, h in enumerate(headers) if "least privileged" in h)
        except StopIteration:
            # Fallback for tables without standard headers
            task_idx, role_idx = 0, 1

        last_task_text = ""  # For handling rowspan/inherited tasks
        
        tbody = table.find("tbody")
        rows = tbody.find_all("tr") if tbody else table.find_all("tr")[1:]

        for row in rows:
            cols = row.find_all(["td", "th"])
            if not cols:
                continue

            # 2. Handle Rowspan / Missing Task Column
            # If the row has fewer cells than columns, the first cell is likely the role
            if len(cols) < len(headers):
                task_text = last_task_text
                # If we are missing the task col, role is shifted
                effective_role_idx = role_idx - 1 
            else:
                task_text = cell_text(cols[task_idx])
                last_task_text = task_text
                effective_role_idx = role_idx

            if not task_text or task_text.lower() == "task":
                continue

            # 3. Extract Role and Alt Roles
            if effective_role_idx < len(cols):
                min_roles = cell_roles(cols[effective_role_idx])
                min_role = min_roles[0] if min_roles else ""
                
                if not min_role:
                    continue

                # Alt roles are typically the next column after 'Least Privileged'
                alt_idx = effective_role_idx + 1
                alt_roles = cell_roles(cols[alt_idx]) if alt_idx < len(cols) else []

                tasks.append({
                    "feature_area": feature_area,
                    "task": task_text,
                    "min_role": min_role,
                    "alt_roles": alt_roles,
                    "source_url": SOURCE_URL,
                })

    return tasks, feature_areas_seen


MANUAL_FEATURE_AREAS = {"Agent Identity", "Backup and Recovery", "Tenant Governance"}
MANUAL_SOURCE_MARKER = "permissions-reference"


def load_manual_tasks(path: Path) -> list[dict]:
    """Return tasks from existing file that are manually curated (not scraped)."""
    if not path.exists():
        return []
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [
        t for t in existing
        if t.get("feature_area") in MANUAL_FEATURE_AREAS
        or MANUAL_SOURCE_MARKER in t.get("source_url", "")
    ]


def merge_tasks(scraped: list[dict], manual: list[dict]) -> list[dict]:
    """Scraped tasks win on description collision; manual tasks are appended."""
    scraped_descs = {t["task"].strip().lower() for t in scraped}
    deduped_manual = [
        t for t in manual
        if t["task"].strip().lower() not in scraped_descs
    ]
    return scraped + deduped_manual


def main() -> None:
    print(f"Fetching: {SOURCE_URL}")
    html = fetch_page(SOURCE_URL)

    tasks, feature_areas = scrape(html)

    if len(tasks) < MIN_TASKS:
        print(
            f"ERROR: only {len(tasks)} tasks scraped (expected >= {MIN_TASKS}). "
            "Page structure may have changed.",
            file=sys.stderr,
        )
        sys.exit(1)

    manual = load_manual_tasks(OUTPUT_PATH)
    merged = merge_tasks(tasks, manual)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(merged, fh, indent=2, ensure_ascii=False)

    print(
        f"Scraped {len(tasks)} tasks across {len(feature_areas)} feature areas"
        f" + preserved {len(manual)} manual tasks = {len(merged)} total"
    )
    print(f"Written -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
