/*
 * Static "always not-taken" conditional branch predictor.
 * See static_not_taken.hh for the rationale.
 */

#include "cpu/pred/static_not_taken.hh"

namespace gem5
{

namespace branch_prediction
{

StaticNotTakenBP::StaticNotTakenBP(const StaticNotTakenBPParams &params)
    : ConditionalPredictor(params)
{
}

bool
StaticNotTakenBP::lookup(ThreadID tid, Addr pc, void * &bp_history)
{
    // No state is kept: never predict taken.
    return false;
}

void
StaticNotTakenBP::updateHistories(ThreadID tid, Addr pc, bool uncond,
                                  bool taken, Addr target,
                                  const StaticInstPtr &inst,
                                  void * &bp_history)
{
}

void
StaticNotTakenBP::squash(ThreadID tid, void * &bp_history)
{
}

void
StaticNotTakenBP::update(ThreadID tid, Addr pc, bool taken,
                         void * &bp_history, bool squashed,
                         const StaticInstPtr &inst, Addr target)
{
}

void
StaticNotTakenBP::branchPlaceholder(ThreadID tid, Addr pc, bool uncond,
                                    void * &bp_history)
{
}

} // namespace branch_prediction
} // namespace gem5
