# Changelog — ShintTools Core

All notable changes to the Core engine are documented here. Format loosely
follows [Keep a Changelog](https://keepachangelog.com/); versions match
`core/api/version.py::CORE_VERSION`, bumped in lockstep with the `v*.*.*`
tag that publishes the image.

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
