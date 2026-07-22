# Predictive Profiler — Arquitectura

Predice el impacto en CPU, GPU, memoria y build ANTES de ejecutar o compilar el proyecto, por análisis estático. Studio-only.

## Visión de 5 capas

**Layer 1 — Asset Intelligence**: Escanea texturas, mallas y config de LOD. Consume `lod_auditor.vram_model` para VRAM exacta y ejecuta audit internamente para findings costeables. Input: lista de assets. Output: `CostItem[]` de memoria, build size, cada uno con `impact` y `remediation.recovery`.

**Layer 2 — Scene Intelligence**: Digiere escenas (actores/GameObjects ticking, luces dinámicas, Niagara/partículas, Blueprints/prefabs pesados). Mapea engine-specific (UE5 vs Unity) al modelo canónico. Output: `SceneSummary.runtime_cost` — un `dict[str, Prediction]` con **ambas** dimensiones, no solo CPU: `cpu_ms_frame` (overhead de despacho de tick/Update — actor tick nativo, VM de Blueprint ~10×, MonoBehaviour Update) y `gpu_ms_frame` (luces dinámicas sombreadas por tipo — la parte dominante de la capa — y Niagara/partículas cuando `sim_target=GPU`).

**Layer 3 — Deep Code Intelligence**: Tablatura de reglas de `code_validator` con coste en milisegundos de CPU/frame (tabla `rule_costs.yaml`). Contextualiza occurrence en el código (callsite, frecuencia de invocación). Output: banda de CPU por issue, agrupado por regla.

**Layer 4 — Predictive Engine**: Agrega Layer 1–3 en bandas, calcula `overall_project_health` (0–100) con riesgo por eje. Input: perfil de plataforma. Output: `PredictiveReport` con scores, drivers, top issues.

**Layer 5 — Impact Simulator**: Runbook de remediation — qué issue fijar primero, qué impacto en cada eje. Reutiliza `remediation.recovery` de Layer 1 + deltas de Layer 3. Output: ranking de fixed/unfixed mundo alternativo.

---

## Prediction — tipo de moneda

Vive en `core/modules/predictive/cost_model/prediction.py`. Todo número es una **banda**, nunca escalar:

```python
class Prediction(BaseModel):
    expected: float
    min: float
    max: float
    unit: str          # "ms_frame" | "mb" | "mb_min" | "s" | "min"
    confidence: str     # "high" | "medium" | "low"
    basis: str          # 1 frase de origen
```

**Semántica de confidence**:
- `high`: matemática determinista (VRAM de bloques BCn vía lod_auditor)
- `medium`: patrones calibrados contra ground truth (rule_costs.yaml con `calibration_version`)
- `low`: heurísticas sin calibrar aún

**Aritmética de bandas**: `plus()`, `scaled()`, `negated()`, `sum_predictions()`. La suma NUNCA estrecha incertidumbre; confianza combinada = peor de operandos. No existe constructor sin banda+confidence+basis — es honestidad impuesta, no convención.

---

## Perfiles de plataforma

`cost_model/platform_profiles.py` + YAML en `cost_model/config/platform_*.yaml`. Cada perfil declara `frame_budget_ms`, `cpu_budget_ms`, `gpu_budget_ms`, `vram_budget_mb`, `ram_budget_mb`, `reference_hw`.

| Perfil | frame_budget_ms | Calibrated | Flags |
|--------|-----------------|-----------|-------|
| desktop_60 (baseline) | 16.67 | Sí | — |
| desktop_144 | 6.94 | No | — |
| console_30 | 33.33 | No | — |
| console_60 | 16.67 | No | — |
| mobile_30 | 33.33 | No | — |
| vr_90 | 11.11 | No | `strict_budget` (endurece riesgo en overrun) |
| steamdeck_60 | 16.67 | No | `unified_memory` (RAM + VRAM comparten pool) |

Property `.is_calibrated`: si falso, cualquier score sobre ese perfil queda confidence ≤ `medium` sin importar origen de la regla.

---

## Contrato API v1

`core/modules/predictive/schema.py` (`SCHEMA_VERSION = "1.0"`) + rutas en `core/api/routes/predictive.py`.

