#!/usr/bin/env python3
"""stdio MCP proxy: the agent runs here (Loom server), qnx_mcp.py runs on the
Windows dev host (where SDP + the VM live). Each request is sent one-shot via
`loom-node write` + `loom-node exec`, so no cloud credentials ever reach the
dev host and no long-lived tunnel is needed. qnx_mcp.py is stateless per call.

Optional QNX_SYNC=<local_dir>=<remote_dir>: before every qnx_build whose
project_dir is <remote_dir>, the top-level files of <local_dir> are pushed
there (so the agent edits locally and builds remotely).

Env: QNX_NODE (default HomeWindows), QNX_REMOTE_DIR (default E:\\qnx-work),
     QNX_TARGET_IP (optional, forwarded).
"""
import json, os, subprocess, sys, tempfile

NODE = os.environ.get("QNX_NODE", "HomeWindows")
RDIR = os.environ.get("QNX_REMOTE_DIR", r"E:\qnx-work")
REQ = RDIR + r"\proxy-req.jsonl"
ENV = {"QNX_SDP": r"E:\qnx800", "QNX_IMAGE_DIR": r"E:\qnx-vm",
       "QNX_SSH_KEY": r"E:\qnx-vm\keys\qnxvm"}
if os.environ.get("QNX_TARGET_IP"):
    ENV["QNX_TARGET_IP"] = os.environ["QNX_TARGET_IP"]


def sync(msg):
    spec = os.environ.get("QNX_SYNC")
    if not spec or msg.get("method") != "tools/call":
        return
    p = msg.get("params") or {}
    local, rdir = spec.split("=", 1)
    if p.get("name") != "qnx_build" or (p.get("arguments") or {}).get("project_dir") != rdir:
        return
    for n in sorted(os.listdir(local)):
        fp = os.path.join(local, n)
        if os.path.isfile(fp):
            with open(fp, "rb") as fh:
                subprocess.run(["loom-node", "write", NODE, rdir + "\\" + n], stdin=fh,
                               check=True, stdout=subprocess.DEVNULL)


def remote(msg, timeout=900):
    sync(msg)
    lines = [{"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}}, msg]
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write("\n".join(json.dumps(l) for l in lines) + "\n")
    with open(f.name, "rb") as fh:
        subprocess.run(["loom-node", "write", NODE, REQ], stdin=fh, check=True,
                       stdout=subprocess.DEVNULL)
    os.unlink(f.name)
    sets = "".join(f"$env:{k}='{v}'; " for k, v in ENV.items())
    cmd = f"{sets}cmd /c 'python {RDIR}\\qnx_mcp.py < {REQ}'"
    out = subprocess.run(["loom-node", "exec", NODE, "--timeout", str(timeout), "--", cmd],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    replies = [l for l in out.stdout.splitlines() if l.startswith('{"jsonrpc"')]
    if len(replies) < 2:
        raise RuntimeError("remote failed: " + (out.stderr or out.stdout)[-800:])
    return json.loads(replies[-1])


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if "id" not in msg:
            continue
        if msg.get("method") == "initialize":
            p = msg.get("params") or {}
            reply = {"jsonrpc": "2.0", "id": msg["id"], "result": {
                "protocolVersion": p.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "qnx-agent-kit (via loom-node)", "version": "0.1.0"}}}
        else:
            try:
                reply = remote(msg)
                reply["id"] = msg["id"]
            except Exception as e:
                reply = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
