# ShintTools Assistant — Client Contract v1.1

Wire contract for the UE5 and Unity plugins. Frozen at Core **2.14.0**;
additive changes only from here (new optional fields, new intents), and
any breaking change bumps this document's version.

**v1.1 (Core 2.15.0)** — all additive, nothing removed or renamed:
a streaming endpoint (§2.1), a `continued` flag on the response, and
`rule_id`/`asset_path` echoed on each turn. A v1.0 client keeps working
unchanged.

Base: the local Core (`http://127.0.0.1:18200` by default). Every route
ships in **both** editions — unlike `/agent/*`, the assistant is not
paid-image-only.

---

## 1. The model a client must hold

Three ideas carry the whole integration:

**`context_ref`** — the `analysis_id` a scan returned. The client hands
it back and the Core resolves the actual findings server-side. This is
how "explain this" works without the plugin re-sending project data, and
it is the only thing the client must remember after a scan.

**Confirmation gates.** Facts and rules arrive as *proposals*. They do
nothing until the user accepts them through the confirm endpoints. A
client that never renders the confirmation UI has an assistant that never
learns — this is deliberate, not a default to work around.

**Honest degradation.** Every reply is a real answer or a specific
statement of what's missing. Clients should render `reply` verbatim; they
never need to synthesise a fallback.

---

## 2. `POST /assistant/message`

One conversation turn.

```jsonc
{
  "api_key": "st_…",
  "message": "why is this flagged?",       // required
  "conversation_id": "ac-…",               // omit on the first turn
  "intent": "explain_finding",             // omit to let the router classify
  "context_ref": "an-…",                   // analysis_id from a scan
  "rule_id": "LT003",                      // selector within the analysis
  "asset_path": "/Game/Props/T_Barrel",
  "finding": { … },                        // or send the row inline
  "report_id": "pr-…",                     // simulate_change
  "selected_item_ids": ["ci-1", "ci-2"],   // simulate_change
  "platform_profile": "mobile_30",
  "studio_id": "acme",
  "project_id": "gameA",
  "module_context": "lod_audit",
  "engine": "unreal"
}
```

Response:

```jsonc
{
  "error": "",
  "conversation_id": "ac-7f2a91c4bd0e",
  "tier": "studio",
  "intent": "explain_finding",
  "continued": false,           // true -> intent inherited from the last turn
  "reply": {
    "turn_id": "at-…",
    "role": "assistant",
    "intent": "explain_finding",
    "raw_text": "…",
    "context_ref": "an-…",
    "rule_id": "LT003",         // the grounding this turn resolved to
    "asset_path": "/Game/Props/T_Barrel"
  }
}
```

**Follow-ups need no context.** Send the user's words and the
`conversation_id`; a short anaphoric message ("and why?", "más simple")
inherits the previous turn's intent and grounding server-side, and the
response comes back with `continued: true`. Show that in the UI — "following
up on LT003" — so a two-word question that gets a detailed answer doesn't
look like a coincidence. Sending `context_ref`/`rule_id` anyway is always
safe: an explicit value overrides what would have been inherited.

The echoed `rule_id`/`asset_path` let a reopened thread restore its own
context without the client having to remember what each turn was about.

**Send `intent` when you know it.** A button labelled "Explain" should
send `explain_finding` rather than making the router infer it from the
user's words — it is faster and cannot be misclassified. Leave it empty
only for free-text input.

**403** when the resolved tier may not run that intent. The detail lists
what it *can* run:

```jsonc
{
  "detail": {
    "error": "The 'simulate_change' capability requires a higher plan.",
    "current_tier": "free",
    "allowed_intents": ["explain_finding", "general_help"]
  }
}
```

This is a per-intent gate. The endpoint itself never 403s on tier — do
not hide the assistant from Free users.

**404** when `conversation_id` is unknown or expired (12 h idle). Start a
new one by omitting the field.

### The intents

