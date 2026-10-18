/*
 * Static "always not-taken" conditional branch predictor.
 *
 * Added for the ILP assignment (Part 2): stock gem5 has no way to switch
 * branch prediction off, so this is the "no dynamic prediction" baseline.
 * Every conditional branch is predicted not-taken, so fetch simply keeps
 * running down the fall-through path and each taken branch is only
 * discovered (and the pipeline squashed) when it is resolved.
 *
 * The predictor keeps no state, so bp_history is never allocated and must
 * stay NULL (same contract as LocalBP).
 */

#ifndef __CPU_PRED_STATIC_NOT_TAKEN_HH__
#define __CPU_PRED_STATIC_NOT_TAKEN_HH__

#include "base/types.hh"
#include "cpu/pred/conditional.hh"
#include "params/StaticNotTakenBP.hh"

namespace gem5
{

namespace branch_prediction
{

class StaticNotTakenBP : public ConditionalPredictor
{
  public:
    StaticNotTakenBP(const StaticNotTakenBPParams &params);

    bool lookup(ThreadID tid, Addr pc, void * &bp_history) override;

    void updateHistories(ThreadID tid, Addr pc, bool uncond, bool taken,
                         Addr target, const StaticInstPtr &inst,
                         void * &bp_history) override;

    void squash(ThreadID tid, void * &bp_history) override;

    void update(ThreadID tid, Addr pc, bool taken, void * &bp_history,
                bool squashed, const StaticInstPtr &inst,
                Addr target) override;

    void branchPlaceholder(ThreadID tid, Addr pc, bool uncond,
                           void * &bp_history) override;
};

} // namespace branch_prediction
} // namespace gem5

#endif // __CPU_PRED_STATIC_NOT_TAKEN_HH__
