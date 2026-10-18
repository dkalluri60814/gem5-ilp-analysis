#!/usr/bin/env python3
"""Draw a cycle-by-cycle pipeline diagram from a gem5 O3PipeView trace.

    python3 scripts/pipeline_diagram.py TRACE.txt -o fig.png \
            --skip 40 --count 28 --title "O3, scalar, int_indep"

Every micro-op is one row; the coloured segments are the cycles it spends
between two pipeline events recorded by gem5:

    fetch -> decode -> rename -> dispatch -> issue -> complete -> retire

Squashed (wrong-path) micro-ops are drawn hatched and in grey, which makes
branch mispredictions visible: they are fetched, partly executed and thrown
away.
"""

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

STAGES = ["fetch", "decode", "rename", "dispatch", "issue", "complete",
          "retire"]
# segment i spans STAGES[i] -> STAGES[i+1]
SEGMENTS = [
    ("Fetch (I-cache)", "#4e79a7"),
    ("Decode", "#76b7b2"),
    ("Rename", "#59a14f"),
    ("Dispatch to IQ / wait for operands", "#edc948"),
    ("Execute (issue to complete)", "#e15759"),
    ("Wait in ROB / commit", "#b07aa1"),
]


def read_trace(path):
    """Return a list of dicts: pc, seq, disasm, and a tick per stage."""
    ops, cur = [], None
    with open(path, errors="replace") as f:
        for line in f:
            if not line.startswith("O3PipeView:"):
                continue
            p = line.rstrip("\n").split(":", 6)
            stage = p[1]
            if stage == "fetch":
                cur = {"pc": p[3], "seq": int(p[5]) if len(p) > 5 else 0,
                       "disasm": p[6].strip() if len(p) > 6 else "",
                       "fetch": int(p[2])}
            elif cur is not None and stage in STAGES:
                cur[stage] = int(p[2])
                if stage == "retire":
                    ops.append(cur)
                    cur = None
    return ops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--skip", type=int, default=40,
                    help="micro-ops to skip at the start of the trace")
    ap.add_argument("--count", type=int, default=28)
    ap.add_argument("--cycle-ticks", type=int, default=500)
    ap.add_argument("--title", default="")
    args = ap.parse_args()

    # gem5 prints committed and squashed micro-ops in different orders;
    # sorting by sequence number gives program (= fetch) order, and puts
    # wrong-path micro-ops right behind the branch that caused them.
    ops = sorted(read_trace(args.trace), key=lambda o: o["seq"])
    ops = ops[args.skip:args.skip + args.count]
    if not ops:
        raise SystemExit("no micro-ops found in the trace")
    t0 = min(o["fetch"] for o in ops)
    cyc = lambda t: (t - t0) / args.cycle_ticks

    fig, ax = plt.subplots(figsize=(11, 0.28 * len(ops) + 1.8))
    for row, op in enumerate(ops):
        squashed = op.get("retire", 0) == 0
        for i, (_, color) in enumerate(SEGMENTS):
            a, b = op.get(STAGES[i], 0), op.get(STAGES[i + 1], 0)
            if squashed:
                if a <= 0:
                    break
                b = b if b > 0 else a
            if a <= 0 or b <= 0:
                continue
            width = max(cyc(b) - cyc(a), 0.12)   # keep 0-cycle hops visible
            ax.barh(row, width, left=cyc(a), height=0.72,
                    color="#bdbdbd" if squashed else color,
                    hatch="///" if squashed else None, edgecolor="white",
                    linewidth=0.4)
        if op.get("retire", 0):
            ax.plot(cyc(op["retire"]), row, marker="|", color="black",
                    markersize=7)
    labels = [f"{o['pc'][-6:]}  {o['disasm'][:46]}" for o in ops]
    ax.set_yticks(range(len(ops)))
    ax.set_yticklabels(labels, fontsize=6.5, family="monospace")
    ax.invert_yaxis()
    ax.set_xlabel("cycle (relative to the first fetch in this window)")
    ax.set_title(args.title or "gem5 O3 pipeline diagram", fontsize=11)
    ax.grid(axis="x", linewidth=0.3, alpha=0.6)
    ax.set_axisbelow(True)
    handles = [Patch(color=c, label=n) for n, c in SEGMENTS]
    handles.append(Patch(facecolor="#bdbdbd", hatch="///", edgecolor="white",
                         label="Squashed (wrong path)"))
    ax.legend(handles=handles, loc="upper center", ncol=3, fontsize=7,
              bbox_to_anchor=(0.5, -0.1 - 0.0 * len(ops)), frameon=False)
    fig.tight_layout()
    fig.savefig(args.out, dpi=170, bbox_inches="tight")
    print(f"wrote {args.out} ({len(ops)} micro-ops)")


if __name__ == "__main__":
    main()
