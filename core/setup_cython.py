# core/setup_cython.py
#
# Compiles protected modules to .so (Linux) / .pyd (Windows).
# Run: python setup_cython.py build_ext --inplace
#
# After compilation the Dockerfile (or build.bat in the Launcher)
# deletes the original .py files so only the binary remains.
# Python imports .so/.pyd with the same priority as .py.
#
# Files NOT compiled (must stay as plain Python):
#   - __init__.py  (needed for package discovery)
#   - tests/       (not shipped to client)
#   - api/         (thin HTTP layer, no business logic)
#   - scripts/     (dev/ops utilities, not shipped)

import os

from Cython.Build import cythonize
from setuptools import Extension, setup

# ── Files to protect ─────────────────────────────────────────────────────────
# All rule detection logic, fix patterns, tier gating, scoring, and LLM
# explanation logic — the intellectual property of ShintTools.

_MODULES = [
    # ── C++ rules ─────────────────────────────────────────────────────────
    "modules/code_validator/unreal/cpp/cpp_performance.py",
    "modules/code_validator/unreal/cpp/cpp_best_practices.py",
    "modules/code_validator/unreal/cpp/cpp_security.py",
    "modules/code_validator/unreal/cpp/cpp_maintainability.py",
    "modules/code_validator/unreal/cpp/_cpp_helpers.py",
    "modules/code_validator/unreal/cpp/cpp_orchestrator.py",
    # ── Blueprint rules ───────────────────────────────────────────────────
    "modules/code_validator/unreal/blueprint/blueprint_rules.py",
    "modules/code_validator/unreal/blueprint/blueprint_orchestrator.py",
    # ── C# rules (Unity) ──────────────────────────────────────────────────
    "modules/code_validator/unity/csharp/csharp_performance.py",
    "modules/code_validator/unity/csharp/csharp_best_practices.py",
    "modules/code_validator/unity/csharp/csharp_security.py",
    "modules/code_validator/unity/csharp/csharp_maintainability.py",
    "modules/code_validator/unity/csharp/unity_specific.py",
    "modules/code_validator/unity/csharp/_csharp_helpers.py",
    "modules/code_validator/unity/csharp/csharp_orchestrator.py",
    # ── Unity Visual Scripting graphs ─────────────────────────────────────
    "modules/code_validator/unity/visual_scripting/unity_graph_rules.py",
    "modules/code_validator/unity/visual_scripting/unity_graph_orchestrator.py",
    "modules/code_validator/unity/parsers/unity_vs_parser.py",
    # ── Parsers & fixers ──────────────────────────────────────────────────
    "modules/code_validator/unity/parsers/csharp_parser.py",
    "modules/code_validator/unreal/parsers/fixers/fix_patterns.py",
    "modules/code_validator/unreal/parsers/fixers/cpp_fixer.py",
    # ── Shared ────────────────────────────────────────────────────────────
    "modules/code_validator/shared/_rule_metadata.py",
    "modules/code_validator/shared/tiers.py",
    # ── Scoring engine ────────────────────────────────────────────────────
    "modules/metrics/score_calculator.py",
    # ── Naming rules ──────────────────────────────────────────────────────
    "modules/naming/unreal/ue5_naming_rules.py",
    "modules/naming/unity/unity_naming_rules.py",
    "modules/naming/naming_orchestrator.py",
    # ── Agent / LLM explanation logic ─────────────────────────────────────
    "modules/agent/explainer.py",
    "modules/agent/llm_backend.py",
    "modules/agent/prefab_explanations.py",
]

# Filter to only files that actually exist — avoids build failure when a
# module has been moved or is not yet implemented.
_MODULES = [m for m in _MODULES if os.path.exists(m)]

_EXTENSIONS = [
    Extension(
        name=m[: -len(".py")].replace("/", "."),
        sources=[m],
    )
    for m in _MODULES
]

setup(
    name="shinttools-core",
    ext_modules=cythonize(
        _EXTENSIONS,
        compiler_directives={
            "language_level": "3",
        },
        build_dir="build/cython",
    ),
    zip_safe=False,
)
