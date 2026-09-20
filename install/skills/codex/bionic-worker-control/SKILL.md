---
name: bionic-worker-control
description: Activate and verify Bionic job workers so Codex can route coding jobs to Bionic. Use when Codex needs to submit jobs to Bionic, check whether any Bionic workers are alive, or (re)start Bionic and its worker sessions when none are running.
---

# Bionic Worker Control

Bionic runs coding jobs from a shared spool. Codex submits jobs via the
`bionic-jobs` MCP server (`submit_job`), and Bionic "workers" (agent sessions
parked on a blocking poll) pick them up. This skill covers checking worker
liveness and (re)activating workers when none are alive.

## The pieces

- **MCP server `bionic-jobs`** exposes `list_workers`, `submit_job`, `list_jobs`,
  `job_status`, `wait_job`, `get_result`, `cancel_job`.
- **Repo checkout**: wherever the Bionic Job Bridge was cloned. Default on
  Windows: `%USERPROFILE%\Bionic-Projects\Bionic-Slave`. If you cannot find it,
  look for `bridge/bionic_worker.py`.
- **Bionic app**: `C:\Program Files\Bionic\Bionic.exe` (Windows).
- **Bionic project**: `Bionic-Slave`.
- **Worker CLI**: `py bridge\bionic_worker.py`, run from the checkout root.

## Step 1 — Check worker liveness

Call the `list_workers` MCP tool. It returns `{"alive": N, "workers": [...]}`.

- `alive > 0` → workers are running; skip to Step 3.
- `alive == 0` → no workers are parked or working; proceed to Step 2.

A worker counts as alive if its heartbeat is fresh (parked, waiting) or it
currently holds a running job (working).

If the `bionic-jobs` tools are not available at all, the MCP server is not
registered. See `install/INSTALL-CODEX.md` in the repo.

## Step 2 — (Re)activate workers

If no workers are alive, start Bionic (if it is not running) and start worker
sessions. Use the `computer-use` tool to drive the Bionic GUI.

1. **Launch Bionic** if it is not already running:
   - Run `Start-Process "C:\Program Files\Bionic\Bionic.exe"` (or use computer-use
     to open it from the Start menu).
   - Wait for the app window to appear.

2. **Open the `Bionic-Slave` project.** If Bionic opens to a different project,
   switch to `Bionic-Slave`.

3. **Start up to 3 worker sessions.** For each `N` in 1..3, create a new session
   and paste the worker loop below, replacing `worker-N` with a unique owner name
   (`worker-1`, `worker-2`, `worker-3`):

   > You are a Bionic job worker (owner: worker-N). Loop forever:
   > 1. Run `py bridge/bionic_worker.py next --forever --owner worker-N`
   >    (this blocks until a job exists).
   > 2. Do the work described by the job, in the job's `cwd` (use shell commands
   >    to reach any path).
   > 3. Write a short summary to a scratch file, then run
   >    `py bridge/bionic_worker.py done <id> --summary-file <file> --files-changed "a,b" --test-evidence "..."`.
   > 4. Repeat from step 1.

   Start with 1 worker; add more only if jobs are queuing up.

4. **Verify.** Call `list_workers` again. `alive` should be >= 1. If it is still
   0, the worker sessions did not start correctly — re-check that the prompt was
   pasted into a session in the `Bionic-Slave` project.

## Step 3 — Submit the job

Use `submit_job` with the task prompt and the target `cwd`. Then poll `wait_job`
(short timeouts) or `job_status` until the job reaches `done`/`failed`, and
report the result to the user.

## Notes

- Workers parked on `next --forever` consume ~zero tokens while idle (they are
  blocked on a subprocess, not generating).
- Jobs are not auto-applied; the worker returns a summary + changed files.
- If Bionic is shut down mid-job, the job's lease goes stale and is reaped back
  to the queue after 60 minutes.
