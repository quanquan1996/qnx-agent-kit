---
name: qnx-dev
description: Develop, run and debug C/C++ software on a QNX OS 8.0 target through the qnx-agent-kit MCP tools. Use when the user mentions QNX, Neutrino, qcc, a QNX VM/target, real-time deadlines, priorities or tracelogger.
---
# Working on QNX 8.0 with qnx-agent-kit

Loop: `qnx_env` once -> edit -> `qnx_build` -> `qnx_deploy` -> `qnx_run` -> if timing is wrong, `qnx_inspect threads` and `qnx_trace` -> fix -> repeat. Start the VM with `qnx_image start` if `qnx_run` cannot connect.

## QNX is not Linux (things agents get wrong)
- Compiler: `qcc -Vgcc_ntox86_64` (or `gcc_ntoaarch64le`), not gcc. Link sockets with `-lsocket`; no `-lpthread`/`-lrt` needed.
- Missing Linux APIs: epoll, inotify, eventfd, signalfd, /proc/<pid>/status text files, systemd. Use `ionotify()`/pulses, `MsgReceive()`, `pidin`.
- Userland is toybox: options of ps/top/grep differ; use `pidin` and `hogs`.
- Logs go to slog2 (`slog2info`), not syslog files.
- Microkernel IPC: client `MsgSend()` -> server `MsgReceive()`/`MsgReply()`; a thread stuck in SEND/REPLY state is waiting on another process, look at who.

## Real-time rules
- Priorities 1-255 (user default max 63 unless `procnto -P`), SCHED_FIFO/RR/SPORADIC. Higher number = more urgent.
- **pthread mutexes inherit priority by default. POSIX semaphores, condvars-as-locks, and spin flags do not.** A shared lock implemented with `sem_t` between threads of different priority is a priority-inversion bug.
- Do periodic work with `clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, ...)` (no drift), never `sleep()` in a loop. Measure lateness against the absolute deadline.
- Timer resolution is 1 ms (`clock_getres`); on QNX 8.0 `ClockPeriod()` to change it returns ENOTSUP. Inside VirtualBox, wake-up jitter is 40-50 ms: judge lock contention by **time spent waiting for the lock**, not by wake lateness, unless on real hardware.
- Pin to one CPU for reproducible timing: `on -C 0 ./prog` (check `on` flags with `use on`).

## Reading `qnx_inspect threads`
State column: RUNNING/READY = wants CPU; MUTEX/SEM/CONDVAR = waiting on a lock (blocked-on shows which); SEND/REPLY/RECEIVE = IPC; NANOSLEEP = timer. A high-priority thread repeatedly in SEM while a middle-priority thread is READY/RUNNING = inversion.

## Reading `qnx_trace`
`runs_per_thread` = how often each thread got the CPU; `blocks_per_thread` = how often it blocked and on what. Compare before/after a fix and report numbers (lock waits, worst wait, misses), not impressions. Trace decoding (traceprinter) happens on the host; the tool does it for you.
