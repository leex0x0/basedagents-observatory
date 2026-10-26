"""Tests for analyzer.py.

Feeds synthetic samples -- including a collection gap and a two-vantage
target-down incident -- and asserts the report:
  * excludes collection gaps from availability but counts them separately,
  * detects the >=2-consecutive-failure incident,
  * marks vantage agreement when both vantages saw it,
  * computes latency percentiles over healthy observations only.

Run from the repo root:  pytest -q   (or: python3 tests/test_analyzer.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyzer  # noqa: E402


def obs(ts, endpoint, vantage, ok, status=200, latency=100.0, shape_ok=True):
    return {
        "ts": ts, "endpoint": endpoint, "url": "https://api.basedagents.ai/v1/status",
        "vantage": vantage, "sample_kind": "observation", "latency_ms": latency,
        "http_status": status, "ok": ok, "error": None,
        "cache_headers": {"age": None, "cache-control": None, "etag": None, "x-cache": None},
        "bytes": 100, "shape_ok": shape_ok, "note": None,
    }


def gap(ts, endpoint, vantage):
    return {
        "ts": ts, "endpoint": endpoint, "url": "https://api.basedagents.ai/v1/status",
        "vantage": vantage, "sample_kind": "collection_gap", "latency_ms": None,
        "http_status": None, "ok": False, "error": "URLError: timed out",
        "cache_headers": {"age": None, "cache-control": None, "etag": None, "x-cache": None},
        "bytes": 0, "shape_ok": None, "note": "probe-side failure",
    }


def build_synthetic():
    s = []
    # Vantage A: healthy, healthy, DOWN(500), DOWN(500), healthy  -> 1 incident (2 fails)
    s.append(obs("2026-10-26T00:00:00+00:00", "status", "A", True, 200, 90.0))
    s.append(obs("2026-10-26T00:05:00+00:00", "status", "A", True, 200, 110.0))
    s.append(obs("2026-10-26T00:10:00+00:00", "status", "A", False, 500, 300.0, shape_ok=False))
    s.append(obs("2026-10-26T00:15:00+00:00", "status", "A", False, 503, 320.0, shape_ok=False))
    s.append(obs("2026-10-26T00:20:00+00:00", "status", "A", True, 200, 95.0))
    # Vantage B: healthy, GAP(ours), DOWN, DOWN, healthy -> same incident window, agreement
    s.append(obs("2026-10-26T00:00:30+00:00", "status", "B", True, 200, 130.0))
    s.append(gap("2026-10-26T00:05:30+00:00", "status", "B"))  # our collection gap, excluded
    s.append(obs("2026-10-26T00:10:30+00:00", "status", "B", False, 500, 280.0, shape_ok=False))
    s.append(obs("2026-10-26T00:15:30+00:00", "status", "B", False, 500, 290.0, shape_ok=False))
    s.append(obs("2026-10-26T00:20:30+00:00", "status", "B", True, 200, 100.0))
    # A second endpoint that is perfectly healthy (no incident)
    for i, t in enumerate(["00:00", "00:05", "00:10"]):
        s.append(obs(f"2026-10-26T{t}:00+00:00", "tasks", "A", True, 200, 50.0 + i))
    return s


def test_report_distinguishes_gap_and_detects_incident():
    report = analyzer.build_report(build_synthetic())
    by_ep = {e["endpoint"]: e for e in report["per_endpoint"]}

    status = by_ep["status"]
    # 9 observations for status (5 from A + 4 from B; the B gap is not an observation)
    assert status["sample_count"] == 9
    assert status["collection_gap_count"] == 1
    # Healthy observations: A has 3, B has 2 (its 2nd sample was a gap) -> 5 of 9.
    assert status["healthy_count"] == 5
    assert status["availability_pct"] == round(100.0 * 5 / 9, 2)
    # Probe uptime: 9 observations of 10 attempts (one gap).
    assert status["probe_uptime_pct"] == round(100.0 * 9 / 10, 2)

    # Exactly one incident, confirmed by BOTH vantages.
    assert len(status["incidents"]) == 1
    inc = status["incidents"][0]
    assert inc["vantage_agreement"]["multi_vantage"] is True
    assert inc["vantage_agreement"]["count"] == 2
    assert set(inc["vantage_agreement"]["vantages"]) == {"A", "B"}
    assert inc["failed_observations"] == 4
    # 5xx statuses are recorded in responses_seen.
    assert any(k.startswith("http_5") for k in inc["responses_seen"])

    # Latency percentiles are over healthy observations only (so <=130, never 300+).
    assert status["p50_ms"] is not None
    assert status["p95_ms"] <= 130.0

    # Healthy endpoint has zero incidents and 100% availability.
    tasks = by_ep["tasks"]
    assert tasks["incidents"] == []
    assert tasks["availability_pct"] == 100.0
    assert tasks["collection_gap_count"] == 0


def test_single_failure_is_not_an_incident():
    # One isolated failure must NOT be flagged (needs >=2 consecutive).
    s = [
        obs("2026-10-26T00:00:00+00:00", "status", "A", True, 200),
        obs("2026-10-26T00:05:00+00:00", "status", "A", False, 500, shape_ok=False),
        obs("2026-10-26T00:10:00+00:00", "status", "A", True, 200),
    ]
    report = analyzer.build_report(s)
    assert report["per_endpoint"][0]["incidents"] == []


if __name__ == "__main__":
    test_report_distinguishes_gap_and_detects_incident()
    test_single_failure_is_not_an_incident()
    print("ok: all analyzer tests passed")
