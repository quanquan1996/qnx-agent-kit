# Devpost submission draft — qnx-agent-kit
Repo: https://github.com/quanquan1996/qnx-agent-kit

**Category:** Developer Tooling & Host Tools. **Bonus:** Best Codelab/Tutorial (CODELAB.md); Best use of QNX-specific tech (tracelogger/pidin/priority inheritance).

## Tagline
Give your AI coding agent eyes into a real-time OS: build, run and debug on QNX 8.0 from Claude Code, Cursor or any MCP client.

## Inspiration
AI coding agents are great on Linux and the web, and nearly useless on embedded real-time systems: they reach for gcc, epoll and `ps`, and when timing goes wrong they guess. Real-time bugs are exactly the ones you cannot find by reading code — you need the scheduler's view. We wanted an agent that looks at the kernel trace before it answers.

## What it does
`qnx-agent-kit` is a single-file, dependency-free MCP server plus a skill file:
- **7 tools**: `qnx_env`, `qnx_build` (qcc with parsed diagnostics), `qnx_image` (mkqnximage VM build/start/stop/getip), `qnx_deploy`, `qnx_run`, `qnx_inspect` (read-only `pidin`, `slog2info`, `hogs`, memory, network), `qnx_trace` (record with `tracelogger` on the target, decode with host `traceprinter`, summarise runs and blocks per named thread).
- **SKILL.md** teaches the agent what is different on QNX: qcc variants, no epoll/inotify, toybox, slog2, message passing states, "mutexes inherit priority, semaphores don't", and how to read the tools' output.
- **A demo bug**: a 1 kHz PID loop whose shared lock is a `sem_t`. The agent finds the priority inversion from `pidin` and the trace, swaps in a `pthread_mutex_t`, and proves it: lock waits over 1 ms drop from 126–167 to 2–6 per 5 s, total lock wait from ~500 ms to ~85 ms.

## How we built it
Python standard library only (auditable in one read, ~300 lines), MCP spec 2025-06-18 stdio transport. Developed and tested on a Windows 11 host with QNX SDP 8.0 and a VirtualBox x86_64 image from `mkqnximage`; the tool talks to the target only over SSH, so a QEMU image on Linux works the same.

## Challenges
- `traceprinter` is a host tool, not on the target image — the trace tool records on target, copies the `.kev` back and decodes on the host.
- Windows OpenSSH vs QNX 8.0 sshd: the default MAC fails ("Corrupted MAC on input"); the server pins a working cipher/MAC.
- VirtualBox timer jitter is 40–50 ms and `ClockPeriod()` is not supported on 8.0, so deadline misses are VM noise. We switched the evidence to lock-wait time, which is robust, and put that rule into the skill so the agent doesn't "fix" noise.
- Software Center CLI: `-addLicenseKey` and `-mirror` are required before installs work headless (documented in the codelab).

## Accomplishments
A real, unscripted agent loop on a real QNX kernel, with numbers rather than vibes: given only "the loop stalls, find out why, fix it, prove it" and a source file with no hints (only the kit's SKILL.md as background), Claude Code (Opus) used the kit to build, run, trace, diagnose priority inversion, switch to a PI mutex and re-measure — 16 turns, ~2 minutes, US$0.36. Its before/after: lock waits >1 ms 128–157 → 0–3 per 5 s, total lock wait 458–640 ms → 50–73 ms, control-thread runs in the trace 574 → 1169. A second independent run reached the same diagnosis; a codelab anyone can follow in ~45 minutes on a laptop.

## What we learned
On a real-time OS, the most useful thing an agent can do is ask the scheduler. One `pidin` snapshot — prio 50 in `SEM`, prio 10 `READY`, prio 30 `RUNNING` — explains the bug better than any amount of code review.

## What's next
aarch64 on Raspberry Pi 4, a `pdebug`/GDB tool, a CI action that fails a PR when lock-wait regresses, more inspectors (resource managers, pulses).

## Built with
qnx, qnx-sdp-8.0, mcp, python, c, virtualbox, tracelogger

---

# Video script (≤ 3 min, screen recording + captions, no face/voice needed)
| t | screen | caption |
|---|---|---|
| 0:00–0:15 | title card, then rt_loop.c threads table | "AI agents can't see real-time bugs. Let's give them the scheduler's view." |
| 0:15–0:35 | `.mcp.json` + tool list in the agent | "qnx-agent-kit: one Python file, 7 MCP tools, QNX 8.0 target in a VM." |
| 0:35–0:50 | prompt typed to the agent | "The control loop stalls. Find out why, fix it, prove it." |
| 0:50–1:15 | agent calls qnx_build → qnx_deploy → qnx_run; RESULT line highlighted (159 waits) | "Builds with qcc, runs on QNX: 159 lock waits over 1 ms in 5 s." |
| 1:15–1:45 | qnx_inspect threads snapshot (SEM / READY / RUNNING) + qnx_trace summary | "Prio 50 waits, prio 10 holds the lock, prio 30 runs: priority inversion." |
| 1:45–2:10 | agent's diff sem_t → pthread_mutex_t, explanation | "QNX mutexes inherit priority. Semaphores don't." |
| 2:10–2:35 | re-run, before/after table | "2–6 waits, ~85 ms total. Fixed, with numbers." |
| 2:35–2:55 | CODELAB.md scroll, repo URL | "Try it in 45 minutes: codelab in the repo." |

The video replays a real recorded run (2026-11-16, run2): transcript and final report are in `agent-run/run2/`. The agent ran on a separate machine; tool calls reached the Windows host through a thin proxy (`agent-run/loomnode_proxy.py`).
