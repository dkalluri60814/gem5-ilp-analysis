/* fp_daxpy: y[i] = a*x[i] + y[i] over L1-resident arrays.
 * Every element is independent (loads, FP multiply, FP add, store), so an
 * out-of-order core can overlap many iterations: a floating-point,
 * load/store-heavy kernel with plenty of ILP. */
#include "ilp_common.h"

#define N 1024              /* 2 arrays * 8 KiB = 16 KiB, fits in L1D */

#ifndef REPS
#define REPS 280
#endif

static double x[N], y[N];

int main(int argc, char **argv)
{
    const long reps = arg_or(argc, argv, REPS);
    for (int i = 0; i < N; i++) {
        x[i] = 1.0 + i * 0.001;
        y[i] = 0.5;
    }
    const double a = 1.0000001;

    roi_begin();
    for (long r = 0; r < reps; r++) {
        for (int i = 0; i < N; i++)
            y[i] = a * x[i] + y[i];
    }
    roi_end();

    double s = 0.0;
    for (int i = 0; i < N; i++)
        s += y[i];
    printf("fp_daxpy checksum %.6f\n", s);
    return 0;
}
