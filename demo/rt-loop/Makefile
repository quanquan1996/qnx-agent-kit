# Build for QNX 8.0 x86_64 (use gcc_ntoaarch64le for ARM targets)
CC = qcc -Vgcc_ntox86_64
CFLAGS = -O2 -Wall
all: rt_loop rt_loop_fixed
rt_loop: rt_loop.c
	$(CC) $(CFLAGS) -o $@ $<
rt_loop_fixed: rt_loop.c
	$(CC) $(CFLAGS) -DUSE_MUTEX -o $@ $<
clean:
	rm -f rt_loop rt_loop_fixed
