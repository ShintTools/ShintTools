# Assistant — Memory + Studio Rules, Unity Client Spec

Companion to [`API.md`](API.md) (wire contract) and
[`UNITY_CLIENT.md`](UNITY_CLIENT.md) (full panel spec — steps 4 and 5
cover this same ground at a higher level). This document narrows the scope
to just **Memory** and **Studio Rules**, written to replicate the UE5
client's implementation exactly, section by section.

**Scope owner:** the Unity plugin developer. The Core team does not commit
to `ShintTools_Unity` — if the contract blocks the client, the fix lands
in the Core or arrives as a patch, never as a push to that repo.

---

## 1. The idea both features share

A `remember_fact` or `define_rule` turn never applies anything on its own.
It produces a **proposal** — a fact in `status: "proposed"` or a rule in
`status: "draft"` — and the reply says so in plain language. The proposal
sits inert until the user acts on it through a **confirm card** rendered
in the panel.

This is not UI polish. It is the entire safety mechanism: nothing the
assistant infers from conversation reaches project state without an
explicit accept. A client that never renders the confirm card ships an
assistant that can propose but never learn — worse than no memory at all,
because the user believes they confirmed something they never saw.

**Do not persist facts or rules locally.** The Core is the store. Caching
them client-side (a local JSON, `EditorPrefs`, anything) reintroduces the
exact divergence the confirmation gate exists to prevent — a team member
sees a stale "confirmed" state the server no longer has, or a rule the
server discarded still runs locally.

Both destinations gate on `capabilities`, fetched once from
`GET /assistant/capabilities?api_key=…`:

```csharp
bool ShowMemory = capabilities.HasPersistentMemory(); // memory == "full"
bool ShowRules  = capabilities.StudioRules.Count > 0;  // studio_rules != null
```

Never hardcode a tier check (`if (tier == "studio")`). The UE5 client's
rail (`SShintAssistantPanel.cpp:316-321`) hides the **destination itself**
when the capability is absent, rather than showing it disabled — an
upsell nag inside a working assistant reads as broken, not as a prompt to
upgrade.

Refresh both lists **on window focus and right after a turn returns**, not
on a timer:

```csharp
// After every streamed turn completes (SShintAssistantPanel.cpp:753-759)
if (response.Intent == "remember_fact") RefreshMemory();
if (response.Intent == "define_rule")   RefreshRules();
```

This is what makes a proposal appear in the confirm list the instant the
turn that created it finishes — no manual refresh, no polling.

---

## 2. Memory

Visible only when `capabilities.memory == "full"`.

### 2.1 Fetch

`GET /assistant/memory?api_key&studio_id&project_id` →

```jsonc
{ "facts": [ /* FShintAssistantFact[] */ ], "memory_muted": false }
```

A fact:

```jsonc
{
  "fact_id": "af-…",
  "type": "decision",        // studio_fact | preference | decision
  "value": "all character meshes use Nanite",
  "status": "proposed",      // proposed | confirmed | superseded | retracted
  "source": {"conversation_id": "ac-…", "module": "lod_audit"},
  "created_at": 1754213…
}
```

**Render only `proposed` and `confirmed`.** `superseded` and `retracted`
are history the store keeps for audit — the user never needs to act on
them, and listing them clutters the one list that matters. This is a
client-side filter; the endpoint returns all four states.

### 2.2 Card per status

| `status` | Actions shown |
|---|---|
| `proposed` | **Confirm**, **Reject** |
| `confirmed` | **Forget** |

Both call the same endpoint, `POST /assistant/memory/confirm`, with
`{fact_id, accept}` — `accept: true` on Confirm, `accept: false` on both
Reject and Forget (rejecting a proposal retracts it; forgetting a
confirmed fact also retracts it — same verb server-side).

```csharp
async void OnMemoryAction(string factId, bool accept)
{
    var result = await coreClient.ConfirmAssistantMemory(factId, accept);
    if (!result.Success) { ShowErrorToast("Could not update memory", result.ErrorMessage); return; }
    RefreshMemory(); // re-read from the server, never mutate the local card in place
}
```

Re-fetching instead of mutating local state (UE5:
`OnMemoryConfirmed` → `RefreshMemory()`, `SShintAssistantPanel.cpp:909-912`)
matters because the server is the only source of truth — if the confirm
call raced another client instance or a second machine on the same
studio license, the local optimistic update would show something the
server never recorded.

**Display `value` verbatim.** It is the user's own sentence with its
preamble stripped ("remember that…" removed, not paraphrased). Do not
title-case it, do not truncate with an ellipsis mid-sentence, do not
reformat it — what they said is what should appear in the card.

### 2.3 Mute and purge

Expose both, unobtrusively (a small menu or settings row, not the main
list — these are rare actions):

- `POST /assistant/memory/mute` — `{studio_id, project_id, muted}`. NDA
  silent mode: the assistant stops proposing facts for this project
  without disabling the rest of the assistant.
- `DELETE /assistant/memory/project?studio_id&project_id` — purges every
  fact tied to a closed project. Irreversible; confirm before sending.

### 2.4 Empty state

