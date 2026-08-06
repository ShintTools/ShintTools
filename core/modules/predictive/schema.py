# core/modules/predictive/schema.py
#
# Predictive Profiler contract v1 — the field-level agreement both clients
# (UE5 plugin, Unity plugin) build against. Published verbatim in
# docs/predictive/API.md once frozen (milestone M4).
#
# INPUT:  a session assembled from batched ingests of four section kinds —
#         assets / scene / code / config — then analyzed as a whole.
# OUTPUT: PredictiveReport — risk scores, frame budget, memory, build,
#         ranked cost items. Every number is a Prediction band (see
#         cost_model/prediction.py); the report is also the simulator's
#         database (each item carries impact + remediation.recovery).
#
# Convention shared with lod_auditor/schema.py: the input asset models are
# the documented contract, but the orchestrator receives list[dict] and the
# layers access fields via dict.get() with safe defaults — adding a field
# never breaks an older client.

from typing import Any

from pydantic import BaseModel, Field

from predictive.cost_model.prediction import Prediction

SCHEMA_VERSION = "1.0"

# ── Session / ingest ─────────────────────────────────────────────────────────

INGEST_KINDS: frozenset[str] = frozenset(
    {"assets", "scene", "code", "code_files", "config"}
)


class SessionStartRequest(BaseModel):
    """POST /predict/session/start."""

    api_key: str = ""
    engine: str = "UE5"  # "UE5" | "Unity"
    project_name: str = ""
    platform_profile: str = "desktop_60"
    schema_version: str = SCHEMA_VERSION


class SessionStartResponse(BaseModel):
    session_id: str
    schema_version: str = SCHEMA_VERSION


class IngestRequest(BaseModel):
    """POST /predict/session/ingest — one batch of one section kind.

    ``payload`` shape depends on ``kind``:
      assets → {"assets": [<TextureAsset|MaterialAsset|MeshAsset dict>, ...]}
               (same shapes the LOD audit already collects — lod_auditor/schema.py)
      scene  → {"scenes": [<SceneDigest dict>, ...]}
      code   → {"issues": [<validator issue + occurrence_context>, ...]}
      config → {"config": <ProjectConfig dict>}
    Batching: clients chunk assets at 150/request (LOD audit precedent).
    """

    api_key: str = ""
    session_id: str
    kind: str  # one of INGEST_KINDS
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    session_id: str
    kind: str
    accepted: int  # items accepted from this batch
    total_ingested: dict[str, int]  # running per-kind totals for the session


# ── Input sections (documentation contract; layers read dicts) ──────────────


class SceneLight(BaseModel):
    """One light in a scene digest."""

    type: str = "Point"  # Point | Spot | Directional | Rect | Area
    # Static | Stationary | Movable  (Unity: Baked | Mixed | Realtime)
    mobility: str = "Static"
    casts_shadows: bool = False
    attenuation_radius: float = 0.0  # UE5; Unity sends range


class SceneParticleSystem(BaseModel):
    """Niagara system (UE5) or ParticleSystem (Unity) present in the scene."""

    path: str = ""
    sim_target: str = "CPU"  # CPU | GPU
    emitter_count: int = 0
    instance_count_in_scene: int = 1


class SceneHeavyBlueprint(BaseModel):
    """UE5: a ticking Blueprint worth pricing individually."""

    path: str = ""
    tick_enabled: bool = True
    node_count: int = 0
    instances: int = 1


