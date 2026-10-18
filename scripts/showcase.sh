#!/usr/bin/env bash
# Short, readable runs for the report's screenshots and pipeline figures.
# Each run keeps its full gem5 output (stats.txt, config.ini, pipeline trace)
# in results/showcase/<name>/ and gets two pipeline views:
#   pipeline_text.txt  gem5's own viewer (util/o3-pipeview.py)
#   pipeline.png       cycle-by-cycle diagram (scripts/pipeline_diagram.py)
#
#   bash scripts/showcase.sh            # all showcases
#   bash scripts/showcase.sh scalar     # only those whose name contains "scalar"
set -euo pipefail
cd "$(dirname "$0")/.."

GEM5="${GEM5_BIN:-$HOME/gem5-ilp/build/X86/gem5.opt}"   # needs the static-BP patch
GEM5_SRC="${GEM5_SRC:-$HOME/gem5}"                      # for util/o3-pipeview.py
OUT=results/showcase
FILTER="${1:-}"
mkdir -p "$OUT"

showcase() {            # showcase NAME TITLE ARGS...
  local name="$1" title="$2"; shift 2
  [[ -n "$FILTER" && "$name" != *"$FILTER"* ]] && return 0
  echo "=== $name"
  rm -rf "$OUT/$name"; mkdir -p "$OUT/$name"
  "$GEM5" -d "$OUT/$name" --debug-file=pipeview.txt configs/ilp_sim.py "$@" \
      --trace-flag O3PipeView --trace-offset 2000 --trace-cycles 200 \
      > "$OUT/$name/console.txt" 2>&1 || { tail -5 "$OUT/$name/console.txt"; return 1; }
  grep "ilp_sim\]" "$OUT/$name/console.txt" || true
  # gem5's own text viewer: f=fetch d=decode n=rename p=dispatch i=issue
  # c=complete r=retire; a leading "-----" marks a squashed (wrong-path) op.
  python3 "$GEM5_SRC/util/o3-pipeview.py" -c 500 -w 100 \
      -o "$OUT/$name/pipeline_full.txt" "$OUT/$name/pipeview.txt" > /dev/null
  { sed -n 1,3p "$OUT/$name/pipeline_full.txt"; sed -n 60,100p "$OUT/$name/pipeline_full.txt"; } \
      > "$OUT/$name/pipeline_text.txt"
  python3 scripts/pipeline_diagram.py "$OUT/$name/pipeview.txt" \
      -o "$OUT/$name/pipeline.png" --skip 60 --count 30 --title "$title" > /dev/null
  grep -E "^(simInsts|system.cpu.numCycles|system.cpu.ipc|system.cpu.cpi) " \
      "$OUT/$name/stats.txt" | tee "$OUT/$name/key_stats.txt"
}

W="$PWD/workloads/bin"

showcase scalar_int_indep "Scalar O3 pipeline (width 1) - int_indep" \
    --cpu o3 --width 1 --workload "$W/int_indep"
showcase wide4_int_indep "4-wide O3 pipeline - int_indep" \
    --cpu o3 --width 4 --workload "$W/int_indep"
showcase wide4_int_dep "4-wide O3 pipeline - int_dep (serial chain)" \
    --cpu o3 --width 4 --workload "$W/int_dep"
showcase static_br_random "4-wide O3, static not-taken - br_random" \
    --cpu o3 --width 4 --bpred static --workload "$W/br_random"
showcase tage_br_random "4-wide O3, TAGE-SC-L - br_random" \
    --cpu o3 --width 4 --bpred tage --workload "$W/br_random"
showcase static_br_pattern "4-wide O3, static not-taken - br_pattern" \
    --cpu o3 --width 4 --bpred static --workload "$W/br_pattern"
showcase tournament_br_pattern "4-wide O3, tournament - br_pattern" \
    --cpu o3 --width 4 --bpred tournament --workload "$W/br_pattern"
N="$PWD/workloads/native"   # SMT uses the marker-free binaries
showcase smt2_mem_int "2-thread SMT, 4-wide O3 - mem_chase + int_indep" \
    --cpu o3 --width 4 --warmup-insts 500000 --roi-cycles 300000 \
    --workload "$N/mem_chase 1000000000" --workload "$N/int_indep 1000000000"
echo "done -> $OUT"
