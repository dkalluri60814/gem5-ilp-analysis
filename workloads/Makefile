# Builds the ILP workloads as static x86-64 binaries (gem5 SE mode cannot
# load dynamic libraries). Run `make` inside WSL/Linux.
#
#   make          -> bin/<prog>     for gem5 (has region-of-interest markers)
#   make native   -> native/<prog>  no markers; runs on the host as a sanity check
#
#   -fno-tree-vectorize     keep scalar code so instruction counts match
#                           the C source (and no SIMD the sim might lack)
#   -fno-if-conversion*     (branch kernels only) keep real branches
#                           instead of turning them into cmov

CC      ?= gcc
CFLAGS  := -O2 -static -fno-tree-vectorize -fno-asynchronous-unwind-tables
BRFLAGS := -fno-if-conversion -fno-if-conversion2

PROGS := int_dep int_indep fp_dep fp_daxpy mem_stream mem_chase \
         br_pattern br_random matmul

all: $(addprefix bin/,$(PROGS))
native: $(addprefix native/,$(PROGS))

bin/br_pattern bin/br_random native/br_pattern native/br_random: \
    CFLAGS += $(BRFLAGS)

bin/%: %.c ilp_common.h
	@mkdir -p bin
	$(CC) $(CFLAGS) -DGEM5_ROI -o $@ $<

native/%: %.c ilp_common.h
	@mkdir -p native
	$(CC) $(CFLAGS) -o $@ $<

clean:
	rm -rf bin native

.PHONY: all native clean