class SceneDigest(BaseModel):
    """Per-scene composition digest (Layer 2 input).

    UE5 fills the actor/blueprint fields; Unity fills the update_scripts/
    prefab fields. Either engine leaves the other's fields at their defaults —
    Layer 2 rules abstain on absent data rather than guessing.
    """

    scene_name: str = ""
    # Project-relative path of the scene asset — "/Game/Maps/Arena" (UE5) or
    # "Assets/Scenes/Arena.unity" (Unity). Echoed back on SceneSummary so the
    # client can resolve the scene to its asset (icon / open-in-editor).
    # Optional: omit it and SceneSummary.scene_path comes back empty.
    scene_path: str = ""
    # ── UE5 ──
    world_partition: bool = False
    actor_count: int = 0
    ticking_actors: int = 0
    ticking_blueprints: int = 0
    avg_components_per_actor: float = 0.0
    max_components_actor: dict[str, Any] = Field(default_factory=dict)
    heavy_blueprints: list[SceneHeavyBlueprint] = Field(default_factory=list)
    skeletal_meshes: int = 0
    # ── Unity ──
    game_object_count: int = 0
    update_scripts: int = 0  # MonoBehaviours with Update()
    fixed_update_scripts: int = 0
    prefab_max_depth: int = 0
    reflection_probes: int = 0
    # ── shared ──
    lights: list[SceneLight] = Field(default_factory=list)
    particle_systems: list[SceneParticleSystem] = Field(default_factory=list)


class CodeIssueContext(BaseModel):
    """Optional occurrence context the client attaches to a validator issue —
    lets Layer 3 scale the cost (a GetAllActorsOfClass inside a double loop
    in Tick is not priced like a one-off)."""

    in_tick: bool = False
    loop_depth: int = 0
    call_count_estimate: int = 1


class ProjectConfig(BaseModel):
    """Render/build configuration (Layer 4 modifiers)."""

    render: dict[str, Any] = Field(default_factory=dict)
    # UE5: {"pipeline": "Lumen", "nanite": true, "raytracing": false,
    #       "shadow_quality": 3, "aa_method": "TSR"}
    # Unity: {"pipeline": "URP" | "HDRP" | "BuiltIn", "srp_batcher": true, ...}
    build: dict[str, Any] = Field(default_factory=dict)
    # {"target_platforms": ["Win64"], "compression": "Oodle", "pak_chunking": true}
    scalability_defaults: dict[str, Any] = Field(default_factory=dict)


# ── Analyze ──────────────────────────────────────────────────────────────────


class AnalyzeRequest(BaseModel):
    """POST /predict/analyze.

    Session mode: pass ``session_id`` (normal client flow).
    One-shot mode: leave ``session_id`` empty and inline the sections —
    convenient for small projects, curl demos, and tests.
    """

    api_key: str = ""
    session_id: str = ""
    schema_version: str = SCHEMA_VERSION
    # one-shot fields
    engine: str = "UE5"
    project_name: str = ""
    platform_profile: str = "desktop_60"
    assets: list[dict[str, Any]] = Field(default_factory=list)
    scenes: list[dict[str, Any]] = Field(default_factory=list)
    code_issues: list[dict[str, Any]] = Field(default_factory=list)
    # Preferred over code_issues: raw {"path", "content"} source — Predictive
    # scans it in-process (code_scan.py) instead of requiring the client to
    # pre-run /validate/* and forward its output. code_issues stays accepted
    # for backward compat with the frozen v1.0 contract's existing clients.
    code_files: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


# ── Report ───────────────────────────────────────────────────────────────────


class RiskScore(BaseModel):
    """One 0-100 risk figure plus the item ids that drive it (top-5) — the
    UI's answer to "why is this number what it is" in one click."""

    value: int = 0
    drivers: list[str] = Field(default_factory=list)


class Scores(BaseModel):
    cpu_risk: RiskScore = Field(default_factory=RiskScore)
    gpu_risk: RiskScore = Field(default_factory=RiskScore)
    memory_risk: RiskScore = Field(default_factory=RiskScore)
    build_health: RiskScore = Field(default_factory=RiskScore)  # 100 = healthy
    overall_project_health: int = 0  # 100 = healthy


