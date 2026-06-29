"""Powiadomienia na Discord przez webhook (wzorzec z pricescrapingbots/notify_discord.py)."""

from __future__ import annotations

import requests

GREEN = 0x2ECC71
RED = 0xE74C3C


def mask_account(account_number: str) -> str:
    """Maskuje numer rachunku, zostawiając 4 ostatnie cyfry (np. ****1234)."""
    digits = "".join(ch for ch in account_number if ch.isdigit())
    return f"****{digits[-4:]}" if len(digits) >= 4 else "****"


def _post(webhook_url: str, embed: dict) -> None:
    response = requests.post(webhook_url, json={"embeds": [embed]}, timeout=20)
    response.raise_for_status()


def success(webhook_url: str, bank_name: str, summary: dict) -> None:
    """Powiadomienie o sukcesie przetworzenia jednego maila.

    summary: {accounts: [{account, name, count, range, closing}], statement, subject}
    """
    lines = []
    for acc in summary.get("accounts", []):
        lines.append(
            f"**{acc['name']}** ({mask_account(acc['account'])}): "
            f"{acc['count']} transakcji, {acc['range']}, saldo {acc['closing']}"
        )
    embed = {
        "title": f"✅ {bank_name.upper()} — wyciąg zaimportowany",
        "color": GREEN,
        "description": "\n".join(lines) or "Brak transakcji w wyciągu.",
        "fields": [
            {"name": "Mail", "value": summary.get("subject", "—"), "inline": False},
        ],
    }
    if summary.get("statement"):
        embed["fields"].append(
            {"name": "Wyciąg", "value": str(summary["statement"]), "inline": False}
        )
    _post(webhook_url, embed)


def failure(webhook_url: str, bank_name: str, subject: str, error: Exception, attachment: str | None = None) -> None:
    """Powiadomienie o błędzie przetworzenia jednego maila."""
    err_text = f"{type(error).__name__}: {error}"
    if len(err_text) > 1000:
        err_text = err_text[:1000] + "…"
    fields = [
        {"name": "Mail", "value": subject or "—", "inline": False},
        {"name": "Błąd", "value": err_text, "inline": False},
    ]
    if attachment:
        fields.insert(0, {"name": "Załącznik", "value": attachment, "inline": False})
    embed = {
        "title": f"❌ {bank_name.upper()} — błąd przetwarzania",
        "color": RED,
        "fields": fields,
    }
    _post(webhook_url, embed)


def test(webhook_url: str) -> None:
    """Wyślij testowy embed (do ręcznej weryfikacji webhooka)."""
    _post(webhook_url, {"title": "🔧 Test webhooka", "color": GREEN, "description": "Działa."})
