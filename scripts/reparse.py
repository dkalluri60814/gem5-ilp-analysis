#!/usr/bin/env python3
"""Recompute the metrics of every finished run from its saved stats.txt.gz.

Use after changing ilp_lib.summarize(): no simulation is repeated. The
per-instruction latency numbers (lat_*) come from the pipeline trace, which
is not kept, so they are carried over unchanged from the old metrics.json.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ilp_lib  # noqa: E402
from run_experiments import RUNS  # noqa: E402

n = 0
for mj in sorted(RUNS.glob("*/metrics.json")):
    rec = json.loads(mj.read_text())
    cfg = rec["config"]
    stats = ilp_lib.parse_stats(mj.parent / "stats.txt.gz")
    new = ilp_lib.summarize(stats, len(cfg["workloads"]), cfg["cpu"])
    for k, v in rec["metrics"].items():
        if k.startswith("lat_"):
            new[k] = v
    rec["metrics"] = new
    mj.write_text(json.dumps(rec, indent=1))
    n += 1
print(f"re-parsed {n} runs")
