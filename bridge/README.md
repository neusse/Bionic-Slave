# bridge/

Implementation of the Bionic Job Bridge (Beta).

**Full documentation lives in the project root: [`../README.md`](../README.md).**

That document covers principles of operation, architecture, setup, usage from
both Codex and Bionic, the CLI and MCP references, data contracts, a code
overview, troubleshooting, and current Beta limitations.

Quick index of what's in this folder:

| File | Role |
|---|---|
| `job_store.py` | Spool core — the only module with real logic (pure stdlib). |
| `bionic_worker.py` | CLI a Bionic worker session drives (`next`, `done`, `workers`, …). |
| `bionic_jobs_mcp.py` | MCP server Codex connects to (stdio JSON-RPC). |
| `seed_demo_job.py` | Drops a harmless demo job for smoke-testing. |
| `install_codex_mcp_bionic.ps1` | Registers `codex mcp-server` inside Bionic (reverse direction). |
