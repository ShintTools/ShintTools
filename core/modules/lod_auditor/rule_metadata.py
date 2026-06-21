# core/modules/lod_auditor/rule_metadata.py
#
# Customer-facing metadata for LOD findings, kept LOD-local (the code_validator
# metadata map only knows about C++/Blueprint/Naming detectors, so LOD rules
# aren't reachable from there).
#
# Two products, both keyed by rule_id (e.g. "LT003"):
#   1. LOD_RULE_NAMES     — short humanised titles shown to the user and used by
#                           the LLM in user-facing copy (never expose rule_id).
#   2. rule_explanation   — extracted from each rule function's one-line
#                           docstring ("LT003: ..."), prefix stripped. The LLM
#                           uses this as authoritative grounding so the 1.5B
#                           model doesn't have to guess engine semantics.
#
# enrich_lod_finding() stamps both onto a Finding (plus the resolved engine, so
# the agent registry can pick the right prompt template). The LOD orchestrator
# calls it for every finding before returning the response.

from __future__ import annotations

import re

from lod_auditor.schema import Finding

# ── Humanised rule names ───────────────────────────────────────────────────
#
# Keep entries short (< 50 chars) — these are titles, not explanations.

LOD_RULE_NAMES: dict[str, str] = {
    # ── Meshes (LD) ──────────────────────────────────────
    "LD001": "Mesh has no LOD chain",
    "LD002": "LOD chain not monotonic",
    "LD003": "LOD0 over triangle budget",
    # ── Textures (LT) ────────────────────────────────────
    "LT001": "Texture compression not optimal",
    "LT002": "MIP config wrong for usage",
    "LT003": "Texture over resolution budget",
    "LT004": "sRGB flag mismatch",
    "LT005": "Large texture, streaming off",
    # ── Materials (LM) ───────────────────────────────────
    "LM001": "Shader over instruction budget",
    "LM002": "Duplicate texture sampler",
    "LM003": "Material not instanced",
    # ── Animations (LA) ──────────────────────────────────
    "LA001": "Animation compression not optimal",
    "LA002": "Skeletal mesh has no LOD chain",
    "LA003": "Animation has excess curves/keys",
    # ── Audio (LU) ───────────────────────────────────────
    "LU001": "Long audio uncompressed",
    "LU002": "Long audio not streaming",
    # ── Lighting (LL) ────────────────────────────────────
    "LL001": "Lightmap resolution excessive",
    "LL002": "Light overdraw too high",
    # ── Particles (LV) ───────────────────────────────────
    "LV001": "Particle count over budget",
    "LV002": "CPU sim should be GPU",
    "LV003": "No particle bounds culling",
    # ── Mobile (LMB) ─────────────────────────────────────
    "LMB001": "Mobile sampler count over cap",
    "LMB002": "Desktop-only compression on mobile",
    "LMB003": "Screen-space nodes on mobile",
    # ── Cross-asset (LX) ─────────────────────────────────
    "LX001": "Unreferenced (dead) texture",
    "LX002": "Unused (dead) material",
    "LX003": "Duplicate mesh content",
}

# "LT003: ..." → strip the leading id so the explanation reads cleanly.
_RULE_ID_PREFIX_RE = re.compile(r"^L[A-Z]+\d+:\s*")


def _first_line(docstring: str | None) -> str:
    """Return the first non-empty docstring line with the rule_id prefix
    stripped. LOD rule docstrings are single-line summaries
    (e.g. ``\"\"\"LT003: Texture resolution exceeds the slot budget...\"\"\"``),
    so the first line is the whole customer-facing explanation."""
    if not docstring:
        return ""
    for raw in docstring.strip().splitlines():
        line = raw.strip()
        if line:
            return _RULE_ID_PREFIX_RE.sub("", line, count=1)
    return ""


# rule_id -> first-paragraph explanation, built lazily from the rule functions
# the orchestrator registers (so it can never drift from the actual detectors).
_explanations_cache: dict[str, str] | None = None


def _build_explanations() -> dict[str, str]:
    """Map every rule_id to its detector's docstring explanation.

    Imported lazily (inside the function) to avoid a circular import: the
    orchestrator imports this module, and this needs the orchestrator's rule
    registries.
    """
    from lod_auditor import lod_orchestrator as orch

    all_rule_fns = (
        orch.TEXTURE_RULES
        + orch.MATERIAL_RULES
        + orch.MESH_RULES
        + orch.ANIM_RULES
        + orch.PARTICLE_RULES
        + orch.AUDIO_RULES
        + orch.LIGHTING_RULES
        + orch.CROSS_RULES
        + orch.MOBILE_RULES_BY_TYPE.get("Material", [])
        + orch.MOBILE_RULES_BY_TYPE.get("Texture", [])
    )

    explanations: dict[str, str] = {}
    for fn in all_rule_fns:
        explanation = _first_line(fn.__doc__)
        if not explanation:
            continue
        # Derive the rule_id from the docstring prefix so we don't need a
        # second hand-maintained fn->id table.
        match = re.match(r"^(L[A-Z]+\d+):", (fn.__doc__ or "").strip())
        if match:
            explanations[match.group(1)] = explanation
    return explanations


def get_rule_explanation(rule_id: str) -> str:
    global _explanations_cache
    if _explanations_cache is None:
        _explanations_cache = _build_explanations()
    return _explanations_cache.get(rule_id, "")


def enrich_lod_finding(finding: Finding, engine: str) -> Finding:
    """Stamp rule_name, rule_explanation and engine onto *finding* in place.

    rule_name/rule_explanation give the user a readable title + grounding and
    feed the LLM explainer; engine lets the agent registry resolve the right
    prompt template. Returns the same object for convenient chaining.
    """
    finding.rule_name = LOD_RULE_NAMES.get(finding.rule_id, finding.rule_id)
    finding.rule_explanation = get_rule_explanation(finding.rule_id)
    finding.engine = engine
    return finding
