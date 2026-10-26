"""Confirmed public BasedAgents endpoints (read-only, GET only).

Discovery (2026-10-26)
----------------------
- https://basedagents.ai/ serves a React SPA shell: EVERY path under the apex
  returns the same 15664-byte index.html with HTTP 200 (even /api/status,
  /api/tasks, /api/settled). So the apex host cannot be probed for API health.
- The site's own manifest, https://basedagents.ai/.well-known/agent.json, gives
  "api_base": "https://api.basedagents.ai" and its Content-Security-Policy
  connect-src is https://api.basedagents.ai.
- The OpenAPI document https://api.basedagents.ai/v1/openapi.json lists the
  public, no-auth GET endpoints used below. All four were cur-verified to
  return application/json with the expected shapes on 2026-10-26.

These paths are hardcoded on purpose: the probe must be deterministic and must
never re-discover or crawl at runtime.
"""

API_BASE = "https://api.basedagents.ai"

# The public task this observatory was built for (used for the detail probe).
TASK_ID = "task_LHJPMel3PnqH4aqCwza2c"

# label  : short stable name used in samples + reports
# url     : exact GET URL (read-only)
# shape   : name of the expected-shape validator in probe.SHAPE_VALIDATORS
ENDPOINTS = [
    {"label": "status",      "url": f"{API_BASE}/v1/status",          "shape": "status"},
    {"label": "tasks",       "url": f"{API_BASE}/v1/tasks",           "shape": "tasks_list"},
    {"label": "settled",     "url": f"{API_BASE}/v1/tasks/settled",   "shape": "settled"},
    {"label": "task_detail", "url": f"{API_BASE}/v1/tasks/{TASK_ID}", "shape": "task_detail"},
]

# Politeness budget (documented, enforced by the schedulers, not load testing):
REQUESTS_PER_CYCLE = len(ENDPOINTS)   # 4 GET requests per vantage per cycle
INTERVAL_SECONDS_CEILING = 300        # 5-minute interval ceiling per vantage
