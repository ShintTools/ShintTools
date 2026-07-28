# Predictive Profiler — Design Context (UE5 + Unity clients)

> Context document for design sessions (Claude / design tooling). It captures the
> **current ShintTools design system** in both editor clients and proposes visual
> directions for the Predictive Profiler dashboard. Hard rule: **both clients keep
> the existing style, design language and structure** — this is an extension of the
> ShintTools look, not a new one. Data semantics come from the frozen API contract
> (`docs/predictive/API.md` v1.0) and `ARCHITECTURE.md`.

---

## 1. What the product is

The Predictive Profiler **predicts** CPU / GPU / memory / build impact **before**
running or compiling, by static analysis. Unlike Unity Profiler / Unreal Insights
(which measure at runtime), it answers *"what will this cost?"* pre-run — and
*"what do I get back if I fix it?"* via an Impact Simulator. Studio-tier flagship
module. Target UX feel: **Datadog / Grafana-style dashboard inside the editor**.

Three core interactions:
1. **Scan → Report**: risk scores 0–100 per axis (CPU, GPU, Memory, Build) + overall.
2. **Explain**: every score is explained by its top drivers in ≤2 clicks.
3. **Simulate**: check issues → live "what-if" deltas + before/after scores.

---

## 2. Shared design language (both clients)

Dark "web-dashboard" aesthetic shared with the ShintTools Launcher. Pure-black
canvas, layered dark surfaces, white/grey text, **color is reserved for meaning**
(severity, status). No decorative color.

### Palette (identical hexes in both clients)

| Token | Hex | Use |
|---|---|---|
| Bg / canvas | `#000000` | window background, sidebar |
| Bg topbar / box (Unity) | `#0d0d0d` | top bar, Unity content panels |
| Bg card | `#161616` | cards, elevated surfaces |
| Bg hover / button | `#202020` | hover states, Unity buttons |
| Border subtle | `#2a2a2a` (UE5) / `#1a1a1a` (Unity) | card borders, row separators |
| Border strong | `#3a3a3a` | focused / active borders |
| Text primary | `#ffffff` | titles, values |
| Text muted | `#999999` | labels, secondary text |
| Text faint | `#3a3a3a` | disabled, captions |
| Severity critical / error | `#ef4444` | red |
| Severity high / warning | `#f97316` | orange |
| Severity medium | `#a1a1aa` | grey |
| Severity low / success | `#22c55e` | green |
| Accent blue | `#3b82f6` (dim `#2563eb`) | reserved: links, connection LED — **not** decorative |

Unity's frame-budget maqueta adds segment colors for module breakdown:
cyan `#44cfef`, blue `#3b82f6`, muted purple `#857cb4` (plus the severity hexes).
Treat these as the **categorical ramp for stacked bars** (dimension ≠ severity).

### Typography

- **UE5**: Bahnschrift (Windows system font; Roboto fallback). Scale: H1 24 (KPI
  values / section headers), H2 16 (card titles), Body 14, Small 12, Caption 10.
- **Unity**: default editor font, same scale intent: `.title_label` 16 bold,
  `.stat_label` 24 bold (KPI values), body 12–14. Labels muted `#999`, values white.
- Pattern: **small muted uppercase caption above a big white value** (KPI tile).

### Spacing & radii

- UE5: spacing scale 4 / 8 / 12 / 16 / 24 / 32; radii: 4 (controls), 8 (cards), 12 (modals).
- Unity: rhythm of 7 / 14 px; radius 2 px everywhere (flatter, sharper).
- Both: cards with generous inner padding (14–16 px), rows separated by 1 px subtle borders — no zebra striping.

### Existing structure (do not change)

Both clients share the same shell:
- **Left sidebar** (black): logo + version top, module nav buttons (text-only,
  muted → white on hover/selected, selected gets a `#202020`/`#0d0d0d` pill),
  Settings pinned bottom.
- **Top bar** (`#0d0d0d`, ~62 px): current panel title (16 bold), license button,
  update icon button, connection LED (ring icon tinted green/red).
- **Content area**: cards/boxes over the canvas.

Existing reusable components:
- UE5 Slate: `SShintCard` (title header + body), `SShintKpiTile` (caption / big
  value / optional trend, value color bindable), `SShintSeverityBadge` (severity
  string → color chip), `SShintTopBar`, `SShintSidebar`, `SShintEmptyState`,
  `SShintTreemap` (custom-paint precedent — proves bespoke drawing is available).
- Unity UIElements: `.box` (card), `.stat_label` KPI pattern, `.panel_button`,
  `.tab_button`, `.icon_button`, filterable column table (selection / element /
  module / type / cost columns), USS in `Assets/ShintTools/USSs/USS.uss`.

---

## 3. Data semantics the UI must honor

These are contract-level and non-negotiable — they *are* the product's honesty:

1. **Every number is a band, never a scalar**: `{min, expected, max, confidence,
   basis}`. Display pattern: `+0.9–1.8 ms · est. +1.4 ms`. Never show only the
   expected value without the band being reachable (inline or on hover).
