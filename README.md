# ILP with gem5 — Part 2 (practical exploration)

Hands-on study of instruction-level-parallelism techniques with the gem5
simulator (v25.1, x86, syscall-emulation mode): a basic pipeline, branch
prediction, multiple issue (superscalar) and simultaneous multithreading.

Everything here is scripted, so any number in the report can be regenerated.

> This repository contains the code only. `results/`, `figures/` and `report/`
> in the layout below are produced locally by the scripts (section 3) and are
> not committed.

```
ilp-gem5-part2/
├── configs/ilp_sim.py        ONE parameterised gem5 config used by every experiment
├── workloads/                9 small C kernels + Makefile (+ ROI markers)
├── patches/                  static "always not-taken" branch predictor for gem5
├── scripts/
│   ├── run_experiments.py    runs all experiments (parallel, resumable)
│   ├── make_figures.py       results -> figures/*.png and results/tables/*
│   ├── pipeline_diagram.py   gem5 O3PipeView trace -> cycle-by-cycle diagram
│   ├── showcase.sh           short runs to screenshot (stats, pipeline views)
│   ├── build_report.py       assembles report/Part2_Report.docx (numbers come from results/)
│   ├── reparse.py            recompute metrics from saved stats (no re-simulation)
│   └── ilp_lib.py            stats / trace parsing
├── results/runs/<run>/       metrics.json + stats.txt.gz + gem5.log for every run (237 + 4 starved)
├── results/tables/           CSV + Markdown tables used in the report
├── results/showcase/         full outputs of the screenshot runs
├── figures/                  charts used in the report
└── report/                   the written report
```

## 1. Prerequisites

| Need | How |
|---|---|
| gem5 built for X86 | the Week-1 build (`~/gem5`, `scons build/X86/gem5.opt`) |
| A **patched copy** of gem5 with a static predictor | step 2 below (one-time, ~30 min build) |
| gcc, make | `sudo apt install build-essential` |
| Python 3 + matplotlib, numpy, python-docx | `pip3 install --user --break-system-packages matplotlib numpy python-docx` |

Run everything **inside WSL/Linux** from this folder. Keep a copy of the repo
on the Linux side (e.g. `~/ilp`) if it lives on a Windows drive — it is faster.

## 2. One-time setup

```bash
# a) copy gem5 so the original tree stays untouched, add the predictor, build
cp -a ~/gem5 ~/gem5-ilp
bash patches/install_static_bp.sh ~/gem5-ilp
cd ~/gem5-ilp && scons build/X86/gem5.opt -j8        # ~30 min, needs ~6 GB RAM at link time
cd -

# b) build the workloads (static x86-64 binaries)
make -C workloads            # bin/    : with region-of-interest markers
make -C workloads native     # native/ : without markers (used for SMT)
```

Why the patch? Stock gem5 cannot switch branch prediction off — the
assignment's "with and without branch prediction" needs a baseline. The patch
adds `StaticNotTakenBP` (≈40 lines of C++, `patches/static_not_taken.*`): every
conditional branch is predicted not-taken. The unmodified predictors
(local 2-bit, bi-mode, tournament, TAGE-SC-L) are used as they are.

## 3. Reproduce

```bash
python3 scripts/run_experiments.py --list        # show the planned runs (241)
python3 scripts/run_experiments.py --jobs 8      # run them (resumable; ~35 min on 12 cores)
python3 scripts/make_figures.py                  # figures/ + results/tables/
bash    scripts/showcase.sh                      # screenshot runs + pipeline views
python3 scripts/build_report.py                  # report/Part2_Report.docx
```

Set `GEM5_BIN` / `GEM5_SRC` if gem5 is not in `~/gem5-ilp` / `~/gem5`.

## 4. Single runs (use these for your screenshots)

```bash
GEM5=~/gem5-ilp/build/X86/gem5.opt
W=workloads/bin

# Basic pipeline: scalar out-of-order pipeline, one instruction per stage per cycle
$GEM5 -d m5out/scalar configs/ilp_sim.py --cpu o3 --width 1 --workload $W/int_indep

# In-order pipeline (gem5 "Minor": Fetch1/Fetch2 -> Decode -> Execute)
$GEM5 -d m5out/minor configs/ilp_sim.py --cpu minor --width 1 --workload $W/int_indep

# Branch prediction off / on (same workload, same machine)
$GEM5 -d m5out/bp_static     configs/ilp_sim.py --cpu o3 --width 4 --bpred static     --workload $W/br_pattern
$GEM5 -d m5out/bp_tournament configs/ilp_sim.py --cpu o3 --width 4 --bpred tournament --workload $W/br_pattern

# Superscalar: width 1, 2, 4, 8
for w in 1 2 4 8; do $GEM5 -d m5out/w$w configs/ilp_sim.py --cpu o3 --width $w --workload $W/int_indep; done

# SMT: two threads sharing one 4-wide core (marker-free binaries, 1M-cycle window)
N=workloads/native
$GEM5 -d m5out/smt2 configs/ilp_sim.py --cpu o3 --width 4 --warmup-insts 500000 --roi-cycles 1000000 \
      --workload "$N/mem_chase 1000000000" --workload "$N/int_indep 1000000000"
```

