"""Contraseñas (scrypt, stdlib), validación de email y planes/cuotas."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

_N, _R, _P = 2 ** 14, 8, 1
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[A-Za-z]{2,}$")
MIN_PASSWORD = 10

# Planes internos. NO hay cobro integrado: el plan lo asigna un administrador.
PLANS = {
    "free": {"label": "Gratis", "analyses_month": 15, "images_month": 5},
    "premium": {"label": "Premium", "analyses_month": 300, "images_month": 100},
}


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_password(pw: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return scheme == "scrypt" and hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


DUMMY_HASH = hash_password("dummy-password-for-timing")


def normalize_email(e: str) -> str | None:
    e = (e or "").strip().lower()
    return e if EMAIL_RE.match(e) else None


def password_problem(pw: str) -> str | None:
    if len(pw) < MIN_PASSWORD:
        return f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres."
    if len(pw) > 200:
        return "Contraseña demasiado larga."
    if pw.lower() in {"1234567890", "contraseña1", "password123", "qwertyuiop"}:
        return "Contraseña demasiado común."
    return None
