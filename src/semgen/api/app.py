"""The Litestar application: health/readiness, input validation, generalization jobs, concept lift, provenance.

The engine is loaded once per process, in a background thread during startup (``/ready`` reports when it is
usable), and injected into handlers with Litestar's dependency injection. Every lattice run is bounded: a request's
budget is clamped to ``ApiLimits`` and an unbounded request gets the server's limits.
"""
from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import Any, Literal

from litestar import Litestar, Request, Response, get, post
from litestar.datastructures import State
from litestar.di import NamedDependency, Provide
from litestar.exceptions import HTTPException, NotFoundException
from litestar.openapi import OpenAPIConfig
from litestar.params import FromPath, FromQuery, JSONBody
from litestar.status_codes import HTTP_202_ACCEPTED, HTTP_422_UNPROCESSABLE_ENTITY, HTTP_503_SERVICE_UNAVAILABLE
from pydantic import BaseModel, ConfigDict, Field

from semgen.api.jobs import JobStore
from semgen.config import ConfigError
from semgen.engine import SemgenEngine
from semgen.export import semgen_version
from semgen.lattice import Budget
from semgen.motif_io import MotifError
from semgen.settings import Settings
from semgen.snomed import FsnError


@dataclass(frozen=True)
class ApiLimits:
    """Server-side bounds. Request budgets are clamped to these; ``None`` leaves a dimension to the request."""

    max_states: int | None = 20_000
    max_depth: int | None = None
    seconds: float | None = 120.0
    workers: int = 1                  # concurrent enumerations (each holds the GIL while it computes)
    max_jobs: int = 100               # finished jobs kept in memory
    max_body_bytes: int = 5 * 1024 * 1024
    wait_seconds: float = 30.0        # longest ?wait the server honours


# --- request models (validated by Litestar through its pydantic plugin) ------------------------------------------
class BudgetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_states: int | None = Field(default=None, ge=1)
    max_depth: int | None = Field(default=None, ge=0)
    seconds: float | None = Field(default=None, ge=0)


class InputIn(BaseModel):
    """``input``: one motif or bundle object, a motif list, ``{"motifs": [...]}`` or ``{"bundles": [...]}``."""

    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] | list[Any]


class GeneralizeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any]                         # one motif or one bundle
    budget: BudgetIn | None = None
    climb: bool = True


class VerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    specific: dict[str, Any]
    general: dict[str, Any]
    certificate: dict[str, str] | None = None


# --- dependencies ------------------------------------------------------------------------------------------------
def _engine(state: State) -> SemgenEngine:
    engine = state.get("engine")
    if engine is None:
        raise HTTPException(status_code=HTTP_503_SERVICE_UNAVAILABLE,
                            detail="engine not ready" + (f": {state['load_error']}" if state.get("load_error") else ""))
    return engine


def _jobs(state: State) -> JobStore:
    return state["jobs"]


def _limits(state: State) -> ApiLimits:
    return state["limits"]


def _clamp(req: BudgetIn | None, lim: ApiLimits) -> Budget:
    def lo(a, b):
        return b if a is None else a if b is None else min(a, b)
    r = req or BudgetIn()
    return Budget(max_states=lo(r.max_states, lim.max_states), max_depth=lo(r.max_depth, lim.max_depth),
                  seconds=lo(r.seconds, lim.seconds))


def _invalid(e: Exception) -> HTTPException:
    return HTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


# --- handlers ----------------------------------------------------------------------------------------------------
@get("/health", tags=["service"])
async def health() -> dict:
    """Liveness: the process is serving requests (the engine may still be loading)."""
    return {"status": "ok", "version": semgen_version()}


@get("/ready", tags=["service"])
async def ready(state: State) -> Response[dict]:
    """Readiness: 200 once the SNOMED CT release and config are loaded, 503 while loading or after a load error."""
    if state.get("engine") is not None:
        return Response({"status": "ready", "release": state["engine"].release})
    status: Literal["loading", "failed"] = "failed" if state.get("load_error") else "loading"
    return Response({"status": status, "error": state.get("load_error")}, status_code=HTTP_503_SERVICE_UNAVAILABLE)


