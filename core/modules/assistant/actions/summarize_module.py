# core/modules/assistant/actions/summarize_module.py
#
# "How is <module> doing?" — an aggregate over a persisted analysis.
#
# Two things changed here, both of which were making the assistant answer the
# wrong question.
#
# It had no module dimension. `module_context` arrived in the payload and was
# never read, so this action summarised whatever analysis id the client last
# published — ask about the Code Validator with a LOD audit on screen and you
# got the LOD audit, presented as the answer. Resolution now goes through
# module_resolver: a module named in the message beats the ambient panel, and
# its latest scan is looked up directly, so the question works with no panel
# open at all.
#
# And it gave three numbers. Total, severity split, top three rules — true,
# but nothing a developer can act on. It now names the worst files, says
# whether the module got better or worse since the previous scan, and reports
# what the module covers when there is no scan yet, instead of the old dead
# end of "run a scan first".
#
# What has NOT changed is the contract: everything below is computed in
# Python. The model is never handed 400 rows to digest — a 1.5B asked to do
# that invents, and an invented finding is worse than no answer.

from __future__ import annotations

from collections import Counter
from typing import Any

from ..module_registry import ModuleInfo, rule_count
from ..module_resolver import latest_analysis, resolve_analysis, resolve_module

_NEED_MODULE = (
    "Which module? I can summarise the Code Validator, the Asset Naming Bot "
    "or the LOD Auditor — or run a scan and ask from its results."
)


def _issues(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        i for i in (doc.get("issues") or doc.get("results") or [])
        if isinstance(i, dict)
    ]


def _where(issue: dict[str, Any]) -> str:
    """The file or asset a finding is on, whichever key this module uses."""
    return str(
        issue.get("asset_path")
        or issue.get("file")
        or issue.get("file_path")
        or ""
    ).strip()


def _fingerprints(issues: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """(rule, location) pairs — a finding's identity across two scans.

    Deliberately coarse: line numbers move when a file is edited, so keying on
    them would report every finding in a touched file as both resolved and
    new. Rule + location is stable enough to answer "is this getting better?"
    honestly, and that is the only claim made from it.
    """
    return {
        (str(i.get("rule_id") or "?"), _where(i))
        for i in issues
    }


def _no_scan_reply(module: ModuleInfo) -> dict[str, Any]:
    """What we know about a module with nothing stored.

    The old reply was "run a scan first", which is a dead end: the user asked
    a question and got an instruction. The module's own coverage and rule
    count are real information and are available without any scan at all.
    """
    lines = [f"No {module.display} scan is stored yet."]
    lines.append(f"It checks {module.covers}.")
    count = rule_count(module)
    if count:
        lines.append(f"{count} rules ship with it on this Core edition.")
    lines.append("Run it from the ShintTools panel and ask me again.")
    return {
        "reply": " ".join(lines),
        "resolved": False,
        "module": module.id,
        "total": 0,
    }


def _trend_sentence(
    current: list[dict[str, Any]], previous: list[dict[str, Any]]
) -> str:
    """Compare against the module's previous scan, or "" when there isn't one."""
    now, before = _fingerprints(current), _fingerprints(previous)
    new, fixed = now - before, before - now
    if not new and not fixed:
        return "Unchanged since the previous scan."

    parts = []
    if new:
        parts.append(f"{len(new)} new")
    if fixed:
        parts.append(f"{len(fixed)} resolved")
    direction = (
        "better" if len(fixed) > len(new)
        else "worse" if len(new) > len(fixed)
        else "level"
    )
    return f"Since the previous scan: {', '.join(parts)} — trending {direction}."


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    module, source = resolve_module(
        str(payload.get("message") or ""),
        str(payload.get("module_context") or ""),
    )
    doc, module = await resolve_analysis(
        module, str(payload.get("context_ref") or "").strip(), source
    )

    if doc is None:
        return _no_scan_reply(module) if module else {
            "reply": _NEED_MODULE, "resolved": False,
        }

    label = module.display if module else "That scan"
    issues = _issues(doc)
    if not issues:
        return {
            "reply": f"{label} came back clean — nothing was flagged.",
            "resolved": True,
            "module": module.id if module else "",
            "total": 0,
        }

    severities = Counter(str(i.get("severity", "info")) for i in issues)
    by_rule = Counter(
        f"{i.get('rule_id', '?')} ({i.get('rule_name', '')})".strip()
        for i in issues
    )
    by_file = Counter(w for w in (_where(i) for i in issues) if w)
    studio_hits = sum(1 for i in issues if i.get("source") == "studio_rule")

    lines = [
        f"{label}: {len(issues)} findings — "
        + ", ".join(f"{n} {sev}" for sev, n in severities.most_common())
        + "."
    ]
    lines.append(
        "Most frequent: "
        + "; ".join(f"{name} x{n}" for name, n in by_rule.most_common(3))
        + "."
    )
    if by_file:
        # The single most actionable line in the whole summary: a rule
        # histogram tells you what kind of problem you have, this tells you
        # where to go first.
        lines.append(
            "Worst offenders: "
            + "; ".join(
                f"{path.rsplit('/', 1)[-1]} ({n})"
                for path, n in by_file.most_common(3)
            )
            + "."
        )
    if studio_hits:
        lines.append(f"{studio_hits} of them come from your own team rules.")

    trend = ""
    if module:
        previous = await latest_analysis(
            module, skip_id=str(doc.get("analysis_id") or "")
        )
        if previous is not None:
            trend = _trend_sentence(issues, _issues(previous))
            if trend:
                lines.append(trend)

    return {
        "reply": " ".join(lines),
        "resolved": True,
        "module": module.id if module else "",
        "total": len(issues),
        "severities": dict(severities),
        "studio_rule_hits": studio_hits,
        "worst_files": dict(by_file.most_common(3)),
        "trend": trend,
    }
