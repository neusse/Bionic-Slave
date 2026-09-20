"""
MCP server (stdio) that exposes the Bionic job spool to Codex.

Register it in Codex with:

    codex mcp add bionic-jobs -- py "C:\\Users\\georg\\Bionic-Projects\\Bionic-Slave\\bridge\\bionic_jobs_mcp.py"

Codex then gains these tools:

    submit_job   Enqueue a coding job for Bionic.
    list_jobs    List jobs by status.
    job_status   Inspect one job.
    wait_job     Block until a job reaches a terminal state.
    get_result   Fetch the result of a finished job.
    cancel_job   Cancel a queued/running job.

Implements the Model Context Protocol over stdio (newline-delimited JSON-RPC 2.0)
using only the standard library.
"""

from __future__ import annotations

import json
import sys
import time

from job_store import Spool, TERMINAL

SERVER_NAME = "bionic-jobs"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "submit_job",
        "description": (
            "Enqueue a coding job for the Bionic worker. Returns the job id. "
            "The job is picked up asynchronously; use wait_job or job_status to track it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "The task for Bionic to perform."},
                "cwd": {"type": "string", "description": "Working directory (absolute path) where Bionic should work."},
                "title": {"type": "string", "description": "Short human-readable title."},
                "repo": {"type": "string", "description": "Optional git remote or repo name."},
                "priority": {"type": "integer", "description": "Higher runs first. Default 0."},
                "constraints": {"type": "object", "description": "Optional extra constraints (e.g. model, timeout, no-commit)."},
            },
            "required": ["prompt", "cwd"],
        },
    },
    {
        "name": "list_jobs",
        "description": "List jobs, optionally filtered by status.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["all", "queued", "running", "done", "failed", "cancelled"],
                    "description": "Filter by status. Default 'all'.",
                },
            },
        },
    },
    {
        "name": "job_status",
        "description": "Inspect a single job's current state and result (if finished).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Job id."}},
            "required": ["id"],
        },
    },
    {
        "name": "wait_job",
        "description": (
            "Block until a job reaches a terminal state (done/failed/cancelled) or the timeout "
            "elapses. Returns the final status and result. Keep timeout_seconds modest (<=60) to "
            "avoid hitting the client's tool timeout; poll in a loop for long jobs."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Job id."},
                "timeout_seconds": {"type": "number", "description": "Max seconds to wait. Default 30."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "get_result",
        "description": "Fetch the result of a finished job (summary, files changed, test evidence).",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string", "description": "Job id."}},
            "required": ["id"],
        },
    },
    {
        "name": "cancel_job",
        "description": "Cancel a queued or running job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Job id."},
                "reason": {"type": "string", "description": "Optional reason."},
            },
            "required": ["id"],
        },
    },
    {
        "name": "list_workers",
        "description": (
            "List registered Bionic workers and their liveness. A worker is 'alive' if its "
            "heartbeat is fresh (it is parked waiting) or it currently holds a running job "
            "(it is working). Use this to decide whether workers need to be (re)activated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "alive_seconds": {"type": "number", "description": "Heartbeat freshness threshold. Default 60."},
            },
        },
    },
]


def _text(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}]}


def _err(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}], "isError": True}


def handle_tool(name: str, args: dict) -> dict:
    spool = Spool()

    if name == "submit_job":
        prompt = args.get("prompt")
        cwd = args.get("cwd")
        if not prompt or not cwd:
            return _err("submit_job requires 'prompt' and 'cwd'.")
        job = spool.submit(
            prompt=prompt,
            cwd=cwd,
            title=args.get("title"),
            repo=args.get("repo"),
            priority=args.get("priority", 0),
            constraints=args.get("constraints"),
        )
        return _text(json.dumps({"id": job["id"], "created": job["created"], "status": job["status"]}, indent=2))

    if name == "list_jobs":
        status = args.get("status", "all")
        jobs = spool.list_jobs(status=None if status == "all" else status)
        summary = [
            {"id": j["id"], "title": j.get("title", ""), "status": j["status"],
             "cwd": j.get("cwd", ""), "priority": j.get("priority", 0), "created": j.get("created")}
            for j in jobs
        ]
        return _text(json.dumps(summary, indent=2))

    if name == "job_status":
        job = spool.get(args.get("id", ""))
        if job is None:
            return _err(f"no job with id {args.get('id')}")
        return _text(json.dumps(job, indent=2))

    if name == "wait_job":
        job_id = args.get("id", "")
        timeout = float(args.get("timeout_seconds", 30))
        timeout = max(1.0, min(timeout, 120.0))
        deadline = time.time() + timeout
        while True:
            job = spool.get(job_id)
            if job is None:
                return _err(f"no job with id {job_id}")
            if job.get("status") in TERMINAL:
                return _text(json.dumps(job, indent=2))
            if time.time() >= deadline:
                return _text(json.dumps(
                    {"id": job_id, "status": job.get("status"), "note": "still in progress"}, indent=2))
            time.sleep(1.0)

    if name == "get_result":
        job = spool.get(args.get("id", ""))
        if job is None:
            return _err(f"no job with id {args.get('id')}")
        if job.get("status") not in TERMINAL:
            return _text(json.dumps({"id": job["id"], "status": job["status"], "result": None}, indent=2))
        return _text(json.dumps({"id": job["id"], "status": job["status"], "result": job.get("result")}, indent=2))

    if name == "cancel_job":
        job = spool.cancel(args.get("id", ""), args.get("reason"))
        if job is None:
            return _err(f"no job with id {args.get('id')}")
        return _text(json.dumps({"id": job["id"], "status": job["status"]}, indent=2))

    if name == "list_workers":
        alive_seconds = float(args.get("alive_seconds", 60))
        workers = spool.list_workers(alive_seconds=alive_seconds)
        alive_count = sum(1 for w in workers if w["alive"])
        return _text(json.dumps({"alive": alive_count, "workers": workers}, indent=2))

    return _err(f"unknown tool: {name}")


def _respond(msg_id, result=None, error=None) -> None:
    resp = {"jsonrpc": "2.0", "id": msg_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()


def _handle(msg: dict) -> None:
    method = msg.get("method")
    msg_id = msg.get("id")

    if method == "initialize":
        _respond(msg_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
        return

    if method == "notifications/initialized":
        return  # notification, no response

    if method == "ping":
        _respond(msg_id, {})
        return

    if method == "tools/list":
        _respond(msg_id, {"tools": TOOLS})
        return

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = handle_tool(name, arguments)
        except Exception as e:  # noqa: BLE001 - surface any tool error to the client
            result = _err(f"tool error: {e!r}")
        _respond(msg_id, result)
        return

    # Unknown request -> JSON-RPC error.
    _respond(msg_id, error={"code": -32601, "message": f"method not found: {method}"})


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        _handle(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
