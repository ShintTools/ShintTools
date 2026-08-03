# core/modules/assistant/actions/simulate_change.py
#
# "What if I fix these five?" — narrated over the real Impact Simulator.
#
# Wraps predictive's layer5_simulator against a cached report; no new cost
# model, no second opinion. The action's whole job is turning a selection
# the UI already made into the simulator's inputs and the simulator's
# deltas into a sentence. If there's no report to replay against, it says
# so — it never estimates an outcome.

from __future__ import annotations

from typing import Any

_NEED_REPORT = (
    "I need a Predictive Profiler run to simulate against. Analyze the "
    "project in the Predictive panel, then ask again and I'll replay your "
    "selection over those numbers."
)

_NEED_SELECTION = (
    "Pick the issues you'd fix (tick them in the panel) and I'll tell you "
    "what the frame and memory budgets look like afterwards."
)


def _format_deltas(deltas: dict[str, Any]) -> str:
    """Deltas are negative recoveries — render them as savings."""
    parts: list[str] = []
    for dim, pred in deltas.items():
        expected = getattr(pred, "expected", None)
        if expected is None and isinstance(pred, dict):
            expected = pred.get("expected")
        if expected is None:
            continue
        unit = getattr(pred, "unit", "") or (
            pred.get("unit", "") if isinstance(pred, dict) else ""
        )
        parts.append(f"{abs(float(expected)):.2f} {unit} of {dim}".strip())
    return ", ".join(parts)


async def run(payload: dict[str, Any]) -> dict[str, Any]:
    report_id = str(payload.get("report_id") or payload.get("context_ref") or "")
    selected = list(payload.get("selected_item_ids") or [])

    if not report_id:
        return {"reply": _NEED_REPORT, "simulated": False}
    if not selected:
        return {"reply": _NEED_SELECTION, "simulated": False}

    try:
        from predictive.layers.layer5_simulator import simulate
        from predictive.session_store import get_report
    except ImportError:
        return {"reply": _NEED_REPORT, "simulated": False}

    report = await get_report(report_id)
    if report is None:
        return {
            "reply": (
                "That analysis has expired from the cache. Re-run the "
                "Predictive Profiler and I'll simulate against the fresh one."
            ),
            "simulated": False,
        }

    result = simulate(
        report,
        selected,
        inline_items=[],
        platform_profile=str(payload.get("platform_profile") or ""),
    )

    deltas = getattr(result, "deltas", {}) or {}
    savings = _format_deltas(deltas)
    count = getattr(result, "selected_count", len(selected))

    if not savings:
        reply = (
            f"Fixing those {count} wouldn't move the budgets measurably — "
            "their recorded recovery is negligible on this profile."
        )
    else:
        reply = f"Fixing those {count} frees roughly {savings}."

    recommendations = getattr(result, "recommendations", []) or []
    if recommendations:
        top = recommendations[0]
        title = getattr(top, "title", "") or (
            top.get("title", "") if isinstance(top, dict) else ""
        )
        if title:
            reply += f" The biggest remaining item after that would be {title}."

    return {
        "reply": reply,
        "simulated": True,
        "selected_count": count,
        "report_id": report_id,
    }
