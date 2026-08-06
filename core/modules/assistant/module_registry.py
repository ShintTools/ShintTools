# core/modules/assistant/module_registry.py
#
# What a "module" is, in one place.
#
# The assistant had no module dimension at all. `module_context` travelled
# from the client to every action's payload and not one of them read it, so
# "how is the Code Validator doing?" summarised whatever analysis happened to
# be on screen — usually a LOD audit. Fixing that needs three things to agree
# on the same list of modules: the intent router (to recognise the name), the
# resolver (to decide which module a message is about) and the actions (to
# find that module's results). This is that list.
#
# The `report_types` tuples are the part worth reading carefully. A module is
# NOT one report type: the Code Validator writes five, one per scan shape
# (C++ files, whole project, Blueprints, Unity graphs) — plus
# `code_validator_fixes`, which records an Auto-Fix run and is deliberately
# ABSENT here. Querying by an equality on "code_validator" would silently miss
# a project scan; querying by a "code_validator*" prefix would pick up a fix
# log and report its entries as findings. Both are wrong in a way that looks
# like a working answer, so the set is enumerated by hand and checked against
# the persistence call sites in api/routes/{validate,assets,lod_audit}.py.

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleInfo:
    """One analysis module the assistant can talk about."""

    #: Canonical id. Matches the `module_context` wire value the UE5/Unity
    #: clients already send (ShintAssistantContext::GetModuleContextString).
    id: str

    #: Human name, used verbatim in replies.
    display: str

    #: What the module looks for — the answer to "what does X do?" and the
    #: fallback when there is no scan to summarise.
    covers: str

    #: Every report_type this module's SCANS write into analysis_results.
    #: Fix/apply logs are excluded on purpose (see the module docstring).
    report_types: tuple[str, ...]

    #: Lowercase substrings that mean this module in a user's message.
    #: Bilingual because studio chat is; matched longest-first by the
    #: resolver so "lod auditor" cannot be stolen by a bare "lod".
    aliases: tuple[str, ...]

    #: (import path, attribute) of the module's rule-id -> name mapping, when
    #: it has one. None where no catalog exists (the naming bot's rule ids are
    #: not centrally named), and the coverage line is then simply omitted
    #: rather than filled with a guess.
    catalog: tuple[str, str] | None = field(default=None)


MODULES: tuple[ModuleInfo, ...] = (
    ModuleInfo(
        id="code_validator",
        display="Code Validator",
        covers=(
            "C++, Blueprint and C# code — performance traps, unsafe patterns, "
            "engine API misuse and your own studio rules"
        ),
        report_types=(
            "code_validator",
            "code_validator_project",
            "code_validator_blueprints",
            "code_validator_unity_graphs",
        ),
        aliases=(
            "code validator", "validador de codigo", "validador de código",
            "code validation", "validador", "code_validator",
        ),
        catalog=("code_validator.shared._rule_metadata", "RULE_NAMES"),
    ),
    ModuleInfo(
        id="asset_naming",
        display="Asset Naming Bot",
        covers=(
            "asset names and folder structure against your project's naming "
            "convention"
        ),
        report_types=("asset_naming",),
        aliases=(
            "asset naming", "naming bot", "nomenclatura", "naming convention",
            "convencion de nombres", "convención de nombres", "asset_naming",
            "naming",
        ),
    ),
    # [LOD-STRIP-BEGIN]
    ModuleInfo(
        id="lod_audit",
        display="LOD Auditor",
        covers=(
            "meshes, materials, textures and their LOD setup — triangle "
            "budgets, screen sizes, VRAM cost and Nanite readiness"
        ),
        report_types=("lod_audit",),
        aliases=(
            "lod auditor", "lod audit", "auditor de lod", "auditoria de lod",
            "auditoría de lod", "lod_audit", "lods", "lod",
        ),
        catalog=("lod_auditor.rule_metadata", "LOD_RULE_NAMES"),
    ),
    ModuleInfo(
        id="predictive",
        display="Predictive Profiler",
        covers=(
            "predicted CPU, GPU, memory and build cost before you press play"
        ),
        # Predictive persists reports under its own collection, not
        # analysis_results — hence no report_types. It can still be named and
        # described; asking it to summarise findings correctly says it has
        # none of that kind.
        report_types=(),
        aliases=(
            "predictive profiler", "predictive", "profiler", "perfilador",
            "predictivo",
        ),
    ),
    # [LOD-STRIP-END]
)

BY_ID: dict[str, ModuleInfo] = {m.id: m for m in MODULES}

#: report_type -> module, so an analysis document can name its own module.
BY_REPORT_TYPE: dict[str, ModuleInfo] = {
    rt: m for m in MODULES for rt in m.report_types
}

#: Every alias, longest first. Order matters: "lod auditor" must be tested
#: before "lod", otherwise the shorter alias matches first and the specific
#: one never fires.
ALIASES: tuple[tuple[str, ModuleInfo], ...] = tuple(
    sorted(
        ((alias, m) for m in MODULES for alias in m.aliases),
        key=lambda pair: len(pair[0]),
        reverse=True,
    )
)


def get(module_id: str) -> ModuleInfo | None:
    return BY_ID.get((module_id or "").strip().lower())


def for_report_type(report_type: str) -> ModuleInfo | None:
    return BY_REPORT_TYPE.get((report_type or "").strip())


def rule_count(module: ModuleInfo) -> int:
    """How many rules this module's catalog defines, or 0 when it has none.

    Best-effort by design: a Core edition that ships without a module (the
    free image has no LOD auditor) simply reports 0 instead of raising, and
    the caller omits the coverage sentence."""
    if module.catalog is None:
        return 0
    path, attr = module.catalog
    try:
        mod = __import__(path, fromlist=[attr])
    except ImportError:
        return 0
    names = getattr(mod, attr, None)
    return len(names) if isinstance(names, dict) else 0
