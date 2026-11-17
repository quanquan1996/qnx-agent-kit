# qnx-agent-kit
Let an AI coding agent (any MCP client: Claude Code, Cursor, VS Code, ...) build, run and debug real-time software on QNX OS 8.0.
- `qnx_mcp.py` — zero-dependency MCP server (Python 3.10+, stdio). Tools: qnx_env, qnx_build, qnx_image, qnx_deploy, qnx_run, qnx_inspect, qnx_trace.
- `SKILL.md` — what the agent must know about QNX (not-Linux gotchas, real-time rules, how to read the tools' output).
- `demo/rt-loop` — 1 kHz PID loop with an intentional priority-inversion bug (sem_t lock). Fix: pthread mutex (priority inheritance).
Status: WIP for QNX Global Hackathon 2026.

## Verified on a real target (2026-11-16)
QNX SDP 8.0 on Windows 11 host (E:\qnx800), mkqnximage `--type=vbox --arch=x86_64`.
- All 7 MCP tools work end to end (test driver: ../winhost/mcptest.py).
- Windows OpenSSH needs `-c aes128-ctr -o MACs=hmac-sha2-256-etm@openssh.com` (built in).
- traceprinter is a host tool: qnx_trace records on target, copies the .kev back, decodes on host.
- VirtualBox timer jitter is 40-50 ms, so rt-loop reports lock-wait time; pinned to one CPU (`on -C 0`):
  semaphore 126-167 waits >1 ms (440-573 ms total) vs mutex 2-6 (79-91 ms).
- qnx_trace summary on the buggy build shows `control: SEM` blocks (~30/s) -> inversion signature.
- Unscripted agent run (Claude Code, Opus, 2026-11-16, source with no hints): build -> run -> trace -> diagnosis "priority inversion" -> PI mutex -> re-measure; lock waits >1 ms 128-157 -> 0-3, total 458-640 ms -> 50-73 ms. 16 turns, ~2 min.
- Fixed: `mkqnximage` (host/common/bin) and VBoxManage were not on the server's PATH, so `qnx_image` failed when called through MCP.
