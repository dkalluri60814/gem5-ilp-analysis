/* mem_stream: sequential sum over a 2 MiB array (larger than the 256 KiB L2).
 * Loads are independent and addresses are predictable, so a wide
 * out-of-order window can keep several cache-line misses in flight
 * (memory-level parallelism), whereas an in-order pipe stalls on each. */
#include "ilp_common.h"

#define N (512 * 1024)      /* 512K ints = 2 MiB */

#ifndef PASSES
#define PASSES 3
#endif

static int arr[N];

int main(int argc, char **argv)
{
    const long passes = arg_or(argc, argv, PASSES);
    /* Touch one int per 4 KiB page so the pages exist before the timed
     * region (the values themselves do not matter for timing). */
    for (int i = 0; i < N; i += 1024)
        arr[i] = i;

    long s0 = 0, s1 = 0, s2 = 0, s3 = 0;

    roi_begin();
    for (long p = 0; p < passes; p++) {
        for (int i = 0; i < N; i += 4) {
            s0 += arr[i];
            s1 += arr[i + 1];
            s2 += arr[i + 2];
            s3 += arr[i + 3];
        }
    }
    roi_end();

    printf("mem_stream checksum %ld\n", s0 + s1 + s2 + s3);
    return 0;
}
