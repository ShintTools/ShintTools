# ShintTools Assistant — Architecture

The native AI assistant: a conversational layer over the deterministic
Core, running entirely on the studio's own machines.

Introduced across Core 2.14.0 (M0–M6). This document explains the design
and the reasoning behind it; `API.md` is the wire contract for client
teams.

---

## 1. The central constraint, and the answer to it

`core/modules/agent/__init__.py` carries a decision made before this
module existed:

> Earlier sprints prototyped a tool-calling agent (orchestrator, tool
> registry, action parser, multi-domain prompt builder). That layer was
> removed when we confirmed a 1.3B-class model cannot reliably follow a
> JSON tool-calling protocol […] If we ever need an agentic flow again,
> build it from scratch with the right model size and contract for that
> specific task.

This module is that rebuild, with a contract chosen so the failure mode
cannot recur. Every turn is exactly three steps:

```
classify intent  ->  run ONE deterministic action  ->  LLM writes the prose
 (closed menu,        (Python; reads findings,          (over data already
  grammar-forced)      thresholds, cost tables)          computed)
```

Three properties follow, and they are the whole design:

**The model never chooses what to inspect.** Detection is what the ~325
existing deterministic rules already do. The assistant answers *about*
their output; it does not go looking.

**The model never invents arguments.** `rule_id`, `analysis_id`,
`asset_path` come from the request's context fields — what the user has
on screen. A misclassification can pick the wrong *action*; it can never
point an action at a target nobody selected.

**Off-menu answers are structurally impossible, not discouraged.** The
intent enum is compiled to a GBNF grammar and passed to
`llama_cpp.LlamaGrammar`, so tokens outside the menu are never
candidates during decoding. This is the specific mechanism the old
prototype lacked: it asked for a protocol and hoped.

There is no ReAct loop. The orchestrator is Python with conversation
state in Mongo; the "agency" is the action catalog, the same way the LOD
Auditor's is its rule registry.

---

## 2. Components

```
core/modules/assistant/
  tiers.py            capability table (intents / memory / model per tier)
  intent_router.py    closed-menu classification, 3 layers
  conversation_store.py  conversations + turns
  memory_store.py     facts, settings, summaries, compaction
  fact_extractor.py   NL -> proposed fact (deterministic)
  decision_monitor.py fact <-> finding contradiction detector
  rule_templates.py   Tier A: parameterized deterministic checks
  rule_compiler.py    NL rule -> template or LLM tier
  rule_store.py       studio_rules + eval cache
  rule_runner.py      scan-side evaluation
  model_profile.py    light / advanced selection + resource guards
  actions/            one module per intent
  eval/golden_intents.yaml

core/api/routes/assistant.py   the HTTP surface
```

Reused unchanged: `modules/agent/llm_backend.py` (singleton, lock, LoRA),
`modules/agent/explainer.py` and its prompt registry,
`modules/lod_auditor`, `modules/code_validator`,
`modules/predictive/cost_model` and `layers/layer5_simulator.py`.

### Intent routing, in three layers

1. **The UI declared it.** An "Explain" button knows its own intent; the
   router isn't consulted.
2. **Grammar-constrained LLM**, when a model is loaded.
3. **Bilingual keyword table** — the only layer on the free image, and
   the fallback whenever the model isn't up. Unmatched text lands on
   `general_help`; the fallback abstains rather than misroute.

`classify()` reports which layer answered, so the eval harness can score
them separately.

---

## 3. Memory

Local Mongo — the same instance the Core already uses. No vector store
in these milestones: the corpus is tens to hundreds of facts per studio,
where term overlap plus recency is enough. The documented threshold for
revisiting that is ~500 active facts per project *with demonstrated
retrieval failures*, and any replacement must be local (sqlite-vec,
persistent Chroma), never a hosted embedding service.

Collections: `assistant_conversations`, `assistant_memory_facts`,
`assistant_conversation_summaries`, `assistant_settings`.

### The confirmation rule

A fact's lifecycle is `proposed -> confirmed -> (superseded | retracted)`,
and **only `confirmed` facts are visible to anything that acts**:
`memory_store.confirmed_facts()` is the sole accessor used by actions and
by `decision_monitor`. There is no code path from "the model heard
something" to "the assistant acts on it" that does not pass through a
human clicking confirm. Two tests assert this from both directions.

