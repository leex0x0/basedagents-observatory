# Sample schema

Each probe run appends one JSON object per endpoint (one line) to a `.jsonl`
file. Every field below is always present.

| Field | Type | Meaning |
|---|---|---|
| `ts` | string | UTC timestamp, ISO 8601 with offset, e.g. `2026-10-26T18:53:15.281042+00:00`. When the request started. |
| `endpoint` | string | Stable label: `status`, `tasks`, `settled`, or `task_detail`. |
| `url` | string | Exact GET URL probed. |
| `vantage` | string | Honest label of where the probe ran (env `VANTAGE`), e.g. `sandbox-proof`, `ci-ubuntu-a`, `ci-ubuntu-b`, `local`. |
| `sample_kind` | string | `observation` or `collection_gap` — the core honesty field (see below). |
| `latency_ms` | number \| null | Wall-clock request time in ms. `null` for a collection gap. |
| `http_status` | int \| null | HTTP status code. `null` for a collection gap (no response arrived). |
| `ok` | bool | For an observation: `true` = target healthy. For a gap: always `false` (but excluded from availability). See rules below. |
| `error` | string \| null | **Probe-side** failure only (DNS/TLS/connection/timeout). `null` for every observation, even a target-down one. |
| `cache_headers` | object | `{age, cache-control, etag, x-cache}`; each value is the header string or `null` if absent. `x-cache` falls back to `CF-Cache-Status`. |
| `bytes` | int | Response body length in bytes (`0` for a gap). |
| `shape_ok` | bool \| null | Did the body match the endpoint's expected JSON shape? `null` for a gap. |
| `note` | string \| null | Human-readable extra context (e.g. `json_parse_error: ...`, or why a gap happened). |

## The observation vs collection_gap distinction (the whole point)

A status page is self-reported; an independent observatory must never confuse
**"my probe failed to run"** with **"the target is down."** `sample_kind` makes
this unambiguous:

### `sample_kind: "observation"`
We reached the target and received an HTTP response. This is evidence about the
**target**.

- `ok == true`  → **target healthy**: `http_status < 500` **AND** `shape_ok == true`.
- `ok == false` → **target returned an error**: either `http_status >= 500`, or
  the body was not valid JSON / did not match the expected shape
  (`shape_ok == false`). This counts against **availability**.

### `sample_kind: "collection_gap"`
Our probe could **not complete** the request at all — DNS failure, TLS error,
connection refused, or timeout. This is evidence about **our own collection**,
not the target. `error` is set; `http_status`, `latency_ms`, `shape_ok` are
`null`.

- Collection gaps are **excluded** from `availability_pct`.
- They are reported separately as `probe_uptime_pct` (how reliable our
  collection was) and counted as `collection_gap_count`.
- They never count as failures for incident detection.

### Why `ok` alone is not enough
`ok` is a convenience boolean. The pair (`sample_kind`, `ok`) is authoritative:

| sample_kind | ok | Interpretation |
|---|---|---|
| observation | true | target up and well-formed |
| observation | false | target up but erroring (5xx or wrong shape) — **counts as downtime** |
| collection_gap | false | **our** probe failed to run — **NOT** target downtime |

## Expected shapes (used to compute `shape_ok`)

| Endpoint | Shape rule (confirmed live 2026-10-26) |
|---|---|
| `status` | top-level object with a `status` key |
| `tasks` | object with `ok == true` and `tasks` being a list |
| `settled` | object with `ok == true` and `tasks` being a list |
| `task_detail` | object with `ok == true` and `task` object containing `task_id` |

## Report fields (`analyzer.py`)

Per endpoint:

- `availability_pct` — healthy observations ÷ total observations × 100
  (**gaps excluded**).
- `probe_uptime_pct` — observations ÷ (observations + gaps) × 100.
- `p50_ms`, `p95_ms` — latency percentiles over **healthy** observations.
- `sample_count` — number of observations.
- `healthy_count` — healthy observations.
- `collection_gap_count` — number of collection gaps.
- `incidents` — list of consecutive-failure windows (**≥ 2** consecutive failed
  observations). Each incident: `start_ts`, `end_ts`, `duration_s`,
  `failed_observations`, `vantage_agreement` (`vantages`, `count`,
  `multi_vantage`, `note`), and `responses_seen` (counts of statuses / bad-shape
  outcomes). Incident windows that overlap in time across vantages are merged
  into one incident, so `vantage_agreement.multi_vantage == true` means more
  than one independent vantage saw the same outage.