@get("/v1/provenance", tags=["config"])
async def provenance(engine: NamedDependency[SemgenEngine]) -> dict:
    """Release, config, attribute-definition and source fingerprints, concept-lift provenance and the operator set."""
    return engine.provenance()


@get("/v1/config", tags=["config"])
async def config(engine: NamedDependency[SemgenEngine], limits: NamedDependency[ApiLimits], state: State) -> dict:
    """The active configuration (no file contents, no local paths) and the server's limits."""
    cfg = engine.context.config
    return {"status": cfg.status, "protected_roles": sorted(cfg.protected_roles),
            "allow_drop_absent": cfg.allow_drop_absent,
            "attribute_definitions": {k: v.about for k, v in sorted(cfg.attribute_definitions.items())},
            "attribute_definitions_sha256": cfg.attribute_definitions_sha256,
            "pins": {"mayo_sha256": cfg.mayo.sha256, "ucum_sha256": cfg.ucum.sha256 if cfg.ucum else None},
            "locations": state["settings"].describe(), "limits": asdict(limits)}


@post("/v1/validate", tags=["input"], status_code=200)
async def validate(data: JSONBody[InputIn], engine: NamedDependency[SemgenEngine], jobs: NamedDependency[JobStore]) -> dict:
    """Parse and validate motifs/bundles against the loaded release (FSN labels resolved). 422 on invalid input."""
    try:
        bundles = await jobs.run_blocking(lambda: engine.parse(data.input))
    except (MotifError, FsnError) as e:
        raise _invalid(e) from e
    from semgen.lattice import state_hash
    return {"valid": True, "bundles": [{"bundle_id": b.bundle_id, "hash": state_hash(b), "parts": len(b.parts),
                                        "semantics": b.semantics} for b in bundles]}


@post("/v1/verify", tags=["input"], status_code=200)
async def verify(data: JSONBody[VerifyIn], engine: NamedDependency[SemgenEngine], jobs: NamedDependency[JobStore]) -> dict:
    """Independent order proof that ``general`` is at least as general as ``specific`` (not the policy guard)."""
    try:
        return await jobs.run_blocking(lambda: engine.verify(data.specific, data.general, data.certificate))
    except (MotifError, FsnError) as e:
        raise _invalid(e) from e


@post("/v1/generalize", tags=["generalization"], status_code=HTTP_202_ACCEPTED)
async def generalize(data: JSONBody[GeneralizeIn], engine: NamedDependency[SemgenEngine], jobs: NamedDependency[JobStore], limits: NamedDependency[ApiLimits],
                     wait: FromQuery[float] = 0.0) -> Response[dict]:
    """Submit one motif or bundle for lattice enumeration under a clamped budget. Returns the job (202); with
    ``?wait=SECONDS`` the response waits up to that long (capped by the server) and is 200 when the job finished."""
    try:
        (bundle,) = engine.parse(data.input)
    except (MotifError, FsnError) as e:
        raise _invalid(e) from e
    except ValueError as e:   # more than one bundle
        raise _invalid(ValueError("submit exactly one motif or bundle per request")) from e
    budget = _clamp(data.budget, limits)
    job = jobs.submit(bundle.bundle_id, budget.to_json(), lambda: engine.generalize(bundle, budget, climb=data.climb))
    if wait > 0:
        await jobs.wait(job, min(wait, limits.wait_seconds))
    done = job.status in {"succeeded", "failed"}
    return Response(job.to_json(), status_code=200 if done else HTTP_202_ACCEPTED)


@get("/v1/jobs", tags=["generalization"])
async def list_jobs(jobs: NamedDependency[JobStore]) -> list[dict]:
    return [j.to_json() for j in jobs.list()]


@get("/v1/jobs/{job_id:str}", tags=["generalization"])
async def get_job(job_id: FromPath[str], jobs: NamedDependency[JobStore]) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise NotFoundException(f"no job {job_id}")
    return job.to_json()


