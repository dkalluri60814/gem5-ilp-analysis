#!/usr/bin/env python3
"""Turn results/runs/*/metrics.json into the report's figures and tables.

    python3 scripts/make_figures.py

Writes figures/*.png and results/tables/*.csv + *.md. Missing runs are
skipped, so it can be run on a partial sweep.
"""

import csv
import json
import math
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_experiments import (BPREDS, ROOT, RUNS, SMT_CYCLES, SMT_WARMUP,  # noqa
                             WORKLOADS, LONG_ARG, Run)

FIG = ROOT / "figures"
TAB = ROOT / "results" / "tables"
FIG.mkdir(exist_ok=True)
TAB.mkdir(parents=True, exist_ok=True)

# ---- style: validated categorical palette, recessive grid, text in ink ----
SURFACE, INK, INK2, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
CAT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300",
       "#6250d6", "#e34948"]
BLUE_RAMP = ["#cde2fb", "#86b6ef", "#2a78d6", "#184f95", "#0d366b"]
SEQ = LinearSegmentedColormap.from_list("seq", BLUE_RAMP)
WIDTH_SHADES = {1: "#86b6ef", 2: "#5598e7", 4: "#256abf", 8: "#104281"}

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "text.color": INK, "axes.labelcolor": INK2,
    "xtick.color": INK2, "ytick.color": INK2, "axes.edgecolor": GRID,
    "axes.grid": True, "axes.grid.axis": "y", "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
    "axes.titlecolor": INK, "legend.frameon": False,
})

PRETTY = {"int_dep": "int_dep", "int_indep": "int_indep", "fp_dep": "fp_dep",
          "fp_daxpy": "fp_daxpy", "mem_stream": "mem_stream",
          "mem_chase": "mem_chase", "br_pattern": "br_pattern",
          "br_random": "br_random", "matmul": "matmul"}
BP_LABEL = {"static": "static not-taken", "local": "local 2-bit",
            "bimode": "bi-mode", "tournament": "tournament",
            "tage": "TAGE-SC-L"}


# ---------------------------------------------------------------- data ----
def get(cpu, width, bpred, names, rob=192, iq=64, lq=32, sq=32,
        smt=False, fetch="RoundRobin", lsq="Partitioned", btb=1):
    if isinstance(names, str):
        names = [names]
    wl = [(n, LONG_ARG[n] if smt else None) for n in names]
    r = Run("x", cpu, width, bpred, wl, rob=rob, iq=iq, lq=lq, sq=sq,
            warmup_insts=SMT_WARMUP if smt else 0,
            roi_cycles=SMT_CYCLES if smt else 0,
            smt_fetch=fetch, smt_lsq=lsq, btb_assoc=btb)
    f = RUNS / r.key / "metrics.json"
    if not f.exists():
        return None
    return json.loads(f.read_text())["metrics"]


def geomean(xs):
    xs = [x for x in xs if x and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else math.nan


def save(fig, name):
    fig.savefig(FIG / name, dpi=170, bbox_inches="tight")
    plt.close(fig)
    print("wrote figures/" + name)


def write_table(name, header, rows, note=""):
    with open(TAB / f"{name}.csv", "w", newline="") as f:
        csv.writer(f).writerows([header] + rows)

    def fmt(x):
        return f"{x:.3f}" if isinstance(x, float) else str(x)
    md = ["| " + " | ".join(header) + " |",
          "|" + "|".join("---" for _ in header) + "|"]
    md += ["| " + " | ".join(fmt(x) for x in r) + " |" for r in rows]
    (TAB / f"{name}.md").write_text("\n".join(md) + "\n" + note)


def fit_ylim(ax):
    """y axis from 0 to 15% above the highest plotted value."""
    top = max((max(l.get_ydata()) for l in ax.get_lines()), default=1)
    ax.set_ylim(0, top * 1.15 if top > 0 else 1)


def panel_grid(title_fn=None, ncols=3):
    n = len(WORKLOADS)
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(11, 2.6 * nrows),
                             sharex=True)
    return fig, axes.flatten()


