# Codelab: let an AI agent find and fix a priority inversion on QNX 8.0

**Time:** ~45 min (most of it is the one-time SDP install). **You get:** a QNX 8.0 VM, an MCP server your coding agent can drive, and a real-time bug the agent finds from kernel trace data and fixes.

Tested 2026-11-16 on Windows 11 (i7-12700F, VirtualBox 7.2.22, Python 3.10, QNX SDP 8.0). Linux hosts work the same with `--type=qemu`.

## 1. Install QNX SDP 8.0 (free, non-commercial)
1. Create a myQNX account and request the free *QNX SDP 8.0 Non-Commercial* license (qnx.com → Products → Free Non-Commercial License). In *myQNX License Manager* click the serial number to see your **license key**.
2. Download *QNX Software Center* for your host and install it (`/S /D=<dir>` installs silently on Windows).
3. From a terminal (no GUI needed):
   ```
   qnxsoftwarecenter_clt -myqnx.user <email> -myqnx.password <pw> -addLicenseKey <key>
   qnxsoftwarecenter_clt -myqnx.user <email> -myqnx.password <pw> -mirror -listAccessible   # loads the repo
   qnxsoftwarecenter_clt -myqnx.user <email> -myqnx.password <pw> -installBaseline com.qnx.qnx800 -destination E:\qnx800
   ```
   Gotchas we hit: `-syncLicenseKeys` alone did not fetch our key (use `-addLicenseKey`); list/query commands fail with `"allrepos" is null` until you run `-mirror` once. The baseline is 4.7 GB (≈8 min).
4. Check: `E:\qnx800\qnxsdp-env.bat` then `qcc -V` lists `gcc_ntox86_64`.

## 2. Make a QNX VM
```
ssh-keygen -t ed25519 -N "" -f E:\qnx-vm\keys\qnxvm
cd E:\qnx-vm
mkqnximage --type=vbox --arch=x86_64 --ssh-ident=E:/qnx-vm/keys/qnxvm.pub --noprompt
mkqnximage --run=-h        # headless
mkqnximage --getip         # e.g. 192.168.56.102 (changes on each boot)
```
On Windows, `mkqnximage` uses the `bash.exe` shipped in the SDP and needs `VBoxManage` on PATH. QEMU images need a Linux host.

Windows' OpenSSH and the QNX 8.0 sshd disagree on the default MAC (`Corrupted MAC on input`); use `-c aes128-ctr -o MACs=hmac-sha2-256-etm@openssh.com`. The MCP server sets this for you.

## 3. Plug the MCP server into your agent
`qnx_mcp.py` is one file, standard library only. Example (Claude Code `.mcp.json`; Cursor/VS Code are the same shape):
```json
{"mcpServers": {"qnx": {"command": "python", "args": ["qnx_mcp.py"],
  "env": {"QNX_SDP": "E:/qnx800", "QNX_IMAGE_DIR": "E:/qnx-vm",
          "QNX_SSH_KEY": "E:/qnx-vm/keys/qnxvm"}}}}
```
Copy `SKILL.md` into the agent's skills/rules so it knows the QNX-isms. Tools:

| tool | does |
|---|---|
| `qnx_env` | finds the SDP, lists qcc variants |
| `qnx_build` | runs make/qcc, returns parsed `file:line: error` diagnostics |
| `qnx_image` | build / start / stop / getip the VM via mkqnximage |
| `qnx_deploy` | scp a binary to the target |
| `qnx_run` | run a command on the target |
| `qnx_inspect` | fixed read-only views: threads (`pidin`), procs, log (`slog2info`), hogs, mem, net |
| `qnx_trace` | records a kernel trace on the target (`tracelogger`), copies it back, decodes it on the host (`traceprinter`) and summarises runs/blocks per named thread |

## 4. The bug
`demo/rt-loop/rt_loop.c` is a 1 kHz PID control loop with three SCHED_FIFO threads:

| thread | prio | does |
|---|---|---|
| control | 50 | every 1 ms: lock, PID step, unlock |
| logger | 10 | every 10 ms: lock, snapshot (0.4 ms), wakes uploader *while holding the lock* |
| uploader | 30 | busy 4 ms "sending" |

The lock is a `sem_t`. Semaphores have no owner, so the kernel cannot boost the logger: the uploader (30) preempts the logger (10) inside the critical section and the control thread (50) waits ~4 ms. Classic priority inversion (Mars Pathfinder, 1997).

## 5. Ask the agent
Prompt we used:
> The control loop in demo/rt-loop sometimes stalls. Build it for QNX x86_64, run it pinned to one CPU, find out why using the QNX tools, fix it, and prove the fix with numbers.

What a good run looks like (real outputs from our VM):
1. `qnx_build` → 0 diagnostics. `qnx_deploy` → `/data/rt_loop`.
2. `qnx_run "on -C 0 /data/rt_loop"` →
   `RESULT lock=semaphore ... lock_waits_over_1ms=159 worst_lock_wait_us=8113 total_lock_wait_ms=555`
3. `qnx_trace {"seconds":1,"program":"on -C 0 /data/rt_loop","settle":5}` → summary shows
   `["…/2:SEM (control)", 30]`, `["…/4:SEM (uploader)", 31]` — the prio-50 control thread blocks on the semaphore about as often as it runs. `qnx_inspect threads` catches it in the act (real snapshot, 5 of 20 samples looked like this):
   ```
   pid     tid name       prio STATE    Blocked
   1654810   2 ./rt_loop   50f SEM      1171d2f03c   <- control waits for the lock
   1654810   3 ./rt_loop   10f READY                 <- logger holds it, cannot run
   1654810   4 ./rt_loop   30f RUNNING               <- uploader starves the logger
   ```
   High waits on low, low is starved by middle: priority inversion.
4. Agent swaps the `sem_t` for a `pthread_mutex_t` (QNX mutexes inherit priority by default) — in the demo, `-DUSE_MUTEX`.
5. Re-run →
   `RESULT lock=mutex ... lock_waits_over_1ms=4 total_lock_wait_ms=87`

| build | waits > 1 ms (5 s) | total wait |
|---|---|---|
| semaphore (bug) | 126–167 | 440–573 ms |
| mutex (fix) | 2–6 | 79–91 ms |

## 6. Why lock-wait and not deadline misses?
Inside VirtualBox the timer jitter is 40–50 ms (we measured a lone prio-50 thread: 1890/2000 wake-ups more than 200 µs late), and QNX 8.0 returns ENOTSUP for `ClockPeriod()`. Wake lateness is pure VM noise there; lock-wait time is not. On real hardware both metrics work. Teaching the agent this (it's in `SKILL.md`) stopped it from "fixing" VM noise.

## 7. Clean up
`mkqnximage --stop` (or `VBoxManage controlvm noname poweroff`).

## Where to go next
aarch64 on a Raspberry Pi 4 (`qcc -Vgcc_ntoaarch64le`), a `pdebug`/GDB tool, a CI action that runs the trace check on every PR.
