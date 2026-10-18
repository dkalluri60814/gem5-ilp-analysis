"""ILP experiments: one parameterised gem5 (SE mode, x86) configuration.

A single script covers every experiment of Part 2 so that the only thing
that changes between two runs is the knob being studied:

  --cpu minor          in-order pipeline (Fetch1/Fetch2 -> Decode -> Execute
                       -> LSQ/memory -> commit); width 1 = scalar,
                       width 2 = dual-issue in-order superscalar
  --cpu o3             out-of-order pipeline (Fetch -> Decode -> Rename ->
                       IEW(issue/execute/writeback) -> Commit); every stage
                       width follows --width
  --bpred NAME         static | local | bimode | tournament | tage
  --workload "BIN [ARGS]"   repeat once per hardware thread (SMT when > 1)

Memory system (identical for every run): 32 KiB L1I, 32 KiB L1D, 256 KiB L2,
DDR3-1600, 2 GHz clock.

Statistics are collected for the region of interest only: the workloads
signal "work begin" / "work end" (gem5 magic instructions), the stats are
reset at begin and dumped at end (or after --roi-insts instructions).

Run with:  gem5.opt -d OUTDIR configs/ilp_sim.py --cpu o3 --width 4 \
                    --workload "workloads/bin/int_dep"
"""

import argparse
import os
import shlex

import m5
from m5.objects import *

# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
parser.add_argument("--cpu", choices=["minor", "o3"], default="o3")
parser.add_argument("--width", type=int, default=4,
                    help="issue width (minor: 1 or 2; o3: any)")
parser.add_argument("--bpred", default="tournament",
                    choices=["static", "local", "bimode", "tournament",
                             "tage"])
parser.add_argument("--workload", action="append", required=True,
                    help='"binary [args...]" - repeat for SMT threads')
parser.add_argument("--roi-insts", type=int, default=0,
                    help="end the ROI after this many committed insts "
                         "(per thread, first thread to reach it); 0 = run "
                         "until the program's own work_end marker")
parser.add_argument("--roi-cycles", type=int, default=0,
                    help="end the ROI after exactly this many cycles")
parser.add_argument("--warmup-insts", type=int, default=0,
                    help="start measuring once every thread has committed "
                         "this many instructions, instead of waiting for "
                         "the programs' ROI markers (used for SMT: a "
                         "marker instruction can stall an O3 SMT thread)")
parser.add_argument("--btb-assoc", type=int, default=1,
                    help="associativity of the 4096-entry BTB (gem5 default: "
                         "direct-mapped)")
parser.add_argument("--clock", default="2GHz")
parser.add_argument("--l1i-size", default="32KiB")
parser.add_argument("--l1d-size", default="32KiB")
parser.add_argument("--l2-size", default="256KiB")
# O3 window / SMT sharing knobs
parser.add_argument("--rob", type=int, default=192)
parser.add_argument("--iq", type=int, default=64)
parser.add_argument("--lq", type=int, default=32)
parser.add_argument("--sq", type=int, default=32)
parser.add_argument("--smt-fetch", default="RoundRobin",
                    choices=["RoundRobin", "IQCount", "LSQCount"],
                    help="which thread fetches each cycle (gem5's 'Branch' "
                         "policy is not implemented)")
SHARING = ["Partitioned", "Dynamic", "Threshold"]
parser.add_argument("--smt-rob", default="Partitioned", choices=SHARING,
                    help="how the reorder buffer is shared between threads")
parser.add_argument("--smt-lsq", default="Partitioned", choices=SHARING,
                    help="how the load/store queues are shared")
parser.add_argument("--smt-iq", default="Partitioned", choices=SHARING,
                    help="how the issue queue is shared (gem5 25.1 crashes "
                         "with anything but Partitioned)")
parser.add_argument("--smt-commit", default="RoundRobin",
                    choices=["RoundRobin", "OldestReady"])
# pipeline trace window (for the visualisation)
parser.add_argument("--progress-cycles", type=int, default=0,
                    help="print per-thread committed instructions every N "
                         "cycles until the ROI starts (debugging aid)")
parser.add_argument("--trace-flag", default="",
                    help="gem5 debug flag to enable in a window, "
                         "e.g. O3PipeView or MinorTrace")
parser.add_argument("--trace-offset", type=int, default=2000,
                    help="cycles after ROI start before tracing begins")
parser.add_argument("--trace-cycles", type=int, default=300,
                    help="length of the trace window in cycles")
args = parser.parse_args()

nthreads = len(args.workload)
if args.cpu == "minor" and nthreads > 1:
    parser.error("SMT is only configured for --cpu o3")

