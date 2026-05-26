"""Smoke tests for the dashboard.

Build the app, hit each major route, verify 200 + a couple of payload signatures.
"""
import pytest
from fastapi.testclient import TestClient

from archway_benchmarks.benchmarks import TypeEvalPyBenchmark
from archway_benchmarks.dashboard.server import build_app
from archway_benchmarks.engines.stubs import make_stub_pair
from archway_benchmarks.runner import run


@pytest.fixture
def client_with_runs(tmp_path):
    db = tmp_path / "runs.db"
    bench = TypeEvalPyBenchmark()
    snippets = bench.load()

    t1, a1, ad1 = make_stub_pair(snippets, accuracy=1.0, seed=1)
    r1 = run(benchmark=bench, translator=t1, analyzer=a1, adapter=ad1,
             stub_accuracy=1.0, seed=1, db_path=db)
    t2, a2, ad2 = make_stub_pair(snippets, accuracy=0.67, seed=2)
    r2 = run(benchmark=bench, translator=t2, analyzer=a2, adapter=ad2,
             stub_accuracy=0.67, seed=2, db_path=db)

    return TestClient(build_app(db)), r1.run_id, r2.run_id


def test_runs_index_renders(client_with_runs):
    client, _, _ = client_with_runs
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ARCHWAY" in resp.text
    assert "/benchmarks" in resp.text


def test_scores_view_shows_leaderboard(client_with_runs):
    client, r1, _ = client_with_runs
    resp = client.get(f"/runs/{r1}")
    assert resp.status_code == 200
    assert "HeaderGen" in resp.text
    assert "Jedi" in resp.text
    assert "850" in resp.text


def test_inspector_filters_outcome(client_with_runs):
    client, _, r2 = client_with_runs
    resp = client.get(f"/runs/{r2}/inspect?outcome=TYPE_MISS")
    assert resp.status_code == 200
    assert "TYPE_MISS" in resp.text


def test_inspector_filters_fp_only(client_with_runs):
    client, _, r2 = client_with_runs
    resp = client.get(f"/runs/{r2}/inspect?fp_only=1")
    assert resp.status_code == 200


def test_snippet_view_renders_source(client_with_runs):
    client, r1, _ = client_with_runs
    # Walk a known snippet
    resp = client.get(f"/runs/{r1}/snippets/assignments/tuple")
    assert resp.status_code == 200
    assert "func1" in resp.text


def test_targets_board_shows_fp_and_callable(client_with_runs):
    client, r1, _ = client_with_runs
    resp = client.get(f"/runs/{r1}/targets")
    assert resp.status_code == 200
    assert "Function parameters" in resp.text
    assert "Callable GT" in resp.text


def test_compare_view(client_with_runs):
    client, r1, r2 = client_with_runs
    resp = client.get(f"/runs/{r1}/compare/{r2}")
    assert resp.status_code == 200
    assert "Gained EXACT" in resp.text
    assert "Lost EXACT" in resp.text
