# Unity Material Collector — what to send, what to accept

Spec for the Unity client's Asset Optimizer → Materials tab. Companion to
`ASSET_OPTIMIZER_OUTPUT_CONTRACT.md`, which describes what the Core
guarantees about its side of the wire.

Everything here is **additive**. Nothing currently sent changes meaning, and
the plugin keeps working unmodified — it simply reaches more rules and can
apply more of them.

---

## Why the Materials tab is nearly empty today

`AssetOptimizerMaterialsScannerInputFileData` carries four fields:
`blend_mode`, `sampler_count`, `two_sided`, `shading_model`.

The material family has 34 rules (14 LM + 8 LR + 12 LS). With that payload,
**exactly one is reachable** — LM004, the sampler-count budget — and its
recommendation is an advisory threshold (`"<= 12"`), not a property, so it is
correctly filtered out and reports `auto_fixable: false`.

Net result: **one finding, zero fixes**, no matter how bad the project's
materials are. The limit is the payload, not the rule set.

The output side is equally narrow.
`AssetOptimizerMaterialsScannerOutputRecommendedData` declares `blend_mode`
and `two_sided`, so even a rule that produced an applicable property could
only ever deliver those two.

---

## 1. Output — accept the new recommendation keys

These already ship from the Core (2.13.0). Each maps to a property on
`UnityEngine.Material` that the editor can set directly; no shader work, no
reimport.

```csharp
[Serializable]
public class AssetOptimizerMaterialsScannerOutputRecommendedData
{
    public string blend_mode;
    public bool   two_sided;
    public bool   enable_instancing;   // material.enableInstancing
    public int    render_queue;        // material.renderQueue
    public bool   double_sided_gi;     // material.doubleSidedGI
}
```

Apply exactly as for the texture tab: read the key when present, set the
property, `EditorUtility.SetDirty`, save. A key the Core did not send is
absent from the JSON — never treat a default-constructed `false`/`0` as an
instruction.

> Note the JSON these arrive in only ever contains keys this engine can
> apply — the Core filters `recommended` per engine at the output boundary,
> and drops `auto_fixable` to `false` when nothing survives. A `Fix` button
> shown for `auto_fixable: true` is always a real, non-empty action.

---

## 2. Input — fields to add, in value order

### Tier 1 — `used_by_primitives`

```csharp
public int used_by_primitives;   // -1 = not computed
```

The number of `Renderer` components in the project that reference this
material. One `AssetDatabase` sweep, cached per scan.

Unlocks **six** rules on its own: LM015 (GPU instancing), LR002, LR004,
LR006, and the referencer-sensitivity of LM009/LR008. It is also what turns
LR006 (`two_sided → false`) from a guess into a defensible finding.

Send `-1` rather than `0` when the sweep did not run — `0` means "nothing
references this material", which is a different and actionable statement.

### Tier 1 — the GPU instancing pair

```csharp
public bool   gpu_instancing;            // material.enableInstancing
public string render_pipeline;           // "builtin" | "urp" | "hdrp"
public bool   srp_batcher_compatible;    // ShaderUtil.IsPassCompatibleWithSRPBatcher
```

Unlocks **LM015** (fixable) and **LM016**.

All three matter together, and the Core will abstain without them: under
URP/HDRP the SRP Batcher takes precedence over GPU instancing, so
recommending the flag on a batcher-compatible material would be a fix that
changes nothing. The Core only claims the win where it actually lands — the
Built-in pipeline, or a material the batcher cannot take.

### Tier 1 — the two cheap scalars

```csharp
public int  render_queue;        // material.renderQueue, -1 = from shader
public bool double_sided_gi;     // material.doubleSidedGI
```

Unlocks **LM017** and **LM018**, both fixable, both one property read.

### Tier 2 — `texture_samples`

```csharp
public TextureSample[] texture_samples;   // { texture, usage }
```

From the shader's texture property list
(`ShaderUtil.GetPropertyType == TexEnv`). Unlocks **LM002** — the same
texture bound to several slots of one material — which is auto-fixable and
frees real memory.

### Tier 2 — `shader_stats.variant_count`

```csharp
public ShaderStats shader_stats;   // { variant_count, ... }
```

`ShaderUtil.GetVariantCount(shader, usedBySceneOnly: false)`. Unlocks
**LS007**, and variant explosion is one of the top build-size and
shader-compilation problems in Unity projects specifically.

The remaining `shader_stats` members (`instruction_count`,
`texture_fetch_count`, `branch_count`, …) feed LS001–LS012. Send whatever
the pipeline can measure; each rule reads its own field and abstains when it
is absent.

### Tier 3 — `has_thin_geo_consumers`

```csharp
public bool has_thin_geo_consumers;
```

Whether any renderer using this material is foliage or thin geometry.
Without it LR006 reports the two-sided opaque cost but stays advisory:
clearing `two_sided` on foliage is a visual regression, so the Core refuses
to mark the fix safe on unknown data. With it, LR006 becomes fixable.

---

## 3. What will never apply on Unity

These rules describe Unreal machinery with no Unity counterpart, and the
Core now gates them on the engine rather than on whether the data happens to
be absent: **LM003** and **LM010** (Material Instances), **LM007**/**LM008**
(Material Layers), **LM009** (Runtime Virtual Texture), **LM012** (material
usage flags), **LR007** (World Position Offset / Nanite), **LR008** (Pixel
Depth Offset).

This gating is why `used_by_primitives` is safe to start sending: before it,
LM003 would have fired on Unity and told the user to convert a material into
an Unreal Material Instance.

---

## 4. Rules the Core adds for Unity (2.13.0)

| Rule | Fires when | Fix |
|---|---|---|
| **LM015** | GPU Instancing off on a material shared by ≥ 20 renderers (≥ 12 on the mobile profile), where the SRP Batcher does not already own the draw | `enable_instancing: true` |
| **LM016** | Shader is not SRP Batcher compatible under URP/HDRP | advisory — compatibility is decided by the shader's constant buffer, which no material property can change |
| **LM017** | `renderQueue` overridden outside the band its blend mode sorts in (opaque 2000–2449, cutout 2450–2999, transparent 3000+) | `render_queue: <canonical>` |
| **LM018** | Double Sided GI on for a single-sided material — the lightmapper traces faces that never render | `double_sided_gi: false` |

Sending Tier 1 alone takes the Materials tab from **one finding and zero
fixes** to four rules, three of them applicable with a single property write.
