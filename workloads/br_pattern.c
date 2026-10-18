/* br_pattern: data-independent branches that follow short repeating
 * patterns (period 2, period 4, period 16). A history-based predictor
 * learns them perfectly; a plain per-PC 2-bit counter cannot learn the
 * alternating ones; "always not-taken" gets about half of them wrong.
 * Built with if-conversion disabled so the branches stay real branches. */
#include "ilp_common.h"

#ifndef ITERS
#define ITERS 150000
#endif

int main(int argc, char **argv)
{
    const long n = arg_or(argc, argv, ITERS);
    uint64_t a = 0, b = 0, c = 0, d = 0, e = 0;

    roi_begin();
    for (long i = 0; i < n; i++) {
        if (i & 1) {                    /* T N T N ...          */
            a += i;
        } else {
            b -= i;
        }
        if ((i & 3) == 3) {             /* N N N T repeating    */
            c ^= a;
        } else {
            d += b;
        }
        if ((i & 15) == 0) {            /* T once every 16      */
            e += 1;
        }
        OPAQUE_INT(a); OPAQUE_INT(b); OPAQUE_INT(c); OPAQUE_INT(d);
        OPAQUE_INT(e);
    }
    roi_end();

    printf("br_pattern checksum %llu\n", (unsigned long long)(a ^ b ^ c ^ d ^ e));
    return 0;
}
