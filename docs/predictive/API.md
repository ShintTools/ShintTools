# Predictive Profiler — API Contract v1.0 (FROZEN)

Contract for the `/predict/*` surface of the ShintTools Core. This is the
document the Unity and UE5 clients build against. **v1.0 is frozen as of
Core 2.9.0** — fields may be *added* (always optional, always with safe
defaults), never renamed or removed within v1. Breaking changes bump
`schema_version`.

Every JSON example in this document is validated against the Pydantic models
in `core/modules/predictive/schema.py` by
`core/modules/predictive/tests/test_contract_doc.py` — if the doc and the
code disagree, CI fails.

- Base URL: the local Core container, `http://localhost:18200`
- Auth: `api_key` field in every request body (query param on GET)
- Tier: **Studio/Enterprise only.** Any lower tier gets `403` with
  `detail.required_tier = "studio"`. The whole surface answers 404 on the
  free image (the module is physically absent from it).
- `schema_version`: `"1.0"` in every request and response.

## The Prediction band

Every number the module emits is a band — never a bare scalar:

<!-- validate: Prediction -->
```json
{
  "expected": 0.35,
  "min": 0.05,
  "max": 1.2,
  "unit": "ms_frame",
  "confidence": "medium",
  "basis": "O(N) world iteration every frame; 0.2-1.4 ms measured with 5k actors on reference HW"
}
```

- `unit`: `ms_frame` | `mb` | `mb_min` (GC pressure) | `s` (load) | `min` (package time)
- `confidence`: `high` = deterministic math (block-compressed VRAM is exact);
  `medium` = calibrated pattern (see `calibration_version`); `low` =
  uncalibrated heuristic, wide band on purpose.