class BudgetLine(BaseModel):
    """Predicted spend against one budget (CPU or GPU frame ms).

    ``breakdown`` always sums to ``predicted.expected``: the aggregate labels
    cover the itemized rows, and whatever the table doesn't show as its own
    row (scene dispatch below the item threshold) lands in an explicit
    residual entry. A client can therefore reconcile its table against this
    total instead of finding a silent gap.
    """

    budget_ms: float = 0.0
    predicted: Prediction | None = None
    breakdown: list[dict[str, Any]] = Field(default_factory=list)
    # breakdown entries: {"label": "Tick dispatch", "expected_ms": 2.1}
    # How much of `predicted` appears as its own row in cost_items. Aggregate
    # scene dispatch is priced whole but only individually actionable
    # offenders earn a row, so the table legitimately sums to less than the
    # total — render it as "rows account for {itemized_ms} of {predicted} ms"
    # rather than treating the difference as missing data.
    itemized_ms: float = 0.0


class FrameLine(BaseModel):
    """Predicted frame time — NOT cpu + gpu.

    CPU and GPU work on a frame is pipelined, not serial: the GPU renders
    frame N while the CPU prepares N+1. Frame time is therefore governed by
    the slower of the two (the bottleneck), so summing the two axes
    overstates the frame by roughly the smaller one. This line states the
    frame figure explicitly so clients never have to infer it.
    """

    budget_ms: float = 0.0
    predicted_ms: float = 0.0
    bottleneck: str = ""  # "cpu" | "gpu" | "" when unscored
    note: str = ""


class FrameBudget(BaseModel):
    cpu: BudgetLine = Field(default_factory=BudgetLine)
    gpu: BudgetLine = Field(default_factory=BudgetLine)
    frame: FrameLine = Field(default_factory=FrameLine)


class MemoryBudgetLine(BaseModel):
    budget_mb: int = 0
    predicted: Prediction | None = None


class MemoryReport(BaseModel):
    vram: MemoryBudgetLine = Field(default_factory=MemoryBudgetLine)
    ram: MemoryBudgetLine = Field(default_factory=MemoryBudgetLine)
    gc_pressure: Prediction | None = None  # mb_min; Unity only


class BuildReport(BaseModel):
    size_mb: Prediction | None = None
    package_time_min: Prediction | None = None
    cold_load_s: Prediction | None = None


class Remediation(BaseModel):
    """What fixing this item buys back."""

    action: str = ""
    recovery: dict[str, Prediction] = Field(default_factory=dict)
    # keyed by dimension: "cpu_ms_frame" | "gpu_ms_frame" | "vram_mb" |
    # "ram_mb" | "gc_mb_min" | "build_mb"
    auto_fixable: bool = False


# Display metadata per impact dimension: (unit, human label). A table row
# must render its own dimension's unit — an asset costs MB, never ms, and
# showing "0 ms" for a texture is a unit error, not a zero-cost asset.
DIMENSION_DISPLAY: dict[str, tuple[str, str]] = {
    "cpu_ms_frame": ("ms", "CPU frame time"),
    "gpu_ms_frame": ("ms", "GPU frame time"),
    "vram_mb": ("MB", "VRAM"),
    "ram_mb": ("MB", "RAM"),
    "build_mb": ("MB", "Build size"),
    "gc_mb_min": ("MB/min", "GC pressure"),
}


class CostValue(BaseModel):
    """The single figure a table row should display for an item.

    Items are priced in different units — a texture costs VRAM/build MB, a
    Tick pattern costs frame ms. A client that renders one fixed "ms" column
    shows 0 for every asset, which reads as "this asset is free" when it
    actually means "this asset's cost isn't measured in ms". This field
    names the dominant dimension, its value and its unit, so one column can
    render every row correctly.
    """

    dimension: str = ""  # key into `impact`
    value: float = 0.0
    unit: str = ""  # "MB" | "ms" | "MB/min"
    label: str = ""  # "VRAM" | "CPU frame time"