# ----------------------------------------------------------- 1: baseline ----
def fig_baseline():
    rows, ipc_m, ipc_o, upc_m, upc_o = [], [], [], [], []
    for w in WORKLOADS:
        o, m = get("o3", 1, "tournament", w), get("minor", 1, "tournament", w)
        if not (o and m):
            continue
        rows.append([w, round(o["uops_per_inst"], 3), m["ipc"], m["cpi"],
                     o["ipc"], o["upc"], o["cpi"], o["lat_total"],
                     o["lat_fetch_to_decode"], o["lat_decode_to_rename"],
                     o["lat_rename_to_dispatch"], o["lat_dispatch_to_issue"],
                     o["lat_issue_to_complete"], o["lat_complete_to_retire"]])
        ipc_m.append(m["ipc"]); ipc_o.append(o["ipc"])
        upc_m.append(m["upc"]); upc_o.append(o["upc"])
    if not rows:
        return
    names = [r[0] for r in rows]
    write_table("table1_baseline",
                ["workload", "uops/inst", "Minor IPC", "Minor CPI", "O3-1 IPC",
                 "O3-1 uops/cycle", "O3-1 CPI", "latency fetch->retire (cyc)",
                 "fetch->decode", "decode->rename", "rename->dispatch",
                 "dispatch->issue", "issue->complete", "complete->retire"],
                rows)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharey=False)
    x = np.arange(len(names))
    for ax, (a, b, ttl, yl) in zip(axes, [
            (ipc_m, ipc_o, "Instructions per cycle (x86 instructions)", "IPC"),
            (upc_m, upc_o, "Micro-ops per cycle (what the 1-wide pipe limits)",
             "micro-ops / cycle")]):
        ax.bar(x - 0.2, a, 0.38, color=CAT[0], label="In-order (Minor), width 1")
        ax.bar(x + 0.2, b, 0.38, color=CAT[1], label="Out-of-order (O3), width 1")
        ax.set_xticks(x); ax.set_xticklabels(names, rotation=35, ha="right")
        ax.set_title(ttl, fontsize=10); ax.set_ylabel(yl)
    axes[0].legend(fontsize=8, loc="upper left")
    fig.suptitle("Scalar pipelines: throughput per workload", x=0.01,
                 ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "fig1_baseline_pipeline.png")