Extraction is deliberately deterministic: the stored value is the user's
own sentence minus its preamble ("remember that…", "recuerda que…").
Nothing is paraphrased, so nothing can be quietly misheard.

### Compaction

Past 24 turns, older turns fold into a summary document and the last 8
stay verbatim. The digest is deterministic (intent + message opening per
user turn); an LLM-written summary can replace it later behind the same
contract.

### Forgetting

Facts have no TTL — memory is the product. Deletion is explicit:
retract a fact, mute memory per project (NDA silent mode), or
`DELETE /assistant/memory/project` to purge a closed project outright.

---

## 4. Studio rules

Replaces the ephemeral flow (rules travelling in every request body,
re-evaluated from scratch each scan, never persisted).

| Tier | What it is | Cost per scan |
|---|---|---|
| **A — template** | One of four audited, parameterized checks: `forbidden_api`, `naming_pattern`, `required_text`, `file_location`. Pure Python. | Zero. Cannot hallucinate. |
| **B — llm_evaluated** | Today's `custom_rule_checker` semantics, now persisted and versioned, behind a cache keyed `sha1(rule:version:file_hash)`. | One pass per *changed* file. |
| **C — ambiguous** | No template match and too vague to compile. | Flagged for human review; never guessed. |

`rule_compiler` is conservative by design: every required parameter must
extract unambiguously, or the rule falls to Tier B. A wrong Tier B rule
wastes some inference; a wrong Tier A rule produces confident false
findings.

**The LLM never writes executable code for a rule.** There is no
sandboxing in this Core, and generated code running against client
projects under NDA is not a risk worth the capability.

Rules follow the same confirmation contract as facts: a rule is `draft`
until the user activates it, and `rule_runner` only ever runs
`status=active AND confirmed_by_user`.

---

## 5. Model profiles

`light` (Qwen2.5-Coder-1.5B, the current model) and `advanced`
(7B-class, Studio-only) are **configuration over the existing runtime** —
same singleton, same `_LLAMA_LOCK`, same prompt registry, same LoRA
attach-per-request. Both are the same model family, so a profile swap is
never a prompt-format migration (asserted by test).

`advanced` passes three guards before loading: tier entitlement, the
`.gguf` actually present on disk (nothing auto-downloads), and real RAM
headroom read from `/proc/meminfo` — undeterminable memory counts as
"don't risk it". Every downgrade carries a reason code so the panel can
explain itself once instead of silently serving lower quality.

**A bigger model buys router precision on ambiguous phrasing and better
prose. It does not unlock free-form tool-calling** — the contract in §1
is identical for both profiles. Whether `advanced` becomes the Studio
default is decided by `scripts/assistant_router_eval.py` runs on
model-equipped hardware, against `eval/golden_intents.yaml` (61 labeled
pairs, all 8 intents, Spanish + English). CI enforces the anti-drift
properties only: every golden intent exists on the menu, every intent has
coverage, and the keyword layer never leaves the menu.

---

## 6. Tiers

The assistant is **not** gated as a block (unlike LOD Auditor and
Predictive Profiler, which 403 below Studio). Every tier reaches the
endpoint; capabilities differ.

| | Free | Indie | Studio / Enterprise |
|---|---|---|---|
| Intents | `explain_finding`, `general_help` | + `why_rule`, `summarize_module` | all 8 |
| Memory | none (in-process, dies with the session) | session | full, persistent |
| Studio rules | — | Tier B | Tier A + B |
| Model | `light` | `light` | `light`, `advanced` after the M4 gate |

Enterprise shares Studio's row by reference, so they cannot drift
(GH #37: Enterprise is a superset of Studio).

---

## 7. Offline and privacy

Nothing in this module makes a network call. The model is local, the
memory is local, the rules are local, the cost tables ship with the
image. A studio under NDA can mute memory per project or purge it
outright, and the Free path never persists anything at all.

Degradation is always honest: no model loaded, Mongo down, report
expired, rule uncosted, finding unresolvable — each has a specific
message saying what is missing. The assistant abstains; it does not
approximate.
