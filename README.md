# basedagents-observatory

An independent, read-only uptime & latency observatory for the public BasedAgents API: `probe.py` samples 4 public endpoints on a schedule and writes structured JSON-lines; `analyzer.py` turns those samples into availability/latency reports with incident detection. Run it with `VANTAGE=my-host python3 probe.py` (collect) then `python3 analyzer.py --md-out report.md` (analyze).

Status pages are self-reported; an observatory is independent. This kit never
trusts a self-reported status — it measures from the outside, and it rigorously
separates **"my probe failed to run"** (a gap in *my* collection) from **"the
target returned an error"** (real downtime). See `schema.md`.

Stdlib-only for collection (no pip needed to probe). Strictly read-only: GET
only, one request per endpoint per cycle, 5-minute interval ceiling per vantage.

## Confirmed target endpoints (discovered + verified 2026-10-26)

`https://basedagents.ai/` is a React SPA: every apex path returns the same
`index.html` (HTTP 200), so the apex can't be probed for API health. The real
JSON API is `https://api.basedagents.ai` (per the site's own
`/.well-known/agent.json` and `/v1/openapi.json`). The four probed endpoints:

| Label | URL | Expected shape |
|---|---|---|
| `status` | `https://api.basedagents.ai/v1/status` | object with `status` |
| `tasks` | `https://api.basedagents.ai/v1/tasks` | `ok:true`, `tasks:[...]` |
| `settled` | `https://api.basedagents.ai/v1/tasks/settled` | `ok:true`, `tasks:[...]` |
| `task_detail` | `https://api.basedagents.ai/v1/tasks/task_LHJPMel3PnqH4aqCwza2c` | `ok:true`, `task.task_id` |

These are hardcoded in `config.py` on purpose (no runtime crawling).

## Deploy in under 15 minutes

```bash
# 1. Clone
git clone https://github.com/leex0x0/basedagents-observatory.git
cd basedagents-observatory

# 2. No install needed to collect data (stdlib only). Probe once:
VANTAGE=my-host python3 probe.py
#   -> appends 4 lines to samples/samples-my-host.jsonl and prints them.

# 3. Schedule it every 5 minutes. EITHER local cron:
crontab -e      # paste a line from scheduler/cron.example (edit path + VANTAGE)
#   OR GitHub Actions (two vantages, zero machines of your own): just push this
#   repo — .github/workflows/pilot-ci-ubuntu-a.yml and ...-b.yml run on a
#   */5 schedule and commit samples back to samples/. Enable Actions in the
#   repo settings; they need `contents: write` (already declared).

# 4. Analyze whatever you've collected:
python3 analyzer.py --samples-dir samples --json-out report.json --md-out report.md
cat report.md

# 5. (optional) run the tests
python3 tests/test_analyzer.py        # zero dependencies
# or, if you have pytest:  pip install -r requirements.txt && pytest -q
```

## Files

```
config.py        confirmed endpoints + politeness budget (edit here only)
probe.py         one read-only sample of each endpoint -> JSON-lines
analyzer.py      samples -> availability/latency report (JSON + markdown)
run_pilot.sh     run probe.py every INTERVAL for CYCLES cycles (single host)
scheduler/cron.example                 cron line for a local vantage
.github/workflows/pilot-ci-ubuntu-a.yml   CI vantage A (GitHub Actions runner)
.github/workflows/pilot-ci-ubuntu-b.yml   CI vantage B (GitHub Actions runner)
schema.md        every field + the observation-vs-collection-gap distinction
tests/test_analyzer.py   synthetic gap + incident, asserts they're distinguished
samples/         collected .jsonl (one file per vantage)
pilot_proof/     real 30-min sandbox mini-pilot: raw samples + generated report
```

## Vantages used in the pilot (honest labels)

- `sandbox-proof` — a 30-minute mini-pilot run from the build sandbox (a single
  Linux host). Proves the kit works end-to-end on real data. Data +
  report are in `pilot_proof/`.
- `ci-ubuntu-a` / `ci-ubuntu-b` — two **independently scheduled GitHub Actions
  runners** (`ubuntu-latest`, Azure infra). Not machines I own — honestly CI
  runners. These produce the continuous 48-hour, 2-vantage dataset over the two
  days after this repo is pushed and Actions is enabled. Scheduled-run delays or
  drops show up as **collection gaps**, never as target downtime.

## Request-count accounting (politeness)

- **Per cycle, per vantage:** exactly **4** GET requests (one per endpoint).
- **Per vantage per hour:** 12 cycles × 4 = **48** requests (5-min interval).
- **Per vantage per day:** 288 cycles × 4 = **1,152** requests.
- **48-hour pilot, 2 CI vantages:** 2 × 2 days × 1,152 = **≈ 4,608** requests
  total (minus any skipped CI cycles).
- **Sandbox mini-pilot:** 7 cycles × 4 = **28** requests (one vantage, 30 min).

Never POST. No auth. No sign-ups, messages, or third-party contact. The exact
total request count for any dataset = number of lines across its `.jsonl` files
(each line is exactly one HTTP attempt), also reported as `total_requests` by
`analyzer.py`.
