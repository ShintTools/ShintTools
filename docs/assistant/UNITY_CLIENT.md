# Assistant — Unity Client Implementation Spec

Companion to [`API.md`](API.md). That document is the **wire contract** and
is engine-neutral; this one is the **implementation brief** for the Unity
plugin, written after shipping the UE5 client (M5) so the traps found there
do not have to be found twice.

Nothing here changes the contract. Where this document and `API.md`
disagree, `API.md` wins.

**Scope owner:** the Unity plugin developer. The Core team does not commit
to `ShintTools_Unity` — if something in the contract blocks the client, the
fix lands in the Core or arrives as a patch, never as a push to that repo.

---

## 1. What you are building

A single dockable `EditorWindow` — an assistant panel the user anchors
beside their work, not a modal and not a floating utility window. It has
three destinations:

| Destination | Purpose | Shown when |
|---|---|---|
| **Chat** | the conversation thread | always |
| **Memory** | confirm / reject / forget remembered facts | `capabilities.memory == "full"` |
| **Studio Rules** | activate / discard drafted rules | `capabilities.studio_rules != null` |

It replaces the per-finding "Explain" dialog, which answers one finding,
remembers nothing, and is destroyed on every click.

**Availability is not a tier gate.** Every plan reaches the endpoint. Free
gets a working assistant with two intents and no memory. Do not hide the
window behind a paid check — the *features* gate themselves, from the
server. This is the single most important rule in this document.

---

## 2. The three ideas that carry the integration

Read `API.md` §1 first. Restating them in Unity terms:

**`context_ref` is the whole grounding mechanism.** After any scan, keep
the `analysis_id` the response returned. Send it as `context_ref` and the
Core resolves the real findings server-side. The plugin never re-sends
project data to ask a question about it.

**Confirmation gates are the product, not friction.** Facts and rules
arrive as *proposals* and do nothing at all until the user accepts them
through the confirm endpoints. A client that never renders the confirm UI
ships an assistant that can never learn. Build those cards early — they
are not polish.

**Render `reply` verbatim.** Every response is either a real answer or a
specific statement of what is missing. Never synthesise a fallback string,
never map an error to your own wording. The server's text is always
suitable to display as-is.

---

## 3. Build order

Each step is independently demonstrable. Do not skip ahead — step 2 is what
makes the panel worth opening.

### Step 1 — Capabilities + the shell

`GET /assistant/capabilities?api_key=…` once when the window opens. Cache
it for the window's lifetime; re-fetch when the user changes the license
key. Drive every visible affordance from the result.

Never hardcode a tier table. If you find yourself writing
`if (tier == "studio")` in the client, the design has gone wrong — the
whole point is that the Core can widen a plan without a plugin release.

**Degrade to the Free floor on failure.** A Core too old to serve this
router returns 404. Treat that as `tier: "free"`, `intents:
["explain_finding", "general_help"]`, `memory: "none"` and keep the panel
usable, with a one-line notice. The UE5 client does exactly this.

*Demo:* the window opens on a Free key and shows Chat only; on a Studio key
Memory and Studio Rules appear too.

### Step 2 — Grounding: publish `analysis_id` after every scan

This is the step that makes the assistant feel native instead of bolted on.

Add a small process-wide holder — the UE5 equivalent is
`FShintAssistantContext`, roughly 60 lines — that any module can write to
and the panel reads:

```csharp
public static class ShintAssistantContext
{
    public static string AnalysisId  { get; private set; }
    public static string ModuleContext { get; private set; } // "code_validator", …
    public static string Summary     { get; private set; }   // "LOD Audit — 40 findings"

    public static void Publish(string analysisId, string module, string summary);
    public static void Clear();
}
```

Make it **static, not a field on the window**. The publisher (a results
view) and the consumer (a separate editor window) never hold a reference to
each other, and either can be closed while the other stays open.

Publish from the *completion handler* of each scan, never at request time,
so the panel only ever points at an analysis the server actually produced.
An empty `analysis_id` (older Core) must **clear** the context rather than
leave the previous scan's id in place — a stale grounding produces a
confident answer about the wrong scan, which is worse than no grounding.

Which responses carry it (contract §7, additive):
`/validate/unity/scan`, `/assets/unity/scan`, `/validate/unity-graphs`,
`/assets/lod/audit`.

> **Trap — batched scans.** Unity's `SCAN_BATCH` splits large projects
> across several POSTs. Each request would otherwise mint its own analysis,
> and the panel would ground in the **last batch only** while appearing to
> speak for the whole project. Echo the **first** batch's `analysis_id`
> back in the `analysis_id` field of every subsequent request in the chain;
> the Core then appends to that same analysis. This bit the UE5 LOD client
> and was fixed on both sides — do not reintroduce it. The first request
> sends the field empty or omits it.

*Demo:* run a scan, open the panel, and the context strip reads
"Viewing: Code Validator — 23 issues" with nothing typed.

### Step 3 — Chat, streaming

Use `POST /assistant/message/stream` for the turn. The event schema is the
one `/agent/explain/stream` already uses, so whatever SSE reader the Unity
plugin has for the explainer works unchanged.

Send `intent` whenever a button implies it — an "Explain" affordance sends
`explain_finding` rather than letting the router infer it from prose. It is
faster and cannot be misclassified. Leave `intent` empty only for free-text
input.

Three things the UI has to get right:

- **One live bubble, not one per chunk.** Append an assistant bubble when
  the request starts, then rewrite its text as tokens arrive.