Results are in `m5out/<run>/stats.txt`; the key lines are
`system.cpu.ipc`, `system.cpu.cpi`, `system.cpu.numCycles`,
`system.cpu.branchPred.condIncorrect` and, for SMT, `system.cpu.commitStats<N>.ipc`.

### Pipeline visualisation

```bash
bash scripts/showcase.sh scalar          # one showcase; no argument = all
# -> results/showcase/scalar_int_indep/pipeline.png        (diagram)
# -> results/showcase/scalar_int_indep/pipeline_text.txt   (gem5's own o3-pipeview.py)
```

gem5's graphical `minorview` additionally needs the GTK bindings
(`sudo apt install gir1.2-gtk-3.0`) and a display (WSLg works); then
`--debug-flags=MinorTrace` + `~/gem5/util/minorview.py <trace>`.

## 5. What each experiment varies

| Assignment item | Knob (`ilp_sim.py`) | Runs |
|---|---|---|
| Basic pipeline + metrics | `--cpu o3 --width 1` (and `--cpu minor`) | 9 workloads |
| Branch prediction | `--bpred static / local / bimode / tournament / tage` at width 1 and 4 | 9 × 5 × 2 |
| Multiple issue | `--width 1,2,4,8`; Minor width 1,2; ROB size sweep | 9 × (4 + 2 + 5) |
| SMT | 1/2/4 threads, 18 mixes, fetch policy × LSQ sharing, direct-mapped vs 4-way BTB (`--btb-assoc`) | 70 |

Memory system (all runs): 32 KiB L1I (4-way), 32 KiB L1D (8-way), 256 KiB L2
(8-way), DDR3-1600, 2 GHz core clock.

## 6. Measurement method and caveats

* **Region of interest.** Single-thread runs measure only the kernel: the
  workloads emit gem5 `work_begin/work_end` magic instructions, the config
  resets statistics at the first and dumps at the second. libc start-up and
  array set-up are excluded.
* **SMT** runs use marker-free binaries: warm up until every thread has
  committed 500 000 instructions, then measure exactly 1 000 000 cycles. (In
  gem5 25.1 an O3 SMT thread can deadlock on a marker instruction that waits
  for its stores to drain while the other thread keeps running.)
* **IPC counts x86 instructions; the pipeline moves micro-ops.** gem5 cracks
  x86 instructions into 1–3 micro-ops, so a "1-wide" core tops out at
  1 *micro-op*/cycle, i.e. IPC ≈ 0.6–0.9. The tables report both IPC and
  micro-ops per cycle (UPC).
* **Latency** = average fetch→retire time of a committed micro-op, from gem5's
  `O3PipeView` trace over a 5000-cycle window per run (O3 only).
* **Minor on x86 never predicts branches** (its Fetch2 stage only tries on
  micro-ops flagged as control, and x86 macro-ops are not) — so it serves as
  the in-order "no prediction" reference, not as a predictor testbed.
* Writeback width is kept ≥ 8 everywhere: with a small value gem5's IEW stage
  hits an internal assertion when a cache fill returns a burst of loads.
* gem5 25.1 limits on SMT: the `Branch` fetch policy is unimplemented, and
  Dynamic/Threshold sharing of the ROB or IQ crashes; only fetch policy ×
  LSQ sharing is explored. With four threads, the `IQCount`/`LSQCount` fetch
  policies starve one thread (4 runs, kept as `FAILED.txt` records).
* gem5's default BTB is direct-mapped; threads running the same code evict
  each other's entries, so every SMT experiment is reported with it and with a
  4-way BTB (`--btb-assoc 4`, the primary set).
* Static not-taken only mispredicts *taken* branches. GCC lays these loops out
  with the back-edge as a fall-through, so it is not as bad on loops as it
  would be for other code layouts.

## 7. Putting it on GitHub

```bash
cd ilp-gem5-part2
git init && git add . && git commit -m "ILP experiments with gem5"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

`workloads/bin` and `workloads/native` are build products (see `.gitignore`);
`make -C workloads` recreates them.

## 8. The report

`report/Part2_Report.docx` is generated by `scripts/build_report.py`; every
number in it is computed from `results/`. It has **six yellow boxes** where
you paste your own terminal screenshots (the checklist is also in its
Appendix A); the figures and pipeline diagrams are already embedded. Fill in
your name, course and repository link on the first page, then export to PDF.
