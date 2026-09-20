# Install the Bionic Job Bridge — Bionic side

> **You are an AI agent running inside Bionic, reading this file to install
> software for your user.** Follow the steps in order, verify each one, and
> report what you did. Ask the user before anything destructive, and before
> writing outside their home directory. Nothing here requires the user to
> download anything by hand.

**Repository:** <https://github.com/neusse/Bionic-Slave>
**Companion guide:** [INSTALL-CODEX.md](INSTALL-CODEX.md) — install both sides
for the full loop.

## What this installs

1. A checkout of the bridge repo.
2. Verification that the worker CLI runs.
3. The **`bionic-job-worker` skill**, so any Bionic session knows how to pull and
   complete jobs from the queue.

The Codex half (the MCP server that submits jobs) is a separate install. Both are
needed for the loop to work end to end.

## Step 0 — Check prerequisites

```powershell
git --version
python --version          # 3.10 or newer
```

No third-party Python packages are required — the bridge is pure standard library.

## Step 1 — Get the repo

Pick a checkout location. **Default:** `%USERPROFILE%\Bionic-Projects\Bionic-Slave`.
Ask the user if they have a preference; otherwise use the default.

```powershell
$repo = Join-Path $env:USERPROFILE "Bionic-Projects\Bionic-Slave"
if (Test-Path (Join-Path $repo "bridge\bionic_worker.py")) {
    Write-Host "Already checked out at $repo"
    git -C $repo pull --ff-only
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $repo) | Out-Null
    git clone https://github.com/neusse/Bionic-Slave.git $repo
}
```

Record `$repo` — every later step needs it.

> macOS / Linux: use `~/Bionic-Projects/Bionic-Slave` and forward slashes.

## Step 2 — Verify the worker CLI

Run from the checkout root:

```powershell
Set-Location $repo
py bridge\bionic_worker.py list --status all
py bridge\bionic_worker.py workers
```

Both should succeed. An empty list is fine on a fresh install — it means the
spool has no jobs yet. `jobs/` is created automatically.

## Step 3 — Install the `bionic-job-worker` skill

Bionic global skills are installed through the skill installer, which validates
the skill and asks the user to approve it. Do not write into the global skills
folder directly.

1. Get the scratchpad folder using `get_scratchpad_folder`.
2. Copy the packaged skill from the repo into it:

   ```powershell
   $scratch = "<absolute scratchpad path from get_scratchpad_folder>"
   Copy-Item -Recurse -Force `
     (Join-Path $repo "install\skills\bionic\bionic-job-worker") `
     (Join-Path $scratch "bionic-job-worker")
   ```

3. Install it, passing the absolute path:

   ```
   bionic_tool(
     name="skill.install",
     args=["--skill-folder-path", "<absolute scratchpad path>/bionic-job-worker"]
   )
   ```

   Approve prompt: the user will be asked to confirm installing the skill
   globally. This is expected.

4. Verify it is registered:

   ```
   bionic_tool(name="skill.list", args=[])
   ```

   Expected: an entry named `bionic-job-worker`.

> If the user prefers a project-scoped skill instead of a global one, copy the
> same folder to `<project-folder>/.agents/skills/bionic-job-worker/` — project
> skills are regular files and need no approval.

## Step 4 — Start a worker

A worker is a Bionic session running a blocking loop. Start one so jobs submitted
from Codex actually get picked up.

Either **become the worker in this session** (if the user wants that), or tell
the user to open a new session in this project and paste:

> You are a Bionic job worker (owner: worker-1). Loop forever:
> 1. Run `py bridge/bionic_worker.py next --forever --owner worker-1`
> 2. Do the work described by the job, in the job's `cwd`.
> 3. Run `py bridge/bionic_worker.py done <id> --summary-file <file> --files-changed "a,b" --test-evidence "..."`.
> 4. Repeat from step 1.

Up to 3 workers is a sensible ceiling. Use a distinct `--owner` per session
(`worker-1`, `worker-2`, `worker-3`).

## Step 5 — Verify and report back

```powershell
py bridge\bionic_worker.py workers
```

A parked worker reports `[alive]`; one holding a job reports `[working]`. A
worker that has stopped reports `[dead]` once its heartbeat is older than 60
seconds.

Tell the user:

1. What you installed and where (`$repo`, the skill, the worker session).
2. That the **Codex side may not be installed yet**. Give them the companion
   prompt to run inside Codex:

   > Read https://raw.githubusercontent.com/neusse/Bionic-Slave/main/install/INSTALL-CODEX.md and install this for me.

3. That workers parked on `next --forever` cost no tokens while idle.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `list`/`workers` errors with a Python traceback | Run the commands from the checkout root, or pass `--jobs-dir`. |
| `skill.install` says the folder name disagrees | The folder must be named `bionic-job-worker`, matching the skill front matter. |
| `workers` shows `[dead]` for a worker you started | The session's turn ended (or the process exited). Re-prompt that session with "continue the worker loop". |
| Jobs pile up and nothing is claimed | No worker is parked. Start one, or have Codex run `list_workers` and reactivate. |
| Spool looks empty after a cleanup | `jobs/` was deleted. It is recreated on the next submit, but in-flight jobs are lost — never delete it. |
