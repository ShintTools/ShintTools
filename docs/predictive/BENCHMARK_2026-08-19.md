# Predictive Profiler — Benchmark Results (2026-08-19)

Measured on Core 2.17.7 (`shinttools-core:2.17.7`, `edition=paid`), plus a
throwaway rebuild of the same tag with the event-loop fix below, to verify
it end-to-end without touching the live container. All figures are from
this machine; treat them as this hardware's numbers, not universal ones.

**Bench box:** AMD Ryzen 9 5900X (12C/24T), ~32 GB RAM, no GPU, Docker
Desktop (WSL2 backend) on Windows. Core in Docker; Mongo in Docker
(`shinttools-mongo`, healthy). No LLM involved — the Predictive Profiler
is pure deterministic arithmetic, never a model call.

**How to reproduce:**

```
# HTTP, against a running Core (client's real request path)
python core/tests/performance/bench_predictive.py --url http://localhost:18200

# direct-import, per layer, isolated from HTTP/serialization overhead
python core/tests/performance/bench_predictive.py --layers
```

All numbers below discard one warm-up iteration per case (module import,
`lru_cache` fills for `rule_costs.yaml`/`platform_*.yaml`) and report
p50/p95 over the timed repeats, never a mean.

---

## 0. Baseline (before touching anything)

