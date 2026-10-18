/* Shared helpers for the ILP workloads.
 *
 * OPAQUE_*()  An empty inline-asm statement. It generates no instruction,
 *             but tells the compiler the value is "used and modified" here,
 *             which stops GCC from folding a loop into a closed form (e.g.
 *             sum of i) or hoisting work out of it. The dynamic instruction
 *             mix therefore matches what the C source says.
 *
 * roi_begin() / roi_end()
 *             Region-of-interest markers. When built with -DGEM5_ROI they
 *             emit gem5's "work begin / work end" magic instructions (opcode
 *             0F 04 + 16-bit code, same encoding as util/m5/.../m5op.S), so
 *             the simulator config can reset statistics right before the
 *             kernel and stop right after it. That excludes libc start-up
 *             and array initialisation from every measurement.
 *             Without -DGEM5_ROI they compile to nothing (native sanity
 *             runs); the magic instruction would raise SIGILL on real HW.
 *
 * arg_or()    Lets a run override the default iteration count from argv[1]
 *             (used by the SMT experiments to make every thread outlast the
 *             measurement window).
 */
#ifndef ILP_COMMON_H
#define ILP_COMMON_H

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

#define OPAQUE_INT(x) __asm__ volatile("" : "+r"(x))
#define OPAQUE_FP(x)  __asm__ volatile("" : "+x"(x))

#ifdef GEM5_ROI
#define M5_WORK_OP(code, id)                                              \
    do {                                                                  \
        register unsigned long m5a0 __asm__("rdi") = (unsigned long)(id); \
        register unsigned long m5a1 __asm__("rsi") = 0;                    \
        __asm__ volatile(".byte 0x0F, 0x04\n\t.word " #code                \
                         : "+r"(m5a0), "+r"(m5a1)                          \
                         :                                                 \
                         : "rax", "memory");                               \
    } while (0)
#define roi_begin() M5_WORK_OP(0x5a, getpid())
#define roi_end()   M5_WORK_OP(0x5b, getpid())
#else
#define roi_begin() ((void)0)
#define roi_end()   ((void)0)
#endif

static inline long arg_or(int argc, char **argv, long def)
{
    return argc > 1 ? atol(argv[1]) : def;
}

#endif
