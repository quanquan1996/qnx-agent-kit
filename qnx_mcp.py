#!/usr/bin/env python3
"""qnx-agent-kit: a tiny, dependency-free MCP server (stdio, JSON-RPC 2.0)
that lets a coding agent build, deploy, run and inspect software on a
QNX SDP 8.0 target (VirtualBox/VMware/QEMU image made by mkqnximage).

Protocol follows the Model Context Protocol spec (2025-06-18, stdio transport):
https://modelcontextprotocol.io/specification - one JSON object per line.

Config (environment variables):
  QNX_SDP        path to SDP install (dir containing qnxsdp-env.sh/.bat)
  QNX_IMAGE_DIR  directory holding the mkqnximage image (default ~/qnx-vm)
  QNX_TARGET_IP  target IP (optional; else `mkqnximage --getip`)
  QNX_SSH_KEY    ssh identity file (optional)
"""
import json, os, platform, re, shlex, subprocess, sys, time
from pathlib import Path

PROTOCOL = "2025-06-18"
MAX_OUT = 12000  # chars returned to the agent per call


# ---------------------------------------------------------------- env
def sdp_env():
    sdp = os.environ.get("QNX_SDP")
    if not sdp:
        for c in [Path.home() / "qnx800", Path("E:/qnx800"), Path("C:/qnx800")]:
            if c.exists():
                sdp = str(c)
                break
    if not sdp:
        raise RuntimeError("QNX SDP not found: set QNX_SDP")
    hostdir = "win64" if platform.system() == "Windows" else "linux"
    env = dict(os.environ)
    env["QNX_HOST"] = str(Path(sdp) / "host" / hostdir / "x86_64")
    env["QNX_TARGET"] = str(Path(sdp) / "target" / "qnx")
    paths = [str(Path(env["QNX_HOST"]) / "usr" / "bin"), str(Path(sdp) / "host" / "common" / "bin")]
    vbox = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Oracle" / "VirtualBox"
    if platform.system() == "Windows" and vbox.exists():  # mkqnximage --type=vbox needs VBoxManage
        paths.append(str(vbox))
    env["PATH"] = os.pathsep.join(paths + [env["PATH"]])
    env["MAKEFLAGS"] = env.get("MAKEFLAGS", "") + " -I" + str(Path(env["QNX_TARGET"]) / "usr" / "include")
    return sdp, env


def run(cmd, cwd=None, timeout=300, env=None, shell=False):
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, shell=shell, capture_output=True,
                           text=True, errors="replace", timeout=timeout)
        out, code = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired as e:
        out, code = (e.stdout or "") if isinstance(e.stdout, str) else "", -1
        out += f"\n[timeout after {timeout}s]"
    return code, out, round(time.time() - t0, 2)


