# Asset Optimizer — Output Contract

What the Core guarantees about `Finding` for Texture, Mesh and Material
assets, and what a client may rely on. Applies to `POST /assets/lod/audit`
and every consumer of `lod_auditor.audit_assets`.

Introduced in Core **2.12.0**. Additive: no field was removed or retyped, so
an older client keeps working — the values it receives simply become correct.

---

## 1. `recommended` contains only applicable properties

`recommended` is the set of properties the **calling engine's client can
actually apply**. Nothing else is serialized.

Rules build a richer internal dict to explain themselves (`vram_mb`,
`confidence`, `width`/`height`, advisory strings like `"<= 2048"`, prose
hints). None of that crosses the wire — a client would render it in the fix
diff and, for a typed DTO, try to deserialize an analysis number into a
property slot.

The whitelist is **per engine**, because the two clients genuinely differ:

| Category | Unity (`engine: "unity"`) | Unreal (`engine: "unreal"` / `"UE5"`) |
|---|---|---|
| Texture | `compression`, `max_texture_size`, `srgb`, `streaming`, `mips_enabled` | the same, plus `never_stream`, `lod_group`, `mip_gen` |
| Mesh | `import_uniform_scale` | plus `build_scale`, `recompute_normals`, `recompute_tangents`, `remove_degenerates`, `use_full_precision_uvs`, `generate_lightmap_uvs`, `nanite_enabled`, `complex_as_simple`, `has_simple_collision`, `fallback_percent`, `lod_count`, `screen_sizes`, `lods`, `triangle_ratio_band` |
| Material | `blend_mode`, `two_sided`, `enable_instancing`, `render_queue`, `double_sided_gi` | `blend_mode`, `two_sided`, `clear_usage_flags`, `set_usage_flags` |

The Unity column mirrors the `AssetOptimizer*ScannerOutputFileRecommendedData`
DTOs exactly. The Unreal column mirrors `FShintLodFixerRegistry`'s recognised
keys. Filtering both down to the smaller set would have silently disabled
working UE5 auto-fixes, so each engine receives precisely what it can act on.

**Vocabulary is translated, not dropped.** UE5's `never_stream` and Unity's
`streaming` express the same intent inverted; the Core emits whichever one the
target engine understands.

**Values are type-checked.** An advisory string (`"<= 2048"`, `">= 2"`,
`"weld in DCC"`) is never emitted as an applicable value — it would parse to
`0` in both clients and resize a texture to nothing.

### `auto_fixable` follows the payload

If a finding's recommendation filters down to empty, `auto_fixable` is
`false`. A client can trust that `auto_fixable == true` implies a non-empty,
applicable `recommended`, and never needs to defend against a "Fix" button
that resolves to a no-op.

---

## 2. Memory figures are physically coherent

Three guarantees on `estimated_saving`:

1. **Never negative.** `vram_mb`, `build_size_mb` and `shader_instructions`
   are `>= 0` on every finding.
2. **Never more than the asset holds.** The savings claimed against one asset
   never exceed that asset's actual resident memory, so a panel rendering
   `current − saved` as "potential memory" can never go negative.
3. **Coherent across combinations.** Overlapping optimisations are reconciled
   against their *joint* result rather than summed.

Worked example — a 4096×4096 uncompressed texture (85.33 MB):

| | claimed |
|---|---|
| resize → 2048 | 64 MB |
| compress → BC7 | 64 MB |
| naive sum | **128 MB** — more than the texture holds |
| capped at asset size | 85.33 MB — implies the texture becomes free |
| **reported (joint)** | **80 MB** — because 2048 + BC7 still costs 5.33 MB |

Findings that change memory without claiming a saving participate too:
enabling mips (LT002/LT009) adds ~33%, and the reported total reflects that
rather than contradicting our own advice.

**Removal dominates optimisation.** Deleting an unreferenced texture (LX001)
or a duplicate (LX005) frees all of it, so the removal finding carries the
asset's full cost and the resize/compress findings on that same asset report
`0` — they are alternative routes to a subset of the same memory, not
additional savings.

**The message quotes the same figure as `estimated_saving`.** Where a message
names a VRAM saving, it is the reconciled number, not the rule's isolated
estimate. A panel can render both without them contradicting each other.

**A saving is independent of whether the client can apply the fix.** Some
findings are advisory by nature — LT006's power-of-two resize is a DCC
round-trip, not an importer property — so they arrive with `recommended: {}`
and `auto_fixable: false` while still reporting the memory they would free.
Do not infer "no saving" from "no fix", or drop advisory rows from the memory
totals.

---

## 3. Sizes come from the resident texture, not the source file

Every size decision and every memory figure uses the dimensions the **engine
actually uploads**, i.e. the source resolution after the importer's size cap
(`max_texture_size`; `0` = uncapped in both engines). The cap clamps the long
edge and preserves aspect ratio.

Consequences a client can rely on:

- A 4096 source with `max_texture_size: 2048` is a **2048** texture. It is not
  reported as oversized, and it is priced as 2048 — previously it was read as
  ~4096, priced 4× too high, and told to "reduce to 2048" when it already was.
