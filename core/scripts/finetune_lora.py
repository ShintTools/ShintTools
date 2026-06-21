# core/scripts/finetune_lora.py
#
# Standalone LoRA fine-tuning for the ShintTools explainer model.
#
# Consumes the JSONL that finetuning_logger.py accumulates every time the
# /agent/explain (and the LOD audit explain=true path) generates an
# explanation, and trains a LoRA adapter on top of the base GGUF's HF
# checkpoint (Qwen2.5-Coder-1.5B-Instruct by default).
#
# This is NOT part of the runtime. The serving path is llama.cpp; this script
# pulls in transformers + peft + torch, which live in requirements-finetune.txt
# and are deliberately kept out of the runtime image. The heavy imports are
# guarded inside main() so importing/scanning this file (e.g. by CI lint) does
# not require the training stack to be installed.
#
# Pipeline (see also the "deploy loop" at the bottom of this header):
#   1. Read every *.jsonl under --logs, reconstruct (prompt, completion) pairs.
#        prompt     = build_explainer_prompt(issue_payload)   # exact runtime prompt
#        completion = explanation_generated                   # the label
#   2. Drop warm-up / empty / degenerate rows.
#   3. Tokenise prompt+completion, mask the prompt tokens in the labels so loss
#      is computed only over the completion.
#   4. LoRA fine-tune (r=16, alpha=32, attn projections) and save the adapter.
#
# Run from the repo root:
#   pip install -r core/requirements-finetune.txt
#   python core/scripts/finetune_lora.py \
#       --logs core/finetuning_logs \
#       --out ./lora-out \
#       --base Qwen/Qwen2.5-Coder-1.5B-Instruct \
#       --epochs 3
#
# Deploy loop — LOD adapter (PREFERRED; keeps the shared Coder intact):
#   train (this script) -> llama.cpp convert_lora_to_gguf.py -> a GGUF LoRA
#     adapter -> point SHINTTOOLS_LOD_LORA_PATH at it.
#   The runtime keeps ONE base Coder GGUF in RAM and attaches this adapter
#   ONLY around LOD enrichment generations (llm_backend.lod_adapter()), so
#   the Deep Code Validator's Coder output is unchanged. Do NOT merge for
#   the LOD case — merging into the served GGUF would also alter the Code
#   Validator (and/or force a second model into RAM).
#
# Deploy loop — full model swap (only if you ever want EVERY module to move
# to the fine-tuned weights):
#   train -> peft merge_and_unload() -> fp16 HF model
#     -> llama.cpp convert_hf_to_gguf.py -> quantize to Q4_K_M
#     -> drop the new .gguf in place of the shipped one.
#   The explainer's cache key includes the model id, so swapping the GGUF
#   auto-invalidates any cached explanations.

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Make `agent` importable as a top-level package, matching how the FastAPI app
# (and smoke_llm_explainer.py) load the modules. We import build_explainer_prompt
# at top level on purpose: it is pure-Python (no torch) and reconstructing the
# prompt the exact same way the runtime does is the whole point — train/serve
# parity. If this import ever starts pulling heavy deps, move it into main().
_CORE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_CORE / "modules"))

from agent.explainer import build_explainer_prompt  # noqa: E402


# ── Dataset assembly (pure Python, no training deps) ───────────────────────


