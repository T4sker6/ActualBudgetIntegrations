"""Wczytanie i walidacja konfiguracji z .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """Brakująca lub niepoprawna konfiguracja."""


@dataclass
class Config:
    enabled_banks: list[str]
    imap_host: str
    imap_user: str
    imap_app_password: str
    discord_webhook_url: str
    actual_base_url: str
    actual_password: str
    actual_encryption_password: str | None
    actual_file: str
    actual_verify_ssl: bool

    def pdf_password(self, env_name: str) -> str:
        """Hasło do PDF danego banku (np. VELO_PDF_PASSWORD)."""
        value = os.getenv(env_name, "").strip()
        if not value:
            raise ConfigError(f"Brak hasła do PDF w zmiennej {env_name} (.env).")
        return value


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"Brak wymaganej zmiennej {name} w .env.")
    return value


def load() -> Config:
    """Wczytaj .env i zwaliduj wymagane pola wspólne."""
    load_dotenv(BASE_DIR / ".env")

    enabled = [b.strip().lower() for b in os.getenv("ENABLED_BANKS", "").split(",") if b.strip()]

    encryption = os.getenv("ACTUAL_ENCRYPTION_PASSWORD", "").strip() or None
    verify_ssl = os.getenv("ACTUAL_VERIFY_SSL", "true").strip().lower() not in ("false", "0", "no")

    return Config(
        enabled_banks=enabled,
        imap_host=_require("IMAP_HOST"),
        imap_user=_require("IMAP_USER"),
        imap_app_password=_require("IMAP_APP_PASSWORD"),
        discord_webhook_url=_require("DISCORD_WEBHOOK_URL"),
        actual_base_url=_require("ACTUAL_BASE_URL"),
        actual_password=_require("ACTUAL_PASSWORD"),
        actual_encryption_password=encryption,
        actual_file=_require("ACTUAL_FILE"),
        actual_verify_ssl=verify_ssl,
    )
