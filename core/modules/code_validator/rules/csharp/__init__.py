# core/modules/code_validator/rules/csharp/__init__.py
#
# C# rule modules — mirrors the cpp/ family for Unity targets.
# Each module exports its detector functions for use by the runner.

from code_validator.rules.csharp.csharp_orchestrator import run_all_csharp_rules

__all__ = ["run_all_csharp_rules"]
