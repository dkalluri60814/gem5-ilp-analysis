/* fp_dep: floating-point recurrence x = x*c + d (a Horner-style chain).
 * The multiply feeds the add, which feeds the next multiply, so throughput
 * is set by FP-multiply + FP-add latency rather than by issue width. */
#include "ilp_common.h"

#ifndef ITERS
#define ITERS 300000
#endif

int main(int argc, char **argv)
{
    const long n = arg_or(argc, argv, ITERS);
    double x = 1.0;
    const double c = 0.999999, d = 0.000001;

    roi_begin();
    for (long i = 0; i < n; i++) {
        x = x * c + d;
        OPAQUE_FP(x);
    }
    roi_end();

    printf("fp_dep checksum %.9f\n", x);
    return 0;
}
