# Changelog — ShintTools Core

All notable changes to the Core engine are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions match
`core/api/version.py::CORE_VERSION`, bumped in lockstep with the `v*.*.*`
tag that publishes the image.

## [2.17.9] — 2026-08-25

### Security

- **`POST /config` was writable by any website the user visited (CSRF, High).**
  The endpoint wrote the whole request body over the active project's
  `shinttools.config.json` with no `api_key`, no tier check and no CSRF
  defense; `CORSMiddleware` does not help here, since CORS gates *reading*
  a cross-origin response, not sending the request. FastAPI parses a body
  as JSON when `Content-Type` is absent, and a `fetch()` whose body is a
  `Blob` with no `type` sends no `Content-Type` — a "simple request" that
  skips the preflight entirely. Any page loaded in the user's browser could
  therefore rewrite the config of a Core listening on `127.0.0.1:18200`.
  Impact was not limited to the Core: the UE5 client re-reads `core_host` /
  `core_port` from that same file on paid tiers, so redirecting it sends
  the full source content that `POST /validate/*` uploads to an
  attacker-controlled host; rewriting `dashboard_url` leaks the project's
  `st_…` Bearer key on the next dashboard sync. Fixed with a new
  `enforce_authenticated()` in `core/api/tier_guard.py` (same shape as
  `enforce_studio`, no tier floor) plus `enforce_same_origin()` in
  `core/api/middleware.py`, which rejects a request whose `Origin` header
  is present and outside the CORS allow-list. `ALLOWED_ORIGINS` is now a
  shared constant so the two cannot drift.
- **Origin check extended to `/dashboard/report`, `/assets/scan` and
  `/assets/fix`.** Same missing-CSRF-defense pattern. These are called by
  the shipping plugin on every tier — including Free, which has no key — so
  they get `enforce_same_origin` only; requiring `api_key` there would have
  broken real clients. `POST /assets/unity/scan` has the same shape and is
  deliberately left for a follow-up.
- **Path traversal in the profile loaders (Medium).**
  `load_profile()` (`core/modules/lod_auditor/config/__init__.py`) and
  `load_platform_profile()`
  (`core/modules/predictive/cost_model/platform_profiles.py`) interpolated
  a client-supplied name straight into the YAML path
  (`thresholds_{name}.yaml` / `platform_{name}.yaml`) without checking it
  against the allow-list those modules already expose. Predictive made it
  worse by returning the parsed profile verbatim in the response
  (`platform_profile=profile.model_dump()`), so any reachable `*.yaml`
  matching the `PlatformProfile` schema could be read back over HTTP, and
  the silent fallback to the default profile doubled as a file-existence
  oracle. Both now validate against `available_profiles()` /
  `available_platform_profiles()` and raise, and the LOD/Predictive routes
  translate that into a `400` listing the valid profiles.

Regression tests: `core/tests/test_config.py` (4 new, covering the
no-`Content-Type` bypass and the Origin check),
`core/modules/lod_auditor/tests/test_profile_config.py` (new), and 2 new
cases in `core/modules/predictive/tests/test_platform_profiles.py` — one
asserting `../../../../etc/passwd` is rejected. Note that
`test_unknown_profile_falls_back_to_default` previously *asserted the
vulnerable behaviour* and has been rewritten to require the rejection.

## [2.17.8] — 2026-08-19

### Fixed

- **Predictive Profiler:** `POST /predict/analyze` ran the analysis
  synchronously inline in the async route handler, stalling the shared
  asyncio event loop for the whole duration of a large analysis (measured:
  a 20,000-asset one-shot analyze spiked concurrent `/health` latency from
  ~3 ms to 1.6+ s on a live Core). Wrapped both the one-shot and session
  paths in `asyncio.to_thread`, matching the existing pattern in
  `lod_audit.py`'s LLM enrichment and `explain_finding.py`. Regression
  test: `core/tests/test_predictive.py::TestAnalyze::
  test_analyze_does_not_block_the_event_loop`. See
  `docs/predictive/BENCHMARK_2026-08-19.md` §3 for the measured before/after
  and the known residual limitation (CPython's GIL still causes tail
  latency under very large — 15k+ asset — analyses; full fix needs a
  process pool, out of scope for this pass).

### Added

- `core/tests/performance/bench_predictive.py` — Predictive Profiler
  benchmark (HTTP end-to-end + direct-import per-layer isolation), same
  house style as `bench_core.py`/`bench_assistant.py`.
- `docs/predictive/BENCHMARK_2026-08-19.md` — measured latency/memory
  figures across project scales (100–51,200 assets), baseline test status,
  and the event-loop bug writeup above.
