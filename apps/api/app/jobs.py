"""Background analysis jobs.

The job runs in a worker thread; an in-memory registry tracks state and fans
out events to SSE subscribers. Results are persisted to SQLite per-game as
each one finishes, so progress survives even with no clients attached.

Registry is single-process. If we ever run under `uvicorn --workers N`, move
state to a SQLite `jobs` table.
"""
import threading
import time
import uuid
from typing import Optional

from .analyze import analyze_player_games_events
from .db import conn_ctx


class Job:
    def __init__(self, username: str, params: dict):
        self.id = uuid.uuid4().hex
        self.username = username
        self.params = params
        self.events: list[dict] = []
        self.cond = threading.Condition()
        self.cancel = threading.Event()
        self.snapshot: dict = {
            "id": self.id,
            "username": username,
            "params": params,
            "status": "running",
            "total": 0,
            "analyzed": 0,
            "plies_total": 0,
            "errors": 0,
            "last_label": "",
            "current_game_id": None,
            "current_ply": None,
            "current_game_plies": None,
            "started_at": time.time(),
            "finished_at": None,
            "error_message": None,
        }

    def _push(self, event: dict) -> None:
        snap = self.snapshot
        t = event.get("type")
        if t == "start":
            snap["total"] = int(event.get("games", 0))
        elif t == "ply_progress":
            # Live motion between game completions. plies_total is reconciled to
            # the authoritative count on each game_done.
            snap["plies_total"] = int(event.get("plies_done", snap["plies_total"]))
            snap["current_game_id"] = event.get("game_id")
            snap["current_ply"] = event.get("ply")
            snap["current_game_plies"] = event.get("game_plies")
            snap["last_label"] = str(event.get("label", snap["last_label"]))
        elif t == "game_done":
            snap["analyzed"] = int(event.get("analyzed", snap["analyzed"]))
            snap["plies_total"] = int(event.get("plies_total", snap["plies_total"]))
            snap["last_label"] = str(event.get("label", snap["last_label"]))
        elif t == "game_error":
            snap["errors"] += 1
        elif t == "done":
            snap["status"] = "done"
            snap["finished_at"] = time.time()
        elif t == "error":
            snap["status"] = "error"
            snap["error_message"] = str(event.get("message", ""))
            snap["finished_at"] = time.time()
        self.events.append(event)

    def append(self, event: dict) -> None:
        with self.cond:
            self._push(event)
            self.cond.notify_all()


_jobs: dict[str, Job] = {}
_jobs_lock = threading.Lock()


def get_job(job_id: str) -> Optional[Job]:
    with _jobs_lock:
        return _jobs.get(job_id)


def active_job_for(username: str) -> Optional[Job]:
    with _jobs_lock:
        for j in _jobs.values():
            if j.username == username and j.snapshot["status"] == "running":
                return j
    return None


def active_job() -> Optional[Job]:
    """The most recently started running job across all players (single-user
    local app — at most one job runs at a time in practice)."""
    with _jobs_lock:
        running = [j for j in _jobs.values() if j.snapshot["status"] == "running"]
    if not running:
        return None
    return max(running, key=lambda j: j.snapshot["started_at"])


def start_job(username: str, params: dict) -> Job:
    if active_job_for(username):
        raise RuntimeError(f"a job is already running for {username}")
    job = Job(username, params)
    with _jobs_lock:
        _jobs[job.id] = job
    threading.Thread(
        target=_run, args=(job,), name=f"analyze-{job.id[:8]}", daemon=True
    ).start()
    return job


def _run(job: Job) -> None:
    try:
        with conn_ctx() as conn:
            gen = analyze_player_games_events(job.username, conn, **job.params)
            try:
                for event in gen:
                    if job.cancel.is_set():
                        break
                    job.append(event)
            finally:
                # Closing the generator triggers GeneratorExit at its current
                # yield point, which runs the ProcessPoolExecutor cleanup in
                # analyze.py (terminates Stockfish children).
                gen.close()
        with job.cond:
            if job.cancel.is_set() and job.snapshot["status"] == "running":
                job.snapshot["status"] = "cancelled"
                job.snapshot["finished_at"] = time.time()
                job.events.append({"type": "cancelled"})
            elif job.snapshot["status"] == "running":
                job.snapshot["status"] = "done"
                job.snapshot["finished_at"] = time.time()
                job.events.append({"type": "done"})
            job.cond.notify_all()
    except Exception as e:
        with job.cond:
            job.snapshot["status"] = "error"
            job.snapshot["error_message"] = str(e)
            job.snapshot["finished_at"] = time.time()
            job.events.append({"type": "error", "message": str(e)})
            job.cond.notify_all()


def stream(job: Job):
    """Yield events for SSE. Starts with a `snapshot` event so reconnecting
    clients can paint immediately, then tails new events until terminal."""
    yield {"type": "snapshot", **job.snapshot}
    i = len(job.events)  # snapshot already reflects all events so far
    while True:
        with job.cond:
            while i >= len(job.events) and job.snapshot["status"] == "running":
                if not job.cond.wait(timeout=15):
                    break
            new_events = job.events[i:]
            i = len(job.events)
            terminal = job.snapshot["status"] != "running"
        if new_events:
            for e in new_events:
                yield e
        elif not terminal:
            yield {"type": "heartbeat"}
            continue
        if terminal:
            return
