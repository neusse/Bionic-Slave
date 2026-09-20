# Live job spool — do not delete

This directory is the **live** job queue shared between Codex and Bionic.

- `inbox/`   — queued jobs
- `running/` — jobs a worker has claimed
- `outbox/`  — finished jobs (done / failed / cancelled)
- `log.jsonl` — append-only transition log

Do **not** `rm -rf` this directory. It is recreated automatically on the next
submit, but deleting it drops any in-flight jobs and their results.