| Endpoint | Método | Estado | Descripción |
|----------|--------|--------|-------------|
| /predict/profiles | GET | Vivo | Devuelve catálogo de perfiles |
| /predict/analyze | POST | M1 | One-shot Layer 1; mode=`session_id` responde 501 hasta M3 |
| /predict/session/start | POST | 501 (M3) | Inicia sesión batcheada (lotes de 150) |
| /predict/session/ingest | POST | 501 (M3) | Ingesta incremental (mismo patrón que LOD Auditor) |
| /predict/simulate | POST | 501 (M4) | Impact Simulator |

**Payload de análisis** (`AnalyzeRequest`): 4 secciones
- `assets`: shape idéntico a `/assets/lod/audit` (cero trabajo cliente)
- `scenes`: digest de escena (campos UE5 + Unity conviven; defaults engine-specific)
- `code_issues`: salida de `/validate/*` + ocurrencia opcional
- `config`: render/build settings

**Reporte de salida** (`PredictiveReport`):
- `scores`: [cpu_risk, gpu_risk, memory_risk, build_health, overall_project_health] cada una con `drivers[]` (ids de impacto)
- `frame_budget`: Prediction de spend por frame
- `memory`: {vram, ram} con Prediction cada uno
- `build`: {time, size} con Prediction cada uno
- `top_issues`: [CostItem] — cada uno con `impact` Y `remediation.recovery`
- `cost_items`: desglose completo
- `stats`: incluye `code_issues_uncosted` (cobertura transparente, nunca se inventa coste)

---

## Layer 1 — Asset Intelligence (✓ M1)

`layers/layer1_assets.py` + `cost_model/asset_costs.py`. Reutiliza:
- `lod_auditor.vram_model.estimate_texture_vram_mb()` / `resolve_texture_bpp()` → VRAM exacta (confidence high)
- `lod_auditor.mesh_buffer_mb()` → memoria de buffer
- `lod_auditor.audit_assets()` internamente — cada finding con saving medible se promociona a `CostItem`

Semántica: `impact` == `remediation.recovery` (el exceso de hoy es lo que se recupera al fijar).

Build size (confidence medium, pendiente calibración M5): payload_gpu × (0.65–1.0 ratio empaquetado).

---

## Layer 4 — Scores de riesgo (✓ parcial, M1)

`layers/layer4_scores.py`. Curva de riesgo por tramos sobre % presupuesto utilizado:

```
≤60%       → 0–20 (sano)
60–85%     → 20–50 (precaución)
85–100%    → 50–80 (crítico)
>100%      → 80–100 (overrun, pendiente = 2x si strict_budget)
```

**Scores vivos** (M1):
- `memory_risk`: VRAM + RAM vs budgets
- `build_health`: size vs target

**Scores pendientes** (M2–M3):
- `cpu_risk`: Layer 2 (`cpu_ms_frame` — tick/Update dispatch) + Layer 3 (code)
- `gpu_risk`: Layer 2 (`gpu_ms_frame` — luces dinámicas sombreadas, Niagara/partículas GPU)

`overall_project_health` = 100 − weighted-max(active_risks):
- 75% el peor eje
- 25% media del resto
- Ejes sin datos se excluyen (no cuentan como sanos)

Un solo eje reventado hunde el proyecto.

---

## Gating por tier

**Dockerfile**: `rm -rf modules/predictive api/routes/predictive.py` en imagen free.

**Runtime**: Registro condicional en `core/api/main.py` dentro bloque `if _IS_PAID_EDITION`.

**Tier gate** (`core/api/tier_guard.py`): Studio + Enterprise (factorizado de LOD Auditor — lección real donde `!= "studio"` bloqueaba Enterprise).

---

## Roadmap

| Milestone | Contenido |
|-----------|-----------|
| M2 | rule_costs.yaml (≥25 reglas code_validator) + layer3_code.py + cpu_risk |
| M3 | layer2_scene.py + sesiones batcheadas reales (Mongo TTL) |
| M4 | layer5_simulator.py + contrato API frozen para cliente Unity |
| M5 | Calibración vs CitySample (fixtures + Unreal Insights ground truth) |
| M6–M8 | Cliente UE5: colectores de escena/config + ShintCoreClient_Predictive.cpp + ventana independiente (segundo nomad tab, NO sidebar) + 3 zonas (scores, top issues, simulator) |
| M9 | Docs usuario + material comercial |

---

## Principio de diseño

Ninguna cifra sale sin banda+confianza+origen. Ninguna capa inventa cobertura que no tiene — issues sin coste se cuentan, no se ocultan; ejes de score sin datos no puntúan. Es la diferencia entre un profiler estático creíble y un generador de números bonitos para una demo.
