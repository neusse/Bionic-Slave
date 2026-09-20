"""
CLI used by a Bionic worker session to pull and complete jobs from the spool.

This is the Bionic-side half of the bridge. A worker session loops:

    py bridge/bionic_worker.py next --wait 900
    # ... do the work described in the returned job ...
    py bridge/bionic_worker.py done <id> --summary-file result.md

Subcommands:

    next      Claim the highest-priority queued job (optionally blocking).
    done      Mark a job done and attach a result.
    fail      Mark a job failed with an error message.
    list      List jobs, optionally filtered by status.
    status    Show one job and its result.
    cancel    Cancel a queued or running job.
    heartbeat Refresh the lease on a running job.

Pure stdlib.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

from job_store import Spool, DONE, FAILED, TERMINAL


def _read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _print_job(job: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(job, indent=2, ensure_ascii=False))
        return
    print(f"JOB {job['id']}")
    print(f"title:    {job.get('title') or '(untitled)'}")
    print(f"cwd:      {job.get('cwd') or '(none)'}")
    print(f"repo:     {job.get('repo') or '(none)'}")
    print(f"priority: {job.get('priority', 0)}")
    print(f"created:  {job.get('created')}")
    if job.get("constraints"):
        print(f"constraints: {json.dumps(job['constraints'], ensure_ascii=False)}")
    print("-" * 60)
    print(job.get("prompt", ""))
    print("-" * 60)
    print(f"STATUS: {job['status']}")


def _summary_value(args) -> str | None:
    if args.summary_file:
        return _read_file(args.summary_file)
    return args.summary


def _files_value(args) -> list[str] | None:
    if not args.files_changed:
        return None
    if args.files_changed_file:
        text = _read_file(args.files_changed_file)
        return [ln.strip() for ln in text.splitlines() if ln.strip()]
    return [f.strip() for f in args.files_changed.split(",") if f.strip()]


def cmd_next(args) -> int:
    spool = Spool()
    timeout = math.inf if args.forever else args.wait
    job = spool.claim_next(
        timeout=timeout,
        poll=args.poll,
        stale_minutes=args.stale_minutes,
        owner=args.owner,
    )
    if job is None:
        if not args.json:
            print("NO_JOB", file=sys.stderr)
        return 0
    _print_job(job, args.json)
    return 0


def cmd_done(args) -> int:
    spool = Spool()
    try:
        job = spool.complete(
            args.id,
            DONE if args.status == "ok" else FAILED,
            summary=_summary_value(args),
            files_changed=_files_value(args),
            test_evidence=args.test_evidence,
            transcript_ref=args.transcript_ref,
            error=args.error,
        )
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _print_job(job, args.json)
    return 0


def cmd_fail(args) -> int:
    spool = Spool()
    try:
        job = spool.complete(args.id, FAILED, error=args.error or "failed")
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _print_job(job, args.json)
    return 0


def cmd_list(args) -> int:
    spool = Spool()
    status = args.status if args.status != "all" else None
    jobs = spool.list_jobs(status=status)
    if args.json:
        print(json.dumps(jobs, indent=2, ensure_ascii=False))
        return 0
    if not jobs:
        print("(no jobs)")
        return 0
    for j in jobs:
        print(f"{j['id']}  [{j.get('status')}]  {j.get('title') or '(untitled)'}  -> {j.get('cwd') or '(none)'}")
    return 0


def cmd_status(args) -> int:
    spool = Spool()
    job = spool.get(args.id)
    if job is None:
        print(f"no job with id {args.id}", file=sys.stderr)
        return 1
    _print_job(job, args.json)
    if job.get("result"):
        print("RESULT:")
        print(json.dumps(job["result"], indent=2, ensure_ascii=False))
    return 0


def cmd_cancel(args) -> int:
    spool = Spool()
    job = spool.cancel(args.id, args.reason)
    if job is None:
        print(f"no job with id {args.id}", file=sys.stderr)
        return 1
    _print_job(job, args.json)
    return 0


def cmd_heartbeat(args) -> int:
    spool = Spool()
    ok = spool.heartbeat(args.id, args.owner)
    print("ok" if ok else "not-running")
    return 0 if ok else 1


def cmd_workers(args) -> int:
    spool = Spool()
    workers = spool.list_workers(alive_seconds=args.alive_seconds)
    if args.json:
        print(json.dumps(workers, indent=2, ensure_ascii=False))
        return 0
    if not workers:
        print("(no workers registered)")
        return 0
    for w in workers:
        state = "alive" if w["alive"] else "dead"
        if w["working"]:
            state = "working"
        age = f"{w['age_seconds']}s ago" if w["age_seconds"] is not None else "never"
        print(f"{w['owner']}  [{state}]  last_seen {age}  pid {w.get('pid')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="bionic_worker", description="Bionic worker CLI for the job spool.")
    p.add_argument("--jobs-dir", default=None, help="Override the spool root (default: <project>/jobs or $BIONIC_JOBS_DIR).")
    sub = p.add_subparsers(dest="command", required=True)

    n = sub.add_parser("next", help="Claim the next queued job.")
    n.add_argument("--wait", type=float, default=0.0, help="Seconds to block waiting for a job (default 0).")
    n.add_argument("--forever", action="store_true", help="Block until a job exists (never return NO_JOB).")
    n.add_argument("--poll", type=float, default=1.0, help="Poll interval in seconds (default 1).")
    n.add_argument("--stale-minutes", type=float, default=60.0, help="Reap running jobs with a lease older than this (default 60).")
    n.add_argument("--owner", default=None, help="Worker name recorded on the lease.")
    n.add_argument("--json", action="store_true", help="Print the job as JSON.")
    n.set_defaults(func=cmd_next)

    d = sub.add_parser("done", help="Mark a job done.")
    d.add_argument("id")
    d.add_argument("--status", choices=["ok", "failed"], default="ok")
    d.add_argument("--summary", default=None)
    d.add_argument("--summary-file", default=None, help="Read the summary from a file.")
    d.add_argument("--files-changed", default=None, help="Comma-separated list of changed files.")
    d.add_argument("--files-changed-file", default=None, help="Read changed files (one per line) from a file.")
    d.add_argument("--test-evidence", default=None)
    d.add_argument("--transcript-ref", default=None)
    d.add_argument("--error", default=None)
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_done)

    f = sub.add_parser("fail", help="Mark a job failed.")
    f.add_argument("id")
    f.add_argument("--error", default=None)
    f.add_argument("--json", action="store_true")
    f.set_defaults(func=cmd_fail)

    l = sub.add_parser("list", help="List jobs.")
    l.add_argument("--status", default="all", choices=["all", "queued", "running", "done", "failed", "cancelled"])
    l.add_argument("--json", action="store_true")
    l.set_defaults(func=cmd_list)

    s = sub.add_parser("status", help="Show one job.")
    s.add_argument("id")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    c = sub.add_parser("cancel", help="Cancel a job.")
    c.add_argument("id")
    c.add_argument("--reason", default=None)
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_cancel)

    h = sub.add_parser("heartbeat", help="Refresh a running job's lease.")
    h.add_argument("id")
    h.add_argument("--owner", default=None)
    h.set_defaults(func=cmd_heartbeat)

    w = sub.add_parser("workers", help="List registered workers and their liveness.")
    w.add_argument("--alive-seconds", type=float, default=60.0, help="Heartbeat freshness threshold (default 60).")
    w.add_argument("--json", action="store_true")
    w.set_defaults(func=cmd_workers)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.jobs_dir:
        os.environ["BIONIC_JOBS_DIR"] = args.jobs_dir
        import job_store
        job_store.DEFAULT_JOBS_DIR = args.jobs_dir
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
