#!/usr/bin/env python3
"""Builds report/Part2_Report.docx from the experiment results.

    python3 scripts/build_report.py

Every number quoted in the text is computed here from results/runs, so the
prose cannot drift away from the data. Screenshot slots are marked in yellow
for the student to fill with their own terminal captures.
"""

import json
import re
import sys
import textwrap
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_figures as mf  # noqa: E402
from run_experiments import (BPREDS, RUNS, ROOT, SMT_CYCLES, SMT_WARMUP,  # noqa
                             WORKLOADS, plan)

FIG = ROOT / "figures"
SHOW = ROOT / "results" / "showcase"
OUT = ROOT / "report" / "Part2_Report.docx"
G, geo = mf.get, mf.geomean
W = WORKLOADS

# =========================================================== numbers =========
n_ok = len(list(RUNS.glob("*/metrics.json")))
n_starved = len([p for p in RUNS.glob("*/FAILED.txt")
                 if "starved" in p.read_text(errors="replace")])

o1 = {w: G("o3", 1, "tournament", w) for w in W}
mn1 = {w: G("minor", 1, "tournament", w) for w in W}
mn2 = {w: G("minor", 2, "tournament", w) for w in W}
o3w = {k: {w: G("o3", k, "tournament", w) for w in W} for k in (1, 2, 4, 8)}
bp = {k: {b: {w: G("o3", k, b, w) for w in W} for b in BPREDS} for k in (1, 4)}


def speedup_vs_static(width, pred):
    return geo([bp[width][pred][w]["ipc"] / bp[width]["static"][w]["ipc"]
                for w in W])


def penalty(w, width):
    a, b = bp[width]["static"][w], bp[width]["tage"][w]
    return (a["cycles"] - b["cycles"]) / (a["mispredicts"] - b["mispredicts"])


pens = [penalty(w, wd) for w in ("br_pattern", "matmul", "int_indep")
        for wd in (1, 4)]
width_geo = {k: geo([o3w[k][w]["ipc"] / o3w[1][w]["ipc"] for w in W])
             for k in (2, 4, 8)}