2. **Confidence is 3-state** (`high` / `medium` / `low`) and must be visible as a
   pill/chip next to any number. Suggested encoding: filled pill (high), outlined
   (medium), dashed/faint (low). Color: neutral greys — confidence is *not* severity.
3. **Risk scores 0–100 per axis** with fixed color ramp by band: 0–20 green
   (`#22c55e`), 20–50 grey (`#a1a1aa`), 50–80 orange (`#f97316`), 80–100 red
   (`#ef4444`). Overall = same ramp.
4. **Transparency stats**: `code_issues_uncosted`, `calibration_version` and the
   HW disclaimer must be visible (footer level, muted — honest, not hidden).
5. **Drivers**: each score carries top-5 driver item ids — clicking a score
   filters the issue list to its drivers (the "≤2 clicks to explain" rule).
6. **Simulator**: selection (checkboxes) → `POST /predict/simulate` → deltas per
   dimension (always negative = recovered) + scores before/after + recommendations
   ("Largest remaining recovery: …").
7. **Platform profile** is the denominator of every budget — switching profile
   (desktop_60, mobile_30, vr_90, steamdeck_60…) re-frames everything ("porting
   scenario"). Uncalibrated profiles cap confidence at medium.

---

## 4. UE5 client — current state & target

- Predictive Profiler opens in an **independent dockable window** (second nomad
  tab, `Profiler` icon already registered) — NOT a sidebar section of the main
  panel. It keeps the ShintTools top bar styling but is its own dashboard.
- Everything is Slate; custom-painted widgets are fine (`SShintTreemap` precedent).
- Planned widgets: `SShintScoreGauge`, `SShintFrameBudgetBar`,
  `SShintTopIssuesList`, `SShintImpactSimulator`.

### Layout target (3 zones, top → bottom)

```
┌─────────────────────────────────────────────────────────────┐
│ TopBar: "Predictive Profiler"   [profile ▾]  [Scan]  ● LED │
├─────────────────────────────────────────────────────────────┤
│ Zone 1 — Scores                                             │
│ [CPU 62] [GPU 38] [Memory 81] [Build 24]   [OVERALL 31]     │
│ [Frame budget bar: CPU+GPU stacked vs 16.67 ms budget]      │
├─────────────────────────────────────────────────────────────┤
│ Zone 2 — Top Issues (name + cost, ranked by budget share)   │
│ ▢ Enemy.cpp:42          +0.9–1.8 ms · est +1.4  ↩ −0.9  [med]│
│ ▢ T_Rock_04.png         9.5 MB VRAM             ↩ −7.1  [high]│
│   T_Sky_Clean.png       3.2 MB VRAM                     [high]│
├─────────────────────────────────────────────────────────────┤
│ Zone 3 — Impact Simulator                                   │
│ 2 selected → CPU −1.4 ms · VRAM −7.1 MB   scores 31 → 54    │
│ "Largest remaining recovery: L_Main shadowed light (+0.29ms)"│
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Unity client — current state (dev maqueta, branch `develop`)

The Unity dev already has a working maqueta (`PredictiveProfilerPanelUXML.uxml`);
it lives as a **panel inside the main ShintTools window** (sidebar entry
"Predictive Profiler") — that placement stays. Current pieces:

- **Frame box** (`#161616` card): "FRAME **6ms**" + horizontal **stacked bar**
  (32 px tall, flat segments per module: Render red, Memory orange, Lighting
  green, Physics cyan, Audio blue, Shaders purple) + legend row with 16 px color
  squares (`Render: 1ms 10%`).
- **Stat boxes** row (hidden for now): TOTAL MEMORY / POTENTIAL MEMORY / SAVINGS
  (green values) — same KPI pattern as Asset Optimizer.
- **Scanner row**: big bold `Scan` button (flex-grow) + `profile` dropdown
  (desktop_60…steamdeck_60) + `platform` dropdown (Standalone/Android/iOS).
- **Table**: search field + module/type filter dropdowns + Export; columns
  Selection (checkbox) / ELEMENT (icon + path) / MODULE (colored label) /
  TYPE / COST (`0.1ms` + `10%`).

Design work for Unity = **evolve this maqueta** to the full report semantics
(scores, bands, confidence, simulator) without breaking its structure.

---

## 6. Visual ideas (apply to both clients, same language)

### 6.1 Score gauges (Zone 1)
- **Radial arc gauge** 0–100, 270° sweep, 6–8 px stroke, number centered in H1
  (24) white, axis caption below in muted caps ("CPU RISK"). Arc color = risk
  band ramp. Track in `#2a2a2a`.
- Overall gauge ~1.5× larger, right-aligned or centered as anchor.
- Unity fallback (no easy arc painting in USS): **horizontal meter bar** inside a
  `.box` — same caption/value pattern, 6 px bar under the number, radius 2.
- Hover: show drivers preview; click: filters Top Issues to that axis's drivers.
- Simulator animates value + arc from before → after (300 ms ease).

### 6.2 Frame budget bar
- Stacked horizontal bar = predicted spend vs budget line. Segments use the
  categorical ramp (per layer/module), **budget marker** = 1 px white line with
  caption ("16.67 ms · desktop_60").
- **Uncertainty**: extend each stack with a semi-transparent tail from `expected`
  to `max` (30% alpha of segment color) — the visual signature of the product:
  bars that admit a range. UE5: custom paint. Unity: extra flex segment at
  reduced opacity.
- Overrun: portion past the budget marker gets red tint + caption turns red.

### 6.3 Prediction band chip (the atom of the whole UI)
Everywhere a cost appears, render one consistent atom:
`[+0.9–1.8 ms · est. +1.4 ms] [●high]`
- Band text Small (12) muted; expected value Body (14) white bold.
- Confidence pill: caption size, radius-full; filled `#2a2a2a`+white text (high),
  outlined (medium), dashed border + faint text (low).
- Tooltip/detail shows `basis` ("BC7 block math, mip chain included").

### 6.4 Top issues list (Zone 2)
**Name + cost is the primary row — every priced item shows one, whether or
not it has a remediation.** Predictive prices; it doesn't diagnose. Severity
badges, rule descriptions and fix text are secondary and only render when
an item actually carries a `remediation` (`remediation: null` is the common
case, not an edge case — a clean 2K texture still costs VRAM and still gets
a row).
- Row: checkbox → `title` (white, Body — the entity's name/location:
  `T_Rock.png`, `Enemy.cpp:42`, never a validator sentence) → prediction
  chip right-aligned (the "band + confidence" atom from §6.3).
- Only when `remediation` is present: `SShintSeverityBadge` prefix + recovery
  chip in green (`↩ −16.0 MB`) appended after the cost chip. No remediation
  → no badge, no chip — the row still reads cleanly as "name: cost".
- Click row → detail panel/expando: `basis` line (always present — it's the
  cost's origin, not a diagnosis) +, only if `remediation` exists,
  `remediation.action` and a "Select for simulation" checkbox.
- Sort/rank comes from the server (budget-normalized cost magnitude) — an
  expensive unflagged asset legitimately outranks a small flagged issue;
  don't re-sort client-side by severity.
- Filters: dimension, "has remediation" toggle — not "severity" as the
  primary filter axis, since most rows won't have one.
- Keep 1 px `#2a2a2a`/`#161616` row separators (existing table language).

### 6.5 Impact Simulator (Zone 3)
- Sticky bottom card (UE5) / bottom `.box` (Unity) that activates when ≥1
  item **with a remediation** is checked (unfixable items aren't
  selectable — no recovery to simulate). Debounce 300 ms → simulate call.
- Content: **KPI tiles of deltas** (existing KpiTile: caption "CPU", value
  "−1.4 ms" in green) + before→after score pair per axis rendered as
  `31 → 54` with an arrow, after-value colored by its new band.
- Recommendations strip below: "Largest remaining recovery: …" rows (cost
  language, matching the report) with the remaining recovery chip —
  one-click "add to selection".
- Porting scenario: profile dropdown inside the simulator card ("Simulate on:
  mobile_30") — re-frames both sides; label makes the comparison explicit
  ("same project · mobile budgets").

### 6.6 Honesty footer
Muted caption row at the bottom of the report:
`calibration 2026.07-uncalibrated-r1 · 4 issues without cost model (not summed) · reference HW: Ryzen 7 5800X / RTX 3070`
Never hidden; part of the brand ("credible static profiler, not demo numbers").

### 6.7 States
- **Empty** (no scan yet): existing EmptyState pattern — muted icon + one-line
  promise ("Predict cost before you run") + primary Scan button.
- **Scanning**: Scan button → "Scanning…" disabled (Unity pattern already);
  progress as thin indeterminate bar under the top bar; batched ingest progress
  ("assets 300/450") in muted caption.
- **Degraded** (no scenes ingested): axis gauges without data render hollow with
  "—" and caption "no scene data" — axes without data never fake a score.

---

## 7. Per-engine constraints

| | UE5 (Slate) | Unity (UIElements/USS) |
|---|---|---|
| Custom drawing | Yes — OnPaint (Treemap precedent); arcs, uncertainty tails OK | Limited — prefer flex-based bars/meters; arcs need `generateVisualContent` (possible but keep optional) |
| Radius | 8 px cards, 4 px controls | 2 px everywhere (keep) |
| Rhythm | 4/8/12/16/24/32 | 7/14 px (keep) |
| Font | Bahnschrift 10–24 | Editor font, 12–24, bold for values |
| Placement | Independent dockable window (nomad tab) | Panel inside main window (sidebar entry) |
| Animation | Slate curves OK (300 ms, before→after) | USS transitions — keep subtle, opacity/width only |

Both clients read from the same report JSON (`API.md` v1.0) — visual vocabulary
must map 1:1 across engines so screenshots of either client are recognizably the
same product.