| Intent | Needs | Tier |
|---|---|---|
| `explain_finding` | `finding` inline, or `context_ref` + `rule_id`/`asset_path` | Free |
| `general_help` | — | Free |
| `summarize_module` | a module named in `message`, or `module_context`, or `context_ref` | Indie |
| `why_rule` | `rule_id`, or a `finding`, or the id in the text | Indie |
| `simulate_change` | `report_id` + `selected_item_ids` | Studio |
| `define_rule` | the rule in `message` | Studio (Indie: Tier B only) |
| `remember_fact` | the fact in `message` | Studio |
| `recall_fact` | the question in `message` | Studio |

#### How a turn picks the analysis it answers about

Since Core 2.17.0 this is explicit, because getting it wrong is silent: the
assistant used to answer confidently about the wrong thing.

1. **A module named in `message` wins.** "How is the Code Validator doing?"
   is answered about the Code Validator even when `module_context` /
   `context_ref` point at a LOD audit. Asking about one module while looking
   at another's results is the normal case.
2. **Otherwise `module_context`** — the panel the user has open.
3. A `context_ref` is honoured unless step 1 named a *different* module, in
   which case it is dropped: it grounds a question nobody asked. With no
   usable `context_ref`, the module's most recent stored scan is used, so a
   module can be asked about with none of its panels open.
4. With a module but no scan at all, the reply describes what that module
   covers and how many rules it ships. It never answers "run a scan first".

`explain_finding` additionally **refuses to guess**. Given a `context_ref`
and no `rule_id`/`asset_path`, it does not fall back to the first row of the
analysis; unless the scan holds exactly one finding, it replies naming the
most frequent candidates and asks which one. Clients that have the row on
screen should keep sending it inline (or as `rule_id` + `asset_path`) — that
path is unchanged and never asks.

---

## 2.1 `POST /assistant/message/stream`

Identical inputs, gating and semantics to `POST /assistant/message` — pick
per call. Returns `text/event-stream`, one JSON object per `data:` line,
**the same schema `/agent/explain/stream` already uses**, so an existing SSE
parser works unchanged.

```jsonc
data: {"meta": {"conversation_id": "ac-…", "intent": "explain_finding",
                "tier": "studio", "continued": true}}
data: {"chunk": "The texture is "}
data: {"chunk": "4096 px on its long edge…"}
data: {"done": true, "full_text": "…", "cached": false,
       "source": "assistant", "degraded": false,
       "conversation_id": "ac-…", "intent": "explain_finding",
       "continued": true, "turn_id": "at-…"}
```

`meta` arrives first so the panel can label the thread before any text
appears. A parser that ignores unknown keys handles it correctly without
changes.

Notes that matter for the UI:

- **403 and 404 are real status codes**, raised before the stream opens —
  not error events inside a 200 response. Handle them as you would on the
  blocking endpoint.
- **Only `explain_finding` streams token-by-token.** Everything else
  answers from a table in microseconds and arrives as one chunk. Do not
  animate it.
- `{"error": …}` may appear when a generation dies mid-way. It is always
  preceded by a `chunk` carrying the grounded deterministic fallback and
  followed by `done` with `degraded: true` — so there is always something
  correct to display.
- The turn is persisted exactly as on the blocking path, so a follow-up
  after a streamed answer has its history.

## 3. `GET /assistant/capabilities?api_key=…`

Ask once at startup and drive the UI from it — never hardcode a tier
table client-side.

```jsonc
{
  "tier": "indie",
  "intents": ["explain_finding", "general_help", "summarize_module", "why_rule"],
  "memory": "session",              // "none" | "session" | "full"
  "model_profile": "light",
  "studio_rules": "llm_evaluated"   // null | "llm_evaluated" | "all"
}
```

`GET /assistant/conversations/{id}` returns the full thread (turns in
order) for restoring a panel after a restart.

---

## 4. Memory (`memory: "full"` only)

| Route | Purpose |
|---|---|
| `GET /assistant/memory?api_key&studio_id&project_id` | `{facts: [...], memory_muted: bool}` |
| `POST /assistant/memory/confirm` | `{fact_id, accept}` — accept promotes to `confirmed`, reject retracts |
| `POST /assistant/memory/mute` | `{studio_id, project_id, muted}` — NDA silent mode |
| `DELETE /assistant/memory/project?studio_id&project_id` | purge a closed project |

