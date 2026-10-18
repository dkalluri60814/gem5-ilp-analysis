#!/usr/bin/env python3
"""Runs every Part 2 experiment through gem5 and stores one folder per run.

  python3 scripts/run_experiments.py --list                 # show the plan
  python3 scripts/run_experiments.py --exp pipe,bpred       # run some groups
  python3 scripts/run_experiments.py                        # run everything

Groups
  pipe    basic pipelines: scalar O3 (+ in-order Minor) on every workload
  bpred   branch predictors (static ... TAGE) at issue width 1 and 4
  width   issue width 1/2/4/8 (O3) and 1/2 (in-order Minor)
  window  reorder-buffer size sweep at issue width 8 (limits of ILP)
  smt     1/2/4 hardware threads, mixes, and fetch / LSQ-sharing policies

Each run lands in results/runs/<key>/ with metrics.json (+ stats.txt.gz).
Runs that already have a metrics.json are skipped unless --force is given,
so an interrupted sweep can simply be restarted.
"""

import argparse
import gzip
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ilp_lib  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "configs" / "ilp_sim.py"
BIN = ROOT / "workloads" / "bin"             # with ROI markers (1 thread)
BIN_NATIVE = ROOT / "workloads" / "native"   # no markers (SMT runs)
RUNS = ROOT / "results" / "runs"
SCRATCH = Path(os.environ.get("ILP_SCRATCH", "/tmp/ilp_scratch"))

CLOCK_TICKS = 500           # 2 GHz with gem5's 1 ps tick
TRACE_OFFSET = 3000         # cycles into the ROI before tracing starts
TRACE_CYCLES = 5000         # length of the pipeline-trace window

WORKLOADS = ["int_dep", "int_indep", "fp_dep", "fp_daxpy", "mem_stream",
             "mem_chase", "br_pattern", "br_random", "matmul"]
BPREDS = ["static", "local", "bimode", "tournament", "tage"]

# Iteration arguments that make a kernel outlast the measurement window
# (used for the SMT runs, which measure a fixed number of cycles).
LONG_ARG = {"int_dep": 10**9, "int_indep": 10**9, "fp_dep": 10**9,
            "fp_daxpy": 10**7, "mem_stream": 1000, "mem_chase": 10**9,
            "br_pattern": 10**9, "br_random": 10**9, "matmul": 10**6}
SMT_WARMUP = 500_000        # committed instructions per thread before measuring
SMT_CYCLES = 1_000_000      # length of the SMT measurement window


@dataclass
class Run:
    group: str
    cpu: str
    width: int
    bpred: str
    workloads: list                 # [(name, arg_or_None), ...] one per thread
    warmup_insts: int = 0           # >0: no ROI markers, warm up then measure
    roi_cycles: int = 0             # >0: fixed-length measurement window
    rob: int = 192
    iq: int = 64
    lq: int = 32
    sq: int = 32
    smt_fetch: str = "RoundRobin"
    smt_lsq: str = "Partitioned"
    btb_assoc: int = 1
    trace: bool = True

    @property
    def key(self):
        names = "+".join(w for w, _ in self.workloads)
        k = f"{self.cpu}-w{self.width}-{self.bpred}-{names}"
        if self.cpu == "o3":
            if (self.rob, self.iq, self.lq, self.sq) != (192, 64, 32, 32):
                k += f"-rob{self.rob}-iq{self.iq}-lq{self.lq}-sq{self.sq}"
        if self.btb_assoc != 1:
            k += f"-btb{self.btb_assoc}"
        if self.warmup_insts:
            k += (f"-wu{self.warmup_insts // 1000}k-"
                  f"rc{self.roi_cycles // 1000}k-{self.smt_fetch}-"
                  f"lsq{self.smt_lsq}")
        return k