class CostItem(BaseModel):
    """One priced finding — a row of the report and the simulator's unit of
    selection. ``impact`` and ``remediation.recovery`` are keyed by dimension
    so a single item can cost CPU *and* GC (e.g. LINQ in Update)."""

    item_id: str  # "ci-0042" — stable within a report
    layer: int  # 1 assets | 2 scene | 3 code
    rank: int = 0  # position in top_issues (0 = not ranked)
    severity: str = "warning"  # critical | warning | info
    title: str = ""
    rule_id: str = ""  # source rule when layer 3 / LOD rule when layer 1
    source: dict[str, Any] = Field(default_factory=dict)
    # {"kind": "blueprint"|"texture"|"scene"|..., "path": ..., "line": ...,
    #  "instances_in_scene": 60}
    impact: dict[str, Prediction] = Field(default_factory=dict)
    remediation: Remediation | None = None
    # The dimension a single-column table should render for this row. Set by
    # the orchestrator (it needs the platform budgets to pick the dominant
    # one). Never null on a returned report.
    primary_cost: CostValue | None = None


class SceneSummary(BaseModel):
    scene_name: str = ""
    # Project-relative asset path of the scene ("/Game/Maps/Arena" on UE5,
    # "Assets/Scenes/Arena.unity" on Unity). Clients need the path — not just
    # the display name — to resolve the scene back to its asset (icon,
    # thumbnail, click-to-open). Echoed from the digest's ``scene_path``,
    # falling back to ``path``; empty when the client sent neither.
    scene_path: str = ""
    complexity_score: int = 0  # 0-100
    runtime_cost: dict[str, Prediction] = Field(default_factory=dict)
    # {"cpu_ms_frame": Prediction, "gpu_ms_frame": Prediction}


class ReportStats(BaseModel):
    """Coverage transparency — how much of the project the numbers actually
    cover. ``code_issues_uncosted`` counts validator issues with no entry in
    rule_costs.yaml: they appear by severity but contribute 0 to budgets."""

    assets_analyzed: int = 0
    scenes_analyzed: int = 0
    code_issues_costed: int = 0
    code_issues_uncosted: int = 0


class PredictiveReport(BaseModel):
    """POST /predict/analyze response."""

    schema_version: str = SCHEMA_VERSION
    report_id: str = ""
    generated_at: str = ""  # ISO-8601 UTC
    engine: str = "UE5"
    project_name: str = ""
    platform_profile: dict[str, Any] = Field(default_factory=dict)
    calibration_version: str = ""
    disclaimer: str = ""
    scores: Scores = Field(default_factory=Scores)
    frame_budget: FrameBudget = Field(default_factory=FrameBudget)
    memory: MemoryReport = Field(default_factory=MemoryReport)
    build: BuildReport = Field(default_factory=BuildReport)
    top_issues: list[CostItem] = Field(default_factory=list)
    cost_items: list[CostItem] = Field(default_factory=list)
    scene_summaries: list[SceneSummary] = Field(default_factory=list)
    stats: ReportStats = Field(default_factory=ReportStats)


# ── Simulate ─────────────────────────────────────────────────────────────────


class SimulateRequest(BaseModel):
    """POST /predict/simulate.

    Normal mode: ``report_id`` of a cached report + selection.
    Stateless fallback (report expired): inline the ``cost_items`` the client
    kept from its copy of the report.
    ``platform_profile`` switches the budget the after-scores are computed
    against — the "what if I port to Steam Deck?" scenario.
    """

    api_key: str = ""
    report_id: str = ""
    selected_item_ids: list[str] = Field(default_factory=list)
    platform_profile: str = ""
    cost_items: list[dict[str, Any]] = Field(default_factory=list)
    schema_version: str = SCHEMA_VERSION


class SimulateResponse(BaseModel):
    schema_version: str = SCHEMA_VERSION
    report_id: str = ""
    selected_count: int = 0
    deltas: dict[str, Prediction] = Field(default_factory=dict)
    # keyed by dimension, values negative (savings)
    scores_before: Scores = Field(default_factory=Scores)
    scores_after: Scores = Field(default_factory=Scores)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    # {"item_id": ..., "reason": ..., "auto_fixable": bool}


# ── Profiles endpoint ────────────────────────────────────────────────────────


class ProfilesResponse(BaseModel):
    """GET /predict/profiles."""

    schema_version: str = SCHEMA_VERSION
    profiles: list[dict[str, Any]] = Field(default_factory=list)
