"""Secure loader for rule modules in tier-locked deployments.

Goal:
    Free-tier core engine ships rule files (fix_patterns.py,
    csharp_rules.py, unity_graph_rules.py …) as AES-256-GCM blobs
    on disk: `<module>.shintenc` instead of `<module>.py`. The
    loader resolves the env-var key, decrypts each blob in memory
    only, and registers a synthetic module so the rest of the core
    keeps importing exactly the same way (no rule-side code needs
    to know encryption is happening).

Threat model:
    This is NOT DRM against a determined attacker — the AES key
    ends up in process memory on every run. The point is to:

      * Stop casual `unzip image | cat *.py` browsing of the
        free-tier container.
      * Force activation traffic on first run so we know who's
        running what.
      * Prevent unmodified copy-paste of the rule catalogue into
        someone else's product.

Key derivation:
    `SHINTTOOLS_AGENT_KEY` is the env var the launcher injects
    after a successful indie sign-in. The actual AES key is
    HKDF(SHA-256, info=b"shinttools-rules-v1") so rotating the
    info string invalidates every older container's keys without
    requiring a user-facing key change.

Free-tier (no key):
    The loader returns early; nothing decrypts; rule modules are
    not registered. The /validate/* routes check
    `app.state.has_decrypted_rules` and return 403 with an
    upgrade message when the loader didn't activate.
"""

from __future__ import annotations

import os
import sys
import types
import logging
from pathlib import Path
from typing import Iterable, Optional

LOG = logging.getLogger("shinttools.secure_loader")

# Modules we ship encrypted. Each path is relative to <core>/modules
# and ends in .py (the loader transparently swaps the suffix to
# .shintenc when reading from disk).
_ENCRYPTED_MODULES: tuple[str, ...] = (
    "code_validator/parsers/fixers/fix_patterns.py",
    "code_validator/rules/csharp/csharp_rules.py",
    "code_validator/rules/unity_graphs/unity_graph_rules.py",
)

# Bumping the info bytes invalidates every previously-shipped blob.
# Bump it whenever we re-encrypt with a rule-format breaking change.
_HKDF_INFO = b"shinttools-rules-v1"
_HKDF_SALT = b"shinttools-fixed-salt"   # constant per design — same key derivation across hosts


def _derive_key(secret: str) -> bytes:
    """HKDF(SHA-256) -> 32-byte AES key. Pure stdlib fallback path
    used in tests where cryptography may be absent; production
    code always has cryptography available (requirements pin)."""
    try:
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        from cryptography.hazmat.primitives.hashes import SHA256
        return HKDF(algorithm=SHA256(), length=32, salt=_HKDF_SALT,
                    info=_HKDF_INFO).derive(secret.encode("utf-8"))
    except ImportError:
        # Last-ditch stdlib HKDF emulation — RFC 5869 inline.
        import hashlib, hmac
        prk = hmac.new(_HKDF_SALT, secret.encode("utf-8"), hashlib.sha256).digest()
        t = hmac.new(prk, _HKDF_INFO + b"\x01", hashlib.sha256).digest()
        return t  # length=32, single block


def _decrypt_blob(blob: bytes, key: bytes) -> bytes:
    """AES-256-GCM decryption. Layout: 12B nonce || ciphertext || 16B tag."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if len(blob) < 28:
        raise ValueError("encrypted blob too short (need >= 28 bytes)")
    nonce, ciphertext = blob[:12], blob[12:]
    return AESGCM(key).decrypt(nonce, ciphertext, None)


def _install_module(qual_name: str, source: str, file_path: Path) -> None:
    """Register a synthetic module under `qual_name` whose body is
    the decrypted source text. We compile + exec so tracebacks
    still point at the encrypted file's path (helps debugging
    without leaking source through __loader__.get_source)."""
    mod = types.ModuleType(qual_name)
    mod.__file__ = str(file_path)
    code = compile(source, str(file_path), "exec")
    exec(code, mod.__dict__)
    sys.modules[qual_name] = mod


def _path_to_module(rel_py: str) -> str:
    """code_validator/rules/csharp/csharp_rules.py -> code_validator.rules.csharp.csharp_rules"""
    return rel_py[:-3].replace("/", ".").replace("\\", ".")


def try_activate(modules_root: Path,
                 secret: Optional[str] = None,
                 entries: Iterable[str] = _ENCRYPTED_MODULES) -> bool:
    """Decrypt every entry under `modules_root` using the env-derived
    key. Returns True when at least one .shintenc was decrypted and
    installed as a sys.module — the /validate/* routes use that flag
    to decide whether to serve real rules or 403.

    Layout contract:
        modules_root/code_validator/rules/csharp/csharp_rules.shintenc
        modules_root/code_validator/rules/csharp/csharp_rules.py     ← absent in free image

    On a plain dev install both files may coexist; .py wins because
    Python's import system finds it first and the loader is a no-op.
    The shintenc files only matter in the locked container variant.
    """
    secret = secret if secret is not None else os.environ.get("SHINTTOOLS_AGENT_KEY", "")
    if not secret:
        LOG.warning(
            "[secure_loader] SHINTTOOLS_AGENT_KEY not set — leaving rule "
            "modules unloaded. /validate/* will return 403 until the "
            "launcher injects a valid indie key."
        )
        return False

    key = _derive_key(secret)
    decrypted_any = False
    for rel in entries:
        plaintext_py = modules_root / rel
        encrypted    = modules_root / (rel[:-3] + ".shintenc")

        # Prefer plain .py when present (dev environment, CI, anyone
        # running from source). Only fall into decryption when the
        # encrypted blob is the only artefact on disk.
        if plaintext_py.exists():
            LOG.debug(f"[secure_loader] {rel} present as .py — skipping decrypt")
            continue
        if not encrypted.exists():
            LOG.warning(f"[secure_loader] {rel}: neither .py nor .shintenc found")
            continue

        try:
            blob = encrypted.read_bytes()
            source = _decrypt_blob(blob, key).decode("utf-8")
        except Exception as e:
            LOG.error(f"[secure_loader] {rel}: decrypt failed — {e}")
            continue

        qual = _path_to_module(rel)
        try:
            _install_module(qual, source, encrypted)
            decrypted_any = True
            LOG.info(f"[secure_loader] decrypted + installed {qual}")
        except Exception as e:
            LOG.error(f"[secure_loader] {rel}: exec failed — {e}")

    return decrypted_any
