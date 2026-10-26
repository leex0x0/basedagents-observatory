#!/usr/bin/env python3
"""analyzer.py -- turn JSON-lines samples into availability + latency reports.

Reads every *.jsonl file under a samples dir (or files passed as args) and, per
endpoint, computes:

  availability_pct   % of OBSERVATIONS that were healthy (ok == true).
                     Collection gaps are EXCLUDED from this number.
  probe_uptime_pct   % of all attempts that were observations (not gaps) --
                     i.e. how reliable OUR own collection was.
  p50_ms / p95_ms    latency percentiles over healthy observations.
  sample_count       number of observations for the endpoint.
  collection_gap_count
  incidents          consecutive-failure windows: >= 2 consecutive FAILED
                     observations (ok == false) for a vantage. Collection gaps
                     never count as failures (they are our gaps, not the
                     target's). Each incident records start_ts, end_ts,
                     duration_s, vantage_agreement (which vantages saw it +
                     whether >=2 agreed), and the statuses/responses seen.

Outputs clean JSON (--json-out / stdout) and a human-readable markdown summary
(--md-out). Standard library only.

Usage:
    python3 analyzer.py                         # read ./samples/*.jsonl -> JSON to stdout
    python3 analyzer.py --samples-dir samples --json-out report.json --md-out report.md
    python3 analyzer.py file1.jsonl file2.jsonl --md-out report.md
"""
import argparse
import glob
import json
import math
import os
import sys
from datetime import datetime


# ---- helpers ------------------------------------------------------------------
def parse_ts(ts):
    """Parse an ISO8601 timestamp (with 'Z' or offset) to an aware datetime."""
    if ts is None:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def percentile(values, p):
    """Linear-interpolation percentile over a list of numbers (p in 0..100)."""
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    s = sorted(vals)
    if len(s) == 1:
        return round(float(s[0]), 2)
    k = (len(s) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return round(float(s[int(k)]), 2)
    return round(float(s[f] + (s[c] - s[f]) * (k - f)), 2)


def load_samples(paths):
    """Load and return all sample dicts from the given .jsonl file paths."""
    out = []
    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    # Skip a corrupt line rather than abort the whole report.
                    continue
    return out


def _find_incidents_for_vantage(obs_sorted):
    """Given one vantage's observations (time-sorted, gaps already removed),
    return runs of >=2 consecutive failed observations (ok == false)."""
    incidents = []
    run = []
    for s in obs_sorted:
        if s.get("ok") is False:
            run.append(s)
        else:
            if len(run) >= 2:
                incidents.append(run)
            run = []
    if len(run) >= 2:
        incidents.append(run)
    return incidents


def _responses_seen(samples):
    """Summarise the statuses/shape outcomes observed in an incident window."""
    seen = {}
    for s in samples:
        key = f"http_{s.get('http_status')}"
        if s.get("shape_ok") is False:
            key += "+bad_shape"
        seen[key] = seen.get(key, 0) + 1
    return seen


def build_report(samples):
    """Build the full structured report dict from a list of sample records."""
    endpoints = {}
    for s in samples:
        endpoints.setdefault(s.get("endpoint"), []).append(s)

    all_ts = [parse_ts(s["ts"]) for s in samples if s.get("ts")]
    window = {
        "start_ts": min(all_ts).isoformat() if all_ts else None,
        "end_ts": max(all_ts).isoformat() if all_ts else None,
    }
    all_vantages = sorted({s.get("vantage") for s in samples if s.get("vantage")})

    per_endpoint = []
    total_obs = 0
    total_gaps = 0
    for label in sorted(endpoints.keys()):
        rows = endpoints[label]
        observations = [s for s in rows if s.get("sample_kind") == "observation"]
        gaps = [s for s in rows if s.get("sample_kind") == "collection_gap"]
        healthy = [s for s in observations if s.get("ok") is True]
        total_obs += len(observations)
        total_gaps += len(gaps)

        availability_pct = round(100.0 * len(healthy) / len(observations), 2) if observations else None
        attempts = len(observations) + len(gaps)
        probe_uptime_pct = round(100.0 * len(observations) / attempts, 2) if attempts else None
        latencies = [s.get("latency_ms") for s in healthy]

        # Incident detection: per vantage, runs of >=2 consecutive failures,
        # then merge overlapping windows across vantages into single incidents.
        raw = []
        for v in all_vantages:
            v_obs = sorted(
                [s for s in observations if s.get("vantage") == v],
                key=lambda s: parse_ts(s["ts"]),
            )
            for run in _find_incidents_for_vantage(v_obs):
                raw.append({
                    "vantage": v,
                    "start": parse_ts(run[0]["ts"]),
                    "end": parse_ts(run[-1]["ts"]),
                    "samples": run,
                })
        raw.sort(key=lambda r: r["start"])

        merged = []
        for r in raw:
            if merged and r["start"] <= merged[-1]["end"]:
                m = merged[-1]
                m["end"] = max(m["end"], r["end"])
                m["start"] = min(m["start"], r["start"])
                m["vantages"].add(r["vantage"])
                m["samples"].extend(r["samples"])
            else:
                merged.append({
                    "start": r["start"], "end": r["end"],
                    "vantages": {r["vantage"]}, "samples": list(r["samples"]),
                })

        incidents = []
        for m in merged:
            vs = sorted(m["vantages"])
            incidents.append({
                "start_ts": m["start"].isoformat(),
                "end_ts": m["end"].isoformat(),
                "duration_s": round((m["end"] - m["start"]).total_seconds(), 2),
                "failed_observations": len(m["samples"]),
                "vantage_agreement": {
                    "vantages": vs,
                    "count": len(vs),
                    "multi_vantage": len(vs) >= 2,
                    "note": ("confirmed by multiple vantages" if len(vs) >= 2
                             else "seen by a single vantage only"),
                },
                "responses_seen": _responses_seen(m["samples"]),
            })

        per_endpoint.append({
            "endpoint": label,
            "url": rows[0].get("url"),
            "availability_pct": availability_pct,
            "probe_uptime_pct": probe_uptime_pct,
            "p50_ms": percentile(latencies, 50),
            "p95_ms": percentile(latencies, 95),
            "sample_count": len(observations),
            "healthy_count": len(healthy),
            "collection_gap_count": len(gaps),
            "vantages": sorted({s.get("vantage") for s in rows if s.get("vantage")}),
            "incidents": incidents,
        })

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "window": window,
        "vantages": all_vantages,
        "total_requests": len(samples),
        "total_observations": total_obs,
        "total_collection_gaps": total_gaps,
        "per_endpoint": per_endpoint,
    }


