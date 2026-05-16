"""Encrypt rule modules into .shintenc blobs the secure_loader can decrypt.

Run before building the locked-tier Docker image:

    python tools/encrypt_rules.py --key "<secret>" \\
        --modules-root core/modules

For every entry in shint_secure_loader._ENCRYPTED_MODULES:

    code_validator/rules/csharp/csharp_rules.py
        -> code_validator/rules/csharp/csharp_rules.shintenc

The plaintext .py is left in place — strip it from the image with
the Dockerfile so the encrypted blob is the only thing shipped:

    RUN find core/modules -name "*.py" -path "*/rules/csharp/*" -delete

Threat model + caveats live in shint_secure_loader docstring.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from the repo root without installing the package.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "core"))

from shint_secure_loader import _derive_key, _ENCRYPTED_MODULES  # noqa: E402

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as e:
    print(
        f"cryptography package is required: {e}\n"
        "Install via:  pip install cryptography",
        file=sys.stderr,
    )
    sys.exit(2)


def encrypt_one(path: Path, key: bytes) -> Path:
    """Encrypt a single .py file in place, writing alongside as .shintenc."""
    plaintext = path.read_bytes()
    nonce = os.urandom(12)
    cipher = AESGCM(key).encrypt(nonce, plaintext, None)
    out = path.with_suffix(".shintenc")
    out.write_bytes(nonce + cipher)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--key", required=True,
        help="Shared secret. The loader derives the AES key via HKDF(SHA-256).",
    )
    ap.add_argument(
        "--modules-root", required=True, type=Path,
        help="Path to core/modules — the root containing code_validator/",
    )
    ap.add_argument(
        "--keep-py", action="store_true",
        help="Don't delete the source .py after encrypting (default: delete).",
    )
    args = ap.parse_args()

    if not args.modules_root.is_dir():
        print(f"modules-root does not exist: {args.modules_root}", file=sys.stderr)
        return 1

    key = _derive_key(args.key)
    encrypted_count = 0
    for rel in _ENCRYPTED_MODULES:
        py_path = args.modules_root / rel
        if not py_path.is_file():
            print(f"skipping (missing): {py_path}", file=sys.stderr)
            continue
        out = encrypt_one(py_path, key)
        print(f"  {py_path}  ->  {out}  ({out.stat().st_size} bytes)")
        encrypted_count += 1
        if not args.keep_py:
            py_path.unlink()
            print(f"    removed plaintext: {py_path}")

    print(f"\nEncrypted {encrypted_count} module(s).")
    return 0 if encrypted_count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