def plan():
    runs = {}

    def add(r):
        runs.setdefault(r.key, r)

    one = lambda w, arg=None: [(w, arg)]

    # ---- pipe: baseline scalar pipelines -------------------------------
    for w in WORKLOADS:
        add(Run("pipe", "o3", 1, "tournament", one(w)))
        add(Run("pipe", "minor", 1, "tournament", one(w), trace=False))

    # ---- bpred ----------------------------------------------------------
    for width in (1, 4):
        for bp in BPREDS:
            for w in WORKLOADS:
                add(Run("bpred", "o3", width, bp, one(w)))

    # ---- width ----------------------------------------------------------
    for w in WORKLOADS:
        for width in (1, 2, 4, 8):
            add(Run("width", "o3", width, "tournament", one(w)))
        for width in (1, 2):
            add(Run("width", "minor", width, "tournament", one(w),
                    trace=False))

    # ---- window ---------------------------------------------------------
    for w in WORKLOADS:
        for rob in (16, 32, 64, 128, 256):
            add(Run("window", "o3", 8, "tournament", one(w), rob=rob,
                    iq=max(8, rob // 2), lq=max(8, rob // 4),
                    sq=max(8, rob // 4)))

    # ---- smt ------------------------------------------------------------
    def smt(names, fetch="RoundRobin", lsq="Partitioned", btb=1):
        return Run("smt", "o3", 4, "tournament",
                   [(n, LONG_ARG[n]) for n in names],
                   warmup_insts=SMT_WARMUP, roi_cycles=SMT_CYCLES,
                   smt_fetch=fetch, smt_lsq=lsq, btb_assoc=btb)

    for w in WORKLOADS:                                   # alone
        add(smt([w]))
    pairs = [("int_indep", "int_indep"), ("int_dep", "int_dep"),
             ("int_dep", "int_indep"), ("mem_chase", "mem_chase"),
             ("mem_chase", "int_indep"), ("mem_chase", "int_dep"),
             ("mem_stream", "int_indep"), ("fp_daxpy", "fp_dep"),
             ("br_random", "br_random"), ("br_random", "int_indep"),
             ("matmul", "matmul"), ("fp_daxpy", "fp_daxpy")]
    quads = [("int_dep",) * 4, ("int_indep",) * 4, ("mem_chase",) * 4,
             ("matmul",) * 4,
             ("int_dep", "fp_dep", "mem_chase", "br_random"),
             ("int_indep", "fp_daxpy", "mem_stream", "br_pattern")]
    for p in pairs + quads:
        add(smt(list(p)))
    # Same SMT experiments with a 4-way BTB. With gem5's direct-mapped BTB,
    # threads running the same code evict each other's entries (see report).
    for w in WORKLOADS:
        add(smt([w], btb=4))
    for p in pairs + quads:
        add(smt(list(p), btb=4))
    # fetch policy x LSQ sharing on two contended mixes. (gem5 25.1: the
    # "Branch" fetch policy is unimplemented and Dynamic/Threshold ROB or IQ
    # sharing crash, so only these combinations are explored.)
    for mix in (("mem_chase", "int_indep"),
                ("int_dep", "fp_dep", "mem_chase", "br_random")):
        for fetch in ("RoundRobin", "IQCount", "LSQCount"):
            for lsq in ("Partitioned", "Threshold"):
                add(smt(list(mix), fetch, lsq))
                if len(mix) == 2 or fetch == "RoundRobin":   # 4 threads +
                    add(smt(list(mix), fetch, lsq, btb=4))   # IQ/LSQCount starve
    return list(runs.values())


def command(r, gem5, outdir):
    bindir = BIN_NATIVE if r.warmup_insts else BIN
    cmd = [gem5, "-d", str(outdir)]
    if r.trace and r.cpu == "o3":
        cmd.append("--debug-file=pipeview.txt")
    cmd += [str(CONFIG), "--cpu", r.cpu, "--width", str(r.width),
            "--bpred", r.bpred]
    for name, arg in r.workloads:
        cmd += ["--workload",
                shlex.quote(str(bindir / name)) + (f" {arg}" if arg else "")]
    if r.warmup_insts:
        cmd += ["--warmup-insts", str(r.warmup_insts)]
    if r.roi_cycles:
        cmd += ["--roi-cycles", str(r.roi_cycles)]
    if r.cpu == "o3":
        cmd += ["--rob", str(r.rob), "--iq", str(r.iq), "--lq", str(r.lq),
                "--sq", str(r.sq), "--smt-fetch", r.smt_fetch,
                "--smt-lsq", r.smt_lsq, "--btb-assoc", str(r.btb_assoc)]
        if r.trace:
            cmd += ["--trace-flag", "O3PipeView", "--trace-offset",
                    str(TRACE_OFFSET), "--trace-cycles", str(TRACE_CYCLES)]
    return cmd


def execute(r, gem5, force):
    final = RUNS / r.key
    if (final / "metrics.json").exists() and not force:
        return r.key, "cached", 0.0
    failed = final / "FAILED.txt"
    if (failed.exists() and "starved" in failed.read_text(errors="replace")
            and not force):
        return r.key, "skipped (known: thread starvation)", 0.0
    if final.exists():
        shutil.rmtree(final)
    # gem5 writes in a scratch dir on the Linux filesystem (writing traces
    # across /mnt/<drive> is very slow); only the small results are copied.
    outdir = SCRATCH / r.key
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True)

    t0 = time.time()
    with open(outdir / "gem5.log", "w") as log:
        rc = subprocess.run(command(r, gem5, outdir), stdout=log,
                            stderr=subprocess.STDOUT, cwd=ROOT).returncode
    dt = time.time() - t0
    stats_path = outdir / "stats.txt"
    if rc != 0 or not stats_path.exists():
        text = (outdir / "gem5.log").read_bytes().decode(errors="replace")
        text = text.replace("\0", "")
        keep = [l for l in text.splitlines()
                if any(k in l for k in ("Assertion", "panic", "fatal",
                                        "aborted"))]
        final.mkdir(parents=True)
        (final / "FAILED.txt").write_text(
            f"exit code {rc}\n" + "\n".join(keep[:5]) + "\n" + text[-800:])
        shutil.rmtree(outdir, ignore_errors=True)
        return r.key, f"FAILED (rc={rc})", dt

    nthreads = len(r.workloads)
    stats = ilp_lib.parse_stats(stats_path)
    metrics = ilp_lib.summarize(stats, nthreads, r.cpu)
    pv = outdir / "pipeview.txt"
    if pv.exists():
        metrics.update(ilp_lib.parse_pipeview(pv, CLOCK_TICKS))
    record = {"key": r.key, "config": asdict(r), "metrics": metrics,
              "wall_seconds": round(dt, 1)}
    # keep disk use small: only compressed stats + metrics + the log are kept
    final.mkdir(parents=True)
    with open(stats_path, "rb") as fi, gzip.open(final / "stats.txt.gz",
                                                  "wb") as fo:
        shutil.copyfileobj(fi, fo)
    shutil.copy(outdir / "gem5.log", final / "gem5.log")
    (final / "metrics.json").write_text(json.dumps(record, indent=1))
    shutil.rmtree(outdir, ignore_errors=True)
    return r.key, "ok", dt


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--exp", default="pipe,bpred,width,window,smt")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--gem5", default=os.environ.get(
        "GEM5_BIN", os.path.expanduser("~/gem5-ilp/build/X86/gem5.opt")))
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--limit", type=int, default=0,
                    help="run only the first N planned runs (smoke test)")
    ap.add_argument("--no-static", action="store_true",
                    help="skip runs that need the patched gem5 "
                         "(--bpred static)")
    args = ap.parse_args()

    groups = set(args.exp.split(","))
    runs = [r for r in plan() if r.group in groups]
    if args.no_static:
        runs = [r for r in runs if r.bpred != "static"]
    if args.limit:
        runs = runs[:args.limit]
    if args.list:
        for r in runs:
            print(f"{r.group:7s} {r.key}")
        print(f"{len(runs)} runs")
        return
    if not Path(args.gem5).exists():
        sys.exit(f"gem5 binary not found: {args.gem5}")
    missing = [w for d in (BIN, BIN_NATIVE) for w in WORKLOADS
               if not (d / w).exists()]
    if missing:
        sys.exit(f"workloads not built (run `make` in workloads/): {missing}")

    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"{len(runs)} runs, {args.jobs} in parallel, gem5 = {args.gem5}")
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(args.jobs) as ex:
        futs = [ex.submit(execute, r, args.gem5, args.force) for r in runs]
        for i, f in enumerate(as_completed(futs), 1):
            key, status, dt = f.result()
            failed += status.startswith("FAILED")
            print(f"[{i:3d}/{len(runs)}] {status:14s} {dt:6.1f}s  {key}",
                  flush=True)
    print(f"finished in {(time.time() - t0) / 60:.1f} min, {failed} failed")


if __name__ == "__main__":
    main()
