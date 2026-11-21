"""The Litestar HTTP API over a synthetic engine (fake hierarchy) and over the tiny fixture RF2 release."""
import copy
import time
from pathlib import Path

import pytest

pytest.importorskip("litestar")
from litestar.testing import TestClient  # noqa: E402

from semgen import Budget, SemgenEngine, Settings  # noqa: E402
from semgen.api import ApiLimits, create_app  # noqa: E402
from semgen.config import load_config  # noqa: E402
from semgen.interfaces import GenContext  # noqa: E402
from tests.support.fake_snomed import BRCA, FAKE_M1, FAKE_M2, fake_boundary_policy, fake_hierarchy  # noqa: E402

pytestmark = pytest.mark.api
FIXTURE_RF2 = Path(__file__).resolve().parent / "fixtures" / "rf2"


@pytest.fixture
def engine():
    h = fake_hierarchy()
    return SemgenEngine(GenContext(h, load_config(), fake_boundary_policy(h)))


@pytest.fixture
def client(engine, tmp_path):
    with TestClient(create_app(engine, settings=Settings(cache_dir=tmp_path))) as c:
        yield c


def _wait_ready(c, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        r = c.get("/ready")
        if r.status_code == 200 or r.json()["status"] == "failed":
            return r
        time.sleep(0.05)
    raise AssertionError("engine never became ready")


def test_health_and_ready(client):
    assert client.get("/health").json()["status"] == "ok"
    r = client.get("/ready")
    assert r.status_code == 200 and r.json()["release"] == {"edition": "TEST", "release": "TEST"}


def test_engine_loads_in_background_from_settings(tmp_path):
    app = create_app(settings=Settings(rf2_dir=FIXTURE_RF2, cache_dir=tmp_path / "cache"))
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200                   # live while (or before) loading
        r = _wait_ready(c)
        assert r.status_code == 200 and r.json()["release"]["release"] == "20990101"


def test_not_ready_without_a_release(tmp_path):
    with TestClient(create_app(settings=Settings(cache_dir=tmp_path))) as c:
        r = _wait_ready(c)
        assert r.status_code == 503 and r.json()["status"] == "failed" and "SEMGEN_RF2_DIR" in r.json()["error"]
        dep = c.get("/v1/provenance")
        assert dep.status_code == 503 and "not ready" in dep.json()["detail"]


def test_validate(client):
    r = client.post("/v1/validate", json={"input": {"motifs": [FAKE_M1, FAKE_M2]}})
    assert r.status_code == 200 and [b["bundle_id"] for b in r.json()["bundles"]] == ["M1", "M2"]
    bad = copy.deepcopy(FAKE_M1)
    bad["anchor"] = "nope"
    r = client.post("/v1/validate", json={"input": bad})
    assert r.status_code == 422
    assert client.post("/v1/validate", json={"input": FAKE_M1, "extra": 1}).status_code == 400


def test_generalize_wait_and_result_match_the_library(client, engine):
    r = client.post("/v1/generalize?wait=10", json={"input": FAKE_M1, "budget": {"max_depth": 2}})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "succeeded" and job["summary"]["bundle_id"] == "M1"
    # unspecified dimensions get the server limits; given ones are kept when below them
    assert job["budget"] == {"max_states": ApiLimits().max_states, "max_depth": 2, "seconds": ApiLimits().seconds}
    full = client.get(f"/v1/jobs/{job['job_id']}/result").json()
    lib = engine.generalize(copy.deepcopy(FAKE_M1), Budget(**job["budget"])).to_json()
    assert full["candidates"] == lib["candidates"] and full["edges"] == lib["edges"]
    assert full["run_header"] == lib["run_header"]
    shallow = client.get(f"/v1/jobs/{job['job_id']}/result?depth=1").json()
    assert {c["depth"] for c in shallow["candidates"]} <= {0, 1} < {c["depth"] for c in full["candidates"]}
    assert client.get(f"/v1/jobs/{job['job_id']}").json()["status"] == "succeeded"
    assert any(j["job_id"] == job["job_id"] for j in client.get("/v1/jobs").json())


def test_budget_is_clamped_to_server_limits(engine, tmp_path):
    limits = ApiLimits(max_states=3, seconds=None)
    with TestClient(create_app(engine, settings=Settings(cache_dir=tmp_path), limits=limits)) as c:
        job = c.post("/v1/generalize?wait=10", json={"input": FAKE_M1, "budget": {"max_states": 10_000}}).json()
        assert job["budget"]["max_states"] == 3 and job["status"] == "succeeded"
        # the BFS stores at most max_states states; per-node concept-lift climbs are bounded by the (finite)
        # ancestor set, not by the budget (semgen.lattice.search), so axis candidates may add to the count
        assert job["summary"]["status"] == "budget_limited" and job["summary"]["budget_hit"] == ["max_states"]
        nolift = c.post("/v1/generalize?wait=10", json={"input": FAKE_M1, "climb": False}).json()
        assert nolift["summary"]["candidates"] <= 3


def test_generalize_async_then_poll(client):
    r = client.post("/v1/generalize", json={"input": FAKE_M2, "budget": {"max_depth": 1}})
    assert r.status_code in {200, 202}
    jid = r.json()["job_id"]
    end = time.monotonic() + 30
    while client.get(f"/v1/jobs/{jid}").json()["status"] not in {"succeeded", "failed"}:
        assert time.monotonic() < end
        time.sleep(0.02)
    assert client.get(f"/v1/jobs/{jid}/result").status_code == 200


def test_generalize_errors(client):
    assert client.post("/v1/generalize", json={"input": {"motifs": [FAKE_M1, FAKE_M2]}}).status_code == 422
    assert client.post("/v1/generalize", json={"input": FAKE_M1, "budget": {"max_states": 0}}).status_code == 400
    assert client.get("/v1/jobs/unknown").status_code == 404
    assert client.get("/v1/jobs/unknown/result").status_code == 404


def test_failed_job_reports_invariant_violation(engine, tmp_path):
    from semgen import ChangeRecord, Move, OperatorResult

    def bad(m, ctx):
        child = m.without({m.anchor}, {e.key for e in m.edges if m.anchor in e.key})
        return OperatorResult([Move(child, ChangeRecord("bad", m.anchor, "node", None, None, {}))])
    e = engine.with_operators(engine.operators.with_operator(bad))
    with TestClient(create_app(e, settings=Settings(cache_dir=tmp_path))) as c:
        job = c.post("/v1/generalize?wait=10", json={"input": FAKE_M1}).json()
        assert job["status"] == "failed" and job["error"]["type"] == "invariant_violated"
        assert c.get(f"/v1/jobs/{job['job_id']}/result").status_code == 409


def test_verify(client, engine):
    child = copy.deepcopy(FAKE_M1)                     # input format: n1 lifted to one of its IS-A parents
    child["nodes"][1]["code"] = sorted(engine.context.hierarchy.parents(BRCA))[0]
    assert client.post("/v1/verify", json={"specific": FAKE_M1, "general": child}).json()["ok"] is True
    assert client.post("/v1/verify", json={"specific": child, "general": FAKE_M1}).json()["ok"] is False


def test_concept_lift_endpoints(client, engine):
    assert client.get(f"/v1/concepts/{BRCA}").json()["active"] is True
    ex = client.get(f"/v1/concepts/{BRCA}/lift").json()
    assert ex == engine.inspect_lift(BRCA)
    parent = sorted(engine.context.hierarchy.parents(BRCA))[0]
    step = client.get(f"/v1/concepts/{BRCA}/lift/{parent}").json()
    assert step["child"] == BRCA and step["verification"]["status"] in {"verified", "failed"}
    assert client.get(f"/v1/concepts/{BRCA}/lift?max_transitions=0").status_code == 422


def test_config_and_provenance(client, tmp_path):
    cfg = client.get("/v1/config").json()
    assert cfg["status"].startswith("DRAFT") and cfg["protected_roles"] == ["anchor", "patient"]
    assert str(tmp_path) not in client.get("/v1/config").text
    prov = client.get("/v1/provenance").json()
    assert prov["operators"]["bundle"] == ["motif_deletion"] and "floor_policy" in prov


def test_openapi_schema(client):
    paths = client.get("/schema/openapi.json").json()["paths"]
    assert {"/health", "/ready", "/v1/generalize", "/v1/jobs/{job_id}/result", "/v1/concepts/{code}/lift"} <= set(paths)