- `basis`: one human sentence explaining the figure. Render it in detail views.
- All `ms_frame` figures are relative to the reference hardware named in the
  platform profile. Aggregated maxima are upper bounds (correlation between
  items is not modelled).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/predict/profiles` | Platform budget profiles |
| POST | `/predict/session/start` | Open a batched-ingest session |
| POST | `/predict/session/ingest` | Append one batch (`assets` \| `scene` \| `code` \| `config`) |
| POST | `/predict/analyze` | Produce a `PredictiveReport` (session or one-shot) |
| POST | `/predict/simulate` | Impact Simulator over a cached report |

## Session flow (recommended for real projects)

Chunk assets at **150 per ingest** (the same batch size the LOD audit uses).
Sessions expire after 6 h; reports are cached for 24 h.

<!-- validate: SessionStartRequest -->
```json
{
  "api_key": "st_xxx",
  "engine": "Unity",
  "project_name": "MyGame",
  "platform_profile": "mobile_30",
  "schema_version": "1.0"
}
```

→ `{"session_id": "ps-3f9c01ab77de", "schema_version": "1.0"}`

<!-- validate: IngestRequest -->
```json
{
  "api_key": "st_xxx",
  "session_id": "ps-3f9c01ab77de",
  "kind": "assets",
  "payload": {
    "assets": [
      {
        "asset_path": "Assets/Textures/T_Rock.png",
        "asset_type": "Texture2D",
        "usage": "BaseColor",
        "width": 4096,
        "height": 4096,
        "compression": "ASTC_6x6",
        "mips_enabled": true,
        "streaming": true,
        "lod_group": "World",
        "size_kb": 9707
      }
    ]
  }
}
```

→ `{"session_id": "...", "kind": "assets", "accepted": 1, "total_ingested": {"assets": 1, "scenes": 0, "code_issues": 0, "config": 0}}`

Ingest `kind` → payload key: `assets` → `assets[]` (same shapes as
`/assets/lod/audit` — reuse the collector you already have; include
`size_kb` = measured runtime memory so unmapped formats price exactly);
`scene` → `scenes[]`; `code` → `issues[]` (your `/validate/*` output,
optionally + `occurrence_context`); `config` → `config{}`.

Then `POST /predict/analyze` with just `{"api_key": "...", "session_id": "..."}`.

### Scene digest (the `scene` kind)

UE5 fills the actor/Blueprint fields, Unity the script/GameObject fields —
leave the other engine's fields out, absent data abstains rather than
guessing:

<!-- validate: SceneDigest -->
```json
{
  "scene_name": "MainScene",
  "game_object_count": 3200,
  "update_scripts": 240,
  "fixed_update_scripts": 40,
  "lights": [
    {"type": "Point", "mobility": "Realtime", "casts_shadows": true}
  ],
  "particle_systems": [
    {"path": "PS_Rain", "sim_target": "CPU", "emitter_count": 3,
     "instance_count_in_scene": 2}
  ]
}
```

Light `mobility`: UE5 `Static|Stationary|Movable`, Unity `Baked|Mixed|Realtime`.
Static/Baked lights are free at runtime and are not billed.

### Code issues (the `code` kind)

<!-- validate: CodeIssueContext -->
```json
{"in_tick": true, "loop_depth": 2, "call_count_estimate": 1}
```

Attach that as `occurrence_context` on any issue you forward and the cost
scales with it. Issues whose rule has no cost entry are **counted, never
priced** — see `stats.code_issues_uncosted`.

## One-shot analyze (small projects, demos, tests)

<!-- validate: AnalyzeRequest -->
```json
{
  "api_key": "st_xxx",
  "engine": "Unity",
  "project_name": "MyGame",
  "platform_profile": "mobile_30",
  "schema_version": "1.0",
  "assets": [
    {
      "asset_path": "Assets/Textures/T_Rock.png",
      "asset_type": "Texture2D",
      "usage": "BaseColor",
      "width": 4096,
      "height": 4096,
      "compression": "ASTC_6x6",
      "mips_enabled": true,
      "streaming": true,
      "lod_group": "World",
      "size_kb": 9707
    }
  ],
  "scenes": [
    {
      "scene_name": "MainScene",
      "update_scripts": 240,
      "lights": [
        {"type": "Point", "mobility": "Realtime", "casts_shadows": true}
      ]
    }
  ],
  "code_issues": [
    {
      "rule_id": "CSP001",
      "rule_name": "LINQ operator in Update",
      "file": "Assets/Scripts/Spawner.cs",
      "line": 17,
      "severity": "warning"
    }
  ],
  "config": {}
}
```

## The report

Real (trimmed) response for the request above. `cost_items` is the full
list; `top_issues` is the ranked head of it. **Keep your copy of the report:
it is the simulator's input.**

<!-- validate: PredictiveReport -->
```json
{
  "schema_version": "1.0",
  "report_id": "pr-e2db0fa3a5a7",
  "generated_at": "2026-07-22T16:04:16+00:00",
  "engine": "Unity",
  "project_name": "MyGame",
  "platform_profile": {
    "profile": "mobile_30",
    "display_name": "Mobile — 30 fps (mid-tier reference)",
    "target_fps": 30,
    "frame_budget_ms": 33.3,
    "cpu_budget_ms": 18.0,
    "gpu_budget_ms": 22.0,
    "vram_budget_mb": 2048,
    "ram_budget_mb": 3072,
    "reference_hw": "Uncalibrated — scaled from desktop_60 baseline",
    "hw_scale_factor": 3.5
  },
  "calibration_version": "2026.07-uncalibrated-r1",
  "disclaimer": "Static estimate relative to reference hardware. Bands are honest uncertainty, not decoration.",
  "scores": {
    "cpu_risk": {"value": 10, "drivers": ["ci-0003", "ci-0002"]},
    "gpu_risk": {"value": 3, "drivers": ["ci-0001"]},
    "memory_risk": {"value": 0, "drivers": ["ci-0000"]},
    "build_health": {"value": 100, "drivers": []},
    "overall_project_health": 92
  },
  "frame_budget": {
    "cpu": {
      "budget_ms": 18.0,
      "predicted": {"expected": 1.54, "min": 0.46, "max": 5.76,
                    "unit": "ms_frame", "confidence": "medium",
                    "basis": "code patterns + scene dispatch"},
      "breakdown": [
        {"label": "Code patterns", "expected_ms": 0.68},
        {"label": "Scene dispatch", "expected_ms": 0.86}
      ]
    },
    "gpu": {
      "budget_ms": 22.0,
      "predicted": {"expected": 0.6, "min": 0.2, "max": 1.8,
                    "unit": "ms_frame", "confidence": "low",
                    "basis": "Σ dynamic lights + GPU particles across 1 scenes"},
      "breakdown": [
        {"label": "Dynamic lights + GPU particles", "expected_ms": 0.6}
      ]
    }
  },
  "memory": {
    "vram": {
      "budget_mb": 2048,
      "predicted": {"expected": 9.48, "min": 9.48, "max": 9.48, "unit": "mb",
                    "confidence": "high",
                    "basis": "Σ exact GPU payload of 1 priced assets"}
    },
    "ram": {"budget_mb": 3072, "predicted": null},
    "gc_pressure": {"expected": 3.0, "min": 0.5, "max": 12.0,
                    "unit": "mb_min", "confidence": "medium",
                    "basis": "Σ 1 GC-pressure patterns"}
  },
  "build": {
    "size_mb": {"expected": 8.06, "min": 6.16, "max": 9.48, "unit": "mb",
                "confidence": "medium",
                "basis": "Σ cooked-size bands of 1 priced assets"},
    "package_time_min": null,
    "cold_load_s": null
  },
  "top_issues": [
    {
      "item_id": "ci-0000",
      "layer": 1,
      "rank": 1,
      "severity": "warning",
      "title": "Texture over resolution budget — Assets/Textures/T_Rock.png",
      "rule_id": "LT003",
      "source": {"kind": "texture", "path": "Assets/Textures/T_Rock.png"},
      "impact": {
        "vram_mb": {"expected": 7.11, "min": 7.11, "max": 7.11, "unit": "mb",
                    "confidence": "high",
                    "basis": "LT003 saving from the LOD audit"}
      },
      "remediation": {
        "action": "4096×4096 texture exceeds the 2048 px max-size budget.",
        "recovery": {
          "vram_mb": {"expected": 7.11, "min": 7.11, "max": 7.11,
                      "unit": "mb", "confidence": "high",
                      "basis": "LT003 saving from the LOD audit"}
        },
        "auto_fixable": true
      }
    }
  ],
  "cost_items": [],
  "scene_summaries": [
    {
      "scene_name": "MainScene",
      "complexity_score": 30,
      "runtime_cost": {
        "cpu_ms_frame": {"expected": 0.86, "min": 0.36, "max": 2.06,
                         "unit": "ms_frame", "confidence": "medium",
                         "basis": "scene dispatch + particles (MainScene)"},
        "gpu_ms_frame": {"expected": 0.6, "min": 0.2, "max": 1.8,
                         "unit": "ms_frame", "confidence": "low",
                         "basis": "dynamic lights (MainScene)"}
      }
    }
  ],
  "stats": {
    "assets_analyzed": 1,
    "scenes_analyzed": 1,
    "code_issues_costed": 1,
    "code_issues_uncosted": 0
  }
}
```

Reading the report:

- `scores.*.drivers` — item_ids that contribute most to that score. Wire
  "click a gauge → filter the issue list" with them.
- Axes without data are **unscored** (`value: 0`, empty `drivers`) and are
  excluded from `overall_project_health` — "no data" is not "healthy".
- `stats.code_issues_uncosted` — issues that reached the report by severity
  but contributed 0 ms (no cost entry). Show coverage honestly.
- Every `CostItem.remediation.recovery` is what fixing it buys back — the
  simulator's currency.

## Impact Simulator

<!-- validate: SimulateRequest -->
```json
{
  "api_key": "st_xxx",
  "report_id": "pr-e2db0fa3a5a7",
  "selected_item_ids": ["ci-0000", "ci-0001"],
  "platform_profile": "",
  "cost_items": [],
  "schema_version": "1.0"
}
```

<!-- validate: SimulateResponse -->
```json
{
  "schema_version": "1.0",
  "report_id": "pr-e2db0fa3a5a7",
  "selected_count": 2,
  "deltas": {
    "vram_mb": {"expected": -7.11, "min": -7.11, "max": -7.11, "unit": "mb",
                "confidence": "high",
                "basis": "Σ recovery of 2 selected fixes"},
    "gpu_ms_frame": {"expected": -0.54, "min": -0.18, "max": -1.62,
                     "unit": "ms_frame", "confidence": "low",
                     "basis": "Σ recovery of 2 selected fixes"}
  },
  "scores_before": {
    "cpu_risk": {"value": 10, "drivers": ["ci-0003"]},
    "gpu_risk": {"value": 3, "drivers": ["ci-0001"]},
    "memory_risk": {"value": 0, "drivers": ["ci-0000"]},
    "build_health": {"value": 100, "drivers": []},
    "overall_project_health": 92
  },
  "scores_after": {
    "cpu_risk": {"value": 10, "drivers": ["ci-0003"]},
    "gpu_risk": {"value": 0, "drivers": []},
    "memory_risk": {"value": 0, "drivers": []},
    "build_health": {"value": 100, "drivers": []},
    "overall_project_health": 93
  },
  "recommendations": [
    {"item_id": "ci-0003",
     "reason": "Largest remaining recovery: +0.29 ms (cpu_ms_frame)",
     "auto_fixable": false}
  ]
}
```

- Deltas are negative Predictions (savings), per dimension, summed over the
  selection. Debounce UI toggles (~300 ms) — the endpoint is cheap but not free.
- `platform_profile` set to a different profile answers "what if I port
  this?": **both** `scores_before` and `scores_after` are recomputed against
  the new platform's budgets.
- **Stateless fallback**: if the cached report expired (404 semantics below),
  resend with your kept `cost_items` inline — deltas and recommendations
  still work; before/after scores need the report's aggregate totals and
  stay at defaults.

## Errors

| Status | When | Body shape |
|---|---|---|
| 403 | tier below Studio | `detail: {error, current_tier, required_tier, reason?, message?}` |
| 404 | unknown/expired `session_id` or `report_id` (with no inline `cost_items`) | `detail: {error, session_id \| report_id}` |
| 422 | invalid `kind` on ingest / malformed body | FastAPI validation shape or `detail: {error, valid_kinds}` |

## Compatibility rules

1. Clients MUST ignore unknown response fields (v1.x adds fields, never
   removes).
2. Absent optional request fields never change existing behaviour.
3. `calibration_version` identifies the cost tables that produced a report —
   display it; comparisons across different calibration versions are not
   apples-to-apples.
4. Reports/sessions are cache, not storage: hold your own copy of a report
   if you need it past 24 h.
