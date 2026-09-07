"""Symmetric encryption for the one genuinely sensitive autofill-profile field
(the throwaway "application password" some ATS's require to create an account
during apply). Stored encrypted at rest; decrypted only transiently, server
side, at the moment a form is actually being filled — never echoed back to the
browser in plaintext via GET /api/extension/profile.
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _fernet() -> Fernet:
    secret = os.getenv("AUTOFILL_SECRET_KEY", "").strip() or os.getenv("JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("JWT_SECRET (or AUTOFILL_SECRET_KEY) is not configured.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
