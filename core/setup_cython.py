# core/setup_cython.py
#
# Compiles protected modules to .so (Linux) / .pyd (Windows).
# Run: python setup_cython.py build_ext --inplace
#
# After compilation, delete the original .py files so
# only the binary .so/.pyd remains in the Docker image.
# Python imports .so/.pyd with the same priority as .py.
#
# Files NOT compiled:
#   - __init__.py  (needed for package discovery)
#   - tests/       (not shipped to client)
#   - api/         (thin HTTP layer, no business logic)

from Cython.Build import cythonize
from setuptools import setup

# ── Files to protect ─────────────────────────────────
# These contain all rule logic, fix patterns, and tier
# definitions — the intellectual property of ShintTools.

_PROTECTED_FILES = [
    # Code Validator — parsers
    "modules/code_validator/parsers/cpp_fixer.py",
    "modules/code_validator/parsers/cpp_parser.py",
    "modules/code_validator/parsers/fix_patterns.py",
    # Code Validator — C++ rules
    "modules/code_validator/rules/cpp/_cpp_helpers.py",
    "modules/code_validator/rules/cpp/cpp_best_practices.py",
    "modules/code_validator/rules/cpp/cpp_maintainability.py",
    "modules/code_validator/rules/cpp/cpp_performance.py",
    "modules/code_validator/rules/cpp/cpp_security.py",
    "modules/code_validator/rules/cpp/ue5_cpp_rules.py",
    # Code Validator — Blueprint rules
    "modules/code_validator/rules/blueprint_rules.py",
    # Code Validator — tier config
    "modules/code_validator/tiers.py",
    # Naming Bot
    "modules/naming/rules/ue5_naming_rules.py",
]

setup(
    name="shinttools-core",
    ext_modules=cythonize(
        _PROTECTED_FILES,
        compiler_directives={
            "language_level": "3",
        },
    ),
)
