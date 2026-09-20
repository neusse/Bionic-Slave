"""
Job spool shared between Codex (producer) and Bionic (worker).

A job is a JSON file that moves through three directories:

    inbox/<id>.json    -> queued
    running/<id>.json  -> claimed by a worker (holds a lease)
    outbox/<id>.json   -> terminal (done | failed | cancelled)

Every state transition is appended to log.jsonl (append-only, one JSON object
per line). All writes are atomic (write to a `.tmp` sibling, then `os.replace`).

The spool is safe to share between processes on the same machine. It is NOT
safe across a network filesystem without external locking.

Pure stdlib; no third-party dependencies.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from datetime import datetime, timezone

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"

TERMINAL = {DONE, FAILED, CANCELLED}

# Default location: <project-root>/jobs. Override with BIONIC_JOBS_DIR.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JOBS_DIR = os.environ.get("BIONIC_JOBS_DIR") or os.path.join(_PROJECT_ROOT, "jobs")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(3)


class Spool:
    def __init__(self, root: str | None = None):
        self.root = os.path.abspath(root or DEFAULT_JOBS_DIR)
        self.inbox = os.path.join(self.root, "inbox")
        self.running = os.path.join(self.root, "running")
        self.outbox = os.path.join(self.root, "outbox")
        self.workers = os.path.join(self.root, "workers")
        self.log_path = os.path.join(self.root, "log.jsonl")

    # ------------------------------------------------------------------ setup
    def ensure(self) -> None:
        for d in (self.inbox, self.running, self.outbox, self.workers):
            os.makedirs(d, exist_ok=True)

    # ------------------------------------------------------------------ io
    @staticmethod
    def _atomic_write_json(path: str, obj: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp, path)

    @staticmethod
    def _read_json(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _log(self, job_id: str, from_status: str, to_status: str, detail: str | None = None) -> None:
        entry = {
            "ts": now_iso(),
            "id": job_id,
            "from": from_status,
            "to": to_status,
        }
        if detail:
            entry["detail"] = detail
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ locate
    def _job_path(self, job_id: str) -> str | None:
        for d in (self.inbox, self.running, self.outbox):
            p = os.path.join(d, job_id + ".json")
            if os.path.exists(p):
                return p
        return None

    def get(self, job_id: str) -> dict | None:
        p = self._job_path(job_id)
        return self._read_json(p) if p else None

    # ------------------------------------------------------------------ submit
    def submit(
        self,
        prompt: str,
        cwd: str,
        title: str | None = None,
        repo: str | None = None,
        priority: int = 0,
        constraints: dict | None = None,
        job_id: str | None = None,
    ) -> dict:
        self.ensure()
        job_id = job_id or new_id()
        job = {
            "id": job_id,
            "created": now_iso(),
            "title": title or "",
            "cwd": cwd,
            "repo": repo or "",
            "prompt": prompt,
            "priority": int(priority),
            "constraints": constraints or {},
            "status": QUEUED,
        }
        self._atomic_write_json(os.path.join(self.inbox, job_id + ".json"), job)
        self._log(job_id, "", QUEUED)
        return job

    # ------------------------------------------------------------------ list
    def list_jobs(self, status: str | None = None) -> list[dict]:
        jobs: list[dict] = []
        dirs = [self.inbox, self.running, self.outbox]
        for d in dirs:
            if not os.path.isdir(d):
                continue
            for name in os.listdir(d):
                if not name.endswith(".json"):
                    continue
                p = os.path.join(d, name)
                try:
                    job = self._read_json(p)
                except (OSError, json.JSONDecodeError):
                    continue
                if status and job.get("status") != status:
                    continue
                jobs.append(job)
        jobs.sort(key=lambda j: (-int(j.get("priority", 0)), j.get("created", "")))
        return jobs

    # ------------------------------------------------------------------ claim
    def _reap_stale(self, stale_minutes: float) -> int:
        """Move running jobs whose lease is too old back to the inbox."""
        cutoff = time.time() - stale_minutes * 60
        reaped = 0
        if not os.path.isdir(self.running):
            return 0
        for name in os.listdir(self.running):
            if not name.endswith(".json"):
                continue
            p = os.path.join(self.running, name)
            try:
                job = self._read_json(p)
            except (OSError, json.JSONDecodeError):
                continue
            lease = job.get("lease") or {}
            hb = lease.get("heartbeat_at")
            if not hb:
                continue
            try:
                hb_ts = datetime.fromisoformat(hb).timestamp()
            except ValueError:
                continue
            if hb_ts < cutoff:
                job.pop("lease", None)
                job["status"] = QUEUED
                job["reaped_at"] = now_iso()
                self._atomic_write_json(p, job)
                os.replace(p, os.path.join(self.inbox, name))
                self._log(job["id"], RUNNING, QUEUED, "reaped stale lease")
                reaped += 1
        return reaped

    def claim_next(
        self,
        timeout: float = 0.0,
        poll: float = 1.0,
        stale_minutes: float = 60.0,
        owner: str | None = None,
    ) -> dict | None:
        """Claim the highest-priority queued job, optionally long-polling.

        Returns the claimed job dict, or None if `timeout` elapses with no job.
        """
        self.ensure()
        deadline = time.time() + timeout
        owner = owner or "bionic-worker"
        self.register_worker(owner)
        while True:
            self.heartbeat_worker(owner)
            self._reap_stale(stale_minutes)
            names = sorted(
                (n for n in os.listdir(self.inbox) if n.endswith(".json"))
            )
            # Prefer higher priority, then earlier creation time.
            candidates: list[tuple[int, str, str]] = []
            for n in names:
                p = os.path.join(self.inbox, n)
                try:
                    job = self._read_json(p)
                except (OSError, json.JSONDecodeError):
                    continue
                candidates.append((-int(job.get("priority", 0)), job.get("created", ""), n))
            candidates.sort()

            for _neg_prio, _created, name in candidates:
                inbox_path = os.path.join(self.inbox, name)
                running_path = os.path.join(self.running, name)
                try:
                    # Atomic move wins exactly one claimant.
                    os.replace(inbox_path, running_path)
                except FileNotFoundError:
                    continue  # someone else claimed it
                job = self._read_json(running_path)
                job["status"] = RUNNING
                job["lease"] = {
                    "owner": owner,
                    "claimed_at": now_iso(),
                    "heartbeat_at": now_iso(),
                }
                self._atomic_write_json(running_path, job)
                self._log(job["id"], QUEUED, RUNNING, owner)
                return job

            if time.time() >= deadline:
                return None
            time.sleep(poll)

    # ------------------------------------------------------------------ finish
    def complete(
        self,
        job_id: str,
        status: str,
        summary: str | None = None,
        files_changed: list[str] | None = None,
        test_evidence: str | None = None,
        transcript_ref: str | None = None,
        error: str | None = None,
    ) -> dict:
        """Move a running job to a terminal state and attach its result."""
        if status not in TERMINAL:
            raise ValueError(f"status must be one of {sorted(TERMINAL)}")
        running_path = os.path.join(self.running, job_id + ".json")
        if not os.path.exists(running_path):
            # Allow finishing a job that was already reaped back to inbox.
            inbox_path = os.path.join(self.inbox, job_id + ".json")
            if os.path.exists(inbox_path):
                running_path = inbox_path
            else:
                raise FileNotFoundError(f"no running/queued job with id {job_id}")

        job = self._read_json(running_path)
        prev = job.get("status", RUNNING)
        job["status"] = status
        job["finished"] = now_iso()
        result = {
            "summary": summary or "",
            "files_changed": files_changed or [],
            "test_evidence": test_evidence or "",
            "transcript_ref": transcript_ref or "",
        }
        if error:
            result["error"] = error
        job["result"] = result
        job.pop("lease", None)

        outbox_path = os.path.join(self.outbox, job_id + ".json")
        self._atomic_write_json(outbox_path, job)
        if os.path.exists(running_path):
            os.remove(running_path)
        self._log(job_id, prev, status, error or None)
        return job

    # ------------------------------------------------------------------ misc
    def cancel(self, job_id: str, reason: str | None = None) -> dict | None:
        p = self._job_path(job_id)
        if not p:
            return None
        job = self._read_json(p)
        if job.get("status") in TERMINAL:
            return job
        prev = job.get("status", QUEUED)
        job["status"] = CANCELLED
        job["finished"] = now_iso()
        job["result"] = {"summary": "", "files_changed": [], "test_evidence": "", "error": reason or "cancelled"}
        self._atomic_write_json(os.path.join(self.outbox, job_id + ".json"), job)
        if os.path.exists(p):
            os.remove(p)
        self._log(job_id, prev, CANCELLED, reason or None)
        return job

    def heartbeat(self, job_id: str, owner: str | None = None) -> bool:
        p = os.path.join(self.running, job_id + ".json")
        if not os.path.exists(p):
            return False
        job = self._read_json(p)
        lease = job.get("lease") or {}
        lease["heartbeat_at"] = now_iso()
        if owner:
            lease["owner"] = owner
        job["lease"] = lease
        self._atomic_write_json(p, job)
        return True

    # ------------------------------------------------------------------ workers
    def register_worker(self, owner: str) -> dict:
        """Create (or refresh) a worker registration."""
        self.ensure()
        p = os.path.join(self.workers, owner + ".json")
        if os.path.exists(p):
            try:
                w = self._read_json(p)
            except (OSError, json.JSONDecodeError):
                w = {"owner": owner, "started": now_iso()}
        else:
            w = {"owner": owner, "started": now_iso()}
        w.update({"pid": os.getpid(), "last_seen": now_iso(), "status": "parked"})
        self._atomic_write_json(p, w)
        return w

    def heartbeat_worker(self, owner: str) -> None:
        p = os.path.join(self.workers, owner + ".json")
        if not os.path.exists(p):
            return
        try:
            w = self._read_json(p)
        except (OSError, json.JSONDecodeError):
            return
        w["last_seen"] = now_iso()
        w["pid"] = os.getpid()
        self._atomic_write_json(p, w)

    def list_workers(self, alive_seconds: float = 60.0) -> list[dict]:
        """List registered workers with liveness. A worker is 'alive' if its
        heartbeat is fresh OR it currently holds a running job (i.e. it is
        actively working rather than parked)."""
        out: list[dict] = []
        if not os.path.isdir(self.workers):
            return out
        running_owners = set()
        for j in self.list_jobs(status=RUNNING):
            lease = j.get("lease") or {}
            if lease.get("owner"):
                running_owners.add(lease["owner"])
        now = time.time()
        for name in os.listdir(self.workers):
            if not name.endswith(".json"):
                continue
            try:
                w = self._read_json(os.path.join(self.workers, name))
            except (OSError, json.JSONDecodeError):
                continue
            last_seen = w.get("last_seen")
            age = None
            if last_seen:
                try:
                    age = now - datetime.fromisoformat(last_seen).timestamp()
                except ValueError:
                    age = None
            owner = w.get("owner", name[:-5])
            working = owner in running_owners
            alive = working or (age is not None and age <= alive_seconds)
            out.append({
                "owner": owner,
                "pid": w.get("pid"),
                "started": w.get("started"),
                "last_seen": last_seen,
                "age_seconds": round(age, 1) if age is not None else None,
                "working": working,
                "alive": alive,
            })
        out.sort(key=lambda w: w.get("owner", ""))
        return out
