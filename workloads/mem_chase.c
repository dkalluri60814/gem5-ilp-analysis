/* mem_chase: pointer chasing through a scattered cyclic permutation of 32K
 * cache-line-sized nodes (2 MiB, larger than the 256 KiB L2).
 * The address of each load is the data returned by the previous load, so
 * misses cannot overlap. This is latency-bound: neither a wide issue
 * width nor a big window helps. */
#include "ilp_common.h"

#define NODES 32768

#ifndef STEPS
#define STEPS 60000
#endif

struct node {
    long next;
    char pad[56];           /* one node per 64-byte cache line */
};

static struct node nodes[NODES];

int main(int argc, char **argv)
{
    const long steps = arg_or(argc, argv, STEPS);

    /* x -> a*x + c (mod 2^15) with a = 1 (mod 4) and c odd has full period
     * (Hull-Dobell), so following `next` visits every node exactly once
     * before repeating, in a scattered order. Cheap to build, unlike a
     * shuffle, which keeps the simulation set-up phase short. */
    for (long i = 0; i < NODES; i++)
        nodes[i].next = (i * 1103515245L + 12345L) & (NODES - 1);

    long p = 0;

    roi_begin();
    for (long k = 0; k < steps; k++)
        p = nodes[p].next;
    roi_end();

    printf("mem_chase checksum %ld\n", p);
    return 0;
}
