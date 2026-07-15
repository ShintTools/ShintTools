# core/modules/agent/finetuning_logger.py
#
# Log LLM explanations to local JSONL files for potential fine-tuning.
# Bypasses MongoDB cache — every explanation is freshly generated and logged.

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


def get_finetuning_log_dir() -> Path:
    """Return the directory where fine-tuning logs are stored.

    Reads SHINTTOOLS_FINETUNING_DIR env var or defaults to
    core/finetuning_logs/.
    """
    env_dir = os.environ.get("SHINTTOOLS_FINETUNING_DIR")
    if env_dir:
        return Path(env_dir)

    return Path(__file__).resolve().parent.parent.parent / "finetuning_logs"


def log_explanation(
    rule_id: str,
    rule_name: str,
    rule_explanation: str,
    explanation_generated: str,
    issue_payload: Mapping[str, Any],
    generation_seconds: float,
    source: str = "live",
) -> None:
    """Log a generated explanation to a JSONL file for fine-tuning.

    One entry per line, no MongoDB interaction. Overwrites are not
    possible — only appends. Files are organized by date (YYYY-MM-DD).

    Args:
        rule_id: e.g., "CS001"
        rule_name: e.g., "LINQ operator in Update"
        rule_explanation: the full explanation text from the rule
        explanation_generated: the LLM's generated explanation
        issue_payload: the full issue dict sent to the explainer
        generation_seconds: how long the LLM took (or 0 on prefab)
        source: "live" (real LLM generation) or "prefab" (curated answer
            served instantly). The fine-tune pipeline trains only on
            "live" pairs — prefab text describes a synthetic snippet,
            not the user's real code, so pairing it with the real
            issue_payload would teach hallucination.
    """
    log_dir = get_finetuning_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)

    # File: YYYY-MM-DD.jsonl
    today = datetime.utcnow().strftime("%Y-%m-%d")
    log_file = log_dir / f"{today}.jsonl"

    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "rule_id": rule_id,
        "rule_name": rule_name,
        "rule_explanation": rule_explanation,
        "explanation_generated": explanation_generated,
        "generation_seconds": generation_seconds,
        "source": source,
        "issue_payload": dict(issue_payload),
    }

    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        # Best-effort: log failures do not affect the API response.
        print(f"WARNING: Failed to log explanation to {log_file}: {e}")