A fact:

```jsonc
{
  "fact_id": "af-…",
  "type": "decision",          // studio_fact | preference | decision
  "value": "all character meshes use Nanite",
  "status": "proposed",        // proposed | confirmed | superseded | retracted
  "source": {"conversation_id": "ac-…", "module": "lod_audit"},
  "created_at": 1754213…
}
```

**UI requirement:** when a `remember_fact` turn returns, render a
confirm/reject card in the thread. Until the user accepts, the fact is
invisible to every other part of the system.

---

## 5. Studio rules

| Route | Purpose |
|---|---|
| `GET /assistant/rules?api_key&studio_id&project_id` | list drafts + active |
| `POST /assistant/rules/confirm` | `{rule_id, accept}` — accept activates |

A `define_rule` turn creates a **draft** and the reply states how it was
understood (deterministic template + parameters, or LLM-evaluated). Show
that verbatim next to the confirm button: what the user accepts is
exactly what will run.

To make active rules participate in a scan, send `studio_id` on
`POST /validate/project` (optional, additive). Their findings arrive
alongside the built-ins, tagged:

```jsonc
{ "rule_id": "STUDIO", "rule_name": "…", "source": "studio_rule",
  "file": "Source/Foo.h", "line": 2, "severity": "warning", "message": "…" }
```

Badge `source == "studio_rule"` so a team can tell its own conventions
from ShintTools' catalog.

---

## 6. `POST /assistant/decisions/check`

Call after a scan completes to surface "you already decided this"
contradictions.

```jsonc
{ "api_key": "…", "studio_id": "acme", "project_id": "gameA",
  "context_ref": "an-…" }        // or "findings": [ … ] inline
```

```jsonc
{ "contradictions": [
    { "fact_id": "af-…",
      "fact_value": "all character meshes use Nanite",
      "rule_id": "LD012",
      "asset_path": "/Game/Characters/SM_Hero",
      "shared_terms": ["character", "meshes", "nanite"],
      "nudge": "Your team noted: \"all character meshes use Nanite\". /Game/Characters/SM_Hero was just flagged: …" }
] }
```

The detector is deterministic and errs toward silence — an empty array is
the normal case. Render `nudge` as-is.

---

## 7. Scan responses now carry `analysis_id`

Additive on `/validate/code`, `/validate/project`, `/validate/blueprints`,
the Unity graph scan, `/assets/scan` and `/assets/lod/audit`:

```jsonc
{ "summary": { … }, "issues": [ … ], "analysis_id": "an-…" }
```

Store it with the results view; pass it as `context_ref`. It is generated
even when the database is unreachable — the assistant will then say it
cannot resolve that analysis, which is the honest outcome.

### Batched scans must chain the id

Clients that split a large project across several requests (the UE5 and
Unity LOD collectors batch at 150 assets) **must** echo the first batch's
`analysis_id` back in the request body of every later batch:

```jsonc
{ "api_key": "…", "assets": [ … ], "analysis_id": "an-…" }   // batches 2..N
```

The Core then appends to that same analysis instead of minting a new one.
Omit the field on the first batch.

Without this each batch becomes its own analysis and the assistant can only
resolve the **last** one — while appearing to answer for the whole project.
Currently honoured by `/assets/lod/audit`; the other scan routes are
single-request and need nothing.

---

## 8. Notes for the Unity client

> A full implementation brief — build order, Unity-specific threading and
> window-lifetime notes, and the traps found while shipping the UE5 client —
> lives in [`UNITY_CLIENT.md`](UNITY_CLIENT.md). This section stays as the
> contract-level summary.

The contract is engine-neutral; `engine: "unity"` scopes studio rules and
selects engine-specific wording. Two implementation notes:

- The assistant surface is a **single anchored panel** (Copilot-Chat
  style) in the UE5 client, not a second window. Match the pattern if it
  suits Unity's docking, but nothing in this contract depends on it.
- Free tier gets a working assistant with two intents and no memory. Do
  not gate the panel behind a paid check — gate the *features* from
  `GET /assistant/capabilities`.
