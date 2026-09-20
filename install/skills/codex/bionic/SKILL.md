---
name: bionic
description: Submit and manage Bionic cloud-worker jobs through the bionic-jobs MCP server.
argument-hint: "help | submit_job | list_jobs | job_status | wait_job | get_result | cancel_job | list_workers"
disable-model-invocation: true
---

# Bionic jobs

Treat the first skill argument as a command. Supported commands are `help`, `submit_job`, `list_jobs`, `job_status`, `wait_job`, `get_result`, `cancel_job`, and `list_workers`.

Use the correspondingly named tool from the `bionic-jobs` MCP server. The server must be present in the current tool inventory. If it is unavailable, state that this Codex task needs to be reopened after the server was enabled; do not imitate the tool by editing spool files.

Accept arguments as `name=value` pairs. Quoted values may contain spaces. Preserve Windows paths literally. When a required value is absent and cannot be unambiguously obtained from the invocation, ask one concise question for that value.

## Commands

### `help`

Make no MCP call. Print all commands below with their syntax, arguments, allowed values, defaults, and descriptions.

### `submit_job`

Call `submit_job` once to enqueue work.

Syntax:

`$bionic submit_job prompt="<task>" cwd="<absolute path>" [title="<short title>"] [repo="<repo name or remote>"] [priority=<integer>] [constraints='<JSON object>']`

Arguments:

- `prompt` (required string): Complete task instructions for Bionic.
- `cwd` (required string): Absolute working directory Bionic may use.
- `title` (optional string): Short job label.
- `repo` (optional string): Repository name or remote identifier.
- `priority` (optional integer, default `0`): Higher values run first.
- `constraints` (optional object): Extra limits such as `model`, `timeout`, or `no-commit`. Parse JSON when supplied as JSON; otherwise construct an object only from clearly named constraint fields.

Return the created job ID, creation time, and status. Do not wait unless the user also asks to wait.

### `list_jobs`

Call `list_jobs`.

Syntax:

`$bionic list_jobs [status=all|queued|running|done|failed|cancelled]`

Arguments:

- `status` (optional string, default `all`): Limit results to one job state.

Summarize each returned job with ID, title, status, working directory, priority, and creation time.

### `job_status`

Call `job_status`.

Syntax:

`$bionic job_status id=<job-id>`

Arguments:

- `id` (required string): Job identifier returned by `submit_job` or `list_jobs`.

Report the current state and any available result details without claiming completion unless the returned status is terminal.

### `wait_job`

Call `wait_job` once per invocation.

Syntax:

`$bionic wait_job id=<job-id> [timeout_seconds=<number>]`

Arguments:

- `id` (required string): Job identifier.
- `timeout_seconds` (optional number, default `30`): Maximum wait for this call. Keep at or below `60` unless the user explicitly requests a longer wait; the server caps it at `120`.

If the result says the job is still in progress, report that directly. Do not start an unbounded polling loop unless the user explicitly asks to keep waiting.

### `get_result`

Call `get_result`.

Syntax:

`$bionic get_result id=<job-id>`

Arguments:

- `id` (required string): Job identifier.

Return the final summary, changed files, test evidence, and other result fields supplied by the server. If the job is not terminal, report that no final result is available yet.

### `cancel_job`

Call `cancel_job` once.

Syntax:

`$bionic cancel_job id=<job-id> [reason="<reason>"]`

Arguments:

- `id` (required string): Queued or running job identifier.
- `reason` (optional string): Human-readable cancellation reason.

Report the returned status. Do not describe the job as cancelled unless the server confirms that state.

### `list_workers`

Call `list_workers`.

Syntax:

`$bionic list_workers [alive_seconds=<number>]`

Arguments:

- `alive_seconds` (optional number, default `60`): Heartbeat freshness threshold, in seconds.

Report how many workers are alive and, for each, its owner, whether it is parked or working, and when it was last seen. If no workers are alive, say so plainly: a submitted job will sit in the queue until a worker is started. Do not start workers yourself unless the user asks — see the `bionic-worker-control` skill for activation.
