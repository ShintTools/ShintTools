import os

modules = [
    "modules/code_validator/unreal/cpp/cpp_performance.py",
    "modules/code_validator/unreal/cpp/cpp_best_practices.py",
    "modules/code_validator/unreal/cpp/cpp_security.py",
    "modules/code_validator/unreal/cpp/cpp_maintainability.py",
    "modules/code_validator/unreal/cpp/_cpp_helpers.py",
    "modules/code_validator/unreal/cpp/cpp_orchestrator.py",
    "modules/code_validator/unreal/blueprint/blueprint_rules.py",
    "modules/code_validator/unreal/blueprint/blueprint_orchestrator.py",
    "modules/code_validator/unity/csharp/csharp_performance.py",
    "modules/code_validator/unity/csharp/csharp_best_practices.py",
    "modules/code_validator/unity/csharp/csharp_security.py",
    "modules/code_validator/unity/csharp/csharp_maintainability.py",
    "modules/code_validator/unity/csharp/unity_specific.py",
    "modules/code_validator/unity/csharp/_csharp_helpers.py",
    "modules/code_validator/unity/csharp/csharp_orchestrator.py",
    "modules/code_validator/unity/visual_scripting/unity_graph_rules.py",
    "modules/code_validator/unity/visual_scripting/unity_graph_orchestrator.py",
    "modules/code_validator/unity/parsers/unity_vs_parser.py",
    "modules/code_validator/unity/parsers/csharp_parser.py",
    "modules/code_validator/unreal/parsers/fixers/fix_patterns.py",
    "modules/code_validator/unreal/parsers/fixers/cpp_fixer.py",
    "modules/code_validator/shared/_rule_metadata.py",
    "modules/code_validator/shared/tiers.py",
    "modules/metrics/score_calculator.py",
    "modules/naming/unreal/ue5_naming_rules.py",
    "modules/naming/unity/unity_naming_rules.py",
    "modules/naming/naming_orchestrator.py",
    "modules/agent/explainer.py",
    "modules/agent/llm_backend.py",
    "modules/agent/prefab_explanations.py",
]
ok = [m for m in modules if os.path.exists(m)]
missing = [m for m in modules if not os.path.exists(m)]
print(f"OK: {len(ok)}/{len(modules)}")
for m in missing:
    print(f"  MISSING: {m}")
