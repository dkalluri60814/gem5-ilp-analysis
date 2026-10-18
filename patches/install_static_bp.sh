#!/usr/bin/env bash
# Installs the StaticNotTakenBP predictor into a gem5 source tree.
#   usage: install_static_bp.sh <path-to-gem5-tree>
# Idempotent: running it twice does not duplicate anything.
set -euo pipefail

GEM5_DIR="${1:?usage: $0 <gem5-dir>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRED="$GEM5_DIR/src/cpu/pred"
[ -d "$PRED" ] || { echo "not a gem5 tree: $GEM5_DIR" >&2; exit 1; }

cp "$HERE/static_not_taken.hh" "$HERE/static_not_taken.cc" "$PRED/"

# 1. Python SimObject (appended once)
if ! grep -q 'class StaticNotTakenBP' "$PRED/BranchPredictor.py"; then
cat >> "$PRED/BranchPredictor.py" <<'EOF'


class StaticNotTakenBP(ConditionalPredictor):
    type = "StaticNotTakenBP"
    cxx_class = "gem5::branch_prediction::StaticNotTakenBP"
    cxx_header = "cpu/pred/static_not_taken.hh"
EOF
fi

# 2. Register the SimObject and the source file with SCons
if ! grep -q "StaticNotTakenBP" "$PRED/SConscript"; then
  sed -i "s/'MultiperspectivePerceptronTAGE8KB', 'GshareBP'\]/'MultiperspectivePerceptronTAGE8KB', 'GshareBP',\n    'StaticNotTakenBP']/" "$PRED/SConscript"
  sed -i "s/^Source('gshare.cc')/Source('gshare.cc')\nSource('static_not_taken.cc')/" "$PRED/SConscript"
fi

grep -n "StaticNotTakenBP\|static_not_taken" "$PRED/SConscript" "$PRED/BranchPredictor.py"
echo "Installed. Now build:  cd $GEM5_DIR && scons build/X86/gem5.opt -j\$(nproc)"