def _iter_jsonl(logs_dir: Path):
    """Yield every record from every *.jsonl under *logs_dir*."""
    for path in sorted(logs_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    print(f"  ! skipping malformed line {path.name}:{line_no}")


def _is_usable(record: dict[str, Any]) -> bool:
    """Filter out warm-up, empty, and degenerate rows."""
    completion = (record.get("explanation_generated") or "").strip()
    payload = record.get("issue_payload") or {}
    rule_name = (record.get("rule_name") or payload.get("rule_name") or "").strip()
    # Warm-up rows carry rule_name == "warmup" and no real grounding.
    if rule_name.lower() == "warmup":
        return False
    if len(completion) < 8:  # empty / "n/a" / truncated
        return False
    if not payload:
        return False
    return True


def build_pairs(logs_dir: Path) -> list[dict[str, str]]:
    """Reconstruct (prompt, completion) training pairs from the logs.

    The prompt is rebuilt with the SAME build_explainer_prompt the runtime
    uses, so the model trains on exactly the inputs it will see in production.
    """
    pairs: list[dict[str, str]] = []
    seen = 0
    for record in _iter_jsonl(logs_dir):
        seen += 1
        if not _is_usable(record):
            continue
        payload = record["issue_payload"]
        try:
            prompt = build_explainer_prompt(payload)
        except Exception as e:  # a stale payload shape shouldn't abort the run
            print(f"  ! skipping row (prompt build failed: {e})")
            continue
        pairs.append(
            {
                "prompt": prompt,
                "completion": record["explanation_generated"].strip(),
            }
        )
    print(f"  parsed {seen} rows -> {len(pairs)} usable training pairs")
    return pairs


# ── Training (heavy deps live inside main) ─────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LoRA fine-tune the ShintTools explainer on collected JSONL.",
    )
    parser.add_argument("--logs", type=Path, default=_CORE / "finetuning_logs",
                        help="Directory of *.jsonl explanation logs.")
    parser.add_argument("--out", type=Path, default=Path("./lora-out"),
                        help="Where to write the trained LoRA adapter.")
    parser.add_argument("--base", type=str,
                        default="Qwen/Qwen2.5-Coder-1.5B-Instruct",
                        help="Base HF model id (must match the served GGUF).")
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--max-len", type=int, default=1024)
    parser.add_argument("--dry-run", action="store_true",
                        help="Build + report the dataset, then exit (no training).")
    args = parser.parse_args()

    if not args.logs.is_dir():
        print(f"ERROR: logs dir not found: {args.logs}")
        print("Run audits/explanations with explain=true first to collect data.")
        return 1

    pairs = build_pairs(args.logs)
    if not pairs:
        print("ERROR: no usable training pairs found — nothing to train.")
        return 1

    if args.dry_run:
        print("Dry run — dataset looks like:")
        print(json.dumps(pairs[0], indent=2)[:800])
        return 0

    # Heavy imports — only reached on a real training run. Kept here so the
    # file imports cleanly without the training stack (CI lint, dataset checks).
    try:
        import torch
        from datasets import Dataset
        from peft import LoraConfig, get_peft_model
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
    except ImportError as e:
        print(f"ERROR: training dependencies missing ({e}).")
        print("Install them with:  pip install -r core/requirements-finetune.txt")
        return 1

    print(f"Loading base model: {args.base}")
    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    )

    lora = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        # Qwen2 attention + MLP projections.
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()

    eos = tokenizer.eos_token or ""

    def tokenize(example: dict[str, str]) -> dict[str, list[int]]:
        # Build prompt + completion; mask the prompt tokens in the labels so the
        # loss is only over the explanation the model should learn to produce.
        prompt_ids = tokenizer(example["prompt"], add_special_tokens=False)["input_ids"]
        completion_ids = tokenizer(
            example["completion"] + eos, add_special_tokens=False
        )["input_ids"]
        input_ids = (prompt_ids + completion_ids)[: args.max_len]
        labels = ([-100] * len(prompt_ids) + completion_ids)[: args.max_len]
        return {"input_ids": input_ids, "labels": labels}

    dataset = Dataset.from_list(pairs).map(
        tokenize, remove_columns=["prompt", "completion"]
    )

    args.out.mkdir(parents=True, exist_ok=True)
    training_args = TrainingArguments(
        output_dir=str(args.out),
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        logging_steps=10,
        save_strategy="epoch",
        report_to=[],
        fp16=torch.cuda.is_available(),
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()

    model.save_pretrained(str(args.out))
    tokenizer.save_pretrained(str(args.out))
    print(f"\nLoRA adapter written to {args.out}")
    print("Next: merge_and_unload -> convert_hf_to_gguf.py -> quantize Q4_K_M -> "
          "swap the served .gguf (see the header for the full deploy loop).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