- `current.max_texture_size` reports the effective size, not the source.
- LT003/LT005/LT006/LT007/LT008/LT009/LT014 and LX001 all agree on this
  baseline.

Clients should keep sending the true **source** `width`/`height` plus
`max_texture_size`. The Core does the clamping; sending pre-clamped dimensions
would double-apply it.

---

## 4. Unpriceable textures are skipped entirely

A texture is analysed only when its memory can be priced honestly. Otherwise
it produces **no issues, no fixes, no recommendations, and contributes nothing
to the savings totals** — it is simply absent from the report.

Skipped:

- **Palette-indexed formats** (`Indexed8`, `PAL8`, `TSF_P8`, `Palette`, …).
  Their cost is the palette plus an index table, not `width × height × bpp`,
  so any figure derived the usual way is fiction.
- **Unmapped formats with no measurement.** Unity reports `Automatic` when a
  platform has no explicit override; with no `size_kb` the Core would have to
  assume RGBA8, an up-to-8× over-estimate that invented savings and a false
  "this texture is uncompressed" verdict.

Sending `size_kb` (the client's own measured size) makes an otherwise-unmapped
format analysable — the Core backs the real bytes-per-pixel out of it. This is
the recommended way to get `Automatic`-import textures covered.

**A measurement is authoritative and is reproduced exactly.** When `size_kb`
resolves the format, the Core's memory figure for that asset equals the
client's own — so a panel that shows its measured size next to the Core's
findings never displays two different numbers for one texture. The only
sanity check applied is that the measurement can be bytes-for-these-pixels at
all (0.1–32 B/px); the previous 4 B/px ceiling rejected legitimate readings
(RGBAHalf is 8 B/px, and a Read/Write-enabled texture's CPU copy counts too)
and silently substituted the model's figure.

The measured bytes-per-pixel is anchored at the texture's **current** size.
A proposed downsize keeps that density instead of re-deriving it, and a
proposed *format* is priced from the model — a measurement of BC1 says
nothing about what BC7 would cost.

---

## 5. Rules abstain on data they were not given

A rule that needs a field the client does not send now returns nothing rather
than assuming a default. The concrete case: `srgb` is absent from the Unity
collector's payload, and defaulting it to `true` made LT004 fire on **every**
Normal/Mask/HDR/Data texture in a Unity project — an entire engine's worth of
false positives. LT004 now abstains unless `srgb` is present.

This holds at the HTTP boundary too: an omitted optional boolean stays
omitted. It is not materialised as `false`. Send a field only when the
collector actually read it — sending `srgb: true` because the DTO needed
*something* re-arms exactly the false positives this rule avoids.

### Fields worth adding to a collector

Optional, and each one removes a specific class of wrong answer:

| Field | Effect when sent |
|---|---|
| `size_kb` | Makes `Automatic`/unmapped formats analysable and pins the Core's memory figure to the engine's own (§4). |
| `npot_scale` | Unity's `TextureImporter.npotScale`. Anything but `None` means the upload is already power-of-two, and LT006 abstains instead of reporting padding that does not exist. |
| `compression` as the **resident** format | Unity's `TextureImporterPlatformSettings.format` is `Automatic` whenever a platform has no explicit override, which tells the Core nothing about the payload. `Texture2D.format` (what the panel already displays in its Format column) lets the Core name and price the real format, and suppresses claims that only apply to uncompressed data. |

---

## 6. Target platform

Two platforms of the same project **should** report different numbers — a
mobile target usually carries a smaller size cap and an ASTC override, so the
same source texture is physically cheaper there. That difference must come
from the payload, not from the Core being unable to read it.

Two things make it work:

**Send the resident format per platform.** A texture's cost and its verdict
follow the format the selected platform actually uploads. Where the importer
reports no explicit override (Unity's `Automatic`, the Standalone default),
the Core classifies the payload from `size_kb` instead — 4 bytes per pixel is
uncompressed whatever the setting is named. Before that, a Standalone scan
reported **zero** savings on textures whose Android scan reported the full
compression win: same bytes, same texture, different answer.

**Send `profile: "mobile"` for mobile targets.** The profile selects the
threshold set — halved size budgets, tighter uncompressed limits — *and* the
format vocabulary. Recommendations are profile-driven because they have to
be: mobile GPUs cannot sample BC/DXT at all, so proposing BC7 there makes the
runtime decompress to RGBA32 and the "fix" multiplies the texture's memory by
eight. On the mobile profile the Core proposes ASTC, and abstains entirely for
HDR and Data textures rather than guess an encoding.

A client that pins `profile: "default"` while scanning an Android target gets
desktop budgets and desktop formats. Drive it from the same control that
selects the platform.

## 7. Engine consistency

Given the same asset, Unity and Unreal receive identical memory figures,
identical savings and identical rule outcomes. The only permitted differences
are:

- **Engine-specific rules** — e.g. LT010 (texture LOD groups) is a UE5 concept
  and abstains on Unity.
- **`recommended` vocabulary and breadth** — per the table in §1.
- **Message copy** — wording is tailored per engine; the numbers are not.