# --------------------------------------------------------------------------
# System, clock, memory
# --------------------------------------------------------------------------
system = System()
system.clk_domain = SrcClockDomain(clock=args.clock,
                                   voltage_domain=VoltageDomain())
system.mem_mode = "timing"
system.multi_thread = nthreads > 1      # required for SMT
system.mem_ranges = [AddrRange("512MiB")]


# --------------------------------------------------------------------------
# Branch predictor
# --------------------------------------------------------------------------
def make_bpred(kind):
    """Direction predictor + the same 4K-entry BTB, RAS and indirect
    predictor in every case, so only the direction predictor differs."""
    cond = {
        # no dynamic prediction: every conditional branch "not taken"
        "static": lambda: StaticNotTakenBP(),
        # 2-bit saturating counters indexed by PC
        "local": lambda: LocalBP(localPredictorSize=2048, localCtrBits=2),
        "bimode": lambda: BiModeBP(),
        "tournament": lambda: TournamentBP(),
        # TAGE with a loop predictor and statistical corrector (8 KB)
        "tage": lambda: TAGE_SC_L_8KB(),
    }[kind]()
    return BranchPredictor(conditionalBranchPred=cond,
                           btb=SimpleBTB(associativity=args.btb_assoc))


# --------------------------------------------------------------------------
# CPU
# --------------------------------------------------------------------------
if args.cpu == "minor":
    cpu = X86MinorCPU()
    w = args.width
    # The Minor stages: Fetch1 (I-cache access) -> Fetch2 (line -> insts,
    # branch prediction) -> Decode -> Execute (issue, FUs, LSQ, commit).
    cpu.decodeInputWidth = w
    cpu.executeInputWidth = w
    cpu.executeIssueLimit = w
    cpu.executeCommitLimit = w
    cpu.fetch2InputBufferSize = max(2, w)
else:
    cpu = X86O3CPU()
    w = args.width
    cpu.fetchWidth = w
    cpu.decodeWidth = w
    cpu.renameWidth = w
    cpu.dispatchWidth = w
    cpu.issueWidth = w
    # Writeback bandwidth is deliberately NOT the studied resource: gem5's
    # IEW stage asserts (TimeBuffer index) when wbWidth is small, e.g. when a
    # cache fill returns a burst of loads in one cycle. Keep it >= 8.
    cpu.wbWidth = max(8, w)
    cpu.commitWidth = w
    cpu.numROBEntries = args.rob
    cpu.LQEntries = args.lq
    cpu.SQEntries = args.sq
    cpu.instQueues = [IQUnit(numEntries=args.iq, smtIQPolicy=args.smt_iq)]
    cpu.smtFetchPolicy = args.smt_fetch
    cpu.smtROBPolicy = args.smt_rob
    cpu.smtLSQPolicy = args.smt_lsq
    cpu.smtCommitPolicy = args.smt_commit
    cpu.smtNumFetchingThreads = 1
cpu.branchPred = make_bpred(args.bpred)
cpu.numThreads = nthreads               # hardware threads (SMT when > 1)
system.cpu = cpu

# --------------------------------------------------------------------------
# Caches (classic): L1I / L1D -> L2 -> memory bus -> DDR3
# --------------------------------------------------------------------------
system.cpu.icache = Cache(size=args.l1i_size, assoc=4, tag_latency=1,
                          data_latency=1, response_latency=1, mshrs=8,
                          tgts_per_mshr=20)
system.cpu.dcache = Cache(size=args.l1d_size, assoc=8, tag_latency=2,
                          data_latency=2, response_latency=2, mshrs=16,
                          tgts_per_mshr=20)
system.l2cache = Cache(size=args.l2_size, assoc=8, tag_latency=10,
                       data_latency=10, response_latency=10, mshrs=32,
                       tgts_per_mshr=12)
system.l2bus = L2XBar()
system.membus = SystemXBar()

system.cpu.icache.cpu_side = system.cpu.icache_port
system.cpu.dcache.cpu_side = system.cpu.dcache_port
system.cpu.icache.mem_side = system.l2bus.cpu_side_ports
system.cpu.dcache.mem_side = system.l2bus.cpu_side_ports
system.l2cache.cpu_side = system.l2bus.mem_side_ports
system.l2cache.mem_side = system.membus.cpu_side_ports

system.cpu.createInterruptController()      # one per hardware thread
for intr in system.cpu.interrupts:
    intr.pio = system.membus.mem_side_ports
    intr.int_requestor = system.membus.cpu_side_ports
    intr.int_responder = system.membus.mem_side_ports
system.system_port = system.membus.cpu_side_ports

