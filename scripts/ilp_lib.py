"""Parsing helpers shared by the experiment runner and the plotting scripts.

  parse_stats(path)         first statistics block of a gem5 stats.txt(.gz)
  summarize(stats, threads) the derived metrics used in the report
  parse_pipeview(path, ct)  per-instruction latency from an O3PipeView trace
"""

import gzip
import math
import re
from collections import defaultdict

STAGES = ["fetch", "decode", "rename", "dispatch", "issue", "complete",
          "retire"]


def _open(path):
    path = str(path)
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def parse_stats(path):
    """Return {stat name: float} for the first dump in a stats file.

    The configs reset the statistics at the start of the region of interest
    and dump once at its end, so the first block is the ROI.
    """
    out = {}
    began = False
    with _open(path) as f:
        for line in f:
            if line.startswith("---------- Begin"):
                if began:
                    break
                began = True
                continue
            if line.startswith("---------- End"):
                break
            if not began or line.startswith("#") or not line.strip():
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                out[parts[0]] = float(parts[1])
            except ValueError:
                continue
    return out


def _sum_threads(stats, template, nthreads):
    return sum(stats.get(template.format(t=t), 0.0) for t in range(nthreads))


def _frac(stats, prefix):
    """{state: fraction of cycles} for a gem5 'status::' distribution."""
    items = {k[len(prefix):]: v for k, v in stats.items()
             if k.startswith(prefix) and not k.endswith("::total")}
    tot = sum(items.values())
    return {k: (v / tot if tot else 0.0) for k, v in items.items()}


def summarize(stats, nthreads=1, cpu="o3"):
    """Derived per-run metrics (everything the figures/tables need)."""
    m = {}
    cycles = stats.get("system.cpu.numCycles", 0.0)
    insts = _sum_threads(stats, "system.cpu.commitStats{t}.numInsts", nthreads)
    ops = _sum_threads(stats, "system.cpu.commitStats{t}.numOps", nthreads)
    if cpu == "minor" and insts == 0:
        insts = stats.get("system.cpu.thread_0.numInsts", 0.0)
        ops = stats.get("system.cpu.thread_0.numOps", 0.0)
    m["cycles"] = cycles
    m["insts"] = insts
    m["ops"] = ops
    m["ipc"] = insts / cycles if cycles else 0.0       # x86 instr / cycle
    m["upc"] = ops / cycles if cycles else 0.0         # micro-ops / cycle
    m["cpi"] = cycles / insts if insts else 0.0
    m["uops_per_inst"] = ops / insts if insts else 0.0
    for t in range(nthreads):
        ti = stats.get(f"system.cpu.commitStats{t}.numInsts", 0.0)
        m[f"insts_t{t}"] = ti
        m[f"ipc_t{t}"] = ti / cycles if cycles else 0.0

    # caches
    for name, key in (("l1i", "system.cpu.icache"), ("l1d", "system.cpu.dcache"),
                      ("l2", "system.l2cache")):
        m[f"{name}_accesses"] = stats.get(f"{key}.overallAccesses::total", 0.0)
        m[f"{name}_misses"] = stats.get(f"{key}.overallMisses::total", 0.0)
        acc = m[f"{name}_accesses"]
        m[f"{name}_miss_rate"] = m[f"{name}_misses"] / acc if acc else 0.0

    # branch prediction (committed branches, all threads)
    committed = sum(v for k, v in stats.items()
                    if re.fullmatch(r"system\.cpu\.branchPred\.committed_\d+::total", k))
    mispred = sum(v for k, v in stats.items()
                  if re.fullmatch(r"system\.cpu\.branchPred\.mispredicted_\d+::total", k))
    m["branches"] = committed
    m["mispredicts"] = mispred
    m["mispredict_rate"] = mispred / committed if committed else 0.0
    m["mpki"] = 1000.0 * mispred / insts if insts else 0.0
    m["btb_hit_ratio"] = stats.get("system.cpu.branchPred.BTBHitRatio", 0.0)

    if cpu == "o3":
        # work that was fetched/decoded but never committed (wrong path)
        fetched = _sum_threads(stats, "system.cpu.fetchStats{t}.numInsts",
                               nthreads)
        decoded = stats.get("system.cpu.decode.decodedInsts", 0.0)
        m["fetched_insts"] = fetched
        m["wasted_fetch_frac"] = max(0.0, 1.0 - insts / fetched) if fetched else 0.0
        m["wasted_decode_frac"] = max(0.0, 1.0 - ops / decoded) if decoded else 0.0
        m["issue_rate"] = stats.get("system.cpu.issueRate", 0.0)
        m["iq_full_events"] = stats.get("system.cpu.iew.iqFullEvents", 0.0)
        m["lsq_full_events"] = stats.get("system.cpu.iew.lsqFullEvents", 0.0)
        m["fu_busy"] = stats.get("system.cpu.fuBusy", 0.0)
        m["lq_occupancy"] = stats.get("system.cpu.lsq0.lqAvgOccupancy", 0.0)
        m["sq_occupancy"] = stats.get("system.cpu.lsq0.sqAvgOccupancy", 0.0)
        for stage, prefix in (("fetch", "system.cpu.fetch.status::"),
                              ("decode", "system.cpu.decode.status::"),
                              ("rename", "system.cpu.rename.status::"),
                              ("dispatch", "system.cpu.iew.dispatchStatus::"),
                              ("commit", "system.cpu.commit.status::")):
            for state, f in _frac(stats, prefix).items():
                m[f"{stage}_{state.lower()}"] = f
        # commit-width histogram: share of cycles committing k micro-ops
        for k, v in stats.items():
            mm = re.fullmatch(r"system\.cpu\.numIssuedDist::(\d+)", k)
            if mm:
                m[f"issued_{mm.group(1)}"] = v / cycles if cycles else 0.0
    return m


def parse_pipeview(path, cycle_ticks):
    """Average per-micro-op latency (cycles) from an O3PipeView trace.

    Each micro-op appears as 7 consecutive 'O3PipeView:<stage>:<tick>' lines.
    Squashed micro-ops have retire == 0 and are ignored. Returns the mean
    fetch->retire latency, the mean time spent between consecutive stages,
    and the number of micro-ops sampled.
    """
    sums = defaultdict(float)
    n = 0
    cur = {}
    with open(path, errors="replace") as f:
        for line in f:
            if not line.startswith("O3PipeView:"):
                continue
            fields = line.rstrip("\n").split(":")
            stage = fields[1]
            if stage not in STAGES:
                continue
            cur[stage] = int(fields[2])
            if stage == "retire":
                if cur.get("retire", 0) > 0 and all(cur.get(s, 0) > 0
                                                   for s in STAGES):
                    n += 1
                    sums["total"] += (cur["retire"] - cur["fetch"]) / cycle_ticks
                    for a, b in zip(STAGES, STAGES[1:]):
                        sums[f"{a}_to_{b}"] += (cur[b] - cur[a]) / cycle_ticks
                cur = {}
    res = {f"lat_{k}": (v / n if n else math.nan) for k, v in sums.items()}
    res["lat_samples"] = n
    if n == 0:
        res["lat_total"] = math.nan
    return res