- **Only `explain_finding` streams token-by-token.** Everything else
  answers from a table in microseconds and arrives as a single chunk. Do
  not animate that — a typing effect on an instant answer reads as fake.
- **Show `continued`.** When the response comes back `continued: true`,
  label the bubble ("following up on your last question"). Otherwise a
  two-word question that produces a detailed answer looks like a
  coincidence, and users stop trusting it.

**Guard against stale turns.** Give each send a monotonic token and drop
chunks and completions whose token is no longer current. Without this, a
slow answer to a superseded question overwrites the current one. The UE5
client carries the same token through both callbacks.

**403 and 404 are real status codes**, raised before the stream opens — not
error events inside a 200. Handle them the same way you would on the
blocking endpoint. On a 403, `detail.allowed_intents` lists what this tier
*can* run; turn that into a sentence rather than a dead button.

*Demo:* ask "why is this flagged?" with a scan in view, then ask "and why
does that matter?" with no context at all, and get a grounded answer marked
as a follow-up.

### Step 4 — Memory

Only when `capabilities.memory == "full"`.

`GET /assistant/memory` lists facts. Render only `proposed` and `confirmed`
— `superseded` and `retracted` are history the store keeps and the user
does not need to act on.

- `proposed` → **Confirm** / **Reject** buttons
- `confirmed` → **Forget**

Both hit `POST /assistant/memory/confirm` with `accept: true|false`. Re-read
the list afterwards rather than mutating local state, so the card shows what
the server actually recorded.

Also expose, somewhere unobtrusive:

- `POST /assistant/memory/mute` — NDA silent mode, per project
- `DELETE /assistant/memory/project` — purge a closed project

A fact's `value` is the user's own sentence with its preamble removed —
nothing is paraphrased. Display it as stored; do not clean it up.

*Demo:* tell the assistant a convention, confirm it, restart the editor,
open a new conversation, and it still knows.

### Step 5 — Studio rules

Only when `capabilities.studio_rules != null`.

`GET /assistant/rules` lists drafts and active rules. A `define_rule` turn
creates a **draft**, and the reply states how the compiler understood it —
a deterministic template with parameters, or an LLM-evaluated rule.

**Show that reading verbatim, next to the button.** What the user accepts
is exactly what will run, and a Tier A rule that was misunderstood produces
confident false findings across the whole project.

- `draft` → **Activate** / **Discard**
- `active` → **Deactivate**

To make active rules participate in a scan, send `studio_id` on the scan
request. Their findings arrive alongside the built-ins tagged
`source: "studio_rule"` — badge them so a team can tell its own conventions
from ShintTools' catalog.

### Step 6 — Decision check (optional, high value)

After a scan completes, `POST /assistant/decisions/check` with the
`context_ref`. The detector is deterministic and errs toward silence — an
empty array is the normal case and a failure here is never worth
interrupting the user over. Degrade to "no contradictions" quietly.

When it does return something, render `nudge` as-is.

---

## 4. Unity-specific notes

**Threading.** `UnityWebRequest` completion and SSE chunk callbacks must
reach the UI on the main thread before touching `EditorWindow` state; call
`Repaint()` after mutating the thread. The UE5 transport marshals SSE
chunks to the game thread for the same reason.

**Window lifetime.** An `EditorWindow` survives assembly reloads by
serializing its fields. Keep `conversationId` in a `[SerializeField]` so a
domain reload does not silently orphan the thread; on restore, call
`GET /assistant/conversations/{id}` to repaint the history rather than
starting over. Conversations expire after 12 h idle — a 404 there is normal
and means "start a new one by omitting the field", not an error to show.

**Do not persist facts or rules locally.** The Core is the store. Caching
them client-side reintroduces exactly the divergence the confirmation gate
exists to prevent.

**`engine: "unity"`** on every turn. It scopes studio rules and selects
engine-specific wording in the replies.

---

## 5. Definition of done

- [ ] Panel opens on a Free key and answers `general_help` and
      `explain_finding`, with no upsell blocking it
- [ ] Every destination's visibility comes from `capabilities`, with zero
      tier strings in client code
- [ ] Context strip labels the active analysis, with nothing typed
- [ ] A batched scan grounds in the **whole** scan, not the last batch
- [ ] A bare follow-up resolves, and is labelled as a follow-up
- [ ] A superseded turn's late answer is dropped, not rendered
- [ ] A proposed fact does nothing until confirmed in the panel
- [ ] A drafted rule shows the compiler's own reading before it can be
      activated
- [ ] A 403 explains what the current plan *can* do
- [ ] A Core without the assistant router degrades to the Free floor with a
      notice, not an empty window

---

## 6. Reference implementation

The UE5 client is the worked example for every point above:

| Concern | File |
|---|---|
| Transport + all endpoints | `Source/ShintTools/Private/Core/ShintCoreClient_Assistant.cpp` |
| Shared grounding holder | `Source/ShintTools/Public/Core/ShintAssistantContext.h` |
| Panel (chat, memory, rules) | `Source/ShintTools/Private/UI/Assistant/SShintAssistantPanel.cpp` |
| Batch id chaining | `Source/ShintTools/Private/Core/ShintCoreClient_Lod.cpp` (`SendLodAuditBatch`) |

Read it for the shape, not to port it line by line — the Slate and IMGUI
idioms have little in common, but the sequencing and the failure handling
transfer directly.
