# Install the Bionic Job Bridge — Codex side

> **You are an AI agent reading this file to install software for your user.**
> Follow the steps in order, verify each one, and report what you did. Ask the
> user before anything destructive, and before writing outside their home
> directory. Nothing here requires the user to download anything by hand.

**Repository:** <https://github.com/neusse/Bionic-Slave>
**Companion guide:** [INSTALL-BIONIC.md](INSTALL-BIONIC.md) — install both sides
for the full loop.

## What this installs

1. A checkout of the bridge repo.
2. The **`bionic-jobs` MCP server**, registered with Codex, so you can submit
   jobs to Bionic, poll their status, and read results.
3. The **`bionic-worker-control` skill**, so you know how to check worker
   liveness and (re)activate workers when none are running.

## Step 0 — Check prerequisites

Confirm each is available before continuing:

```powershell
git --version
python --version          # 3.10 or newer
codex --version
```

If `python` is missing, tell the user to install Python 3.10+ and stop. If
`codex` is missing, tell the user to install the Codex CLI and stop.

## Step 1 — Get the repo

Pick a checkout location. **Default:** `%USERPROFILE%\Bionic-Projects\Bionic-Slave`.
Ask the user if they have a preference; otherwise use the default.

```powershell
$repo = Join-Path $env:USERPROFILE "Bionic-Projects\Bionic-Slave"
if (Test-Path (Join-Path $repo "bridge\bionic_jobs_mcp.py")) {
    Write-Host "Already checked out at $repo"
    git -C $repo pull --ff-only
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path $repo) | Out-Null
    git clone https://github.com/neusse/Bionic-Slave.git $repo
}
```

Record `$repo` — every later step needs it.

> macOS / Linux: use `~/Bionic-Projects/Bionic-Slave` and forward slashes.

## Step 2 — Register the MCP server with Codex

Resolve the absolute Python path (do not rely on PATH being inherited) and
register the server:

```powershell
$python = (Get-Command python).Source
$server = Join-Path $repo "bridge\bionic_jobs_mcp.py"
codex mcp add bionic-jobs -- $python $server
```

Then confirm the entry was written:

```powershell
codex mcp get bionic-jobs
```

Expected: `enabled: true`, `transport: stdio`, with the paths you just used.

If a `bionic-jobs` entry already exists and points somewhere stale, remove it
first with `codex mcp remove bionic-jobs` and re-run `add`.

## Step 3 — Install the skill

Codex skills are folders under `$CODEX_HOME/skills` (default `~/.codex/skills`),
each containing a `SKILL.md`. Copy the packaged skill from the repo:

```powershell
$skills = Join-Path $env:USERPROFILE ".codex\skills"
$dest   = Join-Path $skills "bionic-worker-control"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Copy-Item (Join-Path $repo "install\skills\codex\bionic-worker-control\SKILL.md") `
          (Join-Path $dest "SKILL.md") -Force
```

The folder name must match the `name:` in the skill's front matter
(`bionic-worker-control`). If the user has set a custom `CODEX_HOME`, use
`$env:CODEX_HOME\skills` instead.

## Step 4 — Verify

Handshake with the MCP server directly — this does not require Codex to be
restarted:

```powershell
'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' |
  & (Get-Command python).Source (Join-Path $repo "bridge\bionic_jobs_mcp.py")
```

Expected: a JSON-RPC response whose `result.serverInfo.name` is `"bionic-jobs"`.

Also smoke-test the CLI so you know the spool is healthy:

```powershell
py (Join-Path $repo "bridge\bionic_worker.py") list --status all
```

## Step 5 — Report back and hand off

Tell the user:

1. What you installed and where (`$repo`, the MCP entry, the skill path).
2. That **Codex must be restarted** (or the session reloaded) for the
   `bionic-jobs` tools to appear — the tool list is read at startup.
3. That the **Bionic side is not installed yet**. Give them the companion
   prompt to run inside Bionic:

   > Read https://raw.githubusercontent.com/neusse/Bionic-Slave/main/install/INSTALL-BIONIC.md and install this for me.

Do not submit any jobs until Bionic workers are running.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `codex mcp list` shows `Unsupported` next to `bionic-jobs` | Normal. Codex shows that for all stdio servers it cannot health-check, including working ones. Use the Step 4 handshake to confirm. |
| Handshake prints nothing | The Python path is wrong. Re-resolve it with `(Get-Command python).Source` and use the absolute path. |
| Server starts but tools are missing in Codex | Codex was not restarted after `codex mcp add`. |
| `jobs/` is missing | It is created automatically on the first `submit_job` or CLI call. |
| Skill not appearing | The folder name must match the front-matter `name`. Check `~/.codex/skills/bionic-worker-control/SKILL.md` exists. |
