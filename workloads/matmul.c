/* matmul: 32x32 double-precision matrix multiply (C = A*B), repeated.
 * A mixed kernel: FP multiply-add, strided loads (B is walked by column),
 * short inner loops (31 taken branches then 1 exit) and a loop-carried FP
 * accumulator. Typical of a "real" numeric inner loop. */
#include "ilp_common.h"

#define N 32

#ifndef REPS
#define REPS 12
#endif

static double A[N][N], B[N][N], C[N][N];

int main(int argc, char **argv)
{
    const long reps = arg_or(argc, argv, REPS);
    for (int i = 0; i < N; i++)
        for (int j = 0; j < N; j++) {
            A[i][j] = 1.0 + (i + j) * 0.01;
            B[i][j] = 2.0 - (i - j) * 0.01;
        }

    roi_begin();
    for (long r = 0; r < reps; r++) {
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                double sum = 0.0;
                for (int k = 0; k < N; k++)
                    sum += A[i][k] * B[k][j];
                C[i][j] = sum;
            }
        }
        A[0][0] += C[0][0] * 1e-9;      /* make reps depend on each other */
    }
    roi_end();

    double t = 0.0;
    for (int i = 0; i < N; i++)
        t += C[i][i];
    printf("matmul checksum %.6f\n", t);
    return 0;
}
