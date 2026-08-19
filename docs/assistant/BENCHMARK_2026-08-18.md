# AI Assistant — Benchmark Results (2026-08-18)

Measured on Core 2.17.5 and 2.17.7, plus the request path the Unreal
client actually uses. All figures are from this machine; treat them as
this hardware's numbers, not universal ones.

**Bench box:** AMD Ryzen 9 5900X (12C/24T), 16 GB, no GPU. Core in Docker,
portable llama.cpp build (`GGML_NATIVE=OFF`), Qwen2.5-Coder-1.5B-Q4_K_M,
12 inference threads, `n_ctx=4096`. Model resident: **1.17 GB peak RSS**.

**How to reproduce:**

```
python core/scripts/assistant_router_eval.py --llm        # per-layer
python core/scripts/assistant_composite_eval.py --llm     # classify() as production calls it
python core/tests/performance/bench_assistant.py --repeat 3
```

The router evals must run **inside the container** — their peak-RSS probe
uses `resource`, which does not exist on Windows.

---

## 1. Intent router accuracy — 74-pair golden set

### Per layer, in isolation

| Layer | 2.17.5 | 2.17.7 | p50 | p95 |
|---|---|---|---|---|
| Keywords (deterministic table) | 66/74 = **89.2%** | 66/74 = **89.2%** | <1 ms | <1 ms |
| LLM (grammar-constrained, 1.5B) | 31/74 = **41.9%** | 31/74 = **41.9%** | 434 ms | 1147 ms |

Identical across versions, including the confusion matrix — which is the
regression check this comparison existed for. 2.17.7 removed bare
`naming`/`lod` as module aliases, and the golden set's module-directed
pairs still resolve **10/10**. The alias cut did not go too deep.

### As production actually calls it — `classify()`

The per-layer numbers describe components, not behaviour: production calls
`classify()`, which tries explicit performative markers first, then the
LLM, then the keyword table.

| Configuration | Accuracy | p50 latency |
|---|---|---|
| `classify()` **with** the model loaded (paid image) | 53/74 = **71.6%** | 354 ms |
| `classify()` **without** it (free image, `modules/agent` stripped) | 66/74 = **89.2%** | <1 ms |

Which layer decided each turn, with the model loaded:

| Layer | Turns | Correct |
|---|---|---|
| `explicit` (performative markers) | 19 | **19/19 — 100%** |
| `llm+module` (deterministic correction over the model) | 11 | **11/11 — 100%** |
| `llm` (the model deciding alone) | 44 | 23/44 — **52%** |

**The deterministic layers are perfect — 30/30. Every error in the router
comes from the model.** Its failure mode is one-directional: it collapses
into `explain_finding` (summarize_module → explain_finding ×16,
define_rule ×7, simulate_change ×6, why_rule ×5). That is the intent whose
action answers with the fixed `_NEED_TARGET` string when it cannot resolve
a finding — so a misrouted turn does not merely answer the wrong question,
it produces the "I need to know which finding you mean" reply users have
been reporting.

**Caveat, stated plainly:** the keyword table and the golden set appear to
have been written together — 47 of the 55 keyword-decided turns matched a
needle, and every keyword miss fell through to `general_help` (no needle
matched at all). So 89.2% is likely optimistic for phrasings the table has
never seen, and the honest comparison needs a set of real user messages
collected independently of the table. **This benchmark does not by itself
justify deleting the LLM layer** — it justifies going and getting that
data, because the current evidence points that way hard enough that the
question is worth settling.

---

## 2. End-to-end, replaying the Unreal client's traffic

Against `POST /assistant/message/stream` with the client's own headers,
and bodies assembled the way `BuildAssistantBody` assembles them (empty
fields omitted, not blank). This is the endpoint that matters: the
blocking `SendAssistantMessage` has **zero callers** in the plugin.

Studio tier, 50 seeded findings, 3 timed iterations after a discarded
warm-up.

| Trigger | TTFT | p50 total | max | chunks |
|---|---|---|---|---|
| Chip "What can you do?" | 50 ms | 52 ms | 53 ms | 1 |
| Chip "Why this rule?" | 51 ms | 53 ms | 53 ms | 1 |
| Chip "Summarize this scan" | 61 ms | 64 ms | 65 ms | 1 |
| Free chat (router classifies) | 252 ms | 255 ms | 257 ms | 1 |
| Row Explain — LLM narration | **111 ms** | 2482 ms | 2485 ms | 49 |
| Row Explain — no context (degraded) | 50 ms | 52 ms | 54 ms | 1 |
| Free-tier 403 gate (transport floor) | — | 44 ms | — | — |

2.17.5 measured within noise of these (e.g. LLM narration 2347 ms vs
2482 ms; free chat 277 ms vs 255 ms). No performance regression, and none
expected — 2.17.7's changes were behavioural.

What these numbers say:

- **The transport floor is 44 ms.** A deterministic action completing in
  ~52 ms is doing roughly 8 ms of its own work; 7 of the 8 actions are
  pure Python and none of them are a cost centre.
- **Routing free text costs ~200 ms** on top of that — the whole gap
  between a chip (which declares its intent) and typed chat (which does
  not) is one model call.
- **TTFT is 111 ms even when the full reply takes 2.5 s.** The dock starts
  streaming almost immediately, so the LLM path reads as responsive
  despite costing ~23 tok/s of real generation. Reporting only total time
  would have badly mischaracterised the experience.
- **Headroom against the client's limits is enormous.** The UE5 stream
  timeout is 180 s and there is no retry logic anywhere; the slowest
  measured turn used 1.4% of that budget. Timeouts are not the risk here.

---

## 3. Behavioural verification of the 2.17.7 fixes

Live, against the running 2.17.7 build:

| Message | Intent | Outcome |
|---|---|---|
| "why does the naming rule NMU001 exist?" | `why_rule` | **Fixed** — rule-specific answer. Previously collapsed to the scan summary. |
| "how is the asset naming bot doing?" | `summarize_module` | Correct by design — this *is* a module question. |
| "what naming convention should I use for textures?" | `summarize_module` | **Still collapses.** |

The third case is a known, deliberate limitation rather than a defect:
`"naming convention"` was kept as a module alias because it names the
practice outright. It is worth revisiting — a question asking *what the
convention is* is not a request for scan totals — but changing it means
re-tuning aliases with the Spanish equivalents in step, so it was left
out of the 2.17.7 fix rather than done hastily.

---

## 4. What this suggests, in priority order

1. **Settle the router question with independent data.** Collect real user
   messages (the Unity and UE5 panels both log them) and re-run both evals
   against that set. If the gap holds outside the co-authored golden set,
   the model is actively degrading the router and the cheapest large win
   available is to stop consulting it for classification — keeping it for
   narration, which is what it is good at.
2. **The `explain_finding` collapse is the user-visible bug.** It is what
   produces the "I need to know which finding you mean" replies. Even
   without touching the router, `explain_finding` could refuse to be the
   fallback when nothing resolves — the two questions "which finding?" and
   "what is this module doing?" are distinguishable in Python.
3. **Nothing here is a performance problem.** Deterministic actions are
   ~8 ms of work, TTFT is ~100 ms, and the slowest turn uses under 2% of
   the client's timeout. Effort should go to correctness, not speed.
