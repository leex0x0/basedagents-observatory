#!/usr/bin/env python3
"""probe.py -- one polite, read-only sample of each BasedAgents public endpoint.

Run it once; it GETs each configured endpoint a single time, measures latency,
captures cache headers, validates the expected JSON shape, and appends one
JSON-lines (.jsonl) record per endpoint to the samples file. Standard library
only (urllib) -- no pip install needed to collect data.

HONESTY CONTRACT (full detail in schema.md)
-------------------------------------------
Every record has a `sample_kind`:

  "observation"    -> We reached the target and got an HTTP response.
                      ok == True  means the target is HEALTHY
                                  (http_status < 500 AND expected shape present).
                      ok == False means the TARGET returned an error:
                                  http_status >= 500, or a non-JSON / wrong-shape
                                  body. `http_status` and `shape_ok` say which.

  "collection_gap" -> OUR probe could not complete the request at all
                      (DNS failure, TLS error, connection refused, timeout).
                      This is a gap in OUR collection, NOT target downtime.
                      `error` is set; `http_status`, `latency_ms`, `shape_ok`
                      are null. The analyzer EXCLUDES these from availability and
                      reports them separately as probe uptime.

This makes "my probe failed to run" vs "the target returned an error"
unambiguous. Read-only: GET only, one request per endpoint per run, never POST.

Usage:
    VANTAGE=my-host python3 probe.py
Env:
    VANTAGE       vantage label (default "local")
    SAMPLES_FILE  output .jsonl path (default samples/samples-<vantage>.jsonl)
    PROBE_TIMEOUT seconds per request (default 20)
"""
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import config

USER_AGENT = (
    "basedagents-observatory/1.0 "
    "(+https://github.com/leex0x0/basedagents-observatory) read-only uptime probe"
)


# ---- expected-shape validators ------------------------------------------------
def _v_status(b):
    return isinstance(b, dict) and "status" in b


def _v_tasks_list(b):
    return isinstance(b, dict) and b.get("ok") is True and isinstance(b.get("tasks"), list)


def _v_settled(b):
    return isinstance(b, dict) and b.get("ok") is True and isinstance(b.get("tasks"), list)


def _v_task_detail(b):
    t = b.get("task") if isinstance(b, dict) else None
    return isinstance(b, dict) and b.get("ok") is True and isinstance(t, dict) and "task_id" in t


SHAPE_VALIDATORS = {
    "status": _v_status,
    "tasks_list": _v_tasks_list,
    "settled": _v_settled,
    "task_detail": _v_task_detail,
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def extract_cache_headers(headers):
    """Pull the cache-relevant response headers (None if absent)."""
    if headers is None:
        return {"age": None, "cache-control": None, "etag": None, "x-cache": None}
    return {
        "age": headers.get("Age"),
        "cache-control": headers.get("Cache-Control"),
        "etag": headers.get("ETag"),
        # X-Cache is the generic CDN hit/miss header; CF-Cache-Status is Cloudflare's.
        "x-cache": headers.get("X-Cache") or headers.get("CF-Cache-Status"),
    }


def probe_one(ep, vantage):
    """Probe a single endpoint once and return a sample dict."""
    url = ep["url"]
    label = ep["label"]
    shape_name = ep["shape"]
    base = {"ts": now_iso(), "endpoint": label, "url": url, "vantage": vantage}

    req = urllib.request.Request(
        url, method="GET",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
    )
    timeout = float(os.environ.get("PROBE_TIMEOUT", "20"))
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body_bytes = resp.read()
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            status = resp.getcode()
            headers = resp.headers
    except urllib.error.HTTPError as e:
        # We DID receive an HTTP response (4xx/5xx) -> this is an OBSERVATION,
        # evidence of a target-side error, not a collection gap.
        body_bytes = e.read() if hasattr(e, "read") else b""
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        status = e.code
        headers = e.headers
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        # Our probe could not complete the request -> COLLECTION GAP.
        return {
            **base,
            "sample_kind": "collection_gap",
            "latency_ms": None,
            "http_status": None,
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "cache_headers": extract_cache_headers(None),
            "bytes": 0,
            "shape_ok": None,
            "note": "probe-side failure (network/DNS/TLS/timeout); not target downtime",
        }

    # We have an HTTP response -> OBSERVATION.
    bytes_len = len(body_bytes)
    shape_ok = None
    note = None
    validator = SHAPE_VALIDATORS.get(shape_name)
    try:
        parsed = json.loads(body_bytes.decode("utf-8"))
        shape_ok = bool(validator(parsed)) if validator else None
    except Exception as e:  # body was not valid JSON -> target returned wrong body
        shape_ok = False
        note = f"json_parse_error: {type(e).__name__}"

    healthy = status is not None and status < 500 and shape_ok is True
    return {
        **base,
        "sample_kind": "observation",
        "latency_ms": latency_ms,
        "http_status": status,
        "ok": bool(healthy),
        "error": None,  # error is reserved for probe-side failures only
        "cache_headers": extract_cache_headers(headers),
        "bytes": bytes_len,
        "shape_ok": shape_ok,
        "note": note,
    }


def main():
    vantage = os.environ.get("VANTAGE", "local")
    here = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.join(here, "samples", f"samples-{vantage}.jsonl")
    samples_path = os.environ.get("SAMPLES_FILE", default_path)
    os.makedirs(os.path.dirname(samples_path), exist_ok=True)

    records = [probe_one(ep, vantage) for ep in config.ENDPOINTS]

    with open(samples_path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Echo to stdout so CI logs show exactly what was collected this cycle.
    for rec in records:
        print(json.dumps(rec, ensure_ascii=False))

    # The probe run itself succeeded (we attempted every endpoint once), even if
    # the target was down or a gap occurred -- so exit 0 and let the analyzer judge.
    return 0


if __name__ == "__main__":
    sys.exit(main())
