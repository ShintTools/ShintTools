# core/scripts/assistant_composite_eval.py
#
# Companion to assistant_router_eval.py, which measures the router's layers
# in ISOLATION (classify_by_keywords, _classify_by_llm). Production never
# calls either directly — it calls classify(), which tries the explicit
# performative markers first, then the LLM, then the keyword table. So the
# per-layer numbers describe components, not behaviour.
#
# That distinction turned out to matter: measured on this box, the LLM
# layer alone scores well below the keyword layer, but several of its worst
# intents (define_rule, remember_fact, recall_fact) are exactly the ones
# layer 0 catches before the model is ever consulted. Reporting the layer
# number as "the router's accuracy" would be unfair in one direction, and
# reporting the keyword number would be unfair in the other.
#
# Also reports the source distribution — which layer actually decided each
# turn — because that is what says how much of the router's behaviour the
# model is responsible for at all.
#
# Usage (from core/):
#   python scripts/assistant_composite_eval.py          # no model: explicit + keywords
#   python scripts/assistant_composite_eval.py --llm    # loads the GGUF

from __future__ import annotations

import argparse
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "modules"))

import yaml  # noqa: E402

GOLDEN = (
    Path(__file__).resolve().parent.parent
    / "modules" / "assistant" / "eval" / "golden_intents.yaml"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true",
                        help="load the model so the LLM layer participates")
    args = parser.parse_args()

    pairs = yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["pairs"]
    print(f"golden set: {len(pairs)} pairs")

    if args.llm:
        from modules.agent.llm_backend import load_model
        from modules.assistant import model_profile as mp
        from modules.assistant.model_profile import resolve_profile
        import os

        profile, reason = resolve_profile("advanced")
        print("profile: " + profile + (f" (downgraded: {reason})" if reason else ""))
        config = mp.profile_config(profile)
        os.environ["SHINTTOOLS_MODELS_DIR"] = str(config["models_dir"])
        os.environ["SHINTTOOLS_MODEL_FILE"] = config["model_file"]
        load_model(n_ctx=config["n_ctx"])
    else:
        print("profile: none (LLM layer will return None and fall through)")

    from modules.assistant.intent_router import classify

    hits = 0
    sources: Counter[str] = Counter()
    per_source_hits: Counter[str] = Counter()
    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    latencies: list[float] = []

    for pair in pairs:
        t0 = time.perf_counter()
        got, source = classify(pair["message"])
        latencies.append(time.perf_counter() - t0)
        expected = pair["intent"]
        sources[source] += 1
        correct = got == expected
        hits += correct
        per_source_hits[source] += correct
        if not correct:
            confusion[expected][got] += 1

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p95 = latencies[int(len(latencies) * 0.95)]

    print("\n== classify() — the composite the API actually calls ==")
    print(f"  accuracy: {hits}/{len(pairs)} = {hits / len(pairs):.1%}")
    print(f"  latency:  p50 {p50 * 1000:.0f} ms / p95 {p95 * 1000:.0f} ms")

    print("\n  decided by layer:")
    for source, count in sources.most_common():
        correct = per_source_hits[source]
        print(f"    {source:<12} {count:>3} turns   {correct}/{count} correct"
              f" ({correct / count:.0%})")

    if confusion:
        print("\n  misses:")
        for expected, got_counts in sorted(confusion.items()):
            print(f"    {expected}: -> {dict(got_counts)}")

    # The module label is only ever checked against the keyword layer in CI;
    # nothing verifies the resolver agrees once the model is in the loop.
    from modules.assistant.module_resolver import resolve_module

    directed = [p for p in pairs if p.get("module")]
    resolved = sum(
        1 for p in directed
        if (lambda m: m is not None and m.id == p["module"])(
            resolve_module(p["message"])[0]
        )
    )
    print(f"\n  module resolution: {resolved}/{len(directed)} "
          f"module-directed pairs resolve to the right module")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
