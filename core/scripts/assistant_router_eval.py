# core/scripts/assistant_router_eval.py
#
# M4 harness: measure the intent router against the golden set, per layer
# and per model profile. Dev-only — runs where a model is installed, never
# in CI (CI covers the keyword layer through the anti-drift test).
#
# Usage (from core/):
#   python scripts/assistant_router_eval.py                 # keyword layer only
#   python scripts/assistant_router_eval.py --llm           # + loaded model
#   SHINTTOOLS_ASSISTANT_PROFILE=advanced \
#   python scripts/assistant_router_eval.py --llm           # advanced profile
#
# Output: accuracy per layer, per-intent confusion, latency percentiles,
# and peak RSS — the numbers the "advanced as Studio default" decision
# needs. Compare one run per profile on the same machine.

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

import yaml  # noqa: E402

GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "modules" / "assistant" / "eval" / "golden_intents.yaml"
)


def _peak_rss_gb() -> float | None:
    try:
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024**2)
    except ImportError:
        return None  # Windows dev box — measure via Docker stats instead


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true",
                        help="load the model and evaluate the LLM layer")
    args = parser.parse_args()

    pairs = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["pairs"]
    print(f"golden set: {len(pairs)} pairs\n")

    from modules.assistant.intent_router import classify_by_keywords

    # Callable[[str], str], not the `callable` builtin — that is a function,
    # not a type, so the annotation was never checking anything.
    layers: dict[str, Callable[[str], str]] = {"keywords": classify_by_keywords}

    if args.llm:
        from modules.assistant.model_profile import resolve_profile
        from modules.agent.llm_backend import load_model

        profile, reason = resolve_profile("advanced")
        print(f"profile: {profile}" + (f" (downgraded: {reason})" if reason else ""))

        from modules.assistant import model_profile as mp
        import os

        config = mp.profile_config(profile)
        os.environ["SHINTTOOLS_MODELS_DIR"] = str(config["models_dir"])
        os.environ["SHINTTOOLS_MODEL_FILE"] = config["model_file"]
        load_model(n_ctx=config["n_ctx"])

        from modules.assistant.intent_router import _classify_by_llm

        layers["llm"] = lambda m: _classify_by_llm(m) or "OFF_MENU"

    for layer_name, fn in layers.items():
        hits = 0
        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        latencies: list[float] = []
        for pair in pairs:
            t0 = time.perf_counter()
            got = fn(pair["message"])
            latencies.append(time.perf_counter() - t0)
            expected = pair["intent"]
            confusion[expected][got] += 1
            hits += got == expected

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]
        print(f"== {layer_name} ==")
        print(f"  accuracy: {hits}/{len(pairs)} = {hits / len(pairs):.1%}")
        print(f"  latency:  p50 {p50 * 1000:.0f} ms / p95 {p95 * 1000:.0f} ms")
        for expected, got_counts in sorted(confusion.items()):
            wrong = {k: v for k, v in got_counts.items() if k != expected}
            if wrong:
                print(f"  {expected}: missed -> {dict(wrong)}")
        print()

    rss = _peak_rss_gb()
    if rss is not None:
        print(f"peak RSS: {rss:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