`pytest core/modules/predictive` — **128/128 passed**.
`pytest core/tests/test_predictive.py` — **19/19 passed**, but only with
`SHINT_CORE_EDITION=paid` set. Without it, all 16 HTTP-surface tests fail
with 404 — the free image doesn't register `/predict/*` at all
(`api/main.py`'s guarded import), so that env var is a hard prerequisite
for this test file locally, not a preexisting failure. Documented here so
the next person doesn't lose the same twenty minutes.

`test_csharp_performance_treesitter.py`'s 2 known `tree_sitter_languages`
failures are unrelated to this module and untouched.

No pre-existing predictive-specific failures. 148/148 after this task's
addition (one new regression test, below).

---

## 1. Layer isolation (direct import, no HTTP)

Assets alternate Texture2D (2048×2048 BC7, mips) / StaticMesh (15k verts) —
the same shape `lod_auditor` and the client both already produce.

### Layer 1 — `layer1_assets.analyze_assets` (includes the LOD-audit call)

| Assets | Time | Per-asset |
|---|---|---|
| 100 | 20.2 ms | 202 µs |
| 1,000 | 58.2 ms | 58 µs |
| 5,000 | 247.1 ms | 49 µs |
| 10,000 | 451.0 ms | 45 µs |

### Full orchestrator — `analyze_oneshot` (assets only, pure timing sweep)

| Assets | Time | Per-asset |
|---|---|---|
| 200 | 8.9 ms | 44.4 µs |
| 1,600 | 80.7 ms | 50.4 µs |
| 6,400 | 379.7 ms | 59.3 µs |
| 25,600 | 1,684.8 ms | 65.8 µs |

Per-asset cost drifts up ~50% from 200 to 25,600 assets (44→66 µs) — mildly
super-linear, not quadratic. This traces to `lod_auditor.audit_assets`'s
cross-asset rules (duplicate/dead-texture detection etc.), which is
`lod_auditor` territory, not `predictive`'s — noted here as a real,
non-pathological cost, not something to fix in this module. **No O(n²) or
worse anywhere in `predictive`'s own code** (`layer1_assets.py`,
`layer2_scene.py`, `layer3_code.py`, `_merge_by_location`, `sum_predictions`,
the orchestrator's sort/rank pass) — every pass over the item list is a
single `for`.

### Memory peak (`tracemalloc`, assets-only sweep)

Measured separately because `tracemalloc` itself adds real overhead (the
timings under it run ~4× slower than the pure-timing sweep above — that
overhead is `tracemalloc`'s bookkeeping, not a regression; only the
`peak_mb` figures are meaningful from this run):

| Assets | Time (profiled) | Peak traced memory |
|---|---|---|
| 10,000 | 2,580.9 ms | 53.3 MB |
| 25,600 | 7,116.4 ms | 142.6 MB |
| 51,200 | 14,733.1 ms | 283.1 MB |

Peak memory scales linearly with input (doubling assets ≈ doubles peak),
consistent with "one `CostItem` + one `Prediction` band per asset, held in
a list" — no accumulation bug, no leak, no quadratic blow-up. ~5.5 KB/asset
traced. A 50k-asset project (larger than any real Unreal/Unity project this
module is likely to see in one shot) tops out under 300 MB.

### Layer 3 — `code_scan.scan_code_files` (in-process C++ rule engine)

| Files | Time | Per-file |
|---|---|---|
| 10 | 24.2 ms | 2.42 ms |
| 50 | 105.1 ms | 2.10 ms |
| 200 | 499.6 ms | 2.50 ms |
| 500 | 1,262.0 ms | 2.52 ms |

Flat ~2.5 ms/file, linear — this is entirely the C++ Code Validator engine
running per file (calibrated against CitySample separately); Layer 3's own
costing loop on top is negligible.

---

## 2. HTTP end-to-end (client's real request path, live Core 2.17.7)

Against `POST /predict/analyze`, `sk_bench_studio` (Studio tier), 5 timed
iterations after 1 discarded warm-up.

| Case | p50 | p95 | Response size |
|---|---|---|---|
| `GET /predict/profiles` | 2.7 ms | 2.9 ms | — |
| `POST /predict/analyze` one-shot, 100 assets | 62.8 ms | 75.1 ms | 60 KB |
| `POST /predict/analyze` one-shot, 1,000 assets | 175.9 ms | 303.8 ms | 540 KB |
| `POST /predict/analyze` one-shot, 10,000 assets | 1,809.2 ms | 1,979.3 ms | 5.3 MB |

Batched session flow — the real client path for a project this size (150
assets/request, the LOD-audit precedent):

| Case | Ingest total (10 batches) | Analyze |
|---|---|---|
| 1,500 assets, session | 499.8 ms | 294.6 ms |

Session ingest + analyze correctness verified by hand over HTTP:
`total_ingested` counters match every batch exactly; `assets_analyzed` in
the final report matches the sum ingested; a duplicate `asset_path` sent
twice in one request collapses to one `CostItem` and `assets_analyzed: 1`
(the intentional de-dup in `layer1_assets.analyze_assets`, verified
working, not a bug). Edge cases all correct: unknown `session_id` → 404,
unknown `report_id` (and no inline `cost_items`) → 404, unknown ingest
`kind` → 422 with the valid-kinds list, empty one-shot → 200 with
`overall_project_health: 100` and empty stats (no data ≠ error).

---

## 3. Bug found and fixed: `/predict/analyze` blocked the event loop

**Symptom (measured):** while a 20,000-asset one-shot analyze was in
flight (~3.5 s of pure synchronous CPU work), concurrent `/health` requests
against the *same* live Core spiked from their normal ~3 ms to **1.6+ s**
— several requests queued up entirely behind the analyze call instead of
being served concurrently.

```
big analyze done: 200  3528 ms
/health pings during big analyze: n=49  p50=3.2 ms  max=1665.4 ms
```

**Cause:** `predict_analyze` in `core/api/routes/predictive.py` called
`analyze_oneshot()`/`analyze_session()` directly, inline, inside the `async
def` handler. Both are pure synchronous Python — no `await` anywhere in
the call graph — so for the whole duration of a large analysis, the single
asyncio event loop that also serves `/health`, `/validate/*`, the
assistant stream, etc. had nothing else to do. This is exactly the failure
mode `lod_audit.py` and `explain_finding.py` already guard against for
their own CPU-heavy work (`asyncio.to_thread`, with the "why" documented
inline in both) — `predictive.py` was the one route in that family that
hadn't been given the same treatment.

**Fix (`core/api/routes/predictive.py`):** wrapped both calls in
`asyncio.to_thread`:

```python
report = await asyncio.to_thread(analyze_session, session)
...
report = await asyncio.to_thread(analyze_oneshot, payload)
```

**Regression test:** `core/tests/test_predictive.py::TestAnalyze::
test_analyze_does_not_block_the_event_loop` — patches `analyze_oneshot` to
sleep 0.3 s, races it against a tick coroutine, and asserts several ticks
land *during* the sleep window (not just after). Verified both directions:
fails with 0 ticks landing when the `to_thread` wrap is reverted, passes
once restored.

**Honest limitation, not swept under the rug:** this fix removes the
*guaranteed, total* stall (every request literally queued behind the
analyze call) — proven by the regression test and by the moderate-scale
HTTP comparison below, where the fixed build served roughly **2× more**
concurrent `/health` requests during the analyze window than the unfixed
one (9–12 completions vs. 4–5, same 5,000-asset payload, 3 repeats each).
It does **not** eliminate tail latency spikes for genuinely large analyses
(15k+ assets, several seconds of CPU): CPython's GIL still serializes
bytecode execution between the worker thread and the event-loop thread, so
a rebuilt image with the fix still showed `/health` maxing out around
1.1–1.6 s under a 15–20k-asset analyze in repeated runs. Fully closing that
tail would mean moving the analysis to a process pool (`ProcessPoolExecutor`
or a separate worker), which is a real architectural change — out of scope
for this pass, and worth raising with the user before touching the shared
route-handling pattern other paid routes rely on. Recommendation #1 below.

---

## 4. Recommendations, in priority order

1. **If large (10k+ asset) one-shot/session analyses become common, move
   the CPU-bound analysis off-thread onto a process pool**, not just a
   worker thread — `asyncio.to_thread` (this fix, and the existing
   `lod_audit.py`/`explain_finding.py` pattern) helps but cannot fully
   solve GIL contention for pure-Python CPU work. This is a Core-wide
   architectural question (affects `lod_audit.py`'s own `audit_assets`
   call too, which isn't threaded at all today), not specific to
   Predictive — raise with the user before touching the shared pattern.
2. **`asset_costs.py`'s `compression_cfg` / `ProjectConfig.build.compression`
   is accepted end-to-end (ingested, stored in the session, forwarded into
   `AnalyzeRequest.config`) but never read by `analyze_oneshot` or
   `asset_build_mb`.** Confirmed this is *not* a regression — the docstring
   says outright "reserved for per-codec ratios once calibrated" — but it
   is worth flagging so M5 calibration work doesn't rediscover it from
   scratch: the plumbing already exists, only the ratio table is missing.
3. **Nothing else here is a performance problem.** Every layer is linear,
   memory is linear and modest even at 50k assets, and the one genuine
   latency bug found (event-loop blocking) is fixed and regression-tested.
   `GET /predict/profiles` and the session ingest/analyze round trip are
   both fast enough that they will never be the client's bottleneck — the
   10,000-asset one-shot case (1.8 s p50) is the only one worth a client
   staying on the batched session flow it already prefers.