@get("/v1/jobs/{job_id:str}/result", tags=["generalization"])
async def get_result(job_id: FromPath[str], jobs: NamedDependency[JobStore], depth: FromQuery[int | None] = None) -> Response[dict]:
    """The full lattice (run header, candidates, edges, blocked moves, termination), optionally filtered to
    candidates at depth <= ``depth`` exactly as ``semgen run --depth``. 409 while the job is not finished."""
    job = jobs.get(job_id)
    if job is None:
        raise NotFoundException(f"no job {job_id}")
    if job.status == "failed":
        return Response({"job_id": job.id, "status": job.status, "error": job.error}, status_code=409)
    if job.result is None:
        return Response({"job_id": job.id, "status": job.status}, status_code=409)
    if depth is not None and depth < 0:
        raise _invalid(ValueError("depth must be >= 0"))
    return Response(job.result.to_json(depth))


@get("/v1/concepts/{code:str}", tags=["concept lift"])
async def concept(code: FromPath[str], engine: NamedDependency[SemgenEngine]) -> dict:
    return engine.concept(code)


@get("/v1/concepts/{code:str}/lift", tags=["concept lift"])
async def lift(code: FromPath[str], engine: NamedDependency[SemgenEngine], jobs: NamedDependency[JobStore], max_transitions: FromQuery[int | None] = None) -> dict:
    """Concept-lift exploration from ``code``: accepted ancestors with derivation paths, every transition and its
    rule evidence, where each branch stops, each candidate re-checked by the independent verifier."""
    if max_transitions is not None and max_transitions < 1:
        raise _invalid(ValueError("max_transitions must be >= 1"))
    return await jobs.run_blocking(lambda: engine.inspect_lift(code, max_transitions))


@get("/v1/concepts/{code:str}/lift/{parent:str}", tags=["concept lift"])
async def lift_step(code: FromPath[str], parent: FromPath[str], engine: NamedDependency[SemgenEngine], jobs: NamedDependency[JobStore]) -> dict:
    """One step ``code -> parent``: the generator's decision with rule evidence and the verifier's verdict."""
    return await jobs.run_blocking(lambda: engine.check_lift(code, parent))


# --- application -------------------------------------------------------------------------------------------------
def _error_handler(_: Request, exc: ConfigError) -> Response:
    return Response({"status_code": 500, "detail": f"configuration error: {exc}"}, status_code=500)


def create_app(engine: SemgenEngine | None = None, *, settings: Settings | None = None,
               limits: ApiLimits | None = None, debug: bool = False) -> Litestar:
    """A Litestar app over ``engine``; without one, the engine is loaded from ``settings`` (default
    ``Settings.from_env()``) in a background thread at startup (``/ready`` turns 200 when it is loaded)."""
    settings = settings if settings is not None else Settings.from_env()
    limits = limits or ApiLimits()

    @contextlib.asynccontextmanager
    async def lifespan(app: Litestar) -> AsyncIterator[None]:
        app.state.jobs = JobStore(limits.workers, limits.max_jobs)
        app.state.limits, app.state.settings = limits, settings
        app.state.engine, app.state.load_error = engine, None
        task = None
        if engine is None:
            async def load() -> None:
                try:
                    app.state.engine = await asyncio.to_thread(SemgenEngine.from_settings, settings)
                except Exception as e:   # noqa: BLE001 - surfaced through /ready
                    app.state.load_error = f"{type(e).__name__}: {e}"
            task = asyncio.create_task(load())
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
            app.state.jobs.shutdown()

    return Litestar(
        route_handlers=[health, ready, provenance, config, validate, verify, generalize, list_jobs, get_job,
                        get_result, concept, lift, lift_step],
        dependencies={"engine": Provide(_engine, sync_to_thread=False), "jobs": Provide(_jobs, sync_to_thread=False),
                      "limits": Provide(_limits, sync_to_thread=False)},
        lifespan=[lifespan],
        exception_handlers={ConfigError: _error_handler},
        request_max_body_size=limits.max_body_bytes,
        openapi_config=OpenAPIConfig(title="semgen", version=semgen_version(),
                                     description="Deterministic symbolic generalization of clinical graph motifs"),
        debug=debug,
    )
