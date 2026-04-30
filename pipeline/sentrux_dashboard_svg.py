"""
sentrux_dashboard_svg.py

Reads .sentrux/quality.json, generates an animated SVG dashboard at
assets/quality-dashboard.svg. The SVG is committed by the workflow
along with other data files, then embedded in README via:
    ![Code quality](assets/quality-dashboard.svg)

Design: hybrid terminal-aesthetic + RoleLens brand language.
Living: pulse animations, fade-in, animated quality bar indicator.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

QUALITY_JSON = Path(".sentrux/quality.json")
SVG_OUTPUT = Path("assets/quality-dashboard.svg")

# RoleLens brand palette
BG     = "#07080D"
PANEL  = "#0E1018"
BORDER = "#1A1D2A"
TEXT   = "#E5E7EB"
DIM    = "#6B7280"
ACCENT = "#00E5A3"   # electric mint
WARN   = "#F59E0B"
ERROR  = "#EF4444"


def health_color(metric: str, value) -> str:
    if value is None:
        return DIM
    if metric in ("cycles", "god_files"):
        return ACCENT if value == 0 else (WARN if value < 3 else ERROR)
    if metric == "coupling":
        return ACCENT if value < 0.1 else (WARN if value < 0.3 else ERROR)
    if metric == "main_sequence":
        return ACCENT if value < 0.3 else (WARN if value < 0.7 else ERROR)
    return ACCENT


def render(metrics: dict) -> str:
    quality  = metrics.get("quality")
    baseline = metrics.get("baseline")
    coupling = metrics.get("coupling_current")
    cycles   = metrics.get("cycles_current")
    god_files = metrics.get("god_files_current")
    distance  = metrics.get("main_sequence_distance")
    verdict   = metrics.get("verdict") or "—"
    timestamp_iso = metrics.get("timestamp", "")

    q_display       = str(quality)   if quality   is not None else "—"
    coupling_display = f"{coupling:.2f}" if coupling is not None else "—"
    cycles_display   = str(cycles)   if cycles    is not None else "—"
    god_display      = str(god_files) if god_files is not None else "—"
    dist_display     = f"{distance:.2f}" if distance is not None else "—"

    delta_str = ""
    if quality is not None and baseline is not None:
        diff = quality - baseline
        if diff > 0:
            delta_str = f"&#9650; +{diff} from baseline"
        elif diff < 0:
            delta_str = f"&#9660; {diff} from baseline"
        else:
            delta_str = "= baseline"

    bar_width = 680
    bar_x     = 20
    quality_pct  = max(0.0, min(1.0, (quality or 0) / 10000))
    indicator_x  = bar_x + bar_width * quality_pct
    filled_width = bar_width * quality_pct

    last_verified = "—"
    if timestamp_iso:
        try:
            dt = datetime.fromisoformat(timestamp_iso.replace("Z", "+00:00"))
            last_verified = dt.strftime("%Y-%m-%d %H:%M UTC")
        except (ValueError, AttributeError):
            last_verified = timestamp_iso[:16]

    verdict_color  = ACCENT if "No degradation" in verdict else (WARN if "WARN" in verdict.upper() else (ERROR if "FAIL" in verdict.upper() else DIM))
    coupling_color = health_color("coupling",      coupling)
    cycles_color   = health_color("cycles",        cycles)
    god_color      = health_color("god_files",     god_files)
    dist_color     = health_color("main_sequence", distance)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 360" font-family="ui-monospace, 'SF Mono', Menlo, Consolas, monospace">
  <defs>
    <linearGradient id="qbar" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0" stop-color="{BORDER}"/>
      <stop offset="0.5" stop-color="{ACCENT}" stop-opacity="0.4"/>
      <stop offset="1" stop-color="{ACCENT}"/>
    </linearGradient>
    <filter id="glow">
      <feGaussianBlur stdDeviation="2.5" result="blur"/>
      <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <!-- KITT scanner beam gradient: bright core, soft fade at edges -->
    <linearGradient id="kitt-beam" x1="0" x2="1" y1="0" y2="0">
      <stop offset="0%"   stop-color="{ACCENT}" stop-opacity="0"/>
      <stop offset="25%"  stop-color="{ACCENT}" stop-opacity="0.55"/>
      <stop offset="50%"  stop-color="#ffffff"  stop-opacity="1"/>
      <stop offset="75%"  stop-color="{ACCENT}" stop-opacity="0.55"/>
      <stop offset="100%" stop-color="{ACCENT}" stop-opacity="0"/>
    </linearGradient>
    <!-- Clip scanner strictly to bar bounds -->
    <clipPath id="bar-clip">
      <rect x="{bar_x}" y="164" width="{bar_width}" height="14"/>
    </clipPath>
  </defs>

  <!-- Background + border -->
  <rect width="720" height="360" fill="{BG}" rx="12"/>
  <rect x="0.5" y="0.5" width="719" height="359" fill="none" stroke="{BORDER}" stroke-width="1" rx="12"/>

  <!-- Header -->
  <text x="20" y="28" font-size="11" fill="{DIM}" letter-spacing="1.5">CODE QUALITY&#160;&#183;&#160;ENTRA ROLELENS&#160;&#183;&#160;SENTRUX v0.5.7</text>
  <circle cx="700" cy="24" r="4" fill="{verdict_color}">
    <animate attributeName="opacity" values="1;0.35;1" dur="2.4s" repeatCount="indefinite"/>
  </circle>

  <!-- Quality score (large) -->
  <text x="20" y="76" font-size="11" fill="{DIM}" letter-spacing="1.5">QUALITY SCORE</text>
  <text x="20" y="132" font-size="60" font-weight="600" fill="{ACCENT}" filter="url(#glow)">
    {q_display}
    <animate attributeName="opacity" values="0;1" dur="0.7s" fill="freeze"/>
  </text>
  <text x="20" y="152" font-size="11" fill="{DIM}">{delta_str}</text>

  <!-- Quality bar (0–10000 scale) -->
  <rect x="{bar_x}" y="168" width="{bar_width}" height="6" fill="{PANEL}" rx="3"/>
  <rect x="{bar_x}" y="168" width="{filled_width:.1f}" height="6" fill="url(#qbar)" rx="3"/>
  <!-- KITT scanner beam sweeping left↔right across full bar -->
  <rect x="-60" y="164" width="80" height="14" fill="url(#kitt-beam)" clip-path="url(#bar-clip)">
    <animate attributeName="x" values="-60;{bar_x + bar_width};-60" dur="2.4s" repeatCount="indefinite" calcMode="linear"/>
  </rect>
  <!-- Static score position marker -->
  <circle cx="{indicator_x:.1f}" cy="171" r="3.5" fill="{ACCENT}"/>
  <text x="{bar_x}" y="190" font-size="9" fill="{DIM}">0</text>
  <text x="{bar_x + bar_width - 32}" y="190" font-size="9" fill="{DIM}">10 000</text>

  <!-- Metric tiles -->
  <!-- Tile 1: Coupling -->
  <g transform="translate(20,202)">
    <rect width="160" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">COUPLING</text>
    <text x="12" y="58" font-size="30" fill="{coupling_color}" font-weight="500">{coupling_display}</text>
    <circle cx="144" cy="20" r="3" fill="{coupling_color}"/>
  </g>

  <!-- Tile 2: Cycles -->
  <g transform="translate(188,202)">
    <rect width="160" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">CYCLES</text>
    <text x="12" y="58" font-size="30" fill="{cycles_color}" font-weight="500">{cycles_display}</text>
    <circle cx="144" cy="20" r="3" fill="{cycles_color}"/>
  </g>

  <!-- Tile 3: God files -->
  <g transform="translate(356,202)">
    <rect width="160" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">GOD FILES</text>
    <text x="12" y="58" font-size="30" fill="{god_color}" font-weight="500">{god_display}</text>
    <circle cx="144" cy="20" r="3" fill="{god_color}"/>
  </g>

  <!-- Tile 4: Main sequence distance -->
  <g transform="translate(524,202)">
    <rect width="176" height="80" fill="{PANEL}" stroke="{BORDER}" rx="6"/>
    <text x="12" y="22" font-size="10" fill="{DIM}" letter-spacing="1">DISTANCE</text>
    <text x="12" y="58" font-size="30" fill="{dist_color}" font-weight="500">{dist_display}</text>
    <text x="12" y="72" font-size="9" fill="{DIM}">main sequence</text>
    <circle cx="160" cy="20" r="3" fill="{dist_color}"/>
  </g>

  <!-- Verdict + timestamp -->
  <text x="20" y="322" font-size="11" fill="{verdict_color}">&#9658; {verdict}</text>
  <text x="700" y="322" font-size="9" fill="{DIM}" text-anchor="end">verified {last_verified}</text>
</svg>"""
    return svg


def main() -> int:
    if not QUALITY_JSON.exists():
        print("dashboard_svg: quality.json missing — skipping SVG generation", file=sys.stderr)
        return 0

    metrics = json.loads(QUALITY_JSON.read_text(encoding="utf-8"))
    if metrics.get("error"):
        print(f"dashboard_svg: quality.json contains error ({metrics['error']}) — skipping", file=sys.stderr)
        return 0

    svg = render(metrics)
    SVG_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    SVG_OUTPUT.write_text(svg, encoding="utf-8")
    print(f"dashboard_svg: wrote {SVG_OUTPUT} ({len(svg):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