system.mem_ctrl = MemCtrl()
system.mem_ctrl.dram = DDR3_1600_8x8()
system.mem_ctrl.dram.range = system.mem_ranges[0]
system.mem_ctrl.port = system.membus.mem_side_ports

# --------------------------------------------------------------------------
# Workloads: one process per hardware thread
# --------------------------------------------------------------------------
procs = []
for i, spec in enumerate(args.workload):
    argv = shlex.split(spec)          # paths with spaces must be quoted
    argv[0] = os.path.abspath(argv[0])
    procs.append(Process(pid=100 + i, cmd=argv, executable=argv[0],
                         output=f"thread{i}.out"))
system.workload = SEWorkload.init_compatible(procs[0].executable)
system.cpu.workload = procs
system.cpu.createThreads()

# Marker mode: exit to Python when every thread has entered its ROI, and
# when the first thread leaves it. (Not used with --warmup-insts.)
system.work_begin_exit_count = nthreads
system.work_end_exit_count = 1
system.num_work_ids = 1024      # the workloads use their pid (100+) as work id

# --------------------------------------------------------------------------
# Simulate
# --------------------------------------------------------------------------
root = Root(full_system=False, system=system)
m5.instantiate()

cycle_ticks = int(round(m5.ticks.fromSeconds(
    1.0 / m5.util.convert.toFrequency(args.clock))))  # ticks per cycle
mode = (f"warm-up {args.warmup_insts} insts/thread" if args.warmup_insts
        else "ROI markers")
print(f"[ilp_sim] cpu={args.cpu} width={args.width} bpred={args.bpred} "
      f"threads={nthreads} cycle={cycle_ticks} ticks, start: {mode}")

WORK_BEGIN = "work started count reach"   # emitted by gem5 (pseudo_inst.cc)
WARMUP = "warm-up instruction budget reached"
LIMIT = "simulate() limit reached"


def simulate_to_next_event(max_ticks=None):
    """m5.simulate(), optionally reporting progress every N cycles."""
    if max_ticks is not None or not args.progress_cycles:
        return m5.simulate(max_ticks) if max_ticks is not None             else m5.simulate()
    while True:
        ev = m5.simulate(args.progress_cycles * cycle_ticks)
        if LIMIT not in ev.getCause():
            return ev
        counts = [system.cpu.getCurrentInstCount(t) for t in range(nthreads)]
        print(f"[ilp_sim] tick {m5.curTick()}: committed per thread {counts}",
              flush=True)


# ---- 1. reach the start of the measured region ---------------------------
if args.warmup_insts:
    # No markers: run until EVERY thread has committed N instructions
    # (libc start-up + array set-up), then start measuring.
    for tid in range(nthreads):
        system.cpu.scheduleInstStop(tid, args.warmup_insts, WARMUP)
    reached = 0
    while reached < nthreads:
        event = simulate_to_next_event()
        if WARMUP not in event.getCause():
            break
        reached += 1
    started = reached == nthreads
else:
    event = simulate_to_next_event()
    started = WORK_BEGIN in event.getCause()
print(f"[ilp_sim] measurement start @ tick {m5.curTick()}: "
      f"{event.getCause()}")

# ---- 2. measure ------------------------------------------------------------
if started:
    m5.stats.reset()
    roi_start = m5.curTick()
    deadline = (roi_start + args.roi_cycles * cycle_ticks
                if args.roi_cycles else None)

    if args.roi_insts:
        for tid in range(nthreads):
            system.cpu.scheduleInstStop(tid, args.roi_insts,
                                        "roi instruction budget reached")

    def sim(ticks=None):
        """Simulate for <= ticks, never beyond the fixed-cycle deadline."""
        if deadline is not None:
            left = deadline - m5.curTick()
            ticks = left if ticks is None else min(ticks, left)
        return simulate_to_next_event(ticks)

    def over(ev):
        return (LIMIT not in ev.getCause() or
                (deadline is not None and m5.curTick() >= deadline))

    event = None
    finished = False
    if args.trace_flag:             # pipeline-trace window for the viewer
        event = sim(args.trace_offset * cycle_ticks)
        finished = over(event)
        if not finished:
            m5.debug.flags[args.trace_flag].enable()
            event = sim(args.trace_cycles * cycle_ticks)
            m5.debug.flags[args.trace_flag].disable()
            finished = over(event)
    if not finished:
        event = sim()
    print(f"[ilp_sim] ROI ended @ tick {m5.curTick()} "
          f"({(m5.curTick() - roi_start) // cycle_ticks} cycles): "
          f"{event.getCause()}")
else:
    print("[ilp_sim] WARNING: program ended before the measured region "
          "began; statistics cover the whole run")

m5.stats.dump()
print("[ilp_sim] done")
