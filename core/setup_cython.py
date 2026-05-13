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

from Cython.Build import cythonize
from setuptools import Extension, setup

# ── Files to protect ─────────────────────────────────────────────────────────
# All rule detection logic, fix patterns, tier gating, scoring, and LLM
# explanation logic — the intellectual property of ShintTools.
#
# Using explicit Extension() objects so each .so/.pyd lands at the correct
# importable dotted path. Plain path strings passed directly to cythonize()
# can produce binaries at the wrong location, causing ImportError at runtime.
#
# NOTE: boundscheck and wraparound must NOT be disabled. The rule modules
# use regular list slicing and negative indices; disabling those checks
# turns ordinary index errors into native access violations.

_MODULES = [
    # ── C++ rules ─────────────────────────────────────────────────────────
    "modules/code_validator/rules/cpp/cpp_performance.py",
    "modules/code_validator/rules/cpp/cpp_best_practices.py",
    "modules/code_validator/rules/cpp/cpp_security.py",
    "modules/code_validator/rules/cpp/cpp_maintainability.py",
    "modules/code_validator/rules/cpp/_cpp_helpers.py",
    "modules/code_validator/rules/cpp/ue5_cpp_rules.py",
    "modules/code_validator/rules/cpp/cpp_orchestrator.py",
    # ── Blueprint rules ───────────────────────────────────────────────────
    "modules/code_validator/rules/blueprint/blueprint_rules.py",
    "modules/code_validator/rules/blueprint/blueprint_orchestrator.py",
    # ── Rule metadata (names + docstring extraction used by LLM) ─────────
    "modules/code_validator/rules/_rule_metadata.py",
    # ── Parsers & fixers ──────────────────────────────────────────────────
    "modules/code_validator/parsers/cpp_parser.py",
    "modules/code_validator/parsers/fixers/fix_patterns.py",
    "modules/code_validator/parsers/fixers/cpp_fixer.py",
    "modules/code_validator/parsers/cpp_fixer.py",  # legacy top-level copy
    "modules/code_validator/parsers/fix_patterns.py",  # legacy top-level copy
    # ── Tier gating ───────────────────────────────────────────────────────
    "modules/code_validator/tiers.py",
    # ── Scoring engine ────────────────────────────────────────────────────
    "modules/metrics/score_calculator.py",
    # ── Naming rules ──────────────────────────────────────────────────────
    "modules/naming/rules/ue5_naming_rules.py",
    "modules/naming/rules/naming_orchestrator.py",
    # ── Agent / LLM explanation logic ─────────────────────────────────────
    "modules/agent/explainer.py",
    "modules/agent/llm_backend.py",
    "modules/agent/prefab_explanations.py",
]

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