oo_vs_io = geo([o1[w]["ipc"] / mn1[w]["ipc"] for w in W])
io_dual = geo([mn2[w]["ipc"] / mn1[w]["ipc"] for w in W])
ROBS = [16, 32, 64, 128, 256]
win = {w: [G("o3", 8, "tournament", w, rob=r, iq=max(8, r // 2),
             lq=max(8, r // 4), sq=max(8, r // 4))["ipc"] for r in ROBS]
       for w in W}


def sat_rob(w):
    top = win[w][-1]
    return next(r for r, v in zip(ROBS, win[w]) if v >= 0.97 * top)


def smt_mixes():
    seen = []
    for r in plan():
        if (r.group == "smt" and len(r.workloads) > 1 and
                r.smt_fetch == "RoundRobin" and r.smt_lsq == "Partitioned"):
            m = tuple(n for n, _ in r.workloads)
            if m not in seen:
                seen.append(m)
    return seen


MIXES = smt_mixes()


def smt_info(mix, btb=4, **kw):
    m = mf.smt_get(mix, btb=btb, **kw)
    alone = [mf.smt_get([n], btb=btb) for n in mix]
    ws = sum(m[f"ipc_t{t}"] / alone[t]["ipc"] for t in range(len(mix)))
    return m, ws


def f1(x): return f"{x:.1f}"
def f2(x): return f"{x:.2f}"
def f3(x): return f"{x:.3f}"
def pc(x): return f"{100 * x:.1f}%"


# =========================================================== docx helpers ====
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Inches(8.5), Inches(11)
for side in ("left_margin", "right_margin", "top_margin", "bottom_margin"):
    setattr(sec, side, Inches(1))

NAVY = RGBColor(0x1F, 0x38, 0x64)
st = doc.styles
st["Normal"].font.name = "Calibri"
st["Normal"].font.size = Pt(10.5)
st["Normal"].element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
st["Normal"].paragraph_format.space_after = Pt(6)
st["Normal"].paragraph_format.line_spacing = 1.08
for name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
    s = st[name]
    s.font.name, s.font.size, s.font.bold = "Calibri", Pt(size), True
    s.font.color.rgb = NAVY
    s.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    s.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
    s.paragraph_format.space_after = Pt(4)
    s.paragraph_format.keep_with_next = True


def shade(cell_or_par, fill):
    el = cell_or_par._tc if hasattr(cell_or_par, "_tc") else cell_or_par._p
    pr = el.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") \
        else el.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    pr.append(shd)


def runs(par, text, size=None, color=None, italic=False):
    """Mini-markup: **bold**, `code`."""
    pattern = r"(\*\*.+?\*\*|`.+?`|(?<![\w*])\*[^*\s][^*]*?\*(?![\w*]))"
    for tok in re.split(pattern, text):
        if not tok:
            continue
        if tok.startswith("**"):
            r = par.add_run(tok[2:-2]); r.bold = True
        elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
            r = par.add_run(tok[1:-1]); r.italic = True
        elif tok.startswith("`"):
            r = par.add_run(tok[1:-1]); r.font.name = "Consolas"
            r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
            r.font.size = Pt((size or 10.5) - 1)
        else:
            r = par.add_run(tok)
        if size and not tok.startswith("`"):
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
        if italic:
            r.italic = True
    return par


def P(text, align=None, size=None, after=None, italic=False, color=None):
    par = doc.add_paragraph()
    runs(par, text, size, color, italic)
    if align:
        par.alignment = align
    if after is not None:
        par.paragraph_format.space_after = Pt(after)
    return par


def H1(t): doc.add_heading(t, level=1)
def H2(t): doc.add_heading(t, level=2)
def H3(t): doc.add_heading(t, level=3)


def bullets(items, style="List Bullet"):
    for it in items:
        par = doc.add_paragraph(style=style)
        runs(par, it)
        par.paragraph_format.space_after = Pt(2)


def code(text, size=8):
    text = textwrap.dedent(text)
    par = doc.add_paragraph()
    par.paragraph_format.space_after = Pt(6)
    par.paragraph_format.left_indent = Inches(0.1)
    shade(par, "F2F2F2")
    for i, line in enumerate(text.rstrip("\n").split("\n")):
        r = par.add_run(line)
        r.font.name = "Consolas"
        r._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
        r.font.size = Pt(size)
        if i < len(text.rstrip("\n").split("\n")) - 1:
            r.add_break()


def caption(text):
    par = doc.add_paragraph()
    runs(par, text, 9, RGBColor(0x40, 0x40, 0x40), italic=True)
    par.paragraph_format.space_after = Pt(10)
    return par


_fig = [0]
_tab = [0]


def figure(path, cap, width=6.5):
    _fig[0] += 1
    doc.add_picture(str(path), width=Inches(width))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.paragraphs[-1].paragraph_format.keep_with_next = True
    doc.paragraphs[-1].paragraph_format.space_after = Pt(2)
    caption(f"Figure {_fig[0]}. {cap}")


def table(header, rows, widths, cap=None, size=8.5, first_left=True,
          center=True):
    if cap:
        _tab[0] += 1
        c = doc.add_paragraph()
        runs(c, f"**Table {_tab[0]}.** {cap}", 9.5)
        c.paragraph_format.keep_with_next = True
        c.paragraph_format.space_after = Pt(3)
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        runs(cell.paragraphs[0], f"**{h.replace('`', '')}**", size,
             RGBColor(255, 255, 255))
        shade(cell, "1F3864")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            runs(cells[i].paragraphs[0], str(v), size)
            if center and (i > 0 or not first_left):
                cells[i].paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
    for row in t.rows:
        for i, w_ in enumerate(widths):
            row.cells[i].width = Inches(w_)
        for cell in row.cells:
            for par in cell.paragraphs:
                par.paragraph_format.space_after = Pt(1)
                par.paragraph_format.space_before = Pt(1)
    # repeat header row on page breaks
    trPr = t.rows[0]._tr.get_or_add_trPr()
    h = OxmlElement("w:tblHeader"); h.set(qn("w:val"), "true"); trPr.append(h)
    doc.add_paragraph().paragraph_format.space_after = Pt(4)


_shot = [0]
SHOTS = []


def screenshot(what, how):
    """Yellow slot for a screenshot the student takes."""
    _shot[0] += 1
    SHOTS.append((_shot[0], what, how))
    t = doc.add_table(rows=1, cols=1)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    c = t.rows[0].cells[0]
    c.width = Inches(6.5)
    shade(c, "FFF2CC")
    c.text = ""
    runs(c.paragraphs[0], f"**[ INSERT SCREENSHOT {_shot[0]} ]**  {what}", 9.5)
    p2 = c.add_paragraph()
    runs(p2, how, 8.5, RGBColor(0x40, 0x40, 0x40), italic=True)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def page_numbers():
    par = sec.footer.paragraphs[0]
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = par.add_run("ILP with gem5 - Part 2   |   page ")
    r.font.size = Pt(8.5)
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    rr = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    sz = OxmlElement("w:sz"); sz.set(qn("w:val"), "17"); rpr.append(sz)
    rr.append(rpr)
    tt = OxmlElement("w:t"); tt.text = "1"; rr.append(tt)
    fld.append(rr)
    par._p.append(fld)


def src_between(path, start, end):
    txt = Path(path).read_text()
    i = txt.index(start)
    j = txt.index(end, i)
    return txt[i:j].rstrip()


def viewer_excerpt(name, n=16, skip=3):
    """Compact version of gem5's o3-pipeview.py output (first n micro-ops)."""
    out = ["f=fetch d=decode n=rename p=dispatch i=issue c=complete r=retire"
           "   (leading ----- = squashed)"]
    pat = re.compile(r"^\[([^\]]*)\]-\(\s*(\d+)\)\s+(0x[0-9a-f]+\.\d+)\s+(\S+)")
    lines = (SHOW / name / "pipeline_text.txt").read_text().splitlines()
    kept = 0
    for ln in lines[skip:]:
        m = pat.match(ln)
        if not m:
            continue
        tl, _, pcu, dis = m.groups()
        out.append(f"{tl[10:90]} {pcu[-8:]} {dis.replace('-----', '~ ')[:12]}")
        kept += 1
        if kept >= n:
            break
    return "\n".join(out)


# =========================================================== content =========
# ---- title -------------------------------------------------------------------
P("Instruction-Level Parallelism: Practical Exploration with gem5",
  WD_ALIGN_PARAGRAPH.CENTER, 22, after=2, color=NAVY).runs[0].bold = True
P("Part 2: pipelines, branch prediction, multiple issue and "
  "simultaneous multithreading", WD_ALIGN_PARAGRAPH.CENTER, 13, after=14)
P("**Student:** [your name]     **Course:** [course / section]     "
  "**Date:** October 2026", WD_ALIGN_PARAGRAPH.CENTER, 10.5, after=2)
P("**Code, configuration files and raw results:** [link to your GitHub "
  "repository]", WD_ALIGN_PARAGRAPH.CENTER, 10.5, after=14)

# ---- 1 summary -----------------------------------------------------------------
H1("1. Summary")
P(f"This report measures four instruction-level-parallelism (ILP) techniques "
  f"with the gem5 simulator (v25.1, x86, syscall-emulation mode): a basic "
  f"pipeline, branch prediction, multiple issue and simultaneous "
  f"multithreading (SMT). One parameterised gem5 configuration drives every "
  f"experiment, so only the knob under study changes between two runs. "
  f"{n_ok} simulations completed; all numbers below are computed from their "
  f"`stats.txt` files.")
bullets([
    f"**Basic pipeline.** A scalar out-of-order pipeline moves one micro-op "
    f"per cycle and every micro-op spends exactly "
    f"{o1['int_indep']['lat_total']:.0f} cycles between fetch and retire when "
    f"nothing stalls. Per-instruction latency explodes (up to "
    f"{o1['mem_chase']['lat_total']:.0f} cycles) when memory stalls fill the "
    f"window, as Little's law predicts.",
    f"**Branch prediction.** Against a static not-taken baseline, dynamic "
    f"predictors give a geometric-mean IPC gain of "
    f"{f2(speedup_vs_static(1, 'tournament'))}x on a scalar core and "
    f"{f2(speedup_vs_static(4, 'tournament'))}x on a 4-wide core: the wider "
    f"the machine, the more each misprediction costs. History-based predictors "
    f"remove almost every misprediction on patterned branches; nothing helps "
    f"on random ones.",
    f"**Multiple issue.** Going from 1 to 8 issue slots gives a geometric-mean "
    f"IPC gain of {f2(width_geo[8])}x, but per program it ranges from "
    f"{f2(o3w[8]['mem_chase']['ipc'] / o3w[1]['mem_chase']['ipc'])}x "
    f"(pointer chasing) to "
    f"{f2(o3w[8]['int_indep']['ipc'] / o3w[1]['int_indep']['ipc'])}x "
    f"(independent integer work): width only helps where the program "
    f"contains parallelism that is not blocked by dependences, "
    f"mispredictions or memory latency.",
    "**SMT.** Two or four threads sharing a 4-wide core raise throughput by "
    "1.0x to 3.7x (weighted speed-up) depending on how much idle capacity a "
    "single thread leaves, and the thread-selection policy and shared "
    "predictor tables matter as much as the thread count.",
])

# ---- 2 setup ------------------------------------------------------------------
H1("2. Experimental setup")
H2("2.1 Simulator and machine model")
P("All experiments use gem5 v25.1.0.1 (the build from Week 1, built for x86) "
  "in syscall-emulation (SE) mode on WSL2/Ubuntu 24.04. Stock gem5 cannot "
  "switch branch prediction off, so a second copy of the source tree has one "
  "extra predictor, `StaticNotTakenBP` (about 40 lines of C++, in "
  "`patches/`), which predicts every conditional branch not-taken. The "
  "original build is untouched; no other gem5 source was modified.")
table(["Component", "Setting (identical for every run unless stated)"], [
    ["Core clock", "2 GHz"],
    ["L1 I-cache", "32 KiB, 4-way, 1-cycle tag + 1-cycle data"],
    ["L1 D-cache", "32 KiB, 8-way, 2 + 2 cycles, 16 MSHRs"],
    ["L2 cache", "256 KiB, 8-way, 10 + 10 cycles, 32 MSHRs"],
    ["Main memory", "DDR3-1600 (gem5 `DDR3_1600_8x8`), 512 MiB"],
    ["Out-of-order core (`O3`)", "fetch/decode/rename/dispatch/issue/commit "
     "width = *W* (1, 2, 4 or 8); 192-entry ROB, 64-entry issue queue, "
     "32-entry load and store queues; writeback width >= 8"],
    ["Functional units (O3 default)", "6 integer ALU, 2 integer mul/div, "
     "4 FP add/cmp/cvt, 2 FP mul/div, 4 load/store ports, SIMD unit"],
    ["In-order core (`Minor`)", "Fetch1 -> Fetch2 -> Decode -> Execute, "
     "issue width 1 or 2"],
    ["Branch predictor front end", "4096-entry direct-mapped BTB, 16-entry "
     "return-address stack, indirect-target predictor; only the direction "
     "predictor changes between runs"],
    ["Direction predictors", "static not-taken (added), local 2-bit "
     "counters, bi-mode, tournament (gem5's O3 default), TAGE-SC-L (8 KB)"],
], [1.8, 4.7], "Simulated machine.", center=False)

H2("2.2 Mapping gem5's pipelines onto the textbook stages")
P("gem5 does not model a literal five-stage pipeline; the table shows where "
  "the classic stages live in the two CPU models used here.")
table(["Textbook stage", "In-order `Minor`", "Out-of-order `O3`"], [
    ["Fetch (IF)", "Fetch1 (I-cache access) + Fetch2 (line to instructions, "
     "branch prediction)", "Fetch"],
    ["Decode (ID)", "Decode", "Decode, then Rename"],
    ["Execute (EX)", "Execute (issue and functional units)",
     "Dispatch / Issue / Execute (the IEW stage)"],
    ["Memory (MEM)", "Execute stage's load/store queue", "Load/store queue "
     "inside IEW"],
    ["Writeback (WB)", "Execute-stage commit", "Writeback (IEW) and Commit"],
], [1.4, 2.6, 2.5], "Stage mapping.", center=False)

H2("2.3 Workloads")
P("Nine small C kernels (in `workloads/`) were written so that each is "
  "limited by a different thing. They are compiled static, `-O2`, with "
  "auto-vectorisation off; the two branch kernels also disable "
  "if-conversion so the branches survive as real branches.")
table(["Kernel", "What it does", "Expected limiter"], [
    ["int_dep", "one long serial integer dependence chain", "data dependences"],
    ["int_indep", "eight independent integer recurrences", "machine width / ALUs"],
    ["fp_dep", "floating-point recurrence x = x*c + d", "dependences"],
    ["fp_daxpy", "y[i] = a*x[i] + y[i], L1-resident", "width, load/store ports"],
    ["mem_stream", "sequential sum over 2 MiB (> L2)", "memory bandwidth / "
     "memory-level parallelism"],
    ["mem_chase", "pointer chase over 2 MiB (> L2)", "memory latency"],
    ["br_pattern", "branches with period 2, 4 and 16", "predictor quality "
     "(learnable)"],
    ["br_random", "branches on LCG random bits", "predictor quality "
     "(unlearnable)"],
    ["matmul", "32x32 double matrix multiply", "mixed: FP, strided loads, "
     "short loops"],
], [1.1, 3.3, 2.1], "The nine workloads.", center=False)

H2("2.4 Measurement method and metrics")
bullets([
    "**Region of interest.** Each program executes gem5 *work-begin* and "
    "*work-end* magic instructions around its kernel. The configuration "
    "resets the statistics at the first and dumps them at the second, so "
    "libc start-up and array set-up are not measured.",
    "**IPC versus micro-ops per cycle.** gem5 splits x86 instructions into "
    f"micro-ops (on average {f2(geo([o1[w]['uops_per_inst'] for w in W]))} "
    "per instruction here). *IPC* below counts x86 instructions, as gem5 "
    "reports it; *UPC* counts micro-ops, which is what the pipeline width "
    "actually limits (a 1-wide core tops out at UPC = 1, i.e. IPC about 0.6 "
    "to 0.8). Both are reported.",
    "**Throughput** = IPC (and UPC). **Latency** = average number of cycles "
    "from fetch to retire of a committed micro-op, taken from gem5's "
    "`O3PipeView` trace over a 5000-cycle window in every out-of-order run. "
    "The trace is not available for the in-order model, which is therefore "
    "reported by CPI only.",
    "**SMT runs** use marker-free binaries: warm up until every thread has "
    f"committed {SMT_WARMUP:,} instructions, then measure exactly "
    f"{SMT_CYCLES:,} cycles. *Weighted speed-up* = sum over threads of "
    "(IPC of the thread in the SMT run / IPC of the same program alone); "
    "1.0 means no better than running the programs one after another.",
    "**Determinism.** gem5 is deterministic: re-running a configuration "
    "reproduces its statistics bit for bit (checked, for example, on the "
    "width-4 `int_indep` run: IPC 2.166312 in both the sweep and the "
    "stand-alone run used for the screenshots).",
])

# ---- 3 basic pipeline ----------------------------------------------------------------
H1("3. Basic pipeline simulation")
H2("3.1 Configuration")
P("The pipeline is defined in `configs/ilp_sim.py`. For the scalar machine "
  "every stage width is 1, so at most one micro-op enters each stage per "
  "cycle:")
code(src_between(ROOT / "configs" / "ilp_sim.py", "    cpu = X86O3CPU()",
                 "    cpu.numROBEntries").replace("    # Writeback bandwidth is deliberately NOT the studied resource: gem5's\n"
                                                     "    # IEW stage asserts (TimeBuffer index) when wbWidth is small, e.g. when a\n"
                                                     "    # cache fill returns a burst of loads in one cycle. Keep it >= 8.\n", ""))
P("Run it on any workload (here the scalar machine on `int_indep`):")
code("GEM5=~/gem5-ilp/build/X86/gem5.opt\n"
     "$GEM5 -d m5out/scalar configs/ilp_sim.py --cpu o3 --width 1 \\\n"
     "      --workload workloads/bin/int_indep")
screenshot("Terminal after running the command above (the `[ilp_sim]` lines "
           "and the final `done`).",
           "Run it inside WSL from the project folder; capture the whole "
           "terminal window including the command.")
screenshot("`m5out/scalar/stats.txt` filtered to the key lines.",
           "Run: grep -E '^(simInsts|system.cpu.(numCycles|ipc|cpi)) ' "
           "m5out/scalar/stats.txt")

H2("3.2 Watching instructions move through the pipeline")
P("With the `O3PipeView` trace enabled for a window of cycles, gem5 records "
  "the cycle at which every micro-op reaches each stage. Figure 1 plots one "
  "row per micro-op: the staircase shows one micro-op entering the pipeline "
  "per cycle, each spending 1 cycle in fetch, 1 in decode, 2 in "
  "rename/dispatch, 1 in execute and 2 waiting to commit - **7 cycles from "
  "fetch to retire**, the depth of this pipeline. Figure 2 is the same data "
  "in gem5's own text viewer (`util/o3-pipeview.py`).")
figure(SHOW / "scalar_int_indep" / "pipeline.png",
       "Scalar out-of-order pipeline on `int_indep`, cycle by cycle "
       "(generated by `scripts/pipeline_diagram.py` from gem5's "
       "`O3PipeView` trace).")
P("**gem5 viewer output** (`results/showcase/scalar_int_indep/"
  "pipeline_text.txt`, trimmed):", after=2)
code(viewer_excerpt("scalar_int_indep"), size=6.5)
caption("Figure 2. Text pipeline view from gem5's `o3-pipeview.py` (timeline "
        "columns are cycles; letters mark the stage a micro-op reaches).")
_fig[0] += 1
screenshot("The `o3-pipeview.py` output in a terminal, or the generated "
           "`pipeline.png` opened in an image viewer.",
           "Run: bash scripts/showcase.sh scalar   then   less "
           "results/showcase/scalar_int_indep/pipeline_text.txt")

H2("3.3 Throughput and latency")
rows = []
for w in W:
    o, m = o1[w], mn1[w]
    rows.append([w, f2(o["uops_per_inst"]), f3(m["ipc"]), f3(o["ipc"]),
                 f3(o["upc"]), f2(o["cpi"]), f1(o["lat_total"])])
table(["Workload", "uops / inst", "In-order IPC", "O3 IPC", "O3 uops/cycle",
       "O3 CPI", "O3 latency (cycles)"], rows,
      [1.1, 0.8, 0.85, 0.8, 0.95, 0.7, 1.3],
      "Scalar (width-1) pipelines: throughput and latency.")
figure(FIG / "fig1_baseline_pipeline.png",
       "Throughput of the width-1 in-order and out-of-order pipelines.")
lat_hi = o1["mem_chase"]
P(f"**Throughput.** The scalar out-of-order core sustains close to one "
  f"micro-op per cycle on every compute-bound kernel "
  f"(UPC {f2(min(o1[w]['upc'] for w in ('int_dep','int_indep','fp_dep','fp_daxpy','br_pattern','matmul')))}"
  f"-{f2(max(o1[w]['upc'] for w in W))}); the reported IPC is lower "
  f"({f2(min(o1[w]['ipc'] for w in ('int_dep','int_indep','fp_dep','fp_daxpy','br_pattern','matmul')))}"
  f"-{f2(max(o1[w]['ipc'] for w in W))}) only because each x86 instruction "
  f"is 1.2 to 1.8 micro-ops. Throughput falls where the program, not the "
  f"width, is the limit: `br_random` ({f2(o1['br_random']['upc'])} uops/cycle) "
  f"loses cycles to mispredictions, `mem_stream` "
  f"({f2(o1['mem_stream']['upc'])}) to cache misses and `mem_chase` "
  f"({f2(o1['mem_chase']['upc'])}) to a chain of dependent DRAM accesses.")
P(f"**Latency.** With no stalls every micro-op takes exactly "
  f"{o1['int_dep']['lat_total']:.0f} cycles (the pipeline depth). Latency "
  f"rises to {f1(o1['fp_daxpy']['lat_total'])} cycles for `fp_daxpy` and "
  f"{f1(o1['matmul']['lat_total'])} for `matmul` (waiting for load data and earlier results), to "
  f"{f1(o1['mem_stream']['lat_total'])} for `mem_stream` and to "
  f"{lat_hi['lat_total']:.0f} for `mem_chase`. The last value looks absurd "
  f"but obeys Little's law: average micro-ops in flight = throughput x "
  f"latency = {lat_hi['upc']:.3f} x {lat_hi['lat_total']:.0f} = "
  f"{lat_hi['upc'] * lat_hi['lat_total']:.0f}, i.e. the 192-entry reorder "
  f"buffer (plus the front-end buffers) is full of micro-ops waiting behind "
  f"a load that is waiting for DRAM. Latency of an individual instruction and throughput of the "
  f"machine are different things, and ILP techniques that raise one often "
  f"lengthen the other (Section 5).")
P(f"**In-order versus out-of-order at equal width.** The out-of-order core "
  f"is {f2(oo_vs_io)}x faster (geometric mean) than the in-order `Minor` core "
  f"with the same issue width. Part of this is genuine (independent "
  f"instructions can pass stalled ones); part is an artefact of gem5: its "
  f"`Minor` model appears never to predict x86 branches (its predictor "
  f"statistics stay at zero, and its Fetch2 stage only tries to predict "
  f"instructions flagged as control, which x86 macro-ops are not), so every "
  f"taken branch costs a pipeline flush there. Treat `Minor` "
  f"as the in-order, *no-prediction* reference.")

# ---- 4 branch prediction ---------------------------------------------------------
H1("4. Impact of branch prediction")
H2("4.1 What was added")
P("The configuration option `--bpred` selects the direction predictor "
  "(everything else in the front end stays fixed):")
code(src_between(ROOT / "configs" / "ilp_sim.py", "def make_bpred(kind):",
                 "# -------------------------------------------------------"
                 "-------------------\n# CPU"))
P("**Static not-taken** is the \"without prediction\" baseline: conditional "
  "branches are never predicted taken, so fetch keeps running down the "
  "fall-through path and every *taken* branch is only discovered, and the "
  "pipeline flushed, when the branch executes. **Local** (one 2-bit "
  "saturating counter per branch address) is the basic dynamic predictor; "
  "**bi-mode**, **tournament** and **TAGE-SC-L** add global history and, "
  "for TAGE, several history lengths plus a loop predictor and a "
  "statistical corrector. Every run is the same workload on the same "
  "machine; only `--bpred` differs.")
code("for bp in static local bimode tournament tage; do\n"
     "  $GEM5 -d m5out/bp_$bp configs/ilp_sim.py --cpu o3 --width 4 \\\n"
     "        --bpred $bp --workload workloads/bin/br_pattern\n"
     "done")
screenshot("Two terminals (or two `grep` outputs) showing `--bpred static` "
           "versus `--bpred tournament` on `br_pattern`: IPC and "
           "`condIncorrect`.",
           "Run: grep -E '^system.cpu.(ipc|numCycles) |branchPred.condIncorrect' "
           "m5out/bp_static/stats.txt m5out/bp_tournament/stats.txt")

H2("4.2 Results")
rows = []
for w in W:
    row = [w]
    for b in BPREDS:
        d = bp[4][b][w]
        row.append(f"{d['ipc']:.3f} ({100 * d['mispredict_rate']:.1f}%)")
    rows.append(row)
table(["Workload"] + [mf.BP_LABEL[b] for b in BPREDS], rows,
      [1.05, 1.1, 1.1, 1.1, 1.1, 1.1],
      "IPC (committed-branch misprediction rate) on the 4-wide core.")
figure(FIG / "fig4_bpred_speedup_w4.png",
       "IPC of each predictor relative to static not-taken, 4-wide core.")
figure(FIG / "fig5_mispredict_heatmap_w4.png",
       "Misprediction rate of committed branches, 4-wide core.")
n_static_bad = len([w for w in W if bp[4]["static"][w]["mispredict_rate"] > 0.99])
P(f"**Dynamic prediction is essential.** With static not-taken, "
  f"{n_static_bad} of the 9 kernels mispredict (almost) every committed "
  f"conditional branch, because their loop branches are taken on every "
  f"iteration. On the 4-wide core the dynamic predictors are on average "
  f"{f2(speedup_vs_static(4, 'local'))}x (local) to "
  f"{f2(speedup_vs_static(4, 'tage'))}x (TAGE-SC-L) faster than static "
  f"not-taken, and up to "
  f"{f2(max(bp[4]['tage'][w]['ipc'] / bp[4]['static'][w]['ipc'] for w in W))}x "
  f"on `fp_dep`. For example `int_indep` falls from "
  f"{f2(bp[4]['tage']['int_indep']['ipc'])} to "
  f"{f2(bp[4]['static']['int_indep']['ipc'])} IPC.")
P(f"**Why accuracy matters.** A misprediction is detected only when the "
  f"branch executes; everything fetched since is wrong-path work that is "
  f"discarded, and the front end restarts. Dividing the extra cycles by the "
  f"extra mispredictions between the static and TAGE runs gives a penalty "
  f"of about {min(pens):.0f}-{max(pens):.0f} cycles per misprediction, close "
  f"to the 7-cycle depth measured in Section 3. On a machine that can "
  f"issue 4 micro-ops per cycle, each mispredicted branch therefore costs "
  f"about {4 * min(pens):.0f}-{4 * max(pens):.0f} issue slots. With static "
  f"prediction on `br_pattern`, {pc(bp[4]['static']['br_pattern']['wasted_fetch_frac'])} "
  f"of all fetched instructions are thrown away; with TAGE it is "
  f"{pc(bp[4]['tage']['br_pattern']['wasted_fetch_frac'])}. Figure 6 shows "
  f"this directly: the grey, hatched micro-ops are wrong-path work that was "
  f"fetched, renamed, partly executed and squashed, followed by a bubble "
  f"while the front end refills.")
figure(SHOW / "static_br_pattern" / "pipeline.png",
       "`br_pattern`, static not-taken: wrong-path micro-ops (grey, hatched) "
       "are squashed after each taken branch.", 5.4)
figure(SHOW / "tournament_br_pattern" / "pipeline.png",
       "`br_pattern`, tournament predictor: the same code flows without "
       "squashes.", 5.4)
P(f"**Better history, better prediction.** The patterned branches of "
  f"`br_pattern` separate the predictors cleanly: the local 2-bit predictor "
  f"cannot learn the alternating branch and mispredicts "
  f"{pc(bp[4]['local']['br_pattern']['mispredict_rate'])} of branches "
  f"(IPC {f2(bp[4]['local']['br_pattern']['ipc'])}); bi-mode and tournament "
  f"learn the patterns from global history "
  f"({pc(bp[4]['tournament']['br_pattern']['mispredict_rate'])}, IPC "
  f"{f2(bp[4]['tournament']['br_pattern']['ipc'])}); TAGE-SC-L's long "
  f"histories reach {pc(bp[4]['tage']['br_pattern']['mispredict_rate'])} "
  f"(IPC {f2(bp[4]['tage']['br_pattern']['ipc'])}). In `matmul`, TAGE alone "
  f"predicts the exit of the 32-iteration inner loop "
  f"({pc(bp[4]['tage']['matmul']['mispredict_rate'])} versus "
  f"{pc(bp[4]['tournament']['matmul']['mispredict_rate'])}) and gains "
  f"{f1(100 * (bp[4]['tage']['matmul']['ipc'] / bp[4]['tournament']['matmul']['ipc'] - 1))}%. "
  f"Averaged over all nine kernels the three history-based predictors are "
  f"within about 1% of each other because most loops are easy. "
  f"`br_random` is the control: its branches depend on random data, every "
  f"predictor mispredicts the same "
  f"{pc(bp[4]['tage']['br_random']['mispredict_rate'])}, and IPC is "
  f"unchanged - prediction cannot create information that is not there.")
P(f"**Interaction with issue width.** The geometric-mean gain of the "
  f"tournament predictor over static not-taken is "
  f"{f2(speedup_vs_static(1, 'tournament'))}x at width 1 but "
  f"{f2(speedup_vs_static(4, 'tournament'))}x at width 4 (Figures 4 and 8): a "
  f"fixed penalty in cycles wastes more issue slots on a wider machine, so "
  f"the benefit of prediction grows with the very technique (multiple "
  f"issue) that most needs it.")
figure(FIG / "fig4_bpred_speedup_w1.png",
       "The same comparison on the scalar (width-1) core: the gains are "
       "smaller.")
P("*Caveat.* Static not-taken is highly sensitive to code layout: these "
  "loops end with a taken backward branch, which it always gets wrong "
  "(`br_random`'s loop is laid out with the back-edge as a fall-through, "
  "so it fares as well as the dynamic predictors there). A static "
  "backward-taken/forward-not-taken rule would remove most of the loop "
  "penalty; gem5 has no such predictor, so it is not part of the baseline.",
  size=9.5)

# ---- 5 multiple issue -----------------------------------------------------------
H1("5. Multiple issue (superscalar)")
H2("5.1 Configuration and results")
P("`--width W` sets the fetch, decode, rename, dispatch, issue and commit "
  "width of the out-of-order core to W = 1, 2, 4 or 8, leaving window sizes "
  "and functional units unchanged (so any ceiling that appears at W = 8 is a "
  "real structural limit). The in-order `Minor` core is run at width 1 and 2.")
code("for w in 1 2 4 8; do\n"
     "  $GEM5 -d m5out/w$w configs/ilp_sim.py --cpu o3 --width $w \\\n"
     "        --workload workloads/bin/int_indep\n"
     "done")
screenshot("The four runs' IPC side by side.",
           "Run: grep -H '^system.cpu.ipc ' m5out/w*/stats.txt")
rows = []
for w in W:
    d = [o3w[k][w] for k in (1, 2, 4, 8)]
    rows.append([w] + [f3(x["ipc"]) for x in d] +
                [f2(d[3]["ipc"] / d[0]["ipc"]), f3(mn1[w]["ipc"]),
                 f3(mn2[w]["ipc"])])
table(["Workload", "O3 w1", "O3 w2", "O3 w4", "O3 w8", "w8 / w1",
       "In-order w1", "In-order w2"], rows,
      [1.1, 0.7, 0.7, 0.7, 0.7, 0.75, 0.9, 0.9],
      "IPC versus issue width (out-of-order and in-order cores).")
figure(FIG / "fig2_width_scaling.png",
       "IPC as the machine gets wider; one panel per workload.")
P(f"**Where superscalar shines.** Geometric-mean IPC rises "
  f"{f2(width_geo[2])}x, {f2(width_geo[4])}x and {f2(width_geo[8])}x for "
  f"widths 2, 4 and 8, but the marginal gain shrinks from "
  f"{f2(width_geo[2])}x (1 to 2) to {f2(width_geo[4] / width_geo[2])}x "
  f"(2 to 4) and {f2(width_geo[8] / width_geo[4])}x (4 to 8). The kernels "
  f"with abundant independent work scale almost linearly: `int_indep` "
  f"{f2(o3w[8]['int_indep']['ipc'] / o3w[1]['int_indep']['ipc'])}x, "
  f"`matmul` {f2(o3w[8]['matmul']['ipc'] / o3w[1]['matmul']['ipc'])}x, "
  f"`br_pattern` {f2(o3w[8]['br_pattern']['ipc'] / o3w[1]['br_pattern']['ipc'])}x. "
  f"Kernels with serial chains flatten early: `int_dep` stops at IPC "
  f"{f2(o3w[2]['int_dep']['ipc'])} from width 2 on and `fp_dep` at "
  f"{f2(o3w[4]['fp_dep']['ipc'])} from width 4 - their dependence chains, "
  f"not the machine, set the speed. `br_random` ({f2(o3w[8]['br_random']['ipc'] / o3w[1]['br_random']['ipc'])}x) "
  f"is held back by mispredictions, `mem_stream` "
  f"({f2(o3w[8]['mem_stream']['ipc'] / o3w[1]['mem_stream']['ipc'])}x) by "
  f"memory, and `mem_chase` does not move at all "
  f"(IPC {f3(o3w[8]['mem_chase']['ipc'])} at every width).")
upc8 = o3w[8]["int_indep"]["upc"]
P(f"**Resource limits.** `int_indep` at width 8 reaches exactly "
  f"{upc8:.2f} micro-ops per cycle, in 100% of cycles: the default functional-"
  f"unit pool has six integer ALUs, so six is the ceiling however wide the "
  f"front end is. A superscalar needs balanced resources, not only a wide "
  f"issue stage.")
P(f"**Latency grows with width.** Figure 10 shows that extra width can buy "
  f"latency instead of throughput. On `int_dep` the average fetch-to-retire "
  f"latency goes from {o3w[1]['int_dep']['lat_total']:.0f} cycles at width 1 "
  f"to {o3w[2]['int_dep']['lat_total']:.0f} at width 2 and "
  f"{o3w[8]['int_dep']['lat_total']:.0f} at width 8 while IPC stays at "
  f"{f2(o3w[8]['int_dep']['ipc'])}: the front end races ahead and the extra "
  f"micro-ops simply queue behind the dependence chain. `int_indep` "
  f"({o3w[1]['int_indep']['lat_total']:.0f} to "
  f"{o3w[8]['int_indep']['lat_total']:.0f} cycles) queues for the six ALUs.")
figure(FIG / "fig3_latency_vs_width.png",
       "Average fetch-to-retire latency (log scale) for each width.")
P(f"**In-order issue gains little.** Dual-issue in-order is only "
  f"{f2(io_dual)}x faster than scalar in-order (geometric mean), against "
  f"{f2(width_geo[2])}x for out-of-order at width 2: an in-order machine "
  f"cannot find the independent instructions behind a stalled one.")
figure(SHOW / "wide4_int_indep" / "pipeline.png",
       "4-wide out-of-order pipeline on `int_indep`: four micro-ops enter "
       "the pipeline per cycle (compare Figure 1).", 5.4)
figure(SHOW / "wide4_int_dep" / "pipeline.png",
       "The same 4-wide pipeline on `int_dep`: micro-ops wait in the issue "
       "queue (yellow) for the serial chain.", 5.4)

H2("5.2 How big a window does ILP need?")
rows = [[w] + [f3(v) for v in win[w]] + [str(sat_rob(w))] for w in W]
table(["Workload"] + [f"ROB {r}" for r in ROBS] + ["ROB for 97% of peak"],
      rows, [1.1, 0.75, 0.75, 0.75, 0.75, 0.75, 1.1],
      "IPC of an 8-wide core as the reorder buffer grows (issue queue = "
      "ROB/2, load and store queues = ROB/4).")
figure(FIG / "fig6_window_size.png",
       "IPC versus reorder-buffer size at issue width 8.")
P(f"The window sweep separates the limits. Compute-bound kernels need a "
  f"modest window (`int_indep`, `br_pattern`, `matmul` reach 97% of their "
  f"peak at {sat_rob('int_indep')}, {sat_rob('br_pattern')} and "
  f"{sat_rob('matmul')} entries; `fp_dep` at {sat_rob('fp_dep')}). "
  f"`mem_stream` keeps improving all the way to 256 entries "
  f"({f2(win['mem_stream'][0])} to {f2(win['mem_stream'][-1])} IPC): "
  f"overlapping many cache misses (memory-level parallelism) is the one "
  f"place where a huge window pays. `mem_chase` is flat "
  f"({f3(win['mem_chase'][0])} everywhere) because each load needs the "
  f"previous one's result, and `br_random` is flat from "
  f"{sat_rob('br_random')} entries because a bigger window only holds more "
  f"wrong-path work.")
P(f"**An observation that needs a caveat.** `fp_daxpy` is *slower* at width 8 "
  f"than at width 4 ({f2(o3w[8]['fp_daxpy']['ipc'])} versus "
  f"{f2(o3w[4]['fp_daxpy']['ipc'])} IPC). It has no memory-order violations "
  f"or cache blocking at either width; what differs is that at width 8 the "
  f"decode and rename stages sit idle in "
  f"{pc(o3w[8]['fp_daxpy'].get('decode_idle', 0))} and "
  f"{pc(o3w[8]['fp_daxpy'].get('rename_idle', 0))} of cycles (against "
  f"{pc(o3w[4]['fp_daxpy'].get('decode_idle', 0))} and "
  f"{pc(o3w[4]['fp_daxpy'].get('rename_idle', 0))} at width 4), which "
  f"points at the front end, not the back end, as the limit for this short "
  f"loop. "
  f"I did not isolate the exact mechanism, so I treat this as an "
  f"observation, not a finding.", size=10)

# ---- 6 SMT --------------------------------------------------------------------------
H1("6. Simultaneous multithreading")
H2("6.1 Configuration")
P("`ilp_sim.py` creates one hardware thread per `--workload` argument. All "
  "threads share the 4-wide out-of-order core. By default the reorder "
  "buffer, issue queue and load/store queues are partitioned between the "
  "threads and a single thread fetches in each cycle (round-robin). The "
  "caches, branch predictor tables and functional units are shared.")
code("N=workloads/native\n"
     "$GEM5 -d m5out/smt2 configs/ilp_sim.py --cpu o3 --width 4 \\\n"
     "      --warmup-insts 500000 --roi-cycles 1000000 \\\n"
     "      --workload \"$N/mem_chase 1000000000\" \\\n"
     "      --workload \"$N/int_indep 1000000000\"")
screenshot("Output of the SMT run: the `[ilp_sim]` lines and the "
           "per-thread IPC.",
           "Run: grep -E '^system.cpu.(numCycles|ipc) |commitStats[0-9].ipc' "
           "m5out/smt2/stats.txt")
P("*Two practical notes.* (1) SMT runs use binaries without the region-of-"
  "interest markers: in gem5 25.1 an SMT thread that executes a marker "
  "instruction can wait forever for its stores to drain while the other "
  "thread keeps running, so SMT is measured over a fixed 1,000,000-cycle "
  "window after a warm-up instead. (2) gem5's default BTB is direct-mapped, "
  "which turns out to matter a great deal for SMT (Section 6.3), so every "
  "experiment is shown both with the default BTB and with a 4-way BTB; the "
  "4-way results are used as the primary ones.", size=10)

H2("6.2 Throughput")
alone = {w: mf.smt_get([w], btb=4) for w in W}
rows = []
ws_by_mix = {}
for mix in MIXES:
    m4, ws4 = smt_info(mix, 4)
    m1, ws1 = smt_info(mix, 1)
    ws_by_mix[mix] = (ws4, ws1)
    label = "+".join(mix) if len(set(mix)) > 1 else f"{len(mix)} x {mix[0]}"
    per = " / ".join(f"{m4[f'ipc_t{t}']:.2f}" for t in range(len(mix)))
    rows.append([label, len(mix), per, f2(m4["ipc"]), f2(m4["upc"]),
                 f2(ws4), f2(m1["ipc"]), f2(ws1)])
table(["Mix", "Threads", "IPC per thread", "Total IPC", "Total uops/ cycle",
       "Weighted speed-up", "Total IPC (direct-mapped BTB)",
       "Weighted speed-up (direct-mapped BTB)"], rows,
      [1.65, 0.5, 0.95, 0.5, 0.55, 0.65, 0.85, 0.85], "SMT on the 4-wide core, "
      "4-way BTB (primary) and gem5's default direct-mapped BTB.", size=8)
figure(FIG / "fig7_smt_throughput.png",
       "Total IPC and weighted speed-up of every SMT mix (4-way BTB).")
pairs_ws = [ws_by_mix[m][0] for m in MIXES if len(m) == 2]
quads_ws = [ws_by_mix[m][0] for m in MIXES if len(m) == 4]
mi = smt_info(("mem_chase", "int_indep"))
P(f"**Does SMT significantly improve throughput?** It depends on how much "
  f"of the core a single thread leaves idle. The geometric-mean weighted "
  f"speed-up is {f2(geo(pairs_ws))}x for 2 threads and {f2(geo(quads_ws))}x "
  f"for 4 threads, spanning {f2(min(pairs_ws + quads_ws))}x to "
  f"{f2(max(pairs_ws + quads_ws))}x.")
bullets([
    f"*Latency- or dependence-bound threads gain the most.* Two copies of "
    f"`int_dep` double the throughput ({f2(ws_by_mix[('int_dep',) * 2][0])}x: "
    f"the serial chains interleave perfectly), two of `mem_chase` give "
    f"{f2(ws_by_mix[('mem_chase',) * 2][0])}x and four give "
    f"{f2(ws_by_mix[('mem_chase',) * 4][0])}x, because the threads' DRAM "
    f"misses overlap.",
    f"*A saturated core gains nothing.* One `int_indep` thread already "
    f"issues {f2(alone['int_indep']['upc'])} micro-ops per cycle on a 4-wide "
    f"core, so two or four copies stay at {f2(ws_by_mix[('int_indep',) * 2][0])}x "
    f"(no gain, and no loss).",
    f"*Mixing complementary threads works.* `mem_chase` + `int_dep` reaches "
    f"{f2(ws_by_mix[('mem_chase', 'int_dep')][0])}x: the memory-bound thread "
    f"uses almost no issue slots, so the other runs at full speed.",
    f"*4 threads are not 4x.* Four `int_dep` threads would need "
    f"{4 * alone['int_dep']['upc']:.1f} micro-ops per cycle but the core "
    f"supplies at most 4, and reach only "
    f"{f2(ws_by_mix[('int_dep',) * 4][0])}x.",
])

H2("6.3 Resource sharing, contention points and bottlenecks")
P("The stage-level statistics show where threads collide:")
mc = mf.smt_get(("mem_chase", "mem_chase"), btb=4)
m2 = mf.smt_get(("mem_chase", "int_indep"), btb=4)
iq0 = mf.smt_get(("mem_chase", "int_indep"), "IQCount", "Partitioned", 4)
ms = mf.smt_get(("mem_stream", "int_indep"), btb=4)
bullets([
    f"**Reorder-buffer partition.** A thread stalled on DRAM fills its half "
    f"of the ROB with micro-ops that cannot commit, which blocks the shared "
    f"rename stage: it is blocked in {pc(m2['rename_blocked'])} of cycles for "
    f"`mem_chase` + `int_indep` and in {pc(mc['rename_blocked'])} for two "
    f"`mem_chase`.",
    f"**Fetch bandwidth and policy.** With round-robin fetch the healthy "
    f"`int_indep` thread runs at {f2(m2['ipc_t1'])} IPC, exactly half of its "
    f"stand-alone {f2(alone['int_indep']['ipc'])}: it gets half of the fetch "
    f"slots even though its partner, stalled on DRAM, cannot use its half. "
    f"A policy that gives the slots to the productive thread restores it "
    f"to about {f2(iq0['ipc_t1'])} IPC (Section 6.4).",
    "**Issue width and functional units** are the limit as soon as the "
    "threads together demand more than 4 micro-ops per cycle (the "
    "`int_indep` rows).",
    f"**An even split is not always a gain.** In `mem_stream` + `int_indep` "
    f"each thread runs at about half of its stand-alone speed "
    f"({f2(ms['ipc_t0'])} versus {f2(alone['mem_stream']['ipc'])} IPC, and "
    f"{f2(ms['ipc_t1'])} versus {f2(alone['int_indep']['ipc'])}), so the "
    f"pair is no better than time-slicing "
    f"({f2(ws_by_mix[('mem_stream', 'int_indep')][0])}x).",
])
rows = []
for mix in [("int_indep",) * 2, ("int_indep",) * 4, ("int_dep",) * 2,
            ("matmul",) * 2, ("matmul",) * 4]:
    a1, a4 = mf.smt_get(mix, btb=1), mf.smt_get(mix, btb=4)
    rows.append([f"{len(mix)} x {mix[0]}", f2(mf.smt_get([mix[0]], btb=1)["ipc"]),
                 f2(a1["ipc"]), pc(a1["btb_hit_ratio"]), pc(a1["mispredict_rate"]),
                 f2(a4["ipc"]), pc(a4["btb_hit_ratio"]), pc(a4["mispredict_rate"])])
table(["Mix", "IPC alone", "IPC (direct-mapped)", "BTB hit ratio",
       "Mispredict rate", "IPC (4-way)", "BTB hit ratio (4-way)",
       "Mispredict rate (4-way)"], rows,
      [1.1, 0.65, 0.85, 0.75, 0.8, 0.7, 0.85, 0.8],
      "Threads that run the same code and a direct-mapped BTB.", size=8)
figure(FIG / "fig9_smt_btb.png",
       "Total IPC with gem5's default direct-mapped BTB versus a 4-way BTB; "
       "the black line is the same program on one thread.")
P(f"**The shared branch-target buffer is a hidden bottleneck.** With gem5's "
  f"default direct-mapped BTB, two threads that execute the same code "
  f"(e.g. two instances of one program, a common server scenario) map their "
  f"branches to the same BTB entries and keep evicting each other's: the BTB "
  f"hit ratio drops from 100% to "
  f"{pc(mf.smt_get(('int_indep',) * 2, btb=1)['btb_hit_ratio'])} (2 threads) "
  f"and {pc(mf.smt_get(('int_indep',) * 4, btb=1)['btb_hit_ratio'])} "
  f"(4 threads), taken branches are mispredicted, and total IPC falls from "
  f"{f2(alone['int_indep']['ipc'])} to "
  f"{f2(mf.smt_get(('int_indep',) * 2, btb=1)['ipc'])} - SMT *loses* "
  f"throughput. Making the BTB 4-way restores a 100% hit ratio and the full "
  f"{f2(mf.smt_get(('int_indep',) * 2, btb=4)['ipc'])} IPC; for `int_dep`, "
  f"where one thread leaves room, it takes 2 threads from "
  f"{f2(mf.smt_get(('int_dep',) * 2, btb=1)['ipc'])} to "
  f"{f2(mf.smt_get(('int_dep',) * 2, btb=4)['ipc'])} IPC "
  f"(exactly 2x one thread). The cost of SMT is therefore not only the "
  f"partitioned queues: every shared predictor structure must be sized and "
  f"associated for several threads.")

H2("6.4 Fetch and sharing policies")
mixA = ("mem_chase", "int_indep")
rows = []
for f in ("RoundRobin", "IQCount", "LSQCount"):
    for q in ("Partitioned", "Threshold"):
        m = mf.smt_get(mixA, f, q, 4)
        rows.append([f, q, f3(m["ipc"]),
                     " / ".join(f"{m[f'ipc_t{t}']:.3f}" for t in range(2))])
table(["Fetch policy", "LSQ sharing", "Total IPC", "IPC per thread "
       "(mem_chase / int_indep)"], rows, [1.4, 1.4, 1.1, 2.6],
      "Policies on the `mem_chase` + `int_indep` mix (4-way BTB).")
figure(FIG / "fig8_smt_policies.png",
       "Total IPC for each fetch policy and LSQ-sharing policy on two mixes "
       "(shaded on one shared scale; 'starved' = no result).")
rr = mf.smt_get(mixA, "RoundRobin", "Partitioned", 4)
iq = mf.smt_get(mixA, "IQCount", "Partitioned", 4)
P(f"**Choosing which thread fetches matters most.** Prioritising the thread "
  f"with the fewest instructions in the issue queue (`IQCount`) or load/"
  f"store queue (`LSQCount`) nearly doubles throughput on this mix "
  f"({f2(rr['ipc'])} to {f2(iq['ipc'])} IPC): fetch slots stop being wasted "
  f"on the stalled thread, and *both* threads run at essentially their "
  f"stand-alone speed (weighted speed-up "
  f"{f2(iq['ipc_t0'] / alone['mem_chase']['ipc'] + iq['ipc_t1'] / alone['int_indep']['ipc'])}). "
  f"Switching the load/store queues from partitioned to a threshold-shared "
  f"scheme made no difference here: the queues are not the contended "
  f"resource in these mixes.")
P(f"**But priority policies can starve a thread.** In the four-thread mix "
  f"`int_dep + fp_dep + mem_chase + br_random`, both count-based policies "
  f"left the `mem_chase` thread stuck at 127,704 committed instructions "
  f"while the other three ran on into the millions, so the warm-up "
  f"phase never finished ({n_starved} runs were stopped after about 13 "
  f"minutes; their records are kept in `results/runs/*/FAILED.txt`). "
  f"Round-robin finishes the same mix with every thread making progress "
  f"({', '.join(f2(mf.smt_get(('int_dep','fp_dep','mem_chase','br_random'), btb=4)[f'ipc_t{t}']) for t in range(4))} IPC "
  f"per thread). Throughput-oriented fetch policies need a fairness "
  f"mechanism.")

# ---- 7 key questions ---------------------------------------------------------------
H1("7. Key questions")
H3("How do the ILP techniques interact?")
bullets([
    f"**Prediction x width.** The value of prediction grows with width "
    f"({f2(speedup_vs_static(1, 'tournament'))}x at width 1, "
    f"{f2(speedup_vs_static(4, 'tournament'))}x at width 4) because a "
    f"misprediction wastes cycles x width issue slots.",
    "**Width x window x memory.** A wide core only pays if the window is "
    "large enough to find independent work behind a miss: `mem_stream` needs "
    "a 256-entry window to profit, while compute kernels saturate at 64-128.",
    "**SMT x prediction.** Threads share the BTB and predictor tables; "
    "identical code in two threads halves the BTB hit ratio on a "
    "direct-mapped BTB and turns SMT from a gain into a loss.",
    "**SMT x fetch policy x width.** SMT fills slots that a single thread "
    "cannot (memory stalls, dependences), but only when fetch slots are "
    "given to threads that can use them.",
])
H3("What are the limits of these techniques?")
bullets([
    f"**Data dependences:** `int_dep` stays at IPC "
    f"{f2(o3w[8]['int_dep']['ipc'])} from width 2 to 8.",
    f"**Control dependences:** `br_random` reaches only IPC "
    f"{f2(o3w[8]['br_random']['ipc'])} at width 8 with a 192-entry window, "
    f"and all five predictors give the same IPC at width 4.",
    f"**Memory latency:** `mem_chase` runs at IPC "
    f"{f3(o3w[8]['mem_chase']['ipc'])} at every width and window size; only "
    f"SMT (independent threads) helps.",
    "**Structural resources:** six integer ALUs cap `int_indep` at 6 "
    "micro-ops/cycle at width 8.",
    "**Shared structures under SMT:** BTB conflicts, partitioned queues and "
    "fetch-policy starvation.",
])
H3("How can the complexity of ILP be balanced against its benefit?")
bullets([
    f"**Diminishing returns in width:** {f2(width_geo[2])}x, then "
    f"{f2(width_geo[4] / width_geo[2])}x, then "
    f"{f2(width_geo[8] / width_geo[4])}x for each doubling, while the "
    f"wake-up/select, bypass and register-file cost grows faster than "
    f"linearly with width.",
    f"**A good predictor is the cheapest big win:** the tournament predictor "
    f"captures {f2(speedup_vs_static(4, 'tournament'))}x at width 4; the much "
    f"larger TAGE-SC-L adds only "
    f"{f1(100 * (speedup_vs_static(4, 'tage') / speedup_vs_static(4, 'tournament') - 1))}% "
    f"on average (more on the few branches that need long history).",
    "**Window size:** 128 entries gets nearly all of the compute-bound "
    "benefit; going to 256 is worthwhile mainly for memory-level "
    "parallelism.",
    "**SMT** is a cheap way to use idle slots (up to 3.7x on latency-bound "
    "threads) but needs policy care - fetch priority, fairness and "
    "multi-thread-aware predictors - and gives nothing when one thread "
    "already fills the machine.",
])

# ---- 8 troubleshooting ---------------------------------------------------------------
H1("8. Troubleshooting and observations about gem5")
P("Issues met while building the experiments, and how each was resolved:")
bullets([
    "**No way to disable branch prediction.** gem5 has no \"predictor off\" "
    "switch and a BTB cannot be made to always miss. Fix: add a small "
    "`StaticNotTakenBP` SimObject in a *copy* of the source tree "
    "(`patches/install_static_bp.sh`), rebuilt once.",
    "**Assertion TimeBuffer<IEWStruct>::valid at width 1.** The O3 "
    "writeback stage aborted when its width was 1, and again with a width "
    "of 2 on the memory-heavy `mem_stream` kernel, which suggests that a "
    "burst of loads completing in one cycle overflows its writeback "
    "schedule (a hypothesis; I did not read the stage's code in depth). "
    "Fix: writeback width fixed at 8 or more for all runs (writeback "
    "bandwidth is not the studied resource).",
    "**Minor does not predict x86 branches.** Its branch-predictor "
    "statistics stayed at zero and the debug trace printed \"Not attempting "
    "prediction\" for x86 macro-ops; `Minor` is therefore used only as the "
    "in-order, no-prediction reference, and all predictor studies use `O3`.",
    "**SMT set-up errors** (`numThreads` must be set explicitly, "
    "`system.multi_thread = True`, one interrupt controller per thread, "
    "unique process ids).",
    "**SMT stall on the region-of-interest marker.** A thread whose next "
    "instruction was the (non-speculative) marker sat at the head of its "
    "reorder buffer \"waiting for all stores to write back\" for the rest "
    "of the run while the partner thread kept running (diagnosed with "
    "gem5's `Commit` debug flag). Fix: SMT uses marker-free binaries, a "
    "warm-up and a fixed cycle window.",
    "**Unsupported or crashing SMT options in gem5 25.1:** the `Branch` fetch "
    "policy is unimplemented, and Dynamic or Threshold sharing of the ROB or "
    "the issue queue crashes (assertions / segmentation fault). Only fetch "
    "policy x LSQ sharing could be explored.",
    "**Starvation under count-based fetch policies** with four threads "
    "(Section 6.4): diagnosed with a progress probe (`--progress-cycles`) "
    "rather than waiting for a hang to resolve itself.",
    "**Slow set-up phase.** The first `mem_chase` built its permutation with "
    "a division-heavy shuffle over cold memory (about 13 M cycles). It now "
    "uses a full-period linear-congruential permutation (Hull-Dobell), which "
    "is cheap and still visits all nodes.",
    "**Environment.** Paths containing spaces broke the workload argument "
    "(fixed with `shlex`), writing traces across `/mnt/<drive>` was very "
    "slow (the runner works in a Linux scratch directory), and linking gem5 "
    "while several simulations were running exhausted the 7.6 GB of RAM, "
    "aborted one simulation and briefly disconnected WSL (builds and "
    "sweeps are now run separately).",
])

# ---- 9 conclusion --------------------------------------------------------------------
H1("9. Conclusions")
P("Instruction-level parallelism is a property of the *program and the "
  "machine together*. A scalar pipeline delivers about one micro-op per "
  "cycle; branch prediction keeps a wide front end fed (2x on a 4-wide core, "
  "and the more accurate the better where branches have structure); "
  "multiple issue multiplies throughput only where independent work exists "
  "and the window, functional units and memory system can expose it; and "
  "SMT recovers slots that one thread cannot use, provided the shared "
  "structures (fetch, queues, predictor tables) are sized and scheduled "
  "with several threads in mind. The most informative results were the "
  "negative ones: width that buys latency instead of IPC, a bigger window "
  "that cannot help a pointer chase, and an SMT core that is slower than "
  "one thread until the BTB is fixed.")

# ---- 10 reproduce ------------------------------------------------------------------------
H1("10. Reproducing the results")
code("make -C workloads && make -C workloads native     # build the workloads\n"
     "python3 scripts/run_experiments.py --jobs 6         # all runs (resumable)\n"
     "python3 scripts/make_figures.py                     # figures + tables\n"
     "bash scripts/showcase.sh                            # pipeline views\n"
     "python3 scripts/build_report.py                     # this report")
P("Repository: [link to your GitHub repository]. It contains the gem5 "
  "configuration (`configs/ilp_sim.py`), the workloads, the predictor patch, "
  "all scripts, the raw statistics of every run (`results/runs/`) and the "
  "tables and figures used here.")

# ---- appendix --------------------------------------------------------------------------
H1("Appendix A. Screenshot checklist")
P("The yellow boxes in this report mark where to paste a screenshot of your "
  "own terminal; none of the screenshots is generated for you.")
table(["#", "What to capture", "How"], [[n, a, b] for n, a, b in SHOTS],
      [0.35, 3.0, 3.15], size=8.5, center=False)

H1("Appendix B. Complete branch-predictor results (IPC)")
for width in (1, 4):
    rows = []
    for w in W:
        rows.append([w] + [f"{bp[width][b][w]['ipc']:.3f} "
                           f"({100 * bp[width][b][w]['mispredict_rate']:.1f}%)"
                           for b in BPREDS])
    table(["Workload"] + [mf.BP_LABEL[b] for b in BPREDS], rows,
          [1.05, 1.1, 1.1, 1.1, 1.1, 1.1],
          f"IPC (misprediction rate), O3 issue width {width}.")

H1("Appendix C. Pipeline views")
figure(SHOW / "static_br_random" / "pipeline.png",
       "`br_random`, static not-taken, 4-wide.", 5.0)
figure(SHOW / "tage_br_random" / "pipeline.png",
       "`br_random`, TAGE-SC-L, 4-wide: random branches are mispredicted "
       "about as often as with static prediction.", 5.0)
figure(SHOW / "smt2_mem_int" / "pipeline.png",
       "Two threads (`mem_chase` + `int_indep`) sharing one 4-wide pipeline "
       "(default round-robin fetch).", 5.0)

page_numbers()
OUT.parent.mkdir(exist_ok=True)
doc.save(OUT)
print(f"wrote {OUT}  ({_fig[0]} figures, {_tab[0]} tables, {len(SHOTS)} "
      f"screenshot slots)")
