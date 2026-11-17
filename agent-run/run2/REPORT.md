# rt-loop stall report

**Root cause: priority inversion.** The state shared between threads was guarded by a POSIX semaphore (`sem_t lock`, `rt_loop.c:15`). Semaphores don't do priority inheritance. Here is the sequence that stalled the loop, all on CPU 0:

1. The logger (prio 10) takes the lock.
2. While still holding it, the logger calls `sem_post(&kick)`.
3. That wakes the uploader (prio 30), which preempts the logger and spins for 4 ms.
4. The control loop (prio 50) is now waiting for a lock held by a prio-10 thread that can't run, because a prio-30 thread that never touches the lock has the CPU. Each time, the 1 kHz loop loses about 4–7 ms.

**Evidence (before the fix):**
- The kernel trace shows `control` blocked in **SEM** 122 times in 6 s. Over the same period `uploader` ran 236 times on that CPU and only got the CPU through `kick` (it also blocked in SEM 123 times).
- The worst lock wait was 5.1–6.9 ms. That matches the uploader's 4 ms spin plus the logger's remaining 200 µs, plus timer jitter.

**Fix:** I replaced the `sem_t` lock with a `pthread_mutex_t` created with `PTHREAD_PRIO_INHERIT`. When `control` blocks on the mutex, the logger is boosted to prio 50, preempts the uploader, finishes its 200 µs and releases the lock straight away. The `kick` handoff and the thread priorities are unchanged. I rebuilt it, deployed it to `/data/` and ran it with `on -C 0 /data/rt_loop`. I confirmed that `pthread_mutex_lock` is in the deployed binary.

**Numbers** (each run is 5 s; three plain runs plus one under trace, per side):

| Metric | Before (`sem_t`) | After (PI mutex) |
|---|---|---|
| Lock waits > 1 ms | 156 / 128 / 133 / 157 | 3 / 0 / 3 / 2 |
| Worst lock wait | 5124 / 6662 / 6203 / 6889 µs | 3869 / 971 / 4467 / 4482 µs |
| Total lock wait | 582 / 458 / 520 / 640 ms | 64 / 50 / 73 / 61 ms |
| `control` runs in trace | 574 | 1169 |

Lock waits over 1 ms fell by about 98% and total lock wait by about 89%.

In the after trace, `control` still blocks on the mutex about 126 times. That is expected: it waits for the logger's 200 µs critical section, and those waits are now short.

The few waits still over 1 ms (up to about 4.5 ms) happen with the fix in place. I think they are VirtualBox timer and scheduling stalls landing inside the logger's critical section, but I haven't confirmed that. Wake-lateness misses stay high (about 3800–4200 per run against about 4500 before), which is the VM's 40–50 ms timer jitter. As instructed, I didn't use lateness to judge the fix.

**Optional next step:** move `sem_post(&kick)` to after `UNLOCK()` in the logger, so it doesn't wake another thread while holding the lock. The PI mutex already fixes the inversion, so this would be extra hardening.
