"""
Drop a harmless demo job into the spool so you can smoke-test the full
Codex -> Bionic loop without writing any real code.

Default job: write a file `smoke_test_result.txt` in the job's cwd containing
the text "bridge works" and nothing else.

Usage:

    py bridge/seed_demo_job.py
    py bridge/seed_demo_job.py --cwd C:\\path\\to\\repo --prompt "Do X" --title "my job"

Pure stdlib.
"""

from __future__ import annotations

import argparse
import os

from job_store import Spool

DEFAULT_PROMPT = (
    "Write a file named `smoke_test_result.txt` in the working directory "
    "containing exactly the text `bridge works` and nothing else. Do not modify "
    "any other files."
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Seed a demo job into the spool.")
    p.add_argument("--cwd", default=os.getcwd(), help="Working directory for the job (default: current dir).")
    p.add_argument("--prompt", default=DEFAULT_PROMPT, help="Job prompt.")
    p.add_argument("--title", default="smoke test", help="Job title.")
    p.add_argument("--priority", type=int, default=0, help="Job priority.")
    p.add_argument("--jobs-dir", default=None, help="Override spool root.")
    args = p.parse_args(argv)

    if args.jobs_dir:
        os.environ["BIONIC_JOBS_DIR"] = args.jobs_dir
        import job_store
        job_store.DEFAULT_JOBS_DIR = args.jobs_dir

    job = Spool().submit(
        prompt=args.prompt,
        cwd=os.path.abspath(args.cwd),
        title=args.title,
        priority=args.priority,
    )
    print(f"Seeded job {job['id']} -> {job['cwd']}")
    print("Start the Bionic worker, or run: py bridge/bionic_worker.py next --wait 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
