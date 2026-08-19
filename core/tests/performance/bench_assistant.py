# core/tests/performance/bench_assistant.py
#
# ShintTools AI Assistant — end-to-end benchmark over the Unreal client's
# real request path.
#
# This deliberately measures POST /assistant/message/stream, NOT the plain
# endpoint: FShintCoreClient::SendAssistantMessage (the blocking variant)
# has zero callers in the UE5 plugin, so every request a user actually
# generates is SSE. Benchmarking the plain endpoint would produce numbers
# no user ever experiences.
#
# Request bodies are assembled by the same rule BuildAssistantBody uses
# (ShintCoreClient_Assistant.cpp:127): api_key/message/engine always,
# everything else only when non-empty. Sending an empty "intent" would not
# be replaying this client — the server's router behaves differently when
# the field is absent versus present-and-blank.
#
# The cases are the five real trigger points in the plugin: free-typed
# chat, the three quick-prompt chips, and the Code Validator row Explain
# button (measured both grounded and degraded).
#
# Usage (from core/):
#   python tests/performance/bench_assistant.py
#   python tests/performance/bench_assistant.py --url http://localhost:18200
#   python tests/performance/bench_assistant.py --repeat 10
#
# What to look for: TTFT (time to first token) is the number that decides
# how responsive the dock feels — a 12 s reply that starts streaming at
# 0.4 s reads as fast, and one that starts at 11 s reads as frozen. Total
# time alone hides that entirely.

from __future__ import annotations

import argparse
import json
import statistics
import time
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:18200"
DEFAULT_KEY = "sk_bench_studio"

# The UE5 client's own headers, verbatim (ShintCoreClient.cpp:388-390).
UE5_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "text/event-stream",
    "User-Agent": "ShintTools-UE5/1.1",
}

# The client's stream timeout (ShintCoreClient.cpp:421). Requests get the
# same ceiling here so a benchmark run cannot "succeed" on a response the
# real client would have abandoned.
UE5_STREAM_TIMEOUT = 180.0


def build_body(api_key: str, message: str, **optional: Any) -> dict[str, Any]:
    """Assemble a request the way BuildAssistantBody does.

    Empty optional fields are OMITTED, not sent blank — see module header.
    """
    body: dict[str, Any] = {"api_key": api_key, "message": message}
    for field, value in optional.items():
        if value:
            body[field] = value
    body["engine"] = "unreal"
    return body


def stream_once(
    client: httpx.Client, url: str, body: dict[str, Any]
) -> dict[str, Any]:
    """One SSE turn. Returns timings and what the stream actually carried.

    Framing follows FShintSseParser (ShintCoreClient.cpp:52-157): events are
    split on a bare blank line and only lines starting with "data:" are
    read. Parsing it the same way here means an SSE framing regression shows
    up as a benchmark failure instead of silently passing.
    """
    t0 = time.perf_counter()
    ttft: float | None = None
    chunks = 0
    text_parts: list[str] = []
    done = False
    error = ""
    buffer = ""

    with client.stream(
        "POST",
        url + "/assistant/message/stream",
        json=body,
        headers=UE5_HEADERS,
        timeout=UE5_STREAM_TIMEOUT,
    ) as response:
        status = response.status_code
        if status != 200:
            failed = response.read().decode("utf-8", "replace")
            return {
                "status": status,
                "ttft": None,
                "total": time.perf_counter() - t0,
                "chunks": 0,
                "text": "",
                "done": False,
                "error": failed[:200],
            }
        for raw in response.iter_text():
            buffer += raw
            while "\n\n" in buffer:
                event, buffer = buffer.split("\n\n", 1)
                line = event.strip()
                if not line.startswith("data:"):
                    continue
                try:
                    payload = json.loads(line[len("data:"):].strip())
                except json.JSONDecodeError:
                    continue
                if payload.get("chunk"):
                    if ttft is None:
                        ttft = time.perf_counter() - t0
                    chunks += 1
                    text_parts.append(payload["chunk"])
                elif payload.get("error"):
                    error = error or str(payload["error"])
                elif payload.get("done"):
                    done = True
                    if payload.get("full_text"):
                        text_parts = [payload["full_text"]]

    return {
        "status": status,
        "ttft": ttft,
        "total": time.perf_counter() - t0,
        "chunks": chunks,
        "text": "".join(text_parts),
        "done": done,
        "error": error,
    }


