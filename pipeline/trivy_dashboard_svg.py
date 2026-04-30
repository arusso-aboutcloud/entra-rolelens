"""
trivy_dashboard_svg.py

Reads .trivy/worker.json and .trivy/pipeline.json (Trivy JSON output written
by the workflow dashboard job), generates assets/security-dashboard.svg.
Committed by the workflow and embedded in README.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKER_JSON   = Path(".trivy/worker.json")
PIPELINE_JSON = Path(".trivy/pipeline.json")
SVG_OUTPUT    = Path("assets/security-dashboard.svg")

BG     = "#07080D"
PANEL  = "#0E1018"
BORDER = "#1A1D2A"
DIM    = "#6B7280"
ACCENT = "#00E5A3"
WARN   = "#F59E0B"
ERROR  = "#EF4444"


def count_vulns(json_path: Path) -> tuple[int, int]:
    if not json_path.exists():
        return 0, 0
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0, 0
    high = crit = 0
    for result in data.get("Results") or []:
        for v in result.get("Vulnerabilities") or []:
            sev = v.get("Severity", "")
            if sev == "HIGH":
                high += 1
            elif sev == "CRITICAL":
                crit += 1
    return high, crit


def sev_color(high: int, critical: int) -> str:
    if critical > 0:
        return ERROR
    if high > 0:
        return WARN
    return ACCENT


def render(worker_high: int, worker_crit: int,
           pipeline_high: int, pipeline_crit: int,
           timestamp_iso: str, pending: bool = False) -> str:

    total_high = worker_high + pipeline_high
    total_crit = worker_crit + pipeline_crit
    total      = total_high + total_crit

    overall_color  = sev_color(total_high, total_crit)
    worker_color   = sev_color(worker_high, worker_crit)
    pipeline_color = sev_color(pipeline_high, pipeline_crit)

    if pending:
        score_display = "—"
        verdict       = "Pending first scan"
        verdict_color = DIM
    elif total == 0:
        score_display = "0"
        verdict       = "No HIGH or CRITICAL findings"
        verdict_color = ACCENT
    else:
        score_display = str(total)
        frag = []
        if total_crit:
            frag.append(f"{total_crit} CRITICAL")
        if total_high:
            frag.append(f"{total_high} HIGH")
        verdict       = " · ".join(frag)
        verdict_color = ERROR if total_crit > 0 else WARN

    last_scanned = "—"
    if timestamp_iso:
        try:
            dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
            last_scanned = dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, AttributeError):
            last_scanned = timestamp_iso[:16]

    w_high_d = str(worker_high)
    w_crit_d = str(worker_crit)
    p_high_d = str(pipeline_high)
    p_crit_d = str(pipeline_crit)
    t_crit_d = str(total_crit)
    t_high_d = str(total_high)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 280" font-family="ui-monospace, 'SF Mono', Menlo, Consolas, monospace">
  <defs>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>

  <!-- Background + border -->
  <rect width="720" height="280" fill="{BG}" rx="12"/>
  <rect x="0.5" y="0.5" width="719" height="279" fill="none" stroke="{BORDER}" stroke-width="1" rx="12"/>

  <!-- Header -->
  <text x="20" y="28" font-size="11" fill="{DIM}" letter-spacing="1.5">SECURITY SCAN&#160;&#183;&#160;ENTRA ROLELENS&#160;&#183;&#160;TRIVY v0.28.0</text>
  <circle cx="700" cy="24" r="4" fill="{overall_color}">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>

  <!-- Total findings (large) -->
  <text x="20" y="76" font-size="11" fill="{DIM}" letter-spacing="1.5">DEPENDENCY VULNERABILITIES (HIGH + CRITICAL)</text>
  <text x="20" y="132" font-size="60" font-weight="600" fill="{overall_color}" filter="url(#glow)">
    {score_display}
    <animate attributeName="opacity" values="0;1" dur="0.7s" fill="freeze"/>
  </text>
  <text x="20" y="152" font-size="11" fill="{DIM}">across worker (npm) and pipeline (Python)</text>

  <!-- Tile 1: Worker -->
  <g transform="translate(20,166)">
    <rect width="220" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">WORKER &#183; NPM</text>
    <text x="12" y="46" font-size="10" fill="{DIM}">HIGH</text>
    <text x="12" y="65" font-size="26" fill="{worker_color}" font-weight="500">{w_high_d}</text>
    <text x="110" y="46" font-size="10" fill="{DIM}">CRITICAL</text>
    <text x="110" y="65" font-size="26" fill="{worker_color}" font-weight="500">{w_crit_d}</text>
    <circle cx="204" cy="20" r="3" fill="{worker_color}"/>
  </g>

  <!-- Tile 2: Pipeline -->
  <g transform="translate(252,166)">
    <rect width="220" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">PIPELINE &#183; PYTHON</text>
    <text x="12" y="46" font-size="10" fill="{DIM}">HIGH</text>
    <text x="12" y="65" font-size="26" fill="{pipeline_color}" font-weight="500">{p_high_d}</text>
    <text x="110" y="46" font-size="10" fill="{DIM}">CRITICAL</text>
    <text x="110" y="65" font-size="26" fill="{pipeline_color}" font-weight="500">{p_crit_d}</text>
    <circle cx="204" cy="20" r="3" fill="{pipeline_color}"/>
  </g>

  <!-- Tile 3: Totals -->
  <g transform="translate(484,166)">
    <rect width="216" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">ALL COMPONENTS</text>
    <text x="12" y="46" font-size="10" fill="{DIM}">CRITICAL</text>
    <text x="12" y="65" font-size="26" fill="{overall_color}" font-weight="500">{t_crit_d}</text>
    <text x="110" y="46" font-size="10" fill="{DIM}">HIGH</text>
    <text x="110" y="65" font-size="26" fill="{overall_color}" font-weight="500">{t_high_d}</text>
    <circle cx="200" cy="20" r="3" fill="{overall_color}"/>
  </g>

  <!-- Verdict + timestamp -->
  <text x="20" y="260" font-size="11" fill="{verdict_color}">&#9658; {verdict}</text>
  <text x="700" y="260" font-size="9" fill="{DIM}" text-anchor="end">scanned {last_scanned}</text>
</svg>"""


def main() -> int:
    pending = not WORKER_JSON.exists() and not PIPELINE_JSON.exists()
    if pending:
        print("trivy_dashboard_svg: scan JSONs not found — generating pending-state SVG", file=sys.stderr)

    worker_high, worker_crit     = count_vulns(WORKER_JSON)
    pipeline_high, pipeline_crit = count_vulns(PIPELINE_JSON)
    timestamp_iso = datetime.now(timezone.utc).isoformat()

    svg = render(worker_high, worker_crit, pipeline_high, pipeline_crit, timestamp_iso, pending)
    SVG_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUTPUT.write_text(svg, encoding="utf-8")
    print(f"trivy_dashboard_svg: wrote {SVG_OUTPUT} ({len(svg):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
