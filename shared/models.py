"""Wspólne modele danych i kontrakt, który implementuje każdy bank."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class Transaction:
    """Pojedyncza transakcja z wyciągu."""

    booking_date: date  # data księgowania — używana jako data w Actual
    transaction_date: date  # data transakcji
    description: str  # pełny, znormalizowany opis -> notes w Actual
    payee: str  # kontrahent / typ -> payee w Actual
    amount: Decimal  # ze znakiem: uznanie +, obciążenie -
    balance_after: Decimal  # saldo po transakcji


@dataclass
class ParsedStatement:
    """Wynik sparsowania jednego PDF-a (jednego rachunku)."""

    account_number: str  # znormalizowany (same cyfry)
    transactions: list[Transaction]
    opening_balance: Decimal
    closing_balance: Decimal
    meta: dict = field(default_factory=dict)  # numer wyciągu, okres itp.


@runtime_checkable
class Bank(Protocol):
    """Kontrakt banku. Orchestrator (run.py) używa tylko tych pól/metod."""

    name: str  # klucz w ENABLED_BANKS, np. "velo"
    imap_folder: str  # folder/etykieta na koncie śmieciowym, np. "velo-billing"
    processed_folder: str  # folder po sukcesie, np. "velo-billing-processed"
    pdf_password_env: str  # nazwa zmiennej w .env z hasłem do PDF, np. "VELO_PDF_PASSWORD"
    accounts_path: Path  # ścieżka do accounts.json banku

    def parse(self, pdf_bytes: bytes, password: str) -> ParsedStatement:
        """Sparsuj jeden (odszyfrowany hasłem) PDF do ParsedStatement."""
        ...
