"""Symmetric encryption utilities for secret storage.

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the ``cryptography``
package.  The key is derived from ``settings.encryption_key`` via
SHA-256 so any passphrase length is accepted.
"""

import base64
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet

from terminals.config import settings

_fernet: Fernet | None = None

_KEY_FILE = Path(settings.data_dir) / ".encryption_key"


def _get_fernet() -> Fernet:
    """Return a cached Fernet instance, bootstrapping the key if needed."""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = settings.encryption_key
    if not key:
        # Auto-generate and persist a key on first use.
        if _KEY_FILE.exists():
            key = _KEY_FILE.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
            _KEY_FILE.write_text(key)
            os.chmod(_KEY_FILE, 0o600)

        settings.encryption_key = key

    # Derive a valid 32-byte Fernet key from an arbitrary passphrase.
    raw = hashlib.sha256(key.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(raw)
    _fernet = Fernet(fernet_key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string → URL-safe base64 ciphertext."""
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string → original plaintext."""
    return _get_fernet().decrypt(ciphertext.encode()).decode()