def seed_analysis(
    client: httpx.Client, url: str, api_key: str
) -> tuple[str, list[dict[str, Any]]]:
    """Run a real scan so context_ref resolves to a stored analysis.

    explain_finding answers from a constant string when it cannot resolve a
    finding, so without this the LLM case would silently measure the
    fallback path and report it as if the model had run.
    """
    assets = [
        {
            "asset_path": "/Game/Textures/rockDiffuse_" + str(i),
            "name": "rockDiffuse_" + str(i),
            "type": "Texture2D",
            "category": "",
        }
        for i in range(25)
    ]
    response = client.post(
        url + "/assets/scan",
        json={"api_key": api_key, "asset_paths": assets, "engine": "unreal"},
        timeout=60.0,
    )
    response.raise_for_status()
    data = response.json()
    return data.get("analysis_id", ""), data.get("issues", [])


def build_cases(
    api_key: str, analysis_id: str, first: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """The five real trigger points, in the order a user meets them."""
    rule_name = first.get("rule_name") or "this rule"
    return [
        ("chip: What can you do?", build_body(
            api_key, "What can you help me with?", intent="general_help")),
        ("chip: Why this rule?", build_body(
            api_key, "Why does this rule exist?", intent="why_rule",
            context_ref=analysis_id, rule_id=first.get("rule_id", ""),
            module_context="asset_naming")),
        ("chip: Summarize this scan", build_body(
            api_key, "Summarize this analysis.", intent="summarize_module",
            context_ref=analysis_id, module_context="asset_naming")),
        ("free chat (router classifies)", build_body(
            api_key, "how is the asset naming bot doing?",
            context_ref=analysis_id, module_context="asset_naming")),
        ("row Explain (LLM narration)", build_body(
            api_key, 'Why is "' + rule_name + '" flagged?',
            intent="explain_finding", context_ref=analysis_id,
            rule_id=first.get("rule_id", ""),
            asset_path=first.get("asset_path", ""),
            module_context="asset_naming")),
        # The same button with nothing to resolve — the degraded path. Kept
        # separate because averaging a constant string together with LLM
        # narration would describe neither.
        ("row Explain (no context: degraded)", build_body(
            api_key, "Why is this flagged?", intent="explain_finding")),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ShintTools AI Assistant end-to-end benchmark"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--api-key", default=DEFAULT_KEY)
    parser.add_argument("--repeat", type=int, default=5,
                        help="timed iterations per case (default 5)")
    args = parser.parse_args()

    with httpx.Client() as client:
        health = client.get(args.url + "/health", timeout=10.0).json()
        print("\nShintTools AI Assistant — end-to-end benchmark")
        print("  URL     : " + args.url)
        print("  Version : {} ({})".format(
            health.get("version"), health.get("edition")))
        print("  LLM     : " + str(health.get("llm_status")))
        print("  Repeat  : {} timed iterations (+1 warm-up)".format(args.repeat))
        print("-" * 74)

        analysis_id, issues = seed_analysis(client, args.url, args.api_key)
        first = issues[0] if issues else {}
        print("  Seeded analysis {} with {} findings".format(
            analysis_id, len(issues)))
        print("-" * 74)

        rows: list[dict[str, Any]] = []
        for label, body in build_cases(args.api_key, analysis_id, first):
            stream_once(client, args.url, body)  # warm-up, discarded
            ttfts: list[float] = []
            totals: list[float] = []
            sample: dict[str, Any] = {}
            for _ in range(args.repeat):
                result = stream_once(client, args.url, body)
                sample = result
                totals.append(result["total"])
                if result["ttft"] is not None:
                    ttfts.append(result["ttft"])
            rows.append({
                "case": label,
                "status": sample.get("status"),
                "chunks": sample.get("chunks", 0),
                "ttft_p50": statistics.median(ttfts) if ttfts else None,
                "total_p50": statistics.median(totals),
                "total_max": max(totals),
                "preview": sample.get("text", "")[:64].replace("\n", " "),
            })

        header = "{:<36}{:>9}{:>11}{:>11}{:>8}".format(
            "case", "TTFT", "p50", "max", "chunks")
        print("\n" + header)
        print("-" * 74)
        for row in rows:
            ttft = ("{:.0f} ms".format(row["ttft_p50"] * 1000)
                    if row["ttft_p50"] else "—")
            print("{:<36}{:>9}{:>9.0f}ms{:>9.0f}ms{:>8}".format(
                row["case"], ttft, row["total_p50"] * 1000,
                row["total_max"] * 1000, row["chunks"]))

        print("\nReplies (truncated):")
        for row in rows:
            print("  [{}] {}: {}".format(
                row["status"], row["case"], row["preview"]))

        # A 403 is the cheapest possible response and sets the transport
        # floor everything above is measured against.
        gate = stream_once(client, args.url, build_body(
            "", "Summarize this analysis.", intent="summarize_module"))
        print("\nFree-tier gate (transport floor): HTTP {} in {:.0f} ms".format(
            gate["status"], gate["total"] * 1000))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
