/* int_indep: eight independent integer recurrences per iteration.
 * Each accumulator only depends on its own previous value (1-cycle ops), so
 * all eight updates can issue in the same cycle. This is the "easy" case:
 * IPC is limited by the machine width, not by the program. */
#include "ilp_common.h"

#ifndef ITERS
#define ITERS 250000
#endif

int main(int argc, char **argv)
{
    const long n = arg_or(argc, argv, ITERS);
    uint64_t a0 = 1, a1 = 2, a2 = 3, a3 = 4, a4 = 5, a5 = 6, a6 = 7, a7 = 8;

    roi_begin();
    for (long i = 0; i < n; i++) {
        a0 += i;
        a1 ^= i;
        a2 += 3;
        a3 ^= 5;
        a4 += (uint64_t)i << 1;
        a5 -= 7;
        a6 ^= (uint64_t)i >> 1;
        a7 += 11;
        OPAQUE_INT(a0); OPAQUE_INT(a1); OPAQUE_INT(a2); OPAQUE_INT(a3);
        OPAQUE_INT(a4); OPAQUE_INT(a5); OPAQUE_INT(a6); OPAQUE_INT(a7);
    }
    roi_end();

    printf("int_indep checksum %llu\n",
           (unsigned long long)(a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7));
    return 0;
}
