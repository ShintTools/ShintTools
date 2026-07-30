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
| Material | `blend_mode`, `two_sided` | plus `clear_usage_flags`, `set_usage_flags` |

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

---

## 5. Rules abstain on data they were not given

A rule that needs a field the client does not send now returns nothing rather
than assuming a default. The concrete case: `srgb` is absent from the Unity
collector's payload, and defaulting it to `true` made LT004 fire on **every**
Normal/Mask/HDR/Data texture in a Unity project — an entire engine's worth of
false positives. LT004 now abstains unless `srgb` is present.

---

## 6. Engine consistency

Given the same asset, Unity and Unreal receive identical memory figures,
identical savings and identical rule outcomes. The only permitted differences
are:

- **Engine-specific rules** — e.g. LT010 (texture LOD groups) is a UE5 concept
  and abstains on Unity.
- **`recommended` vocabulary and breadth** — per the table in §1.
- **Message copy** — wording is tailored per engine; the numbers are not.
