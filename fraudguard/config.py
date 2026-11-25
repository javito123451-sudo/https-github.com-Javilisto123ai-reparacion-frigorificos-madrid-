from __future__ import annotations

import os
from dataclasses import dataclass


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    model: str = "gpt-4o"
    db_path: str = "data/fraudguard.db"
    retention_days: int = 30
    rate_per_hour: int = 30
    daily_llm_calls: int = 500
    max_text_chars: int = 20_000
    max_images: int = 4
    max_image_bytes: int = 8 * 1024 * 1024
    # Solo para pruebas: permite resolver IPs privadas en el extractor de URLs.
    allow_private_fetch: bool = False
    # Si es True, httpx usa HTTP(S)_PROXY del entorno (p. ej. despliegues tras proxy corporativo).
    fetch_trust_env: bool = False
    secure_cookies: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model=os.getenv("FG_MODEL", cls.model),
            db_path=os.getenv("FG_DB", cls.db_path),
            retention_days=_int("FG_RETENTION_DAYS", cls.retention_days),
            rate_per_hour=_int("FG_RATE_PER_HOUR", cls.rate_per_hour),
            daily_llm_calls=_int("FG_DAILY_LLM_CALLS", cls.daily_llm_calls),
            allow_private_fetch=_bool("FG_ALLOW_PRIVATE_FETCH"),
            fetch_trust_env=_bool("FG_FETCH_TRUST_ENV"),
            secure_cookies=_bool("FG_SECURE_COOKIES"),
        )
