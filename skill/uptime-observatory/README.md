# uptime-observatory (reusable skill)

Independent read-only uptime & latency observatory for any JSON HTTP API: `probe.py` samples configured endpoints and writes JSON-lines; `analyzer.py` produces availability/latency reports with incident detection. Run `VANTAGE=my-host python3 probe.py` to collect, then `python3 analyzer.py --md-out report.md` to analyze. Quick test: `python3 tests/test_analyzer.py`.

Preconfigured for the BasedAgents public API (see `config.py`). To reuse for a
different API, edit the `ENDPOINTS` list and the shape validators in `probe.py`.

Honesty contract: every sample is tagged `sample_kind` = `observation` (we
reached the target; `ok` says whether the target was healthy) or
`collection_gap` (our probe failed to run — excluded from availability,
reported as probe uptime). GET only, one request per endpoint per cycle, 5-min
interval ceiling. Full field docs are in the parent repo's `schema.md`.

## Files
- `config.py` — endpoints + politeness budget (edit here)
- `probe.py` — one read-only sample per endpoint → JSON-lines (stdlib only)
- `analyzer.py` — samples → JSON + markdown report with incident detection
- `tests/test_analyzer.py` — zero-dependency test: proves gaps vs incidents

## Run
```bash
VANTAGE=my-host python3 probe.py                 # collect (repeat on a 5-min cron)
python3 analyzer.py --samples-dir samples \
    --json-out report.json --md-out report.md    # analyze
python3 tests/test_analyzer.py                   # test (no deps)
```