def clip(s):
    return s if len(s) <= MAX_OUT else s[:MAX_OUT // 3] + "\n...[clipped]...\n" + s[-2 * MAX_OUT // 3:]


# ---------------------------------------------------------------- target
def image_dir():
    return os.environ.get("QNX_IMAGE_DIR", str(Path.home() / "qnx-vm"))


def mkqnximage(args, timeout=900):
    _, env = sdp_env()
    exe = "mkqnximage.bat" if platform.system() == "Windows" else "mkqnximage"
    Path(image_dir()).mkdir(parents=True, exist_ok=True)
    return run([exe] + args, cwd=image_dir(), timeout=timeout, env=env,
               shell=platform.system() == "Windows")


def target_ip():
    ip = os.environ.get("QNX_TARGET_IP")
    if ip:
        return ip
    _, out, _ = mkqnximage(["--getip"], timeout=60)
    m = re.search(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b", out)
    if not m:
        raise RuntimeError("cannot get target IP; is the image running? " + out[-400:])
    return m.group(1)


def ssh_base(tool="ssh"):
    base = [tool, "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=" + os.devnull,
            "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
            # Windows OpenSSH 9.5 <-> QNX 8.0 sshd (OpenSSH 10.4): the default
            # MAC gives "Corrupted MAC on input" and sshd offers only aes*-ctr.
            "-c", "aes128-ctr", "-o", "MACs=hmac-sha2-256-etm@openssh.com"]
    if os.environ.get("QNX_SSH_KEY"):
        base += ["-i", os.environ["QNX_SSH_KEY"]]
    return base


def ssh(cmd, timeout=60):
    return run(ssh_base() + ["root@" + target_ip(), cmd], timeout=timeout)


# ---------------------------------------------------------------- tools
ERR_RE = re.compile(r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>error|warning|note):\s*(?P<msg>.*)$", re.M)


def t_env(_):
    sdp, env = sdp_env()
    code, out, _ = run(["qcc", "-V"], env=env, timeout=30, shell=platform.system() == "Windows")
    return {"sdp": sdp, "QNX_HOST": env["QNX_HOST"], "QNX_TARGET": env["QNX_TARGET"],
            "image_dir": image_dir(), "qcc_variants": clip(out)}


def t_build(a):
    _, env = sdp_env()
    cmd = a.get("command") or "make"
    code, out, secs = run(cmd, cwd=a["project_dir"], env=env, timeout=a.get("timeout", 600), shell=True)
    diags = [m.groupdict() for m in ERR_RE.finditer(out)][:50]
    return {"exit_code": code, "seconds": secs, "diagnostics": diags, "log": clip(out)}


def t_image(a):
    action = a["action"]
    args = {"build": ["--type=" + a.get("type", "vbox"), "--arch=" + a.get("arch", "x86_64"), "--build"],
            "start": ["--run=-h"], "stop": ["--stop"], "getip": ["--getip"],
            "options": ["--options"]}[action]
    code, out, secs = mkqnximage(args)
    res = {"exit_code": code, "seconds": secs, "log": clip(out)}
    if action == "start" and code == 0:
        for _ in range(30):  # wait for sshd
            try:
                c, o, _ = ssh("uname -a", timeout=15)
                if c == 0:
                    res["uname"] = o.strip()
                    break
            except RuntimeError:
                pass
            time.sleep(5)
    return res


def t_deploy(a):
    ip = target_ip()
    remote = a.get("remote_path", "/tmp/")
    code, out, secs = run(ssh_base("scp") + [a["local_path"], f"root@{ip}:{remote}"], timeout=120)
    return {"exit_code": code, "seconds": secs, "log": clip(out)}


def t_run(a):
    code, out, secs = ssh(a["command"], timeout=a.get("timeout", 60))
    return {"exit_code": code, "seconds": secs, "output": clip(out)}


# Fixed, read-only inspection commands (no arbitrary shell here).
INSPECT = {
    "threads": "pidin",                    # default fmt: pid tid name prio state blocked-on
    "procs": "pidin -f an",
    "log": "slog2info | tail -n 200",
    "hogs": "hogs -i 3 -s 1",
    "mem": "pidin info; pidin -f anc",
    "net": "ifconfig; netstat -rn",
}


def t_inspect(a):
    kind = a["kind"]
    if kind not in INSPECT:
        raise ValueError("kind must be one of " + ", ".join(INSPECT))
    code, out, _ = ssh(INSPECT[kind], timeout=60)
    return {"exit_code": code, "command": INSPECT[kind], "output": clip(out)}


def t_trace(a):
    """Capture a kernel event trace on the target while optionally running a
    program, copy the .kev back, and decode it with the HOST traceprinter
    (traceprinter ships in the SDP host tools, not on the target image).
    Verified on QNX 8.0 VBox image 2026-11-16: lines look like
    't:0x8471518e CPU:00 THREAD :THRUNNING pid:864282 tid:2'."""
    import tempfile
    secs = int(a.get("seconds", 3))
    prog = a.get("program", "")
    sh = ((f"({prog} > /tmp/agent.out 2>&1 &); sleep 1; " if prog else "")
          + f"tracelogger -n 0 -s {secs} -f /tmp/agent.kev; sleep {int(a.get('settle', 1))}; "
          + ("cat /tmp/agent.out" if prog else "true"))
    code, out, _ = ssh(sh, timeout=secs + 60)
    kev = Path(tempfile.gettempdir()) / "agent.kev"
    c2, o2, _ = run(ssh_base("scp") + [f"root@{target_ip()}:/tmp/agent.kev", str(kev)], timeout=120)
    if c2 != 0:
        return {"exit_code": c2, "error": "scp of trace failed", "log": clip(o2)}
    _, env = sdp_env()
    c3, text, _ = run(["traceprinter", "-f", str(kev)], env=env, timeout=120,
                      shell=platform.system() == "Windows")
    return {"exit_code": c3, "program_output": clip(out), "summary": summarise_trace(text),
            "events_lines": text.count("\n"), "raw_head": clip(text[:6000])}


def summarise_trace(text):
    # Count thread state transitions per (pid,tid) and context switches; cheap,
    # good enough for an agent to spot starvation / priority inversion.
    running, blocked = {}, {}
    # thread names come from PROCTHREAD_NAME records spread over 3 lines
    names = {f"{p}/{t}": n.strip() for p, t, n in
             re.findall(r"PROCTHREAD_NAME\s*\n\s*pid:(\d+)\s*\n\s*tid:(\d+)\s*\n\s*name:(.*)", text)}
    for line in text.splitlines():
        m = re.search(r"THRUNNING\s+pid:(\d+)\s+tid:(\d+)", line)
        if m:
            k = m.group(1) + "/" + m.group(2)
            running[k] = running.get(k, 0) + 1
        m = re.search(r"TH(MUTEX|SEM|CONDVAR|RECEIVE|REPLY|SEND)\s+pid:(\d+)\s+tid:(\d+)", line)
        if m:
            k = m.group(2) + "/" + m.group(3) + ":" + m.group(1)
            blocked[k] = blocked.get(k, 0) + 1
    label = lambda k: k + (" (" + names[k.split(":")[0]] + ")" if k.split(":")[0] in names else "")
    top = lambda d: [(label(k), v) for k, v in sorted(d.items(), key=lambda x: -x[1])[:15]]
    return {"runs_per_thread": top(running), "blocks_per_thread": top(blocked)}


TOOLS = {
    "qnx_env": (t_env, "Show QNX SDP location, image dir and available qcc variants.", {}),
    "qnx_build": (t_build, "Build a project with the QNX toolchain (qcc/q++ on PATH). Returns parsed compiler diagnostics.",
                  {"project_dir": {"type": "string"}, "command": {"type": "string", "description": "default: make"},
                   "timeout": {"type": "integer"}}),
    "qnx_image": (t_image, "Manage the QNX VM image via mkqnximage: build|start|stop|getip|options.",
                  {"action": {"type": "string", "enum": ["build", "start", "stop", "getip", "options"]},
                   "type": {"type": "string", "enum": ["vbox", "vmware", "qemu"]},
                   "arch": {"type": "string", "enum": ["x86_64", "aarch64le"]}}),
    "qnx_deploy": (t_deploy, "Copy a file to the target with scp.",
                   {"local_path": {"type": "string"}, "remote_path": {"type": "string"}}),
    "qnx_run": (t_run, "Run a shell command on the target over ssh and return output and exit code.",
                {"command": {"type": "string"}, "timeout": {"type": "integer"}}),
    "qnx_inspect": (t_inspect, "Read-only target inspection: threads (priority, state, blocked-on), procs, log (slog2), hogs, mem, net.",
                    {"kind": {"type": "string", "enum": list(INSPECT)}}),
    "qnx_trace": (t_trace, "Capture a kernel event trace (tracelogger) for N seconds, optionally while running a program, and summarise thread runs/blocks.",
                  {"seconds": {"type": "integer"}, "program": {"type": "string"}, "settle": {"type": "integer", "description": "seconds to wait after the trace before reading program output (default 1)"}}),
}
REQUIRED = {"qnx_build": ["project_dir"], "qnx_image": ["action"], "qnx_deploy": ["local_path"],
            "qnx_run": ["command"], "qnx_inspect": ["kind"]}


# ---------------------------------------------------------------- MCP loop
def tool_list():
    return [{"name": n, "description": d,
             "inputSchema": {"type": "object", "properties": p, "required": REQUIRED.get(n, [])}}
            for n, (_, d, p) in TOOLS.items()]


def handle(msg):
    method, mid, params = msg.get("method"), msg.get("id"), msg.get("params") or {}
    if method == "initialize":
        return {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "qnx-agent-kit", "version": "0.1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": tool_list()}
    if method == "tools/call":
        name = params.get("name")
        if name not in TOOLS:
            raise KeyError("unknown tool " + str(name))
        try:
            res = TOOLS[name][0](params.get("arguments") or {})
            return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, indent=1)}]}
        except Exception as e:  # tool errors go back to the model, not as protocol errors
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}
    raise NotImplementedError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if "id" not in msg:  # notification (e.g. notifications/initialized)
            continue
        try:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": handle(msg)}
        except NotImplementedError as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "method not found: " + str(e)}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32602, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
