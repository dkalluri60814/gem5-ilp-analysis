/* br_random: two branches per iteration whose outcome comes from a
 * pseudo-random generator (LCG high bits). They are inherently
 * unpredictable (~50% taken), so every predictor mispredicts about half of
 * them and the pipeline-flush penalty dominates.
 * Built with if-conversion disabled so the branches stay real branches. */
#include "ilp_common.h"

#ifndef ITERS
#define ITERS 120000
#endif

int main(int argc, char **argv)
{
    const long n = arg_or(argc, argv, ITERS);
    uint64_t s = 88172645463325252ULL;
    uint64_t a = 0, b = 0, c = 0, d = 0;

    roi_begin();
    for (long i = 0; i < n; i++) {
        s = s * 6364136223846793005ULL + 1442695040888963407ULL;
        OPAQUE_INT(s);
        if ((s >> 33) & 1) {
            a += s;
        } else {
            b ^= s;
        }
        if ((s >> 41) & 1) {
            c += a;
        } else {
            d -= b;
        }
        OPAQUE_INT(a); OPAQUE_INT(b); OPAQUE_INT(c); OPAQUE_INT(d);
    }
    roi_end();

    printf("br_random checksum %llu\n", (unsigned long long)(a ^ b ^ c ^ d));
    return 0;
}
