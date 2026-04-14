"""
scrape_tasks.py

Scrapes the Microsoft Learn "least privileged role by task" page and writes
a structured task→role mapping to data/tasks.json.

Source:
  https://learn.microsoft.com/en-us/entra/identity/role-based-access-control/delegate-by-task

Page structure:
  <h2>Feature Area least privileged roles</h2>
  <div class="mx-tableFixed">
    <table>
      <thead><tr><th>Task</th><th>Least privileged role</th><th>Additional roles</th></tr></thead>
      <tbody>
        <tr><td>task text</td><td><a>Role Name</a></td><td><a>Alt</a><br/><a>Alt2</a></td></tr>
        ...
      </tbody>
    </table>
  </div>
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

# h2 headings that are not feature-area sections
SKIP_HEADINGS = {"next steps", "feedback", "additional resources", "in this article"}

# Suffix to strip from h2 text to get the clean feature-area name
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
    """Strip trailing 'least privileged roles' variants from an h2 to get feature area name."""
    text = text.strip()
    lower = text.lower()
    for suffix in HEADING_SUFFIXES:
        if lower.endswith(suffix):
            text = text[: len(text) - len(suffix)].strip()
            break
    return text


def cell_text(td) -> str:
    """Return stripped plain-text content of a table cell."""
    return td.get_text(separator=" ", strip=True)


def cell_roles(td) -> list[str]:
    """
    Extract role name(s) from a table cell.
    Prefers <a> link text; falls back to plain text.
    Multiple roles may be separated by <br> tags.
    Returns a list (may be empty).
    """
    links = td.find_all("a")
    if links:
        return [a.get_text(strip=True) for a in links if a.get_text(strip=True)]
    text = td.get_text(separator="|", strip=True)
    parts = [p.strip() for p in text.split("|") if p.strip()]
    return parts


def scrape(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tasks = []
    feature_areas_seen = set()

    # The page has two div.content elements; the second one holds the article body.
    # Pick the one that contains tables (i.e. has the most h2s / tables).
    candidates = soup.find_all("div", class_="content")
    content = max(candidates, key=lambda d: len(d.find_all("table"))) if candidates else soup

    for h2 in content.find_all("h2"):
        heading_raw = h2.get_text(strip=True)
        if heading_raw.lower() in SKIP_HEADINGS:
            continue

        feature_area = clean_heading(heading_raw)
        if not feature_area:
            continue

        # Find the next <table> sibling (may be wrapped in a div)
        table = None
        for sibling in h2.find_next_siblings():
            if sibling.name == "table":
                table = sibling
                break
            if sibling.name in ("h2", "h3"):
                break  # next section started, no table for this heading
            inner = sibling.find("table") if hasattr(sibling, "find") else None
            if inner:
                table = inner
                break

        if table is None:
            continue

        feature_areas_seen.add(feature_area)
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")[1:]

        for row in rows:
            cols = row.find_all("td")
            if len(cols) < 2:
                continue

            task_text = cell_text(cols[0])
            if not task_text:
                continue

            min_roles = cell_roles(cols[1])
            min_role = min_roles[0] if min_roles else ""
            if not min_role:
                continue

            alt_roles = cell_roles(cols[2]) if len(cols) > 2 else []

            tasks.append({
                "feature_area": feature_area,
                "task": task_text,
                "min_role": min_role,
                "alt_roles": alt_roles,
                "source_url": SOURCE_URL,
            })

    return tasks, feature_areas_seen


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

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        json.dump(tasks, fh, indent=2, ensure_ascii=False)

    print(f"Scraped {len(tasks)} tasks across {len(feature_areas)} feature areas")
    print(f"Written -> {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