def to_markdown(report):
    """Render a human-readable markdown summary of a report dict."""
    L = []
    L.append("# BasedAgents API uptime & latency observatory -- report")
    L.append("")
    L.append(f"- Generated: {report['generated_at']}")
    w = report["window"]
    L.append(f"- Window: {w['start_ts']} -> {w['end_ts']}")
    L.append(f"- Vantages: {', '.join(report['vantages']) or '(none)'}")
    L.append(f"- Total requests (all attempts): {report['total_requests']}")
    L.append(f"- Observations: {report['total_observations']}  |  "
             f"Collection gaps: {report['total_collection_gaps']}")
    L.append("")
    L.append("Availability counts OBSERVATIONS only; collection gaps (our own "
             "probe failures) are excluded and shown as probe uptime.")
    L.append("")
    L.append("| Endpoint | Availability % | Probe uptime % | p50 ms | p95 ms | "
             "Obs | Gaps | Incidents |")
    L.append("|---|---|---|---|---|---|---|---|")
    for e in report["per_endpoint"]:
        L.append("| {ep} | {av} | {pu} | {p50} | {p95} | {oc} | {gc} | {inc} |".format(
            ep=e["endpoint"], av=e["availability_pct"], pu=e["probe_uptime_pct"],
            p50=e["p50_ms"], p95=e["p95_ms"], oc=e["sample_count"],
            gc=e["collection_gap_count"], inc=len(e["incidents"])))
    L.append("")
    any_inc = False
    for e in report["per_endpoint"]:
        if not e["incidents"]:
            continue
        any_inc = True
        L.append(f"## Incidents -- {e['endpoint']}")
        for i, inc in enumerate(e["incidents"], 1):
            va = inc["vantage_agreement"]
            L.append(f"- Incident {i}: {inc['start_ts']} -> {inc['end_ts']} "
                     f"({inc['duration_s']}s, {inc['failed_observations']} failed obs)")
            L.append(f"  - Vantage agreement: {va['count']} vantage(s) "
                     f"[{', '.join(va['vantages'])}] -- {va['note']}")
            L.append(f"  - Responses seen: {json.dumps(inc['responses_seen'])}")
        L.append("")
    if not any_inc:
        L.append("## Incidents")
        L.append("None detected (no endpoint had >=2 consecutive failed observations).")
        L.append("")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Analyze BasedAgents observatory samples.")
    ap.add_argument("files", nargs="*", help="explicit .jsonl sample files")
    ap.add_argument("--samples-dir", default="samples",
                    help="directory of *.jsonl samples (used if no files given)")
    ap.add_argument("--json-out", help="write JSON report here (else stdout)")
    ap.add_argument("--md-out", help="write markdown summary here")
    args = ap.parse_args(argv)

    paths = args.files or sorted(glob.glob(os.path.join(args.samples_dir, "*.jsonl")))
    if not paths:
        print("no sample files found", file=sys.stderr)
        return 2

    samples = load_samples(paths)
    report = build_report(samples)
    text = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    else:
        print(text)

    if args.md_out:
        with open(args.md_out, "w", encoding="utf-8") as f:
            f.write(to_markdown(report) + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