# -------------------------------------------------------------- 2: width ----
def fig_width():
    widths = [1, 2, 4, 8]
    fig, axes = panel_grid()
    tab, lat_tab = [], []
    for ax, w in zip(axes, WORKLOADS):
        o = [get("o3", k, "tournament", w) for k in widths]
        m = [get("minor", k, "tournament", w) for k in (1, 2)]
        if all(o):
            ax.plot(range(4), [r["ipc"] for r in o], "-o", color=CAT[0],
                    lw=2, ms=6, label="O3 (out-of-order)")
            tab.append([w] + [r["ipc"] for r in o] +
                       [o[3]["ipc"] / o[0]["ipc"]])
            lat_tab.append([w] + [r["lat_total"] for r in o])
        if all(m):
            ax.plot([0, 1], [r["ipc"] for r in m], "s--", color=CAT[1],
                    lw=2, ms=6, label="Minor (in-order)")
        ax.set_title(w, fontsize=10, loc="left")
        ax.set_xticks(range(4)); ax.set_xticklabels(widths)
        fit_ylim(ax)
    for ax in axes[6:]:
        ax.set_xlabel("issue width")
    for ax in axes[::3]:
        ax.set_ylabel("IPC")
    axes[0].legend(fontsize=8, loc="lower right")
    fig = axes[0].figure
    fig.suptitle("IPC as the machine gets wider (1, 2, 4, 8 "
                 "instructions/cycle)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "fig2_width_scaling.png")
    write_table("table2_width_ipc",
                ["workload", "IPC w1", "IPC w2", "IPC w4", "IPC w8",
                 "speedup w8/w1"], tab)
    write_table("table2b_width_latency",
                ["workload", "lat w1", "lat w2", "lat w4", "lat w8"], lat_tab)

    # latency vs width
    if lat_tab:
        fig, ax = plt.subplots(figsize=(11, 3.6))
        x = np.arange(len(lat_tab))
        for i, k in enumerate(widths):
            ax.bar(x + (i - 1.5) * 0.2, [r[1 + i] for r in lat_tab], 0.18,
                   color=WIDTH_SHADES[k], label=f"width {k}")
        ax.set_xticks(x)
        ax.set_xticklabels([r[0] for r in lat_tab], rotation=35, ha="right")
        ax.set_ylabel("average fetch-to-retire latency (cycles)")
        ax.set_yscale("log")
        ax.legend(ncol=4, fontsize=8, loc="upper left")
        ax.set_title("Per-instruction latency grows with width and "
                     "with memory stalls", loc="left")
        save(fig, "fig3_latency_vs_width.png")


# ----------------------------------------------------------- 3: bpred ----
def fig_bpred():
    have = False
    for width in (1, 4):
        data = {bp: [get("o3", width, bp, w) for w in WORKLOADS]
                for bp in BPREDS}
        if not all(all(v) for v in data.values()):
            continue
        have = True
        rows = []
        for i, w in enumerate(WORKLOADS):
            row = [w]
            for bp in BPREDS:
                d = data[bp][i]
                row += [d["ipc"], d["mispredict_rate"], d["mpki"]]
            rows.append(row)
        hdr = ["workload"]
        for bp in BPREDS:
            hdr += [f"{bp} IPC", f"{bp} mispred", f"{bp} MPKI"]
        write_table(f"table3_bpred_width{width}", hdr, rows)

        # speedup vs static
        fig, ax = plt.subplots(figsize=(11, 3.8))
        x = np.arange(len(WORKLOADS) + 1)
        base = [d["ipc"] for d in data["static"]]
        for j, bp in enumerate(BPREDS):
            sp = [data[bp][i]["ipc"] / base[i] for i in range(len(WORKLOADS))]
            sp.append(geomean(sp))
            ax.bar(x + (j - 2) * 0.16, sp, 0.14, color=CAT[j],
                   label=BP_LABEL[bp])
        ax.axhline(1, color=MUTED, lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(WORKLOADS + ["geomean"], rotation=35, ha="right")
        ax.set_ylabel("IPC relative to static not-taken")
        ax.legend(ncol=5, fontsize=8, loc="upper center",
                  bbox_to_anchor=(0.5, -0.32))
        ax.set_title(f"Speed-up from branch prediction, "
                     f"O3 issue width {width}", loc="left")
        save(fig, f"fig4_bpred_speedup_w{width}.png")

        # misprediction heat map
        fig, ax = plt.subplots(figsize=(11, 3.1))
        mat = np.array([[data[bp][i]["mispredict_rate"] * 100
                         for i in range(len(WORKLOADS))] for bp in BPREDS])
        im = ax.imshow(mat, cmap=SEQ, aspect="auto", vmin=0,
                       vmax=max(60, mat.max()))
        ax.set_xticks(range(len(WORKLOADS)))
        ax.set_xticklabels(WORKLOADS, rotation=35, ha="right")
        ax.set_yticks(range(len(BPREDS)))
        ax.set_yticklabels([BP_LABEL[b] for b in BPREDS])
        ax.grid(False)
        for (r, c), v in np.ndenumerate(mat):
            ax.text(c, r, f"{v:.1f}", ha="center", va="center", fontsize=8,
                    color="white" if v > 30 else INK)
        ax.set_title(f"Committed-branch misprediction rate (%), "
                     f"O3 width {width}", loc="left")
        save(fig, f"fig5_mispredict_heatmap_w{width}.png")
    return have


# ----------------------------------------------------------- 4: window ----
def fig_window():
    robs = [16, 32, 64, 128, 256]
    fig, axes = panel_grid()
    rows = []
    for ax, w in zip(axes, WORKLOADS):
        d = [get("o3", 8, "tournament", w, rob=r, iq=max(8, r // 2),
                 lq=max(8, r // 4), sq=max(8, r // 4)) for r in robs]
        if all(d):
            ax.plot(range(5), [x["ipc"] for x in d], "-o", color=CAT[0],
                    lw=2, ms=6)
            rows.append([w] + [x["ipc"] for x in d])
        ax.set_title(w, fontsize=10, loc="left")
        ax.set_xticks(range(5)); ax.set_xticklabels(robs)
        fit_ylim(ax)
    for ax in axes[6:]:
        ax.set_xlabel("reorder-buffer entries")
    for ax in axes[::3]:
        ax.set_ylabel("IPC")
    fig = axes[0].figure
    fig.suptitle("How much does a bigger instruction window help? "
                 "(8-wide O3)", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, "fig6_window_size.png")
    write_table("table4_window", ["workload"] + [f"IPC rob{r}" for r in robs],
                rows)


# -------------------------------------------------------------- 5: SMT ----
def smt_failed(names, fetch="RoundRobin", lsq="Partitioned"):
    """True when the run was recorded as failed / starved (FAILED.txt)."""
    wl = [(n, LONG_ARG[n]) for n in names]
    r = Run("x", "o3", 4, "tournament", wl, warmup_insts=SMT_WARMUP,
            roi_cycles=SMT_CYCLES, smt_fetch=fetch, smt_lsq=lsq)
    return (RUNS / r.key / "FAILED.txt").exists()


def smt_get(names, fetch="RoundRobin", lsq="Partitioned", btb=1):
    return get("o3", 4, "tournament", list(names), smt=True, fetch=fetch,
               lsq=lsq, btb=btb)


def sfx(btb):
    """File-name suffix: the 4-way-BTB set is the primary one."""
    return "" if btb == 4 else "_default_btb"


def btb_name(btb):
    return "4-way BTB" if btb == 4 else "direct-mapped BTB (gem5 default)"


def fig_smt(btb=4):
    alone = {w: smt_get([w], btb=btb) for w in WORKLOADS}
    alone = {k: v for k, v in alone.items() if v}
    if not alone:
        return
    write_table(f"table5_smt_alone{sfx(btb)}", ["workload", "IPC alone", "uops/cycle"],
                [[w, a["ipc"], a["upc"]] for w, a in alone.items()])

    from run_experiments import plan
    mixes = []
    for r in plan():
        if (r.group == "smt" and len(r.workloads) > 1 and
                r.smt_fetch == "RoundRobin" and r.smt_lsq == "Partitioned"):
            mix = tuple(n for n, _ in r.workloads)
            if mix not in mixes:
                mixes.append(mix)
    rows, labels, tot, ws, nthr = [], [], [], [], []
    for mix in mixes:
        m = smt_get(mix, btb=btb)
        if not m or not all(n in alone for n in mix):
            continue
        per = [m[f"ipc_t{t}"] for t in range(len(mix))]
        weighted = sum(p / alone[n]["ipc"] for p, n in zip(per, mix))
        best_alone = max(alone[n]["ipc"] for n in mix)
        label = "+".join(mix) if len(set(mix)) > 1 else f"{len(mix)} x {mix[0]}"
        labels.append(label); tot.append(m["ipc"]); ws.append(weighted)
        nthr.append(len(mix))
        rows.append([label, len(mix)] + [round(p, 3) for p in per] +
                    [""] * (4 - len(per)) +
                    [m["ipc"], m["upc"], best_alone, m["ipc"] / best_alone,
                     weighted, m["lat_total"], m.get("rename_blocked", 0.0),
                     m["l1d_miss_rate"], m["l2_miss_rate"],
                     m["wasted_fetch_frac"]])
    write_table(f"table6_smt_mixes{sfx(btb)}",
                ["mix", "threads", "IPC t0", "IPC t1", "IPC t2", "IPC t3",
                 "total IPC", "total uops/cycle", "best alone IPC",
                 "total / best alone", "weighted speedup",
                 "avg latency (cyc)", "rename blocked (frac of cycles)",
                 "L1D miss rate", "L2 miss rate", "wasted fetch frac"],
                rows)
    if not rows:
        return
    order = np.argsort(nthr, kind="stable")
    labels = [labels[i] for i in order]; tot = [tot[i] for i in order]
    ws = [ws[i] for i in order]; nthr = [nthr[i] for i in order]
    colors = [CAT[0] if n == 2 else CAT[1] for n in nthr]
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.3 * len(labels) + 1.8),
                             sharey=True)
    y = np.arange(len(labels))
    axes[0].barh(y, tot, color=colors, height=0.62)
    axes[0].set_title("Total IPC of the SMT core", loc="left", fontsize=10)
    axes[1].barh(y, ws, color=colors, height=0.62)
    axes[1].axvline(1, color=MUTED, lw=0.8)
    axes[1].set_title("Weighted speed-up (1.0 = time-slicing)", loc="left",
                      fontsize=10)
    axes[0].set_yticks(y); axes[0].set_yticklabels(labels, fontsize=8)
    axes[0].invert_yaxis()
    for ax in axes:
        ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    for yy, v in zip(y, tot):
        axes[0].text(v + 0.02, yy, f"{v:.2f}", va="center", fontsize=7.5,
                     color=INK2)
    for yy, v in zip(y, ws):
        axes[1].text(v + 0.02, yy, f"{v:.2f}", va="center", fontsize=7.5,
                     color=INK2)
    from matplotlib.patches import Patch
    axes[1].legend(handles=[Patch(color=CAT[0], label="2 threads"),
                            Patch(color=CAT[1], label="4 threads")],
                   loc="lower right", fontsize=8)
    fig.suptitle(f"Simultaneous multithreading on a 4-wide O3 core "
                 f"({btb_name(btb)})", x=0.01, ha="left", fontweight="bold")
    fig.tight_layout()
    save(fig, f"fig7_smt_throughput{sfx(btb)}.png")


def fig_smt_policies(btb=4):
    mixes = [("mem_chase", "int_indep"),
             ("int_dep", "fp_dep", "mem_chase", "br_random")]
    fetches = ["RoundRobin", "IQCount", "LSQCount"]
    queues = ["Partitioned", "Threshold"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 2.8))
    any_data = False
    rows = []
    allv = [smt_get(mix, f, q, btb) for mix in mixes for f in fetches
            for q in queues]
    gmax = max([m["ipc"] for m in allv if m] or [1.0])   # shared colour scale
    for ax, mix in zip(axes, mixes):
        mat = np.full((len(fetches), len(queues)), np.nan)
        for i, f in enumerate(fetches):
            for j, q in enumerate(queues):
                m = smt_get(mix, f, q, btb)
                if m:
                    mat[i, j] = m["ipc"]
                    rows.append(["+".join(mix), f, q, m["ipc"],
                                 " / ".join(f"{m[f'ipc_t{t}']:.3f}"
                                            for t in range(len(mix)))])
        if np.isnan(mat).all():
            continue
        any_data = True
        ax.imshow(mat, cmap=SEQ, aspect="auto", vmin=0, vmax=gmax)
        ax.set_xticks(range(len(queues))); ax.set_xticklabels(queues)
        ax.set_yticks(range(len(fetches))); ax.set_yticklabels(fetches)
        ax.grid(False)
        for (i, j), v in np.ndenumerate(mat):
            if not np.isnan(v):
                dark = v / gmax > 0.55
                ax.text(j, i, f"{v:.3f}", ha="center", va="center",
                        fontsize=9, color="white" if dark else INK)
            elif smt_failed(mix, fetches[i], queues[j]) and btb == 1:
                ax.text(j, i, "thread starved\n(no result)", ha="center",
                        va="center", fontsize=8, color=INK2, style="italic")
                rows.append(["+".join(mix), fetches[i], queues[j],
                             "starved", ""])
        ax.set_title("+".join(mix), fontsize=9, loc="left")
        ax.set_xlabel("load/store-queue sharing policy")
    axes[0].set_ylabel("SMT fetch policy")
    if any_data:
        fig.suptitle(f"Total IPC under different SMT fetch and "
                     f"LSQ-sharing policies ({btb_name(btb)})", x=0.01,
                     ha="left", fontweight="bold")
        fig.tight_layout()
        save(fig, f"fig8_smt_policies{sfx(btb)}.png")
        write_table(f"table7_smt_policies{sfx(btb)}",
                    ["mix", "fetch policy", "LSQ sharing", "total IPC",
                     "per-thread IPC"], rows)
    else:
        plt.close(fig)


def fig_btb():
    mixes = [("int_indep",) * 2, ("int_indep",) * 4, ("int_dep",) * 2,
             ("matmul",) * 2, ("matmul",) * 4]
    rows, labels, a, b, alone = [], [], [], [], []
    for mix in mixes:
        d1, d4 = smt_get(mix), smt_get(mix, btb=4)
        al = smt_get([mix[0]])
        if not (d1 and d4 and al):
            continue
        label = f"{len(mix)} x {mix[0]}"
        labels.append(label); a.append(d1["ipc"]); b.append(d4["ipc"])
        alone.append(al["ipc"])
        rows.append([label, al["ipc"], d1["ipc"], d1["btb_hit_ratio"],
                     d1["mispredict_rate"], d4["ipc"], d4["btb_hit_ratio"],
                     d4["mispredict_rate"]])
    if not rows:
        return
    write_table("table8_smt_btb",
                ["mix", "IPC alone", "IPC direct-mapped BTB", "BTB hit ratio",
                 "mispredict rate", "IPC 4-way BTB", "BTB hit ratio (4-way)",
                 "mispredict rate (4-way)"], rows)
    fig, ax = plt.subplots(figsize=(11, 3.4))
    x = np.arange(len(labels))
    ax.bar(x - 0.2, a, 0.38, color=CAT[0], label="direct-mapped BTB (gem5 default)")
    ax.bar(x + 0.2, b, 0.38, color=CAT[1], label="4-way BTB")
    for xi, v in zip(x, alone):
        ax.plot([xi - 0.4, xi + 0.4], [v, v], color=INK, lw=1.2)
    ax.plot([], [], color=INK, lw=1.2, label="same program, one thread alone")
    ax.set_xticks(x); ax.set_xticklabels(labels)
    ax.set_ylabel("total IPC")
    ax.legend(fontsize=8, ncol=3, loc="upper center",
              bbox_to_anchor=(0.5, -0.12))
    ax.set_title("Threads running the same code fight over a "
                 "direct-mapped BTB", loc="left")
    save(fig, "fig9_smt_btb.png")


def main():
    fig_baseline()
    fig_width()
    fig_bpred()
    fig_window()
    for btb in (4, 1):
        fig_smt(btb)
        fig_smt_policies(btb)
    fig_btb()


if __name__ == "__main__":
    main()
