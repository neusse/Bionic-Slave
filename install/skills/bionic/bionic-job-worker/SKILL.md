---
name: bionic-job-worker
display-name: Bionic Job Worker
description: Use when acting as a Bionic job worker — pulling coding jobs from the shared Codex/Bionic job spool, doing the work, and reporting the result back. Trigger when asked to be a job worker, to run the worker loop, to start consuming the job queue, or to process queued jobs.
---

# Bionic Job Worker

You are the Bionic half of the **Bionic Job Bridge**. Codex (or a person) submits
jobs into a shared on-disk queue; you claim them one at a time, do the work, and
report a result back so Codex can read it.

## Locate the bridge

The bridge lives in a repo checkout — default on Windows:
`%USERPROFILE%\Bionic-Projects\Bionic-Slave`. Run all commands from that
directory. If you cannot find it, search the filesystem for
`bridge/bionic_worker.py`.

## The loop

1. **Claim a job.** This blocks until a job exists, so it costs no tokens while
   waiting:

   ```
   py bridge/bionic_worker.py next --forever --owner <owner-name>
   ```

   Use a unique `--owner` per worker session (`worker-1`, `worker-2`, ...) so
   liveness is attributable.

2. **Do the work.** The job prints its `prompt` and its `cwd`. Work in that
   directory. Shell commands can reach any path on the machine; prefer the job's
   `cwd` so relative paths behave.

3. **Report the result.** Write a short summary to a file, then:

   ```
   py bridge/bionic_worker.py done <id> --summary-file <file> --files-changed "a,b" --test-evidence "..."
   ```

   If the work cannot be completed, mark it failed instead:

   ```
   py bridge/bionic_worker.py fail <id> --error "..."
   ```

4. **Repeat** from step 1. If `next` returns `NO_JOB` (only possible with
   `--wait`), the queue is drained.

## Rules

- **Never delete the spool.** `jobs/` is live data, not scratch. Deleting it
  destroys in-flight jobs and their results.
- **Report, do not apply.** Return a summary, the files you changed, and test
  evidence. Do not commit, merge, or push unless the job explicitly asks.
- **Long jobs:** refresh the lease with
  `py bridge/bionic_worker.py heartbeat <id>` if the work will exceed ~30 minutes,
  so the job is not reaped as stale.
- **Idle is free.** Being parked on `next --forever` consumes no tokens — the
  shell call is blocked on the queue, not generating output.
- **One job at a time per session.** Parallelism comes from running several
  worker sessions with distinct owners, not from interleaving jobs.

## Useful commands

| Command | Purpose |
|---|---|
| `next --forever --owner <name>` | Park until a job arrives, then claim it. |
| `next --wait <sec>` | Same, but give up after `<sec>`. |
| `list --status queued` | See what is waiting. |
| `status <id>` | Inspect one job and its result. |
| `workers` | See which workers are alive and which are working. |
| `done <id> ...` / `fail <id> ...` | Finish a job. |