When `facts` is empty, show a one-line explainer rather than a blank
panel — something in the spirit of "Nothing remembered yet. Tell the
assistant a convention in chat and it will offer to remember it."

---

## 3. Studio rules

Visible only when `capabilities.studio_rules` is non-empty.

### 3.1 Fetch

`GET /assistant/rules?api_key&studio_id&project_id` → drafts and active
rules together, one list.

### 3.2 What a `define_rule` turn produces

The reply that creates the draft **states how the compiler understood the
request** — either a deterministic template with parameters, or an
LLM-evaluated rule (`tier: "template"` vs the LLM tier). This sentence is
not optional decoration: **show it verbatim, next to the confirm button**,
because what the user accepts by clicking Activate is exactly that
reading, and a Tier-A (template) rule that was misunderstood produces
confident false findings across the whole project the moment it goes
live — silently, since it runs on every future scan.

UE5's card layout (`AppendRuleConfirmCard`, `SShintAssistantPanel.cpp:942-1030`)
in order:
1. Rule name
2. Description, if present — the compiler's own reading, shown as body text
3. A status line: `"Template rule" | "LLM-evaluated rule"` + the current
   status (`draft` / `active`)
4. Actions, gated by status (below)

### 3.3 Actions by status

| `status` | Actions shown |
|---|---|
| `draft` | **Activate**, **Discard** |
| `active` | **Deactivate** |

All three call `POST /assistant/rules/confirm` with `{rule_id, accept}` —
`accept: true` for Activate, `accept: false` for Discard and Deactivate.

```csharp
async void OnRuleAction(string ruleId, bool accept)
{
    var result = await coreClient.ConfirmAssistantRule(ruleId, accept);
    if (!result.Success) { ShowErrorToast("Could not update the rule", result.ErrorMessage); return; }
    RefreshRules();
}
```

### 3.4 Wiring active rules into a scan

Send `studio_id` on the scan request (`POST /assets/unity/scan` and the
other Unity scan endpoints — additive field, optional). Active studio
rules then run alongside the built-in catalog and their findings come
back tagged:

```jsonc
{ "rule_id": "STUDIO", "rule_name": "…", "source": "studio_rule",
  "asset_path": "Assets/Foo.fbx", "severity": "warning", "message": "…" }
```

**Badge `source == "studio_rule"` in the results view**, distinct from
ShintTools' own catalog — a team needs to tell at a glance which findings
are their own convention versus the shipped rule set, because the two
have different owners when something looks wrong.

### 3.5 Empty state

When there are no rules yet, prompt with a concrete example rather than a
blank list — UE5 uses: *"No studio rules yet. Describe one in chat — for
example 'textures over 2K should be an error, not a warning.'"*

---

## 4. Unity-specific notes

**Threading.** Both refreshes are async `UnityWebRequest` calls; marshal
the response back to the main thread before touching `EditorWindow`
state, then call `Repaint()`. Same rule as the rest of the panel.

**Window lifetime.** Neither list needs to survive an assembly reload on
its own — both re-fetch from the server on `OnFocus`/`OnEnable`, so there
is nothing to serialize here beyond what the rest of the panel already
keeps (`conversationId`).

**`engine: "unity"`** on every turn that can create a rule or fact. It
scopes studio rules to this engine and affects wording in the compiler's
reading sentence.

---

## 5. Definition of done

- [ ] Memory and Studio Rules destinations are hidden entirely (not
      disabled) when `capabilities` says the plan lacks them
- [ ] A `remember_fact` turn's reply is followed, in the same session, by
      a new card in Memory without a manual refresh
- [ ] A `define_rule` turn's reply is followed by a new draft card in
      Studio Rules, showing the compiler's exact reading
- [ ] Confirm/Reject/Forget/Activate/Discard/Deactivate all re-fetch from
      the server rather than mutating the card in place
- [ ] `superseded` and `retracted` facts never appear in the list
- [ ] A fact's displayed text matches `value` exactly, no paraphrasing
- [ ] An active studio rule's findings in scan results are visibly badged
      `source: "studio_rule"`, distinct from the built-in catalog
- [ ] Mute and project-purge are reachable but not part of the main list
- [ ] Nothing about a fact or rule is cached outside the Core

---

## 6. Reference implementation (UE5)

| Concern | File |
|---|---|
| Memory view + confirm cards | `Source/ShintTools/Private/UI/Assistant/SShintAssistantPanel.cpp` — `BuildMemoryView`, `RefreshMemory`, `OnMemoryConfirmed` (lines ~763-914) |
| Rules view + confirm cards | same file — `BuildRulesView`, `AppendRuleConfirmCard`, `RefreshRules`, `OnRuleConfirmed` (lines ~916-1076) |
| Capability gating for both rails | same file — `IsViewAvailable` (lines ~316-321) |
| Post-turn auto-refresh | same file — the `Response.Intent == "remember_fact" / "define_rule"` branch (lines ~753-759) |
| Transport calls | `Source/ShintTools/Private/Core/ShintCoreClient_Assistant.cpp` — `GetAssistantMemory`, `ConfirmAssistantMemory`, `GetAssistantRules`, `ConfirmAssistantRule` |

Read it for the shape and the sequencing, not to port Slate idioms
line-by-line into IMGUI/UGUI.
