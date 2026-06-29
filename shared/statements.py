"""Pomocnicze operacje na sparsowanych wyciągach: walidacja, CSV, mapowanie kont."""

from __future__ import annotations

import csv
import json
from decimal import Decimal
from pathlib import Path

from .models import ParsedStatement

CENT = Decimal("0.01")


def normalize_account(account_number: str) -> str:
    """Same cyfry numeru rachunku."""
    return "".join(ch for ch in account_number if ch.isdigit())


class BalanceMismatchError(Exception):
    """Suma transakcji nie zgadza się z saldami — prawdopodobny błąd parsera."""


def validate_balance(stmt: ParsedStatement) -> None:
    """Bezpiecznik parsera: saldo_pocz + Σ kwot == saldo_końc (tolerancja 1 gr)."""
    total = sum((tx.amount for tx in stmt.transactions), Decimal("0"))
    expected = stmt.opening_balance + total
    if abs(expected - stmt.closing_balance) > CENT:
        raise BalanceMismatchError(
            f"saldo_pocz {stmt.opening_balance} + suma {total} = {expected}, "
            f"a saldo_końc = {stmt.closing_balance}"
        )


def map_account(accounts_path: Path, account_number: str) -> str:
    """Mapuje numer rachunku na nazwę konta Actual wg accounts.json.

    Klucz w accounts.json to końcówka numeru; dopasowujemy najdłuższy pasujący sufiks.
    """
    if not accounts_path.exists():
        raise FileNotFoundError(f"Brak pliku mapowania kont: {accounts_path}")
    mapping: dict[str, str] = json.loads(accounts_path.read_text(encoding="utf-8"))
    normalized = normalize_account(account_number)
    candidates = [
        (key, name)
        for key, name in mapping.items()
        if normalized.endswith(normalize_account(key))
    ]
    if not candidates:
        raise KeyError(
            f"Numer rachunku {normalized} nie ma mapowania w {accounts_path.name} — dodaj wpis."
        )
    _, name = max(candidates, key=lambda kv: len(kv[0]))
    return name


def write_csv(data_dir: Path, bank: str, stmt: ParsedStatement) -> Path:
    """Zrzuca transakcje do CSV (audyt). Plik trafia do data/ (gitignored)."""
    normalized = normalize_account(stmt.account_number)
    stmt_no = str(stmt.meta.get("statement_no", "")).replace("/", "-") or "wyciag"
    out_dir = data_dir / bank
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{normalized}_{stmt_no}.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["data_ksiegowania", "data_transakcji", "opis", "kontrahent", "kwota", "saldo_po"]
        )
        for tx in stmt.transactions:
            writer.writerow(
                [
                    tx.booking_date.isoformat(),
                    tx.transaction_date.isoformat(),
                    tx.description,
                    tx.payee,
                    str(tx.amount),
                    str(tx.balance_after),
                ]
            )
    return path
