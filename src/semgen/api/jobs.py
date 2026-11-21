"""In-process job runner for lattice enumerations: a bounded thread pool and a bounded in-memory result store.

Enumeration is CPU-bound pure Python, so it never runs on the event loop: each job runs in a worker thread
(``ApiLimits.workers``, default 1) and the handler only awaits its future. A process pool is not used because every
worker would have to load its own copy of the SNOMED CT release (hundreds of MB). Results live in memory for the
lifetime of the process (oldest finished jobs are evicted beyond ``max_jobs``); they are not persisted.
"""
from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from semgen.engine import GeneralizationResult
from semgen.lattice import GeneralizationOrderError, PolicyViolation
from semgen.motif_io import MotifError


@dataclass
class Job:
    id: str
    bundle_id: str
    budget: dict
    status: str = "queued"            # queued | running | succeeded | failed
    submitted: float = field(default_factory=time.time)
    finished: float | None = None
    result: GeneralizationResult | None = None
    error: dict | None = None
    future: Future | None = field(default=None, repr=False)

    def to_json(self) -> dict:
        out: dict[str, Any] = {"job_id": self.id, "bundle_id": self.bundle_id, "status": self.status,
                               "budget": self.budget, "error": self.error}
        if self.finished is not None:
            out["elapsed_seconds"] = round(self.finished - self.submitted, 3)
        if self.result is not None:
            out["summary"] = self.result.summary()
        return out


class JobStore:
    def __init__(self, workers: int, max_jobs: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="semgen-lattice")
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._max = max_jobs

    def submit(self, bundle_id: str, budget: dict, fn: Callable[[], GeneralizationResult]) -> Job:
        job = Job(uuid.uuid4().hex, bundle_id, budget)

        def run() -> None:
            job.status = "running"
            try:
                job.result = fn()
                job.status = "succeeded"
            except (PolicyViolation, GeneralizationOrderError) as e:
                job.status, job.error = "failed", {"type": "invariant_violated", "message": str(e)}
            except MotifError as e:
                job.status, job.error = "failed", {"type": "invalid_input", "message": str(e)}
            except Exception as e:   # noqa: BLE001 - reported to the client, never swallowed silently
                job.status, job.error = "failed", {"type": type(e).__name__, "message": str(e)}
            finally:
                job.finished = time.time()

        with self._lock:
            self._jobs[job.id] = job
            self._evict()
        job.future = self._pool.submit(run)
        return job

    def _evict(self) -> None:
        done = [j for j in self._jobs.values() if j.status in {"succeeded", "failed"}]
        while len(self._jobs) > self._max and done:
            self._jobs.pop(done.pop(0).id, None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())

    async def wait(self, job: Job, timeout: float | None) -> None:
        if job.future is not None:
            try:
                await asyncio.wait_for(asyncio.shield(asyncio.wrap_future(job.future)), timeout)
            except TimeoutError:
                pass

    @staticmethod
    async def run_blocking(fn: Callable[[], Any]) -> Any:
        """Run a short CPU-bound call (lift exploration, validation) off the event loop, in the default thread
        executor, so it never queues behind a long enumeration."""
        return await asyncio.to_thread(fn)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
