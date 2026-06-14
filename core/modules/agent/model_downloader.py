# core/modules/agent/model_downloader.py
#
# Downloads the configured GGUF model from ShintTools' own GitHub Releases
# using only the Python standard library (urllib + hashlib). NO third-party
# HTTP clients, NO huggingface-hub, NO telemetry.
#
# Why stdlib-only:
#   The studio-facing runtime must not contact any service we don't
#   control. huggingface-hub pings huggingface.co with metadata even
#   for a single-file download, which leaks "this customer is using
#   ShintTools" to a third party. GitHub Releases is infrastructure
#   ShintTools controls and the URL is auditable by the studio's IT.
#
# Idempotency:
#   If the GGUF is already on disk, this script makes ZERO network
#   calls. The first successful install means the on-prem deployment
#   is fully offline from then on.
#
# Integrity:
#   The download lands in <name>.gguf.part first; only after SHA-256
#   matches the expected value is it renamed into place. A tampered or
#   truncated transfer never gets installed.
#
# Run as a script (from core/):
#     python -m modules.agent.model_downloader
#
# Env vars (override the defaults below):
#     SHINTTOOLS_MODEL_URL     full HTTPS URL to the .gguf file
#     SHINTTOOLS_MODEL_SHA256  expected SHA-256 hex digest
#     SHINTTOOLS_MODEL_FILE    filename to save as (must match llm_backend)
#     SHINTTOOLS_MODELS_DIR    target directory (default: core/models/)

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional

from .llm_backend import _resolved_model_path

# Single source of truth for where the dev model is published. When a
# new GGUF is uploaded to GitHub Releases, update BOTH constants
# together (the URL points to the release tag, the SHA-256 must match
# the exact bytes of the uploaded file).
#
# Why a SEPARATE public repo for the model:
#   The main `Noctxas97Dev/ShintTools` repo is private (it holds the
#   product source code). GitHub release-asset URLs on private repos
#   require authentication and return 404 to anonymous clients, which
#   breaks the on-prem install flow for studio customers (their
#   Launcher has no GitHub credentials and shouldn't need any).
#   `Noctxas97Dev/ShintTools-Models` is a separate, public repo that
#   contains ONLY model assets in Releases — no source code, no IP.
#   That keeps anonymous downloads working without compromising the
#   privacy of the main codebase.
#
# DEFAULT_MODEL_SHA256 is the SHA-256 of the Qwen2.5-Coder model file.
# We host it at DEFAULT_MODEL_URL on GitHub Releases —
# bytes must match, otherwise integrity verification rejects the file.
#
# Compute the digest locally with PowerShell:
#     Get-FileHash .\path\to\file.gguf -Algorithm SHA256
# or with Python:
#     python -c "import hashlib, sys; \
#                print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
#         path/to/file.gguf
DEFAULT_MODEL_URL = (
    "https://github.com/Noctxas97Dev/ShintTools-Models/releases/download/"
    "v2.0-models/Qwen2.5-Coder-1.5B-Instruct-Q4_K_M.gguf"
)
DEFAULT_MODEL_SHA256 = (
    "f530705d447660a4336c329981af164b471b60b974b1d808d57e8ec9fe23b239"
)

# 1 MiB chunks — large enough to keep syscall overhead negligible,
# small enough that progress feedback feels live on slow connections.
_CHUNK_BYTES = 1 << 20


def _sha256_of(path: Path) -> str:
    """Return the SHA-256 hex digest of a file, streamed in chunks
    so we don't load the whole GGUF into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _stream_download(url: str, dest: Path) -> None:
    """Download `url` into `dest` using only stdlib HTTP. Raises on
    any non-2xx response. Caller is responsible for cleanup of `dest`
    if this raises."""
    # urlopen on https:// uses the system trust store; GitHub's certs
    # are widely trusted, so no extra config needed on a fresh OS.
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ShintTools-ModelDownloader/1.0"},
    )
    with urllib.request.urlopen(req) as resp:
        total: Optional[int] = None
        try:
            total = int(resp.headers.get("Content-Length", "")) or None
        except ValueError:
            total = None

        with open(dest, "wb") as out:
            written = 0
            while True:
                chunk = resp.read(_CHUNK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if total:
                    pct = (written * 100) // total
                    print(
                        f"  {written / (1 << 20):.1f} / "
                        f"{total / (1 << 20):.1f} MiB ({pct}%)",
                        end="\r",
                        flush=True,
                    )
            print()  # newline after the progress carriage returns


def download_model() -> Path:
    """Download the configured model if not already on disk, verify its
    SHA-256, and return its path. Idempotent: if the file is already
    present, no network call is made.
    """
    target = _resolved_model_path()
    if target.exists():
        print(f"Model already present at {target} — skipping download.")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)

    url = os.environ.get("SHINTTOOLS_MODEL_URL", DEFAULT_MODEL_URL)
    expected_sha = (
        os.environ.get("SHINTTOOLS_MODEL_SHA256", DEFAULT_MODEL_SHA256).strip().lower()
    )

    print(f"Downloading from {url}")
    print(f"Target: {target}")

    # Stage to <name>.part — a partial download from a crashed run
    # never gets used as if it were complete.
    staging = target.with_suffix(target.suffix + ".part")
    if staging.exists():
        staging.unlink()

    try:
        _stream_download(url, staging)
    except Exception:
        if staging.exists():
            staging.unlink()
        raise

    if expected_sha:
        actual_sha = _sha256_of(staging)
        if actual_sha != expected_sha:
            staging.unlink()
            raise RuntimeError(
                "SHA-256 mismatch — refusing to install the file.\n"
                f"  expected: {expected_sha}\n"
                f"  actual:   {actual_sha}\n"
                "The download was corrupted in transit, the URL points "
                "to the wrong file, or the release was tampered with."
            )
        print(f"SHA-256 verified ({actual_sha}).")
    else:
        # Until the release is published with a known digest, fail
        # loudly rather than silently install an unverified blob.
        staging.unlink()
        raise RuntimeError(
            "DEFAULT_MODEL_SHA256 is empty and SHINTTOOLS_MODEL_SHA256 was "
            "not set. Refusing to install an unverified model — set the "
            "env var or hardcode the digest in model_downloader.py."
        )

    staging.rename(target)
    print(f"Model installed at {target}")
    return target


if __name__ == "__main__":
    try:
        download_model()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
