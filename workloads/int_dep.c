/* int_dep: integer work forming ONE long serial dependency chain.
 * Every operation needs the result of the previous one, so there is almost
 * no instruction-level parallelism to find: expect IPC ~ 1 on any machine,
 * no matter how wide it is. */
#include "ilp_common.h"

#ifndef ITERS
#define ITERS 300000
#endif

int main(int argc, char **argv)
{
    const long n = arg_or(argc, argv, ITERS);
    uint64_t x = 88172645463325252ULL;

    roi_begin();
    for (long i = 0; i < n; i++) {
        x = (x ^ (x >> 7)) + (uint64_t)i;
        x = (x << 3) ^ x;
        x += 0x9e3779b97f4a7c15ULL;
        x ^= x >> 11;
        OPAQUE_INT(x);
    }
    roi_end();

    printf("int_dep checksum %llu\n", (unsigned long long)x);
    return 0;
}
