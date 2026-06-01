# core/modules/agent/prompts/__init__.py
#
# Server-side prompt registry. System instruction + few-shots live
# in versioned YAMLs under prompts/templates/{module}/{engine}/vN.yaml
# (or _shared/vN.yaml as the cross-module fallback). The explainer
# loads a template at request time and assembles the final prompt
# from it, so prompts can be tuned by editing YAML and restarting
# the API — no code changes, no container rebuild.

from .registry import (
    PromptTemplate,
    assemble,
    list_templates,
    load_template,
    reset_cache,
    resolve_module_engine,
)

__all__ = [
    "PromptTemplate",
    "assemble",
    "list_templates",
    "load_template",
    "resolve_module_engine",
    "reset_cache",
]
