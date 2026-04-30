"""
sentrux_parser.py

Reads .sentrux/gate_stdout.txt (raw Sentrux gate output), extracts all
metrics, writes .sentrux/quality.json with structured data for downstream
consumers (README dashboard generator, D1 push, future frontend endpoint).

If the gate output is missing or malformed, writes a minimal fallback
JSON so downstream consumers can detect "no data" and skip gracefully.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

GATE_STDOUT = Path(".sentrux/gate_stdout.txt")
QUALITY_JSON = Path(".sentrux/quality.json")


def parse_gate_output(text: str) -> dict:
    """Extract metrics from Sentrux gate stdout.

    Returns a dict with quality, baseline, coupling, cycles, god_files,
    main_sequence_distance, verdict, and timestamp. Missing fields are
    None — downstream consumers handle None gracefully.
    """
    result: dict = {
        "quality": None,
        "baseline": None,
        "coupling_current": None,
        "coupling_baseline": None,
        "cycles_current": None,
        "cycles_baseline": None,
        "god_files_current": None,
        "god_files_baseline": None,
        "main_sequence_distance": None,
        "verdict": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Quality:    7003 -> 7005  (ASCII arrow)
    m = re.search(r"Quality:\s+(\d+)\s*(?:->|→)\s*(\d+)", text)
    if m:
        result["baseline"] = int(m.group(1))
        result["quality"] = int(m.group(2))

    # Coupling:   0.00 -> 0.00
    m = re.search(r"Coupling:\s+([\d.]+)\s*(?:->|→)\s*([\d.]+)", text)
    if m:
        result["coupling_baseline"] = float(m.group(1))
        result["coupling_current"] = float(m.group(2))

    # Cycles:     0 -> 0
    m = re.search(r"Cycles:\s+(\d+)\s*(?:->|→)\s*(\d+)", text)
    if m:
        result["cycles_baseline"] = int(m.group(1))
        result["cycles_current"] = int(m.group(2))

    # God files:  0 -> 0
    m = re.search(r"God files:\s+(\d+)\s*(?:->|→)\s*(\d+)", text)
    if m:
        result["god_files_baseline"] = int(m.group(1))
        result["god_files_current"] = int(m.group(2))

    # Distance from Main Sequence: 0.25
    m = re.search(r"Distance from Main Sequence:\s+([\d.]+)", text)
    if m:
        result["main_sequence_distance"] = float(m.group(1))

    # Verdict — look for the meaningful result line
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines):
        if any(marker in line for marker in ["No degradation", "regression", "WARN", "FAIL", "PASS"]):
            cleaned = re.sub(r"^[^A-Za-z]+", "", line).strip()
            if cleaned:
                result["verdict"] = cleaned
                break

    return result


def main() -> int:
    if not GATE_STDOUT.exists():
        print("sentrux_parser: gate_stdout.txt not found — writing empty quality.json", file=sys.stderr)
        QUALITY_JSON.parent.mkdir(parents=True, exist_ok=True)
        QUALITY_JSON.write_text(
            json.dumps({"quality": None, "error": "gate output missing"}, indent=2),
            encoding="utf-8",
        )
        return 0

    # PowerShell's > operator writes UTF-16 LE on Windows; bash > writes UTF-8 on Linux CI.
    # Detect by BOM so the parser works correctly in both environments.
    raw = GATE_STDOUT.read_bytes()
    if raw[:2] == b"\xff\xfe":
        text = raw.decode("utf-16-le")
    elif raw[:2] == b"\xfe\xff":
        text = raw.decode("utf-16-be")
    else:
        text = raw.decode("utf-8", errors="replace")
    metrics = parse_gate_output(text)

    if metrics["quality"] is None:
        print("sentrux_parser: failed to parse Quality from gate output", file=sys.stderr)
        print("=== Raw gate output ===", file=sys.stderr)
        print(text, file=sys.stderr)

    QUALITY_JSON.parent.mkdir(parents=True, exist_ok=True)
    QUALITY_JSON.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"sentrux_parser: wrote {QUALITY_JSON}")
    print(json.dumps(metrics, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
